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


def _metadata_root() -> Path:
    return storage.STORAGE / "metadata_cleaner"


def _originals() -> Path:
    return _metadata_root() / "originals"


def _outputs() -> Path:
    return _metadata_root() / "outputs"

VIDEO_EXTENSIONS = ["mp4", "mov", "mkv", "webm", "avi", "m4v", "mpeg", "mpg"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_filename(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", Path(name).name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_name).strip(".-")
    return ascii_name or "video-terceiro.mp4"


def _ensure_directories() -> None:
    _originals().mkdir(parents=True, exist_ok=True)
    _outputs().mkdir(parents=True, exist_ok=True)


def store_external_video(filename: str, content: bytes) -> tuple[Path, str]:
    """Persist an uploaded third-party video by content hash without overwriting it."""
    if not content:
        raise ValueError("O ficheiro de vídeo está vazio.")
    _ensure_directories()
    digest = hashlib.sha256(content).hexdigest()
    safe_name = _safe_filename(filename)
    path = _originals() / f"{digest[:16]}-{safe_name}"
    if not path.exists():
        path.write_bytes(content)
    return path, digest


def _resolve_ffmpeg(configured_path: str | None = None) -> str:
    configured = (configured_path or "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file():
            return str(candidate)
        resolved = shutil.which(configured)
        if resolved:
            return resolved
    resolved = shutil.which("ffmpeg")
    if resolved:
        return resolved
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover - depends on local installation
        raise RuntimeError("FFmpeg não foi encontrado. Instale-o ou configure o caminho em Configurações.") from exc


def build_description(preview: str, links: str, timestamps: str) -> str:
    """Match the n8n workflow's preview + links + timestamps description format."""
    sections: list[str] = []
    if preview.strip():
        sections.append(preview.strip())
    if links.strip():
        link_lines = links.strip()
        if not link_lines.lower().startswith("links:"):
            link_lines = "Links:\n" + link_lines
        sections.append(link_lines)
    if timestamps.strip():
        sections.append(timestamps.strip())
    return "\n\n".join(sections).strip()


def normalize_tags(tags: str | list[str]) -> list[str]:
    if isinstance(tags, list):
        values = tags
    else:
        values = re.split(r"[,;\n]", tags)
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = re.sub(r"^#+", "", str(value).strip())
        if cleaned and cleaned.lower() not in seen:
            result.append(cleaned)
            seen.add(cleaned.lower())
    return result


def _ffmpeg_metadata_args(metadata: dict[str, Any]) -> list[str]:
    args: list[str] = ["-map_metadata", "-1"]
    mapping = {
        "title": "title",
        "description": "description",
        "comment": "comment",
        "language": "language",
        "creator": "artist",
        "copyright": "copyright",
        "date": "date",
        "genre": "genre",
        "album": "album",
    }
    for field, ffmpeg_key in mapping.items():
        value = str(metadata.get(field, "") or "").strip()
        if value:
            args.extend(["-metadata", f"{ffmpeg_key}={value}"])
    tags = normalize_tags(metadata.get("tags", ""))
    if tags:
        args.extend(["-metadata", f"keywords={', '.join(tags)}"])
        args.extend(["-metadata", f"synopsis={', '.join(tags)}"])
    return args


def clean_video_metadata(
    source: Path,
    metadata: dict[str, Any],
    *,
    ffmpeg_path: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Strip existing container metadata and write a clean third-party copy."""
    if not source.is_file():
        raise FileNotFoundError("O vídeo externo não foi encontrado no armazenamento local.")
    _ensure_directories()
    ffmpeg = _resolve_ffmpeg(ffmpeg_path)
    source_name = _safe_filename(source.name)
    output = _outputs() / f"limpo-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{source_name}"
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(source)]
    command.extend(_ffmpeg_metadata_args(metadata))
    command.extend(["-c", "copy", str(output)])
    completed = subprocess.run(command, capture_output=True, text=True, check=False, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if completed.returncode != 0 or not output.exists() or output.stat().st_size == 0:
        if output.exists():
            output.unlink()
        detail = (completed.stderr or completed.stdout or "erro desconhecido").strip()
        raise RuntimeError(f"FFmpeg não conseguiu limpar os metadados: {detail[-1200:]}")
    return output, {
        "ffmpeg": ffmpeg,
        "command": command,
        "source": str(source),
        "output": str(output),
        "created_at": _now(),
    }


def save_edit_record(source: Path, output: Path, metadata: dict[str, Any], run_info: dict[str, Any]) -> dict[str, Any]:
    tags = normalize_tags(metadata.get("tags", ""))
    record = {
        "id": hashlib.sha256(f"{source}:{output}".encode("utf-8")).hexdigest()[:16],
        "source_type": "third_party_video",
        "source_name": source.name,
        "source_path": str(source),
        "output_name": output.name,
        "output_path": str(output),
        "metadata": {**metadata, "tags": tags},
        "run": {key: value for key, value in run_info.items() if key != "command"},
        "created_at": run_info.get("created_at", _now()),
    }
    storage.append_json("metadata_edits.json", record)
    record_notification(
        "metadata_cleaning_completed",
        f"Metadados limpos: {output.name}",
        "A limpeza de metadados terminou com um ficheiro de saída guardado.",
        metadata={"record_id": record["id"], "output_name": output.name},
        dedupe_key=f"metadata_cleaning_completed:{record['id']}",
    )
    return record


def list_edit_records() -> list[dict[str, Any]]:
    records = storage.read_json("metadata_edits.json", [])
    if not isinstance(records, list):
        return []
    return list(reversed(records))


def metadata_manifest(record: dict[str, Any]) -> bytes:
    """Return a portable JSON sidecar for YouTube title/description/tags upload."""
    return (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
