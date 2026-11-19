from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .provider_routing import route_llm_json
from .storage import BLUEPRINTS, MUSIC_THUMBNAIL_BLUEPRINTS, SEED_BLUEPRINTS, SEED_MUSIC_THUMBNAIL_BLUEPRINTS, SEED_THUMBNAIL_BLUEPRINTS, atomic_write, list_blueprint_files, load_blueprint_file

HORIZONTAL_GENERIC_THUMBNAIL_BLUEPRINT_ID = "Youtube_Generic_Thumbnail_Blueprint"
VERTICAL_GENERIC_THUMBNAIL_BLUEPRINT_ID = "Tiktok_Generic_Thumbnail_Blueprint"
# Backwards-compatible name for callers that only need the landscape default.
GENERIC_THUMBNAIL_BLUEPRINT_ID = HORIZONTAL_GENERIC_THUMBNAIL_BLUEPRINT_ID
GENERIC_ASSOCIATION_ERROR = "Not Allowed to Associate, System Use Only"

PROMPT_MASTER = '''You are a forensic YouTube thumbnail analyst. Build a reusable Thumbnail Blueprint from the reference channel videos below.
The output must be a practical, locked visual system, not a script blueprint. Infer recurring composition, framing, lighting, color, typography, overlay text, symbols, emotional triggers, mobile readability, a horizontal 16:9 canvas, quality and negative constraints. Use the exact Markdown structure of the requested reference: STYLE LOCK, FRAMING & POSE, BACKGROUND & LIGHTING, GEOPOLITICAL SYMBOLS when relevant, VISUAL ATTENTION ELEMENT, TEXT STYLE, TEXT PSYCHOLOGY, COMPOSITION RULES, FORMAT & QUALITY, FINAL OBJECTIVE, FINAL INPUT FORMAT and FINAL SYSTEM INSTRUCTION. In FORMAT & QUALITY, require a landscape 16:9 YouTube thumbnail and a target size of 1792 × 1024 where the image provider supports explicit size parameters; this is a visual output requirement, not a universal API field. Write the document in English. Do not invent channel analytics. The document must instruct future thumbnail generation and include a concise, ready-to-use image prompt template.'''


def _slug(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9À-ÿ]+", "_", str(value or "").strip(), flags=re.UNICODE).strip("_")
    return text or "General"


def _record_name(niche: str) -> str:
    return f"{_slug(niche)}_Thumbnail_Blueprint"


def thumbnail_blueprint_catalog() -> list[tuple[str, str]]:
    folder = BLUEPRINTS / "thumbnails"
    folder.mkdir(parents=True, exist_ok=True)
    result: list[tuple[str, str]] = [("", "Sem Thumbnail Blueprint padrão")]
    for path in sorted(folder.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        result.append((path.stem, path.stem))
    return result


def resolve_thumbnail_blueprint(identifier: Any) -> dict[str, Any]:
    wanted = str(identifier or "").strip()
    if not wanted:
        return {}
    if wanted == "Generic_Thumbnail_Blueprint":
        wanted = HORIZONTAL_GENERIC_THUMBNAIL_BLUEPRINT_ID
    folders = (BLUEPRINTS / "thumbnails", SEED_THUMBNAIL_BLUEPRINTS)
    for folder in folders:
        for path in folder.glob("*.md"):
            if path.stem == wanted or path.name == wanted:
                return {"id": path.stem, "name": path.stem, "path": str(path), "content": path.read_text(encoding="utf-8")}
    return {"id": wanted, "name": wanted}


def _generic_thumbnail_blueprint_id(format_value: Any = "", platform: Any = "") -> str:
    raw = str(format_value or "").strip().casefold()
    if raw in {"portrait", "portrait 9:16", "vertical", "shorts", "9:16", "tiktok", "reels"}:
        return VERTICAL_GENERIC_THUMBNAIL_BLUEPRINT_ID
    platform_raw = str(platform or "").strip().casefold()
    if platform_raw in {"tiktok", "instagram", "instagram reels", "shorts"} and not raw:
        return VERTICAL_GENERIC_THUMBNAIL_BLUEPRINT_ID
    return HORIZONTAL_GENERIC_THUMBNAIL_BLUEPRINT_ID


def thumbnail_blueprint_for_channel(channel: Mapping[str, Any], format_value: Any = "") -> dict[str, Any]:
    direct = channel.get("default_thumbnail_blueprint_id") or channel.get("thumbnail_blueprint_id")
    if direct and str(direct).strip() not in {
        "Generic_Thumbnail_Blueprint",
        HORIZONTAL_GENERIC_THUMBNAIL_BLUEPRINT_ID,
        VERTICAL_GENERIC_THUMBNAIL_BLUEPRINT_ID,
    }:
        return resolve_thumbnail_blueprint(direct)
    script_id = str(channel.get("default_blueprint_id") or channel.get("blueprint_id") or "").strip()
    pairs = _pair_state()
    return resolve_thumbnail_blueprint(
        _paired_thumbnail_id(script_id, pairs) or _generic_thumbnail_blueprint_id(format_value, channel.get("platform"))
    )


def thumbnail_blueprint_for_task(channel: Mapping[str, Any], task: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve a task thumbnail, replacing stale generic orientation defaults."""
    format_value = task.get("format") or (task.get("generation_settings") or {}).get("video_aspect_ratio")
    direct = str(task.get("thumbnail_blueprint_id") or "").strip()
    if direct and direct not in {
        "Generic_Thumbnail_Blueprint",
        HORIZONTAL_GENERIC_THUMBNAIL_BLUEPRINT_ID,
        VERTICAL_GENERIC_THUMBNAIL_BLUEPRINT_ID,
    }:
        return resolve_thumbnail_blueprint(direct)
    return thumbnail_blueprint_for_channel({**channel, "thumbnail_blueprint_id": ""}, format_value)


def thumbnail_aspect_ratio_for_channel_task(
    channel: Mapping[str, Any] | None,
    task: Mapping[str, Any] | None = None,
    blueprint: Mapping[str, Any] | None = None,
) -> str:
    """Resolve thumbnail orientation consistently for new and persisted tasks.

    A channel-specific blueprint remains authoritative. When no specific blueprint
    exists, platform defaults are used: TikTok/Instagram are portrait and YouTube
    is landscape. This deliberately ignores stale generic blueprint ids persisted
    on older YouTube tasks.
    """
    channel = channel or {}
    task = task or {}
    selected = dict(blueprint or {})
    direct = str(
        channel.get("default_thumbnail_blueprint_id")
        or channel.get("thumbnail_blueprint_id")
        or task.get("thumbnail_blueprint_id")
        or ""
    ).strip()
    generic_ids = {
        "Generic_Thumbnail_Blueprint",
        HORIZONTAL_GENERIC_THUMBNAIL_BLUEPRINT_ID,
        VERTICAL_GENERIC_THUMBNAIL_BLUEPRINT_ID,
    }
    if not selected and direct and direct not in generic_ids:
        selected = resolve_thumbnail_blueprint(direct)
    if selected.get("content") and direct not in generic_ids:
        explicit_ratio = _explicit_blueprint_aspect_ratio(selected.get("content"))
        if explicit_ratio:
            return explicit_ratio
        return "9:16" if _contains_vertical_rules(selected.get("content")) else "16:9"

    platform = str(channel.get("platform") or task.get("platform") or "").strip().casefold()
    if platform in {"tiktok", "instagram", "instagram reels"}:
        return "9:16"
    return "16:9"


def _contains_vertical_rules(value: Any) -> bool:
    return bool(re.search(r"\b9\s*:\s*16\b|\bvertical\b|\bportrait\b", str(value or ""), flags=re.IGNORECASE))


def _explicit_blueprint_aspect_ratio(value: Any) -> str:
    """Read the authoritative FORMAT/QUALITY ratio before contextual wording.

    Finance and other landscape blueprints may mention a vertical third or
    vertical positioning in their composition rules. Those words must not
    override an explicit ``Aspect ratio: 16:9`` declaration.
    """
    content = str(value or "")
    format_sections = re.findall(
        r"(?is)(?:FORMAT\s*(?:&|AND)?\s*QUALITY|FORMATO\s*(?:E|&)\s*QUALIDADE)(.*?)(?=\n#{1,6}\s|\Z)",
        content,
    )
    search_area = "\n".join(format_sections) if format_sections else content
    ratio_match = re.search(r"\b(16\s*:\s*9|9\s*:\s*16)\b", search_area)
    if not ratio_match:
        return ""
    return "16:9" if ratio_match.group(1).replace(" ", "") == "16:9" else "9:16"


def _normalised_pair_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _paired_thumbnail_id(blueprint_id: Any, pairs: Mapping[str, str]) -> str:
    wanted = str(blueprint_id or "").strip()
    if not wanted:
        return ""
    if wanted in pairs:
        return str(pairs[wanted] or "")
    wanted_key = _normalised_pair_key(wanted)
    for key, value in pairs.items():
        if _normalised_pair_key(key) == wanted_key:
            return str(value or "")
    return ""


def thumbnail_blueprint_for_blueprint(blueprint_id: Any, format_value: Any = "") -> dict[str, Any]:
    """Resolve the visual pair for a script Blueprint, falling back to Generic."""
    paired_id = _paired_thumbnail_id(blueprint_id, _pair_state())
    if isinstance(paired_id, list):
        paired_id = paired_id[0] if paired_id else ""
    return resolve_thumbnail_blueprint(paired_id or _generic_thumbnail_blueprint_id(format_value))


def _pair_state() -> dict[str, str]:
    result: dict[str, str] = {}
    for path in (SEED_BLUEPRINTS / "thumbnail_blueprint_pairs.json", BLUEPRINTS / "thumbnail_blueprint_pairs.json"):
        try:
            value = __import__("json").loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(value, dict):
            result.update({str(k): str(v) for k, v in value.items()})
    return result


def thumbnail_blueprint_associations() -> dict[str, str]:
    return _pair_state()


def save_thumbnail_blueprint_pair(thumbnail_id: str, blueprint_id: str) -> None:
    pairs = _pair_state()
    if blueprint_id:
        pairs[str(blueprint_id)] = str(thumbnail_id)
    else:
        for key, value in list(pairs.items()):
            if value == thumbnail_id:
                pairs.pop(key, None)
    atomic_write(BLUEPRINTS / "thumbnail_blueprint_pairs.json", pairs)


def save_thumbnail_blueprint_pairs(thumbnail_id: str, blueprint_ids: list[str]) -> None:
    """Associate one thumbnail blueprint with any number of script blueprints."""
    selected = {str(item).strip() for item in blueprint_ids if str(item).strip()}
    pairs = _pair_state()
    for key, value in list(pairs.items()):
        values = value if isinstance(value, list) else [value]
        if str(key) in selected:
            continue
        if str(thumbnail_id) in {str(item) for item in values}:
            pairs.pop(key, None)
    for blueprint_id in selected:
        pairs[blueprint_id] = str(thumbnail_id)
    atomic_write(BLUEPRINTS / "thumbnail_blueprint_pairs.json", pairs)


def generate_thumbnail_blueprint(
    settings: Mapping[str, Any],
    *,
    source_url: str,
    niche: str,
    channel_name: str = "",
    videos: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    clean_niche = str(niche or "General").strip() or "General"
    samples = list(videos or [])[:10]
    sample_text = "\n".join(
        f"- Title: {item.get('title', '')}\n  URL: {item.get('url', '')}\n  Thumbnail URL: {item.get('thumbnail_url', '')}"
        for item in samples
    ) or "- No public sample videos were available; produce a clearly marked baseline system from the niche."
    user_prompt = f"Niche: {clean_niche}\nChannel: {channel_name}\nSource: {source_url}\nReference videos:\n{sample_text}\nReturn JSON with one key content containing only the complete Markdown document."
    try:
        routed = route_llm_json(settings, PROMPT_MASTER, user_prompt)
        content = str(routed.payload.get("content") or "").strip()
    except Exception as exc:
        raise ValueError(f"Não foi possível gerar o Thumbnail Blueprint no provider configurado: {exc}") from exc
    if not content:
        raise ValueError("O provider não devolveu um documento Thumbnail Blueprint válido.")
    if not content.startswith("#"):
        content = f"# {_record_name(clean_niche)}\n\n" + content
    return {
        "id": _record_name(clean_niche),
        "name": _record_name(clean_niche),
        "niche": clean_niche,
        "channel_name": channel_name,
        "source_url": source_url,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "version": 1,
        "sample_videos": samples,
        "content": content.rstrip() + "\n",
    }


def save_thumbnail_blueprint(document: Mapping[str, Any]) -> Path:
    raw_name = str(document.get("niche") or document.get("name") or "General").strip()
    raw_name = re.sub(r"_Thumbnail_Blueprint$", "", raw_name, flags=re.IGNORECASE)
    name = _record_name(raw_name)
    folder = BLUEPRINTS / "thumbnails"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{name}.md"
    content = str(document.get("content") or "").strip()
    if not content:
        raise ValueError("O documento Thumbnail Blueprint não pode ficar vazio.")
    front = ["---", f"type: thumbnail_blueprint", f"id: {name}", f"name: {name}", f"niche: {document.get('niche', '')}", f"source_url: {document.get('source_url', '')}", f"created_at: {document.get('created_at', '')}", "---", ""]
    target.write_text("\n".join(front) + content + "\n", encoding="utf-8")
    return target


def list_thumbnail_blueprint_documents() -> list[Path]:
    folder = BLUEPRINTS / "thumbnails"
    folder.mkdir(parents=True, exist_ok=True)
    return sorted(folder.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)


# ---------------------------------------------------------------------------
# Music Thumbnail Blueprints — EXCLUSIVOS dos clips de música.
#
# Vivem numa pasta própria (seed/blueprints/music_thumbnails/ -> BLUEPRINTS/
# music_thumbnails/), separada dos Thumbnail Blueprints de VÍDEO
# (thumbnails/). O catálogo e o loader de vídeo (thumbnail_blueprint_catalog,
# resolve_thumbnail_blueprint) NUNCA os vêem, e os loaders daqui só leem esta
# pasta. É a fronteira que impede FINANCE/etc. de aparecer na Criação de
# Músicas e impede um blueprint de música de ser usado por um vídeo Pexels/
# Text-to-Images.
# ---------------------------------------------------------------------------


def list_music_thumbnail_blueprints() -> list[tuple[str, str]]:
    """Catálogo exclusivo (id, rótulo) dos Music Thumbnail Blueprints.

    O dropdown "Music Thumbnail Blueprint" da Criação de Músicas usa apenas
    esta lista — nunca o thumbnail_blueprint_catalog de vídeo.
    """
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for folder in (MUSIC_THUMBNAIL_BLUEPRINTS, SEED_MUSIC_THUMBNAIL_BLUEPRINTS):
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.md"), key=lambda item: item.name):
            if path.stem in seen:
                continue
            seen.add(path.stem)
            result.append((path.stem, path.stem))
    return result


def resolve_music_thumbnail_blueprint(identifier: Any) -> dict[str, Any]:
    """Resolve um Music Thumbnail Blueprint pelo id, lendo só esta pasta.

    Devolve {} quando vazio; devolve {"id","name"} sem ``content`` quando o id
    não existe (o chamador — pipeline de música — trata a ausência de conteúdo
    como blueprint não selecionado).
    """
    wanted = str(identifier or "").strip()
    if not wanted:
        return {}
    for folder in (MUSIC_THUMBNAIL_BLUEPRINTS, SEED_MUSIC_THUMBNAIL_BLUEPRINTS):
        for path in folder.glob("*.md"):
            if path.stem == wanted or path.name == wanted:
                return {"id": path.stem, "name": path.stem, "path": str(path), "content": path.read_text(encoding="utf-8")}
    return {"id": wanted, "name": wanted}


def music_thumbnail_blueprint_for_task(channel: Mapping[str, Any], task: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve o Music Thumbnail Blueprint: tarefa primeiro, canal como default.

    O canal pode definir ``default_music_thumbnail_blueprint_id`` (opcional); a
    tarefa carrega ``music_thumbnail_blueprint_id``. Sem fallback genérico: um
    clip de música sem blueprint selecionado permanece sem blueprint.
    """
    direct = str(task.get("music_thumbnail_blueprint_id") or "").strip()
    if not direct and isinstance(channel, Mapping):
        direct = str(channel.get("default_music_thumbnail_blueprint_id") or "").strip()
    return resolve_music_thumbnail_blueprint(direct)
