from __future__ import annotations

import hashlib
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit, urlunsplit

from . import storage
from .notifications import record_notification

try:
    import yt_dlp  # type: ignore
except ImportError:  # pragma: no cover - exercised when the optional dependency is absent
    yt_dlp = None


HISTORY_FILE = "media_downloads.json"
VIDEO_QUALITY_OPTIONS = {
    "Melhor qualidade": "bv*+ba/b",
    "1080p ou inferior": "bv*[height<=1080]+ba/b[height<=1080]",
    "720p ou inferior": "bv*[height<=720]+ba/b[height<=720]",
    "480p ou inferior": "bv*[height<=480]+ba/b[height<=480]",
}
VIDEO_CONTAINERS = ("mp4", "mkv", "webm")
AUDIO_FORMATS = ("mp3", "m4a", "wav", "opus")
ProgressCallback = Callable[[dict[str, Any]], None]


class MediaDownloadError(RuntimeError):
    """Raised when a media download cannot be completed safely."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _download_root() -> Path:
    storage.ensure_storage()
    storage.MEDIA_DOWNLOADS.mkdir(parents=True, exist_ok=True)
    return storage.MEDIA_DOWNLOADS.resolve()


def _deno_runtime_path() -> str | None:
    """Resolve the project-managed Deno binary, with a PATH fallback."""
    try:
        import deno  # type: ignore

        finder = getattr(deno, "find_deno_bin", None)
        if callable(finder):
            candidate = Path(str(finder())).expanduser()
            if candidate.is_file():
                return str(candidate.resolve())
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        pass
    candidate = shutil.which("deno")
    return str(Path(candidate).resolve()) if candidate else None


def _safe_download_path(value: str | Path) -> Path | None:
    root = _download_root()
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return resolved


def _relative_name(path: Path) -> str:
    root = _download_root()
    try:
        return path.resolve().relative_to(root).as_posix()
    except (OSError, ValueError):
        return path.name


def _display_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if not parsed.scheme or not parsed.netloc:
        return value.strip()[:120]
    safe = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return safe[:160]


def _redact(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"(?i)(authorization|bearer|api[_ -]?key|access[_ -]?token|cookie|session[_ -]?info)\s*[:=]?\s*[^\s,;]+", r"\1=[redacted]", text)
    return text[:1200]


def normalize_urls(value: str | Iterable[str]) -> list[str]:
    """Normalize one URL per line and reject unsafe/non-web inputs."""
    if isinstance(value, str):
        candidates = value.splitlines()
    else:
        candidates = list(value)
    urls: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        url = str(candidate or "").strip()
        if not url:
            continue
        if url.startswith("-"):
            raise ValueError("Cada linha deve conter apenas uma URL; opções do yt-dlp não são aceites.")
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"URL inválida ou não suportada: {_display_url(url)}")
        normalized = urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path, parsed.query, parsed.fragment))
        if normalized not in seen:
            urls.append(normalized)
            seen.add(normalized)
    if not urls:
        raise ValueError("Introduza pelo menos uma URL http(s) para descarregar.")
    return urls


def build_download_options(
    *,
    mode: str = "video",
    quality: str = "Melhor qualidade",
    container: str = "mp4",
    audio_format: str = "mp3",
    allow_playlist: bool = False,
    download_subtitles: bool = False,
    embed_metadata: bool = False,
    progress_hook: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Build a constrained YoutubeDL options dictionary without user CLI flags."""
    normalized_mode = str(mode or "video").strip().lower()
    if normalized_mode not in {"video", "audio"}:
        raise ValueError("O modo deve ser Vídeo ou Áudio.")
    normalized_container = str(container or "mp4").lower()
    normalized_audio = str(audio_format or "mp3").lower()
    if normalized_container not in VIDEO_CONTAINERS:
        raise ValueError("Contentor de vídeo não suportado.")
    if normalized_audio not in AUDIO_FORMATS:
        raise ValueError("Formato de áudio não suportado.")
    root = _download_root()
    options: dict[str, Any] = {
        "outtmpl": str(root / "%(title).200B [%(id)s].%(ext)s"),
        "noplaylist": not bool(allow_playlist),
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": False,
        "windowsfilenames": True,
        "overwrites": False,
        "paths": {"home": str(root)},
    }
    deno_path = _deno_runtime_path()
    if deno_path:
        # yt-dlp's Python API expects {runtime: {config}}, not runtime:path.
        options["js_runtimes"] = {"deno": {"path": deno_path}}
    if progress_hook is not None:
        options["progress_hooks"] = [progress_hook]
    if normalized_mode == "audio":
        options.update({"format": "bestaudio/best", "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": normalized_audio, "preferredquality": "192"}]})
    else:
        options.update({"format": VIDEO_QUALITY_OPTIONS.get(quality, VIDEO_QUALITY_OPTIONS["Melhor qualidade"]), "merge_output_format": normalized_container})
    if download_subtitles:
        options.update({"writesubtitles": True, "writeautomaticsub": True, "subtitlesformat": "best", "subtitleslangs": ["all"]})
    if embed_metadata:
        options["addmetadata"] = True
    return options


def _read_history() -> list[dict[str, Any]]:
    records = storage.read_json(HISTORY_FILE, [])
    return [item for item in records if isinstance(item, dict)] if isinstance(records, list) else []


def _write_history(records: list[dict[str, Any]]) -> None:
    storage.write_json(HISTORY_FILE, records[:200])


def _upsert_history(record: dict[str, Any]) -> None:
    history = [item for item in _read_history() if str(item.get("operation_id")) != str(record.get("operation_id"))]
    _write_history([record, *history])


def list_media_downloads(limit: int = 50) -> list[dict[str, Any]]:
    return _read_history()[: max(0, int(limit))]


def clear_media_download_history() -> int:
    count = len(_read_history())
    _write_history([])
    return count


def media_download_file(record: dict[str, Any], filename: str) -> Path | None:
    """Resolve a history filename strictly inside storage/downloads."""
    allowed = {str(item) for item in record.get("files", []) if item}
    if filename not in allowed:
        return None
    path = _safe_download_path(filename)
    return path if path and path.is_file() else None


def dependency_status() -> dict[str, Any]:
    deno_path = _deno_runtime_path()
    return {
        "yt_dlp": yt_dlp is not None,
        "deno": bool(deno_path),
        "deno_path": deno_path or "",
        "ffmpeg_note": "A conversão/combinação de streams pode exigir FFmpeg.",
    }


def _files_from_info(info: Any, started_at: float) -> list[Path]:
    candidates: list[str] = []
    if isinstance(info, dict):
        for key in ("filepath", "_filename", "filename"):
            if info.get(key):
                candidates.append(str(info[key]))
        requested = info.get("requested_downloads")
        if isinstance(requested, list):
            for item in requested:
                if isinstance(item, dict):
                    for key in ("filepath", "_filename", "filename"):
                        if item.get(key):
                            candidates.append(str(item[key]))
        entries = info.get("entries")
        if isinstance(entries, list):
            for entry in entries:
                candidates.extend(str(path) for path in _files_from_info(entry, started_at))
    output: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        path = _safe_download_path(candidate)
        if path and path.is_file() and path.suffix.lower() not in {".part", ".ytdl"} and str(path) not in seen:
            output.append(path)
            seen.add(str(path))
    root = _download_root()
    try:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() not in {".part", ".ytdl", ".json", ".description", ".vtt", ".srt", ".ass"} and path.stat().st_mtime >= started_at and str(path) not in seen:
                output.append(path)
                seen.add(str(path))
    except OSError:
        pass
    return output


def _operation_id(url: str) -> str:
    digest = hashlib.sha256(f"{url}|{_now()}|{uuid.uuid4().hex}".encode("utf-8")).hexdigest()[:16]
    return f"media_{digest}"


def _notify(record: dict[str, Any]) -> None:
    suffix = "concluído" if record.get("status") == "completed" else "falhou"
    event_type = "media_download_completed" if record.get("status") == "completed" else "media_download_failed"
    title = str(record.get("title") or record.get("display_url") or "Download de mídia")
    message = f"O download de mídia {suffix}."
    if record.get("status") == "failed" and record.get("error"):
        message = f"O download de mídia falhou: {_redact(record['error'])}"
    record_notification(
        event_type,
        title,
        message,
        metadata={"operation_id": record.get("operation_id"), "mode": record.get("mode"), "files": record.get("files", []), "display_url": record.get("display_url")},
        dedupe_key=f"media:{record.get('operation_id')}:{record.get('status')}",
    )


def download_media(
    urls: str | Iterable[str],
    *,
    mode: str = "video",
    quality: str = "Melhor qualidade",
    container: str = "mp4",
    audio_format: str = "mp3",
    allow_playlist: bool = False,
    download_subtitles: bool = False,
    embed_metadata: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> list[dict[str, Any]]:
    """Download one or more public URLs and return one persisted record per URL."""
    normalized_urls = normalize_urls(urls)
    results: list[dict[str, Any]] = []
    for url in normalized_urls:
        operation_id = _operation_id(url)
        record: dict[str, Any] = {
            "operation_id": operation_id,
            "url": _display_url(url),
            "display_url": _display_url(url),
            "mode": str(mode or "video").lower(),
            "status": "processing",
            "title": "",
            "files": [],
            "progress": 0.0,
            "created_at": _now(),
            "completed_at": "",
            "error": "",
        }
        _upsert_history(record)
        if progress_callback:
            progress_callback({**record, "status": "processing"})
        started_at = datetime.now().timestamp()

        def progress_hook(payload: dict[str, Any]) -> None:
            status = str(payload.get("status") or "")
            downloaded = float(payload.get("downloaded_bytes") or 0)
            total = float(payload.get("total_bytes") or payload.get("total_bytes_estimate") or 0)
            progress = min(99.0, (downloaded / total) * 100) if total > 0 else (50.0 if status == "downloading" else 0.0)
            record["progress"] = round(progress, 1)
            if payload.get("filename"):
                record["current_file"] = Path(str(payload["filename"])).name
            if progress_callback:
                progress_callback({**record, "hook_status": status})

        try:
            if yt_dlp is None:
                raise MediaDownloadError("yt-dlp não está instalado. Instale as dependências do Thunderbolt e tente novamente.")
            options = build_download_options(mode=mode, quality=quality, container=container, audio_format=audio_format, allow_playlist=allow_playlist, download_subtitles=download_subtitles, embed_metadata=embed_metadata, progress_hook=progress_hook)
            downloader = yt_dlp.YoutubeDL(options)
            info = downloader.extract_info(url, download=True)
            close = getattr(downloader, "close", None)
            if callable(close):
                close()
            files = _files_from_info(info, started_at)
            if not files:
                raise MediaDownloadError("O yt-dlp terminou sem produzir um ficheiro local verificável.")
            record.update({"status": "completed", "title": str(info.get("title") or "Download concluído") if isinstance(info, dict) else "Download concluído", "files": [_relative_name(path) for path in files], "progress": 100.0, "completed_at": _now(), "error": ""})
            _upsert_history(record)
            _notify(record)
        except Exception as exc:  # the UI receives a persisted failed record per URL
            record.update({"status": "failed", "error": _redact(exc), "completed_at": _now()})
            _upsert_history(record)
            _notify(record)
        results.append(dict(record))
        if progress_callback:
            progress_callback(dict(record))
    return results
