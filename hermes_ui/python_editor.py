from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import storage
from .notifications import record_notification
from .metadata_cleaner import VIDEO_EXTENSIONS as METADATA_VIDEO_EXTENSIONS
from .metadata_cleaner import _resolve_ffmpeg

VIDEO_EXTENSIONS = {f".{extension.lower().lstrip('.')}" for extension in METADATA_VIDEO_EXTENSIONS}
AUDIO_EXTENSIONS = {".mp3", ".mpeg", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


class PythonEditorError(RuntimeError):
    """Raised when a controlled local editing operation cannot be completed."""


def _root() -> Path:
    return storage.STORAGE / "python_editor"


def _outputs() -> Path:
    path = _root() / "outputs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _scripts() -> Path:
    path = _root() / "scripts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_filename(name: str, fallback: str = "video") -> str:
    normalized = unicodedata.normalize("NFKD", Path(name).name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_name).strip(".-")
    return ascii_name or fallback


def _output_path(source: Path, operation: str, suffix: str | None = None) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    source_name = _safe_filename(source.stem, "video")
    extension = suffix or source.suffix or ".mp4"
    if not extension.startswith("."):
        extension = f".{extension}"
    return _outputs() / f"{operation}-{stamp}-{source_name}{extension.lower()}"


def _validate_video(source: Path) -> Path:
    candidate = Path(source).expanduser()
    if not candidate.is_file():
        raise PythonEditorError("O vídeo seleccionado não existe ou não é um ficheiro.")
    if candidate.suffix.lower() not in VIDEO_EXTENSIONS:
        raise PythonEditorError("O ficheiro seleccionado não tem uma extensão de vídeo suportada.")
    return candidate.resolve()


def _validate_audio(source: Path) -> Path:
    candidate = Path(source).expanduser()
    if not candidate.is_file():
        raise PythonEditorError("O áudio seleccionado não existe ou não é um ficheiro.")
    if candidate.suffix.lower() not in AUDIO_EXTENSIONS:
        raise PythonEditorError("O ficheiro seleccionado não tem uma extensão de áudio suportada.")
    return candidate.resolve()


def list_video_files(folder: str | Path) -> list[Path]:
    candidate = Path(folder).expanduser()
    if not candidate.exists():
        return []
    if candidate.is_file():
        return [candidate.resolve()] if candidate.suffix.lower() in VIDEO_EXTENSIONS else []
    try:
        return sorted(
            (path.resolve() for path in candidate.iterdir() if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError as exc:
        raise PythonEditorError(f"Não foi possível ler a pasta de vídeos: {exc}") from exc


def list_generated_videos(tasks: list[dict[str, Any]]) -> list[Path]:
    paths: dict[str, Path] = {}
    for task in tasks:
        if "video_ready" in task and not bool(task.get("video_ready")):
            continue
        artifacts = task.get("artifacts") or {}
        value = artifacts.get("video")
        if isinstance(value, str) and value.strip():
            candidate = Path(value).expanduser()
            if candidate.is_file() and candidate.suffix.lower() in VIDEO_EXTENSIONS:
                paths[str(candidate.resolve())] = candidate.resolve()
    return sorted(paths.values(), key=lambda path: path.stat().st_mtime, reverse=True)


def list_scripts() -> list[Path]:
    return sorted((path for path in _scripts().glob("*.py") if path.is_file()), key=lambda path: path.stat().st_mtime, reverse=True)


def read_script(path: Path) -> str:
    candidate = path.resolve()
    if _scripts().resolve() not in candidate.parents:
        raise PythonEditorError("O script seleccionado tem de estar na pasta local de scripts do Thunderbolt.")
    try:
        return candidate.read_text(encoding="utf-8")
    except OSError as exc:
        raise PythonEditorError(f"Não foi possível ler o script: {exc}") from exc


def save_script(name: str, content: str) -> Path:
    safe_name = _safe_filename(name, "script")
    if not safe_name.lower().endswith(".py"):
        safe_name += ".py"
    if not content.strip():
        raise PythonEditorError("O script não pode ficar vazio.")
    target = (_scripts() / safe_name).resolve()
    if _scripts().resolve() not in target.parents:
        raise PythonEditorError("O nome do script não é válido.")
    target.write_text(content, encoding="utf-8")
    return target


def store_uploaded_asset(name: str, content: bytes, *, audio: bool = False) -> Path:
    if not content:
        raise PythonEditorError("O ficheiro enviado está vazio.")
    allowed = AUDIO_EXTENSIONS if audio else VIDEO_EXTENSIONS
    suffix = Path(name).suffix.lower()
    if suffix not in allowed:
        raise PythonEditorError("O ficheiro enviado não tem uma extensão suportada.")
    directory = _root() / ("audio_inputs" if audio else "video_inputs")
    directory.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(content).hexdigest()[:16]
    target = directory / f"{digest}-{_safe_filename(name, 'media')}"
    if not target.exists():
        target.write_bytes(content)
    return target


def _run(command: list[str], output: Path, operation: str, source: Path, *, extra: dict[str, Any] | None = None) -> tuple[Path, dict[str, Any]]:
    output.parent.mkdir(parents=True, exist_ok=True)
    executed_command = list(command)
    try:
        completed = subprocess.run(executed_command, capture_output=True, text=True, check=False, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except OSError as exc:
        raise PythonEditorError(f"Não foi possível iniciar FFmpeg: {exc}") from exc
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
        raise PythonEditorError(f"A operação {operation} falhou: {detail[-1200:]}")
    run_info = {
        "operation": operation,
        "source": str(source),
        "output": str(output),
        "command": executed_command,
        "created_at": _now(),
    }
    if extra:
        run_info.update(extra)
    return output, run_info


def _ffmpeg(ffmpeg_path: str | None = None) -> str:
    try:
        return _resolve_ffmpeg(ffmpeg_path)
    except RuntimeError as exc:
        raise PythonEditorError(str(exc)) from exc


def _atempo_chain(speed: float) -> str:
    factors: list[float] = []
    remaining = float(speed)
    while remaining > 2.0:
        factors.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        factors.append(0.5)
        remaining /= 0.5
    factors.append(remaining)
    return ",".join(f"atempo={factor:.6f}" for factor in factors)


def trim_video(source: Path, start_seconds: float, end_seconds: float, *, ffmpeg_path: str | None = None) -> tuple[Path, dict[str, Any]]:
    source = _validate_video(source)
    start = max(0.0, float(start_seconds))
    end = float(end_seconds)
    if end <= start:
        raise PythonEditorError("O fim do corte deve ser superior ao início.")
    output = _output_path(source, "corte")
    command = [_ffmpeg(ffmpeg_path), "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(source), "-map", "0", "-c", "copy", "-avoid_negative_ts", "make_zero", str(output)]
    return _run(command, output, "corte", source, extra={"start_seconds": start, "end_seconds": end})


def remove_audio(source: Path, *, ffmpeg_path: str | None = None) -> tuple[Path, dict[str, Any]]:
    source = _validate_video(source)
    output = _output_path(source, "sem-audio")
    command = [_ffmpeg(ffmpeg_path), "-y", "-hide_banner", "-loglevel", "error", "-i", str(source), "-map", "0:v:0", "-c:v", "copy", "-an", str(output)]
    return _run(command, output, "remoção de áudio", source)


def extract_audio(source: Path, *, ffmpeg_path: str | None = None) -> tuple[Path, dict[str, Any]]:
    source = _validate_video(source)
    output = _output_path(source, "audio", ".mp3")
    command = [_ffmpeg(ffmpeg_path), "-y", "-hide_banner", "-loglevel", "error", "-i", str(source), "-vn", "-codec:a", "libmp3lame", "-q:a", "2", str(output)]
    return _run(command, output, "extracção de áudio", source)


def resize_video(source: Path, width: int, height: int, *, ffmpeg_path: str | None = None) -> tuple[Path, dict[str, Any]]:
    source = _validate_video(source)
    width = int(width)
    height = int(height)
    if width < 16 or height < 16:
        raise PythonEditorError("As dimensões do vídeo devem ser pelo menos 16x16.")
    output = _output_path(source, "redimensionado")
    scale = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
    command = [_ffmpeg(ffmpeg_path), "-y", "-hide_banner", "-loglevel", "error", "-i", str(source), "-vf", scale, "-c:v", "h264_nvenc", "-preset", "p1", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(output)]
    return _run(command, output, "redimensionamento", source, extra={"width": width, "height": height})


def change_speed(source: Path, speed: float, *, ffmpeg_path: str | None = None) -> tuple[Path, dict[str, Any]]:
    source = _validate_video(source)
    speed = float(speed)
    if speed < 0.25 or speed > 4.0:
        raise PythonEditorError("A velocidade deve estar entre 0,25x e 4x.")
    output = _output_path(source, "velocidade")
    command = [_ffmpeg(ffmpeg_path), "-y", "-hide_banner", "-loglevel", "error", "-i", str(source), "-filter:v", f"setpts=PTS/{speed:.6f}", "-filter:a", _atempo_chain(speed), "-c:v", "h264_nvenc", "-preset", "p1", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(output)]
    return _run(command, output, "alteração de velocidade", source, extra={"speed": speed})


def replace_audio(source: Path, audio: Path, *, ffmpeg_path: str | None = None) -> tuple[Path, dict[str, Any]]:
    source = _validate_video(source)
    audio = _validate_audio(audio)
    output = _output_path(source, "audio-substituido")
    command = [_ffmpeg(ffmpeg_path), "-y", "-hide_banner", "-loglevel", "error", "-i", str(source), "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-shortest", str(output)]
    return _run(command, output, "substituição de áudio", source, extra={"audio": str(audio)})


def save_edit_record(source: Path, output: Path, run_info: dict[str, Any]) -> dict[str, Any]:
    record = {
        "id": hashlib.sha256(f"{source}:{output}:{run_info.get('created_at', '')}".encode("utf-8")).hexdigest()[:16],
        "source_name": source.name,
        "source_path": str(source),
        "output_name": output.name,
        "output_path": str(output),
        "operation": run_info.get("operation", "editor"),
        "parameters": {key: value for key, value in run_info.items() if key not in {"command", "source", "output", "created_at", "operation"}},
        "created_at": run_info.get("created_at", _now()),
    }
    storage.append_json("python_editor_edits.json", record)
    record_notification(
        "python_edit_completed",
        f"Edição Python concluída: {output.name}",
        f"A operação {record.get('operation') or 'de edição'} terminou com um artefacto guardado.",
        metadata={"record_id": record["id"], "output_name": output.name, "operation": record.get("operation") or ""},
        dedupe_key=f"python_edit_completed:{record['id']}",
    )
    return record


def editor_manifest(record: dict[str, Any]) -> bytes:
    return (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def list_edit_records() -> list[dict[str, Any]]:
    records = storage.read_json("python_editor_edits.json", [])
    return list(reversed(records)) if isinstance(records, list) else []
