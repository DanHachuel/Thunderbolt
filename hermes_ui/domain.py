from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Any

from .notifications import record_notification
from .storage import StorageIntegrityError, append_json, now, read_json, update_json, write_json
from .thumbnail_blueprints import thumbnail_blueprint_for_channel

STAGES = ["niche", "blueprint", "brand", "topic", "script", "title", "keywords", "video", "thumbnail_prompt", "thumbnail", "upload"]
# Ordem executada pelo worker. Cada etapa só é executada quando o seu artefacto
# ainda não existe; os artefactos persistidos tornam a cascata retomável.
CASCADE_STAGE_ORDER = ("topic", "script", "title", "keywords", "video", "thumbnail_prompt", "thumbnail", "upload")
LEGACY_STAGES = {"edit"}
VALID_STATES = {"to_do", "doing", "blocked", "done", "failed", "cancelled"}


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9À-ÿ]+", "-", value.strip().lower()).strip("-")
    return value or "item"


def composio_connected_account_id_from_channel_name(name: str) -> str:
    """Create the editable Composio account alias used by a YouTube channel."""
    normalized = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[A-Za-z0-9]+", normalized)
    return "-".join(words)


def make_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def create_channel(name: str, url: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    channel = {
        "id": make_id("channel"),
        "youtube_channel_id": "",
        "google_account_id": "",
        "google_account_email": "",
        # A technical Composio connected-account ID is discovered after the
        # channel exists; a channel name/alias is never a valid fallback ID.
        "composio_connected_account_id": "",
        "composio": {},
        "name": name.strip(),
        "url": url.strip(),
        "platform": "youtube",
        "social_network": "YouTube",
        "handle": "",
        "bio": "",
        "bio_raw": "",
        "description": "",
        "description_source": "",
        "niche": "",
        "reference_channels": [],
        "thumbnail_url": "",
        "avatar_url": "",
        "subscriber_count": None,
        "post_count": None,
        "following_count": None,
        "video_count": None,
        "view_count": None,
        "metrics_source": "manual",
        "public_lookup": False,
        "last_public_lookup_at": None,
        "country": "",
        "character_id": "",
        "last_youtube_sync": None,
        "language": "Português",
        "blueprint_id": "",
        "default_blueprint_id": "",
        "thumbnail_blueprint_id": "",
        "default_thumbnail_blueprint_id": "",
        "style_wide": "pexels",
        "voice": "",
        "default_voice": "",
        "default_enable_subtitles": True,
        "default_subtitle_font": "MicrosoftYaHeiBold.ttc",
        "default_subtitle_position": "Bottom (Recommended)",
        "default_subtitle_color": "#FFFFFF",
        "default_subtitle_background": True,
        "default_subtitle_background_color": "#000000",
        "default_subtitle_rounded_background": False,
        "default_subtitle_font_size": 60,
        "default_subtitle_outline": "#000000",
        "default_subtitle_outline_width": 1.5,
        "default_background_music_source": "Sem música",
        "default_background_music_volume": "20%",
        "delegated_session_id": "",
        "automation_on": False,
        "automation_time": "00:00",
        "active": True,
        "daily_limit": 1,
        "default_video_duration_minutes": None,
        "import_source": "manual",
        "backlog_total": 0,
        "created_at": now(),
        "updated_at": now(),
    }
    if metadata:
        channel.update({k: v for k, v in metadata.items() if k in channel and k != "id"})
    if str(channel.get("platform") or "").strip().casefold() == "youtube":
        channel.setdefault("default_maximum_clip_duration", 5)
        channel.setdefault("default_video_aspect_ratio", "Landscape 16:9")
        channel.setdefault("default_enable_subtitles", True)
        channel.setdefault("default_background_music_source", "Sem música")
        channel.setdefault("average_video_time", "20:00")
    channels = read_json("channels.json", [])
    channels.append(channel)
    write_json("channels.json", channels)
    return channel


def update_channel(channel_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    channels = read_json("channels.json", [])
    for channel in channels:
        if channel.get("id") == channel_id:
            channel.update(updates)
            channel["updated_at"] = now()
            write_json("channels.json", channels)
            return channel
    return None


def set_channel_defaults(channel_id: str, blueprint_id: str = "", voice: str = "") -> dict[str, Any] | None:
    """Persist the canonical and legacy aliases for a channel's generation defaults."""
    blueprint = str(blueprint_id or "").strip()
    selected_voice = str(voice or "").strip()
    return update_channel(channel_id, {
        "blueprint_id": blueprint,
        "default_blueprint_id": blueprint,
        "voice": selected_voice,
        "default_voice": selected_voice,
    })


def delete_channel(channel_id: str) -> dict[str, Any] | None:
    """Remove apenas o cadastro do canal, preservando tarefas e artefactos."""
    channels = read_json("channels.json", [])
    remaining = [channel for channel in channels if channel.get("id") != channel_id]
    if len(remaining) == len(channels):
        return None
    removed = next(channel for channel in channels if channel.get("id") == channel_id)
    write_json("channels.json", remaining)
    return removed


def create_batch(mode: str, channel_ids: list[str], topic: str, quantity: int, options: dict[str, Any]) -> dict[str, Any]:
    batch = {
        "id": make_id("batch"),
        "mode": mode,
        "channel_ids": channel_ids,
        "topic": topic.strip(),
        "quantity": quantity,
        "status": "to_do",
        "created_at": now(),
        "options": options,
    }
    append_json("batches.json", batch)
    return batch


def create_tasks_for_batch(batch: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand a batch into tasks, allowing independent payloads for each channel."""
    channels = {c["id"]: c for c in read_json("channels.json", [])}
    options = batch.get("options") or {}
    channel_payloads = options.get("channel_payloads") or {}
    target_channels = batch.get("channel_ids") or []
    count = max(1, int(batch.get("quantity") or 1))
    if batch.get("mode") == "general":
        count = 1
    created: list[dict[str, Any]] = []
    for channel_id in target_channels:
        channel = channels.get(channel_id, {})
        payload = channel_payloads.get(channel_id) if isinstance(channel_payloads, dict) else None
        payload = payload if isinstance(payload, dict) else {}
        for index in range(count):
            default_topic = str(batch.get("topic") or "").strip()
            topic_source = str(payload.get("topic_source") or options.get("topic_source") or "manual")
            payload_topic = str(payload.get("topic") or "").strip()
            if count == 1:
                topic = payload_topic or default_topic
            elif payload_topic or default_topic:
                topic = payload_topic or f"{default_topic} — variação {index + 1}"
            else:
                topic = ""
            topic = topic.strip()
            pending_creative = not topic and topic_source in {"auto", "llm_pending"}
            if not topic and not pending_creative:
                topic = f"Vídeo para {channel.get('name', 'Canal')}"
            title = str(payload.get("title") or ("" if pending_creative else topic)).strip()
            artifacts = dict(payload.get("artifacts") or {})
            thumbnail_variants = payload.get("thumbnail_variants") if isinstance(payload.get("thumbnail_variants"), list) else []
            thumbnail_variant = payload.get("thumbnail_variant") if isinstance(payload.get("thumbnail_variant"), dict) else {}
            if count > 1 and thumbnail_variants:
                candidate = thumbnail_variants[index % len(thumbnail_variants)]
                if isinstance(candidate, dict):
                    thumbnail_variant = candidate
            thumbnail_path = str(thumbnail_variant.get("image_path") or payload.get("thumbnail_path") or "").strip()
            thumbnail_prompt = str(thumbnail_variant.get("image_prompt") or payload.get("thumbnail_prompt") or "").strip()
            thumbnail_text = str(thumbnail_variant.get("overlay_text") or payload.get("thumbnail_text") or "").strip()
            thumbnail_status = str(payload.get("thumbnail_status") or ("generated" if thumbnail_path else "not_generated"))
            if thumbnail_path:
                artifacts.setdefault("thumbnail", thumbnail_path)
            initial_stage = "topic" if pending_creative else "script"
            channel_generation_defaults = {
                key.removeprefix("default_"): channel.get(key, default)
                for key, default in {
                    "default_enable_subtitles": True,
                    "default_subtitle_font": "MicrosoftYaHeiBold.ttc",
                    "default_subtitle_position": "Bottom (Recommended)",
                    "default_subtitle_color": "#FFFFFF",
                    "default_subtitle_background": True,
                    "default_subtitle_background_color": "#000000",
                    "default_subtitle_rounded_background": False,
                    "default_subtitle_font_size": 60,
                    "default_subtitle_outline": "#000000",
                    "default_subtitle_outline_width": 1.5,
                "default_background_music_source": "Sem música",
                "default_background_music_volume": "20%",
                }.items()
            }
            if str(channel.get("platform") or "").strip().casefold() == "youtube":
                channel_generation_defaults.update({
                    "maximum_clip_duration": channel.get("default_maximum_clip_duration", 5),
                    "video_aspect_ratio": channel.get("default_video_aspect_ratio", "Landscape 16:9"),
                })
            configured_generation_settings = options.get("generation_settings") if isinstance(options.get("generation_settings"), dict) else {}
            payload_generation_settings = payload.get("generation_settings") if isinstance(payload.get("generation_settings"), dict) else {}
            generation_settings = {**channel_generation_defaults, **configured_generation_settings, **payload_generation_settings}
            # Em automações, as definições guardadas no canal são a fonte de
            # verdade. O payload pendente pode ter sido criado antes de o
            # utilizador alterar as legendas e não deve desligá-las.
            if bool(options.get("automation_worker")):
                generation_settings.update(channel_generation_defaults)
            task = {
                "id": make_id("video"),
                "batch_id": batch["id"],
                "creation_mode": batch.get("mode", "single"),
                "channel_id": channel_id,
                "channel_name": channel.get("name", "Canal"),
                "platform": channel.get("platform", "youtube"),
                "topic": topic,
                "title": title,
                "topic_source": topic_source,
                "language": payload.get("language", options.get("language", channel.get("language", "Português"))),
                "format": payload.get("format", options.get("format", "portrait" if channel.get("platform") == "tiktok" else "wide")),
                "style_wide": payload.get("style_wide", options.get("style_wide", channel.get("style_wide", "pexels"))),
                "material_source": payload.get("material_source", options.get("material_source", channel.get("material_source", ""))),
                "style_ia": payload.get("style_ia", options.get("style_ia", "")),
                "music_mode": payload.get("music_mode", options.get("music_mode", False)),
                "music_path": payload.get("music_path", options.get("music_path", "")),
                "music_source": payload.get("music_source", options.get("music_source", "")),
                "background_mode": payload.get("background_mode", options.get("background_mode", "stock")),
                "generation_settings": generation_settings,
                "blueprint_id": payload.get("blueprint_id") or channel.get("default_blueprint_id") or channel.get("blueprint_id", ""),
                "blueprint_name": payload.get("blueprint_name", ""),
                "thumbnail_blueprint_id": payload.get("thumbnail_blueprint_id") or channel.get("default_thumbnail_blueprint_id") or channel.get("thumbnail_blueprint_id") or thumbnail_blueprint_for_channel({**channel, "thumbnail_blueprint_id": ""}, payload.get("format", options.get("format", ""))).get("id", ""),
                "voice": payload.get("voice") or channel.get("default_voice") or channel.get("voice", ""),
                "automation_on": bool(channel.get("automation_on", False)),
                "automation_time": channel.get("automation_time", "00:00"),
                "automation_worker": bool(options.get("automation_worker")),
                "thumbnail_variant": thumbnail_variant,
                "thumbnail_variants": thumbnail_variants,
                "thumbnail_prompt": thumbnail_prompt,
                "thumbnail_text": thumbnail_text,
                "thumbnail_status": thumbnail_status,
                "title_candidates": payload.get("title_candidates", []),
                "keywords": payload.get("keywords", options.get("keywords", [])),
                "ai_generation": payload.get("ai_generation", {}),
                "stage": initial_stage,
                "orchestration": {
                    "name": "local-cascade",
                    "stage_order": list(CASCADE_STAGE_ORDER),
                    "current_stage": initial_stage,
                    "completed_stages": [],
                    "resumable": True,
                    "last_transition_at": now(),
                },
                "state": "to_do",
                "progress": 0,
                "video_ready": bool(artifacts.get("video")),
                "artifacts": artifacts,
                "error": None,
                "created_at": now(),
                "updated_at": now(),
            }
            created.append(task)

    def persist_tasks(tasks: Any) -> list[dict[str, Any]]:
        if not isinstance(tasks, list):
            raise StorageIntegrityError("O ficheiro tasks.json não contém uma lista válida.")
        tasks.extend(created)
        return created

    update_json("tasks.json", [], persist_tasks)

    def persist_queues(queues: Any) -> dict[str, Any]:
        if not isinstance(queues, dict):
            raise StorageIntegrityError("O ficheiro queues.json não contém um objecto válido.")
        queues.setdefault("script", [])
        if not isinstance(queues["script"], list):
            queues["script"] = []
        queues["script"].extend(task["id"] for task in created)
        return queues

    update_json("queues.json", {}, persist_queues)
    return created


def update_channel_video(video_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    """Actualizar um vídeo remoto sincronizado ou um override local de vídeo do canal."""
    videos = read_json("channel_videos.json", [])
    for video in videos:
        if video.get("id") == video_id:
            video.update(updates)
            video["updated_at"] = now()
            write_json("channel_videos.json", videos)
            return video
    return None


def _notify_task_completion(task: dict[str, Any], previous_state: str = "") -> None:
    current_state = str(task.get("state") or "")
    task_id = str(task.get("id") or "")
    if not task_id or current_state == previous_state and current_state in {"done", "failed"}:
        return
    title = str(task.get("title") or task.get("topic") or "Actividade")
    channel = str(task.get("channel_name") or "Canal")
    if current_state == "failed":
        failure_api = str(task.get("failure_api") or "API não identificada (falha anterior)").strip()
        record_notification(
            "activity_failed",
            f"Actividade falhou: {title}",
            f"A actividade de {channel} terminou com erro. API/provider: {failure_api}.",
            metadata={
                "task_id": task_id,
                "channel_name": channel,
                "error": task.get("error") or "",
                "failure_api": task.get("failure_api") or "API não identificada (falha anterior)",
                "failure_provider": task.get("failure_provider") or "unknown",
                "failure_service": task.get("failure_service") or "Thunderbolt",
                "failure_route": task.get("failure_route") or "",
                "failure_config_fields": task.get("failure_config_fields") or "",
                "failure_stage": task.get("failure_stage") or task.get("failed_stage") or task.get("stage") or "pipeline",
            },
            dedupe_key=f"task:{task_id}:failed",
        )
        return
    if current_state != "done":
        return
    artifacts = task.get("artifacts") if isinstance(task.get("artifacts"), dict) else {}
    if bool(task.get("music_mode")) or str(task.get("style_wide") or "") == "music":
        event_type, label = "music_completed", "Música concluída"
    elif str(task.get("stage") or "") == "script" and not artifacts.get("video"):
        event_type, label = "script_stage_completed", "Roteiro concluído"
    else:
        event_type, label = "video_completed", "Vídeo concluído"
    record_notification(
        event_type,
        f"{label}: {title}",
        f"A actividade de {channel} terminou com sucesso.",
        metadata={"task_id": task_id, "channel_name": channel, "stage": task.get("stage") or "", "creation_mode": task.get("creation_mode") or ""},
        dedupe_key=f"task:{task_id}:{event_type}:done",
    )


def update_task(task_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    previous_state = ""

    def mutate(tasks: Any) -> dict[str, Any] | None:
        nonlocal previous_state
        if not isinstance(tasks, list):
            raise StorageIntegrityError("O ficheiro tasks.json não contém uma lista válida.")
        for task in tasks:
            if isinstance(task, dict) and task.get("id") == task_id:
                previous_state = str(task.get("state") or "")
                task.update(updates)
                task["updated_at"] = now()
                return task
        return None

    updated = update_json("tasks.json", [], mutate)
    if updated is not None:
        _notify_task_completion(updated, previous_state)
    return updated


def delete_task(task_id: str) -> dict[str, Any] | None:
    """Remove uma tarefa de vídeo da fila sem apagar os ficheiros dos artefactos."""
    normalized_id = str(task_id or "").strip()
    if not normalized_id:
        return None
    removed: dict[str, Any] | None = None

    def mutate(tasks: Any) -> list[dict[str, Any]]:
        nonlocal removed
        if not isinstance(tasks, list):
            raise StorageIntegrityError("O ficheiro tasks.json não contém uma lista válida.")
        for task in tasks:
            if isinstance(task, dict) and str(task.get("id") or "") == normalized_id:
                if str(task.get("state") or "") == "doing":
                    raise ValueError("Pare a tarefa antes de a remover da fila.")
                removed = task
                break
        if removed is not None:
            tasks[:] = [task for task in tasks if not (isinstance(task, dict) and str(task.get("id") or "") == normalized_id)]
        return tasks

    update_json("tasks.json", [], mutate)
    if removed is None:
        return None

    def clean_queues(queues: Any) -> dict[str, Any]:
        if not isinstance(queues, dict):
            raise StorageIntegrityError("O ficheiro queues.json não contém um objecto válido.")
        for queue_name, queue_items in list(queues.items()):
            if isinstance(queue_items, list):
                queues[queue_name] = [item for item in queue_items if str(item) != normalized_id]
        return queues

    update_json("queues.json", {}, clean_queues)
    return removed


def transition_task(task_id: str, state: str | None = None, stage: str | None = None, error: str | None = None) -> dict[str, Any] | None:
    if state and state not in VALID_STATES:
        raise ValueError(f"Estado inválido: {state}")
    previous_state = ""

    def mutate(tasks: Any) -> dict[str, Any] | None:
        nonlocal previous_state
        if not isinstance(tasks, list):
            raise StorageIntegrityError("O ficheiro tasks.json não contém uma lista válida.")
        for task in tasks:
            if not isinstance(task, dict) or task.get("id") != task_id:
                continue
            previous_state = str(task.get("state") or "")
            if state:
                task["state"] = state
                if state != "blocked":
                    task.pop("stop_reason", None)
            if stage:
                if stage not in STAGES and stage not in LEGACY_STAGES:
                    raise ValueError(f"Etapa inválida: {stage}")
                task["stage"] = stage
            if error is not None:
                task["error"] = error
            task["updated_at"] = now()
            return task
        return None

    updated = update_json("tasks.json", [], mutate)
    if updated is not None:
        _notify_task_completion(updated, previous_state)
    return updated


def stop_task_by_user(task_id: str) -> dict[str, Any] | None:
    """Stop a running video task and retain the user-originated reason for the UI."""
    task = transition_task(task_id, "blocked")
    if task is None:
        return None
    tasks = read_json("tasks.json", [])
    for persisted in tasks:
        if persisted.get("id") == task_id:
            persisted["stop_reason"] = "user"
            persisted["updated_at"] = now()
            write_json("tasks.json", tasks)
            return persisted
    return task


def retry_task_with_current_settings(task_id: str) -> dict[str, Any] | None:
    """Queue a failed or blocked task without persisting API credentials or provider snapshots.

    The pipeline reloads settings.json immediately before every execution, so a
    retry always uses the currently saved API keys, active provider priorities,
    and provider endpoints while retaining the task's completed artefacts.
    """
    def mutate(tasks: Any) -> dict[str, Any] | None:
        if not isinstance(tasks, list):
            raise StorageIntegrityError("O ficheiro tasks.json não contém uma lista válida.")
        for task in tasks:
            if not isinstance(task, dict) or task.get("id") != task_id:
                continue
            previous_state = str(task.get("state") or "")
            if previous_state not in {"failed", "blocked"}:
                raise ValueError("Apenas tarefas falhadas ou bloqueadas podem ser retomadas.")
            try:
                retry_count = int(task.get("retry_count") or 0)
            except (TypeError, ValueError):
                retry_count = 0
            task["state"] = "to_do"
            task["error"] = None
            task["retry_count"] = retry_count + 1
            task["retry_requested_at"] = now()
            task["retry_config_source"] = "settings.json_at_execution"
            for field in ("failure_api", "failure_provider", "failure_service", "failure_config_fields"):
                task.pop(field, None)
            task["updated_at"] = now()
            return task
        return None

    return update_json("tasks.json", [], mutate)


def _refresh_task_channel_video_settings(task: dict[str, Any]) -> None:
    """Apply the channel's current video defaults while preserving the saved script."""
    channel_id = str(task.get("channel_id") or "").strip()
    channels = read_json("channels.json", [])
    channel = next(
        (item for item in channels if isinstance(item, dict) and str(item.get("id") or "") == channel_id),
        None,
    ) if isinstance(channels, list) else None
    if not channel:
        return
    generation_settings = dict(task.get("generation_settings") or {})
    channel_defaults = {
        "enable_subtitles": ("default_enable_subtitles", True),
        "subtitle_font": ("default_subtitle_font", "MicrosoftYaHeiBold.ttc"),
        "subtitle_position": ("default_subtitle_position", "Bottom (Recommended)"),
        "subtitle_color": ("default_subtitle_color", "#FFFFFF"),
        "subtitle_background": ("default_subtitle_background", True),
        "subtitle_background_color": ("default_subtitle_background_color", "#000000"),
        "subtitle_rounded_background": ("default_subtitle_rounded_background", False),
        "subtitle_font_size": ("default_subtitle_font_size", 60),
        "subtitle_outline": ("default_subtitle_outline", "#000000"),
        "subtitle_outline_width": ("default_subtitle_outline_width", 1.5),
        "background_music_source": ("default_background_music_source", "Sem música"),
        "background_music_volume": ("default_background_music_volume", "20%"),
    }
    for setting_name, (channel_key, default) in channel_defaults.items():
        generation_settings[setting_name] = channel.get(channel_key, default)
    if str(channel.get("platform") or "").strip().casefold() == "youtube":
        generation_settings["maximum_clip_duration"] = channel.get("default_maximum_clip_duration", 5)
        generation_settings["video_aspect_ratio"] = channel.get("default_video_aspect_ratio", "Landscape 16:9")
    task["generation_settings"] = generation_settings
    task["voice"] = channel.get("default_voice") or channel.get("voice") or task.get("voice", "")
    task["thumbnail_blueprint_id"] = (
        channel.get("default_thumbnail_blueprint_id")
        or channel.get("thumbnail_blueprint_id")
        or task.get("thumbnail_blueprint_id")
        or thumbnail_blueprint_for_channel({**channel, "thumbnail_blueprint_id": ""}, task.get("format", "")).get("id", "")
    )
    task["blueprint_id"] = channel.get("default_blueprint_id") or channel.get("blueprint_id") or task.get("blueprint_id", "")
    if channel.get("style_wide"):
        task["style_wide"] = channel["style_wide"]


def remake_video_task(task_id: str) -> dict[str, Any] | None:
    """Queue a fresh video render while retaining the task's creative inputs.

    The persisted script, blueprint, keywords/tags, voice, thumbnail prompt/image,
    generation settings and any non-video creative artefacts are intentionally kept.
    The rendered video, generated narration/audio and publication result are
    invalidated so the worker rebuilds both audio and video from the script.
    """
    normalized_id = str(task_id or "").strip()

    def mutate(tasks: Any) -> dict[str, Any] | None:
        if not isinstance(tasks, list):
            raise StorageIntegrityError("O ficheiro tasks.json não contém uma lista válida.")
        for task in tasks:
            if not isinstance(task, dict) or str(task.get("id") or "") != normalized_id:
                continue
            if str(task.get("state") or "") == "doing":
                raise ValueError("Pare a tarefa antes de refazer o vídeo.")
            _refresh_task_channel_video_settings(task)
            artifacts = dict(task.get("artifacts") or {})
            artifacts.pop("video", None)
            artifacts.pop("upload", None)
            for audio_key in ("audio", "narration", "voiceover", "voiceover_audio", "audio_path", "narration_audio"):
                artifacts.pop(audio_key, None)
            try:
                remake_count = int(task.get("remake_count") or 0)
            except (TypeError, ValueError):
                remake_count = 0
            for field in (
                "video_log",
                "video_result",
                "video_helper_status",
                "video_elapsed_seconds",
                "audio_result",
                "audio_path",
                "narration_path",
                "generated_audio",
                "error",
            ):
                task.pop(field, None)
            task.update({
                "artifacts": artifacts,
                "stage": "video",
                "state": "to_do",
                "progress": 50,
                "video_ready": False,
                "audio_regeneration_requested": True,
                "audio_regeneration_requested_at": now(),
                "remake_requested_at": now(),
                "remake_count": remake_count + 1,
                "error": None,
                "updated_at": now(),
            })
            orchestration = dict(task.get("orchestration") or {})
            orchestration["current_stage"] = "video"
            orchestration["resumable"] = True
            orchestration["last_transition_at"] = now()
            task["orchestration"] = orchestration
            return task
        return None

    return update_json("tasks.json", [], mutate)


def pipeline_summary() -> dict[str, Any]:
    tasks = read_json("tasks.json", [])
    channels = read_json("channels.json", [])
    return {
        "channels": len(channels),
        "active_channels": sum(1 for c in channels if c.get("active")),
        "total_tasks": len(tasks),
        "done": sum(1 for t in tasks if t.get("state") == "done"),
        "pending": sum(1 for t in tasks if t.get("state") in {"to_do", "doing", "blocked"}),
        "failed": sum(1 for t in tasks if t.get("state") == "failed"),
        "doing": sum(1 for t in tasks if t.get("state") == "doing"),
    }
