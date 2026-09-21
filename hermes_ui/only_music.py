from __future__ import annotations

from pathlib import Path
from typing import Any

from .creative_generation import CreativeGenerationError, generate_thumbnail_prompt
from .media_generation import MediaGenerationError, generate_image_from_pool
from .music import list_music_files
from .thumbnail_blueprints import thumbnail_blueprint_for_channel


def resolve_music_source(task: dict) -> Path | None:
    """Resolve an existing library/upload audio file without creating music."""
    candidates = [
        task.get("music_path"),
        (task.get("generation_settings") or {}).get("music_path") if isinstance(task.get("generation_settings"), dict) else "",
        (task.get("artifacts") or {}).get("music") if isinstance(task.get("artifacts"), dict) else "",
    ]
    for value in candidates:
        path = Path(str(value or "")).expanduser()
        if path.is_file() and path.stat().st_size > 0:
            return path
    available = {path.resolve() for path in list_music_files() if path.is_file()}
    for path in available:
        if path.name == str(task.get("music_filename") or ""):
            return path
    return None


def generate_only_music_thumbnail(task: dict, music_path: Path, settings: dict, channel: dict) -> Path:
    """Generate only the thumbnail for an existing music file."""
    del music_path
    topic = str(task.get("topic") or task.get("title") or "Música").strip()
    blueprint = thumbnail_blueprint_for_channel(channel, task.get("format", "wide"))
    variant = task.get("thumbnail_variant") if isinstance(task.get("thumbnail_variant"), dict) else {}
    if not str(variant.get("image_prompt") or "").strip():
        variant = generate_thumbnail_prompt(
            settings,
            channel,
            topic,
            blueprint=blueprint,
            language=str(task.get("language") or channel.get("language") or "Português"),
        )
    return generate_image_from_pool(
        settings,
        str(variant.get("image_prompt") or topic),
        topic=topic,
        variant_index=0,
        lettering_text=str(variant.get("overlay_text") or ""),
        lettering_prompt=str(variant.get("lettering_prompt") or ""),
        thumbnail_blueprint=blueprint,
        aspect_ratio="9:16" if str(task.get("format") or "").casefold() in {"shorts", "portrait"} else "16:9",
    )


def run_only_music_task(task: dict, settings: dict | None = None, channel: dict | None = None) -> dict[str, Any]:
    """Return Only Music updates; the caller persists them in the task store."""
    music_path = resolve_music_source(task)
    if music_path is None:
        raise ValueError("Only Music exige uma música existente na biblioteca ou um ficheiro carregado.")
    settings = settings if isinstance(settings, dict) else {}
    channel = channel if isinstance(channel, dict) else {}
    thumbnail = generate_only_music_thumbnail(task, music_path, settings, channel)
    variant = task.get("thumbnail_variant") if isinstance(task.get("thumbnail_variant"), dict) else {}
    artifacts = dict(task.get("artifacts") or {})
    artifacts.update({"music": str(music_path), "thumbnail": str(thumbnail)})
    return {
        "stage": "thumbnail",
        "state": "done",
        "progress": 100,
        "artifacts": artifacts,
        "music_ready": True,
        "video_ready": False,
        "thumbnail_status": "generated",
        "thumbnail_prompt": str(variant.get("image_prompt") or task.get("thumbnail_prompt") or ""),
        "error": None,
    }


__all__ = ["resolve_music_source", "generate_only_music_thumbnail", "run_only_music_task"]
