from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import unicodedata
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import requests

from . import storage
from .metadata_cleaner import VIDEO_EXTENSIONS, _resolve_ffmpeg
from .notifications import record_notification


class CutsError(RuntimeError):
    """Raised when a local clip-generation operation cannot be completed."""


OUTPUT_FORMATS: dict[str, dict[str, Any]] = {
    "9:16": {"width": 1080, "height": 1920, "label": "9:16 · Shorts / Reels / TikTok"},
    "1:1": {"width": 1080, "height": 1080, "label": "1:1 · Feed posts"},
    "16:9": {"width": 1920, "height": 1080, "label": "16:9 · YouTube / landscape"},
}

VIDEO_SUFFIXES = {f".{extension.lower().lstrip('.')}" for extension in VIDEO_EXTENSIONS}
MAX_SOURCE_BYTES = 500 * 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root() -> Path:
    path = storage.STORAGE / "cuts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _inputs() -> Path:
    path = _root() / "inputs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _runs_root() -> Path:
    path = _root() / "runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_filename(name: str, fallback: str = "video") -> str:
    normalized = unicodedata.normalize("NFKD", Path(name).name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_name).strip(".-")
    return safe or fallback


def _validate_video(source: Path) -> Path:
    candidate = Path(source).expanduser()
    if not candidate.is_file():
        raise CutsError("O vídeo seleccionado não existe ou não é um ficheiro.")
    if candidate.suffix.lower() not in VIDEO_SUFFIXES:
        raise CutsError("O vídeo seleccionado não tem uma extensão suportada.")
    return candidate.resolve()


def _safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def normalize_output_format(output_format: str) -> str:
    key = str(output_format or "").strip()
    if key not in OUTPUT_FORMATS:
        raise CutsError("Seleccione um formato de saída válido: 9:16, 1:1 ou 16:9.")
    return key


def store_uploaded_video(filename: str, content: bytes) -> Path:
    if not content:
        raise CutsError("O ficheiro de vídeo está vazio.")
    suffix = Path(filename).suffix.lower()
    if suffix not in VIDEO_SUFFIXES:
        raise CutsError("O ficheiro enviado não tem uma extensão de vídeo suportada.")
    digest = hashlib.sha256(content).hexdigest()[:16]
    existing = next(iter(sorted(_inputs().glob(f"{digest}-*"))), None)
    if existing and existing.is_file():
        return existing.resolve()
    target = _inputs() / f"{digest}-{_safe_filename(filename, 'video')}"
    if not target.exists():
        target.write_bytes(content)
    return target.resolve()


def list_video_files(folder: str | Path) -> list[Path]:
    candidate = Path(folder).expanduser()
    if not candidate.exists():
        return []
    if candidate.is_file():
        return [candidate.resolve()] if candidate.suffix.lower() in VIDEO_SUFFIXES else []
    try:
        return sorted(
            (path.resolve() for path in candidate.iterdir() if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError as exc:
        raise CutsError(f"Não foi possível ler a pasta de vídeos: {exc}") from exc


def list_generated_videos(tasks: Iterable[dict[str, Any]]) -> list[Path]:
    paths: dict[str, Path] = {}
    for task in tasks:
        # Um caminho pode existir enquanto a tarefa ainda está a ser processada;
        # só artefactos explicitamente prontos devem entrar nesta biblioteca.
        if "video_ready" in task and not bool(task.get("video_ready")):
            continue
        artifacts = task.get("artifacts") or {}
        value = artifacts.get("video")
        if isinstance(value, str) and value.strip():
            candidate = Path(value).expanduser()
            if candidate.is_file() and candidate.suffix.lower() in VIDEO_SUFFIXES:
                paths[str(candidate.resolve())] = candidate.resolve()
    return sorted(paths.values(), key=lambda path: path.stat().st_mtime, reverse=True)


def resolve_ffmpeg(configured_path: str | None = None) -> str:
    try:
        return _resolve_ffmpeg(configured_path)
    except RuntimeError as exc:
        raise CutsError(str(exc)) from exc


def resolve_ffprobe(configured_path: str | None = None) -> str | None:
    configured = str(configured_path or "").strip()
    candidates: list[str] = []
    if configured:
        configured_path_obj = Path(configured).expanduser()
        if configured_path_obj.name.lower().startswith("ffmpeg"):
            candidates.append(str(configured_path_obj.with_name("ffprobe" + configured_path_obj.suffix)))
        candidates.append(configured)
    detected = shutil.which("ffprobe")
    if detected:
        candidates.append(detected)
    for candidate in candidates:
        resolved = shutil.which(candidate) or (candidate if Path(candidate).is_file() else None)
        if resolved:
            return str(resolved)
    return None


def probe_duration(source: Path, *, ffprobe_path: str | None = None) -> float | None:
    source = _validate_video(source)
    binary = resolve_ffprobe(ffprobe_path)
    if not binary:
        return None
    command = [binary, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(source)]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    duration = _safe_float(completed.stdout.strip(), 0.0)
    return duration if duration > 0 else None


def validate_cut_request(
    *,
    source: Path,
    output_format: str,
    strategy: str,
    max_clips: int,
    min_duration: float,
    max_duration: float,
    rights_confirmed: bool,
    manual_start: float = 0.0,
    manual_end: float | None = None,
) -> dict[str, Any]:
    source = _validate_video(source)
    output_format = normalize_output_format(output_format)
    if strategy not in {"automatic", "manual"}:
        raise CutsError("Seleccione uma estratégia de corte válida.")
    if not rights_confirmed:
        raise CutsError("Confirme que possui os direitos ou autorização para processar este conteúdo.")
    max_clips = int(max_clips)
    if max_clips < 1 or max_clips > 20:
        raise CutsError("A quantidade de clips deve estar entre 1 e 20.")
    min_duration = _safe_float(min_duration)
    max_duration = _safe_float(max_duration)
    if min_duration < 1 or max_duration > 600 or max_duration < min_duration:
        raise CutsError("Defina uma duração válida: mínimo ≥ 1s, máximo ≤ 600s e máximo ≥ mínimo.")
    manual_start = _safe_float(manual_start)
    if manual_start < 0:
        raise CutsError("O início manual não pode ser negativo.")
    normalized_end = None if manual_end is None else _safe_float(manual_end)
    if strategy == "manual" and (normalized_end is None or normalized_end <= manual_start):
        raise CutsError("No modo manual, o fim deve ser superior ao início.")
    return {
        "source": str(source),
        "source_name": source.name,
        "output_format": output_format,
        "strategy": strategy,
        "max_clips": max_clips,
        "min_duration": min_duration,
        "max_duration": max_duration,
        "manual_start": manual_start,
        "manual_end": normalized_end,
        "rights_confirmed": True,
    }


def plan_segments(
    duration: float | None,
    *,
    strategy: str,
    max_clips: int,
    min_duration: float,
    max_duration: float,
    manual_start: float = 0.0,
    manual_end: float | None = None,
) -> list[dict[str, float]]:
    if strategy == "manual":
        if manual_end is None or manual_end <= manual_start:
            raise CutsError("No modo manual, o fim deve ser superior ao início.")
        return [{"index": 1, "start": round(float(manual_start), 3), "end": round(float(manual_end), 3), "duration": round(float(manual_end - manual_start), 3)}]
    if duration is None or duration <= 0:
        raise CutsError("Não foi possível detectar a duração do vídeo. Use o modo manual ou instale/configure FFprobe.")
    if duration < min_duration:
        raise CutsError(f"O vídeo tem apenas {duration:.1f}s e é menor que a duração mínima configurada.")
    count = min(int(max_clips), max(1, int(duration // min_duration)))
    clip_duration = min(float(max_duration), max(float(min_duration), duration / count))
    if clip_duration > duration:
        clip_duration = duration
    if count == 1:
        starts = [0.0]
    else:
        starts = [(duration - clip_duration) * index / (count - 1) for index in range(count)]
    return [
        {"index": index + 1, "start": round(start, 3), "end": round(min(duration, start + clip_duration), 3), "duration": round(min(duration, start + clip_duration) - start, 3)}
        for index, start in enumerate(starts)
    ]


def _video_filter(output_format: str) -> str:
    dimensions = OUTPUT_FORMATS[normalize_output_format(output_format)]
    width = dimensions["width"]
    height = dimensions["height"]
    return f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"


def build_clip_command(source: Path, output: Path, segment: dict[str, float], output_format: str, *, ffmpeg_path: str) -> list[str]:
    start = max(0.0, float(segment["start"]))
    duration = max(0.1, float(segment["duration"]))
    return [
        ffmpeg_path,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-vf",
        _video_filter(output_format),
        "-c:v",
        "h264_nvenc",
        "-preset",
        "p1",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "22",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(output),
    ]


def _run_ffmpeg(command: list[str], output: Path, *, source: Path, segment: dict[str, float]) -> dict[str, Any]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except OSError as exc:
        raise CutsError(f"Não foi possível iniciar FFmpeg: {exc}") from exc
    executed_command = list(command)
    if completed.returncode != 0 and "h264_nvenc" in executed_command:
        fallback = ["libx264" if item == "h264_nvenc" else "veryfast" if item == "p1" else item for item in executed_command]
        if output.exists():
            output.unlink()
        completed = subprocess.run(fallback, capture_output=True, text=True, check=False, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        executed_command = fallback
    if completed.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        if output.exists():
            output.unlink()
        detail = (completed.stderr or completed.stdout or "erro desconhecido").strip()
        raise CutsError(f"O clip não pôde ser gerado: {detail[-1200:]}")
    return {"source": str(source), "output": str(output), "command": executed_command, "segment": segment, "created_at": _now()}


def _write_manifest(record: dict[str, Any], run_dir: Path) -> Path:
    """Write a complete clip manifest atomically."""
    path = run_dir / "manifest.json"
    storage.atomic_write(path, record)
    return path


def generate_clips(
    source: Path,
    *,
    output_format: str,
    strategy: str,
    max_clips: int,
    min_duration: float,
    max_duration: float,
    rights_confirmed: bool,
    ffmpeg_path: str | None = None,
    manual_start: float = 0.0,
    manual_end: float | None = None,
) -> dict[str, Any]:
    request = validate_cut_request(
        source=source,
        output_format=output_format,
        strategy=strategy,
        max_clips=max_clips,
        min_duration=min_duration,
        max_duration=max_duration,
        rights_confirmed=rights_confirmed,
        manual_start=manual_start,
        manual_end=manual_end,
    )
    duration = probe_duration(source)
    segments = plan_segments(
        duration,
        strategy=strategy,
        max_clips=max_clips,
        min_duration=min_duration,
        max_duration=max_duration,
        manual_start=manual_start,
        manual_end=manual_end,
    )
    run_id = f"cut_{datetime.now().strftime('%Y%m%d-%H%M%S')}_{uuid.uuid4().hex[:8]}"
    run_dir = _runs_root() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "id": run_id,
        "created_at": _now(),
        "status": "processing",
        "source": request["source"],
        "source_name": request["source_name"],
        "source_duration": duration,
        "output_format": output_format,
        "strategy": strategy,
        "parameters": {key: value for key, value in request.items() if key not in {"source", "source_name"}},
        "clips": [],
        "error": "",
    }
    try:
        binary = resolve_ffmpeg(ffmpeg_path)
        for segment in segments:
            output = run_dir / f"clip-{int(segment['index']):02d}-{_safe_filename(source.stem, 'video')}-{output_format.replace(':', 'x')}.mp4"
            command = build_clip_command(source, output, segment, output_format, ffmpeg_path=binary)
            run_info = _run_ffmpeg(command, output, source=source, segment=segment)
            record["clips"].append({
                "index": int(segment["index"]),
                "path": str(output),
                "name": output.name,
                "start": segment["start"],
                "end": segment["end"],
                "duration": segment["duration"],
                "size_bytes": output.stat().st_size,
                "command": run_info["command"],
            })
        record["status"] = "complete"
    except (CutsError, OSError, ValueError) as exc:
        record["status"] = "error"
        record["error"] = str(exc)
    _write_manifest(record, run_dir)
    storage.append_json("cuts_runs.json", record)
    if record["status"] == "complete":
        record_notification(
            "cuts_completed",
            "Cortes concluídos",
            f"A geração de cortes para {record['source_name']} terminou com {len(record['clips'])} clip(s).",
            metadata={"run_id": record["id"], "clip_count": len(record["clips"]), "output_format": record.get("output_format") or ""},
            dedupe_key=f"cuts:{record['id']}",
        )
    if record["status"] == "error":
        raise CutsError(record["error"])
    return record


def list_runs() -> list[dict[str, Any]]:
    records = storage.read_json("cuts_runs.json", [])
    return list(reversed(records)) if isinstance(records, list) else []


def manifest_bytes(record: dict[str, Any]) -> bytes:
    return (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def zip_run(record: dict[str, Any]) -> tuple[Path, bytes]:
    run_id = _safe_filename(str(record.get("id") or "run"), "run")
    run_dir = _runs_root() / run_id
    if not run_dir.is_dir():
        raise CutsError("A execução seleccionada já não existe no storage local.")
    archive = run_dir / f"{run_id}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        for clip in record.get("clips", []):
            path = Path(str(clip.get("path") or ""))
            if path.is_file() and run_dir.resolve() in path.resolve().parents:
                handle.write(path, arcname=path.name)
        manifest = run_dir / "manifest.json"
        if manifest.is_file():
            handle.write(manifest, arcname=manifest.name)
    return archive, archive.read_bytes()


def download_direct_video_url(url: str, *, timeout: int = 30) -> Path:
    parsed = urlparse(str(url).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CutsError("Informe uma URL HTTP/HTTPS directa para um ficheiro de vídeo.")
    try:
        response = requests.get(url, stream=True, timeout=timeout, headers={"User-Agent": "Thunderbolt/0.2"})
        response.raise_for_status()
    except requests.RequestException as exc:
        raise CutsError(f"Não foi possível descarregar a URL do vídeo: {exc}") from exc
    content_length = _safe_float(response.headers.get("content-length"), 0.0)
    if content_length > MAX_SOURCE_BYTES:
        raise CutsError("A fonte excede o limite de 500 MB.")
    suffix = Path(parsed.path).suffix.lower()
    if suffix not in VIDEO_SUFFIXES:
        content_type = str(response.headers.get("content-type") or "").lower()
        suffix = ".mp4" if "mp4" in content_type or "video" in content_type else ""
    if suffix not in VIDEO_SUFFIXES:
        raise CutsError("A URL deve apontar para um ficheiro de vídeo MP4, MOV ou formato suportado.")
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    target = _inputs() / f"{digest}-url{suffix}"
    if target.exists():
        return target.resolve()
    total = 0
    temporary = target.with_suffix(target.suffix + ".part")
    try:
        with temporary.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_SOURCE_BYTES:
                    raise CutsError("A fonte excede o limite de 500 MB.")
                handle.write(chunk)
        temporary.replace(target)
    except CutsError:
        temporary.unlink(missing_ok=True)
        raise
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise CutsError(f"Não foi possível guardar o vídeo descarregado: {exc}") from exc
    return target.resolve()
