"""Persistent local notifications for Thunderbolt activity completion events."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from . import storage

NOTIFICATIONS_FILE = "notifications.json"
MAX_NOTIFICATIONS = 500

EVENT_CATALOG: tuple[dict[str, str], ...] = (
    {"code": "video_completed", "category": "Produção", "label": "Vídeo concluído", "description": "Quando uma tarefa de vídeo chegar ao estado final."},
    {"code": "music_completed", "category": "Produção", "label": "Música concluída", "description": "Quando uma tarefa musical ou um ficheiro musical terminar de ser guardado."},
    {"code": "standalone_script_generated", "category": "Roteiros", "label": "Roteiro autónomo gerado", "description": "Quando um roteiro independente terminar de ser gerado."},
    {"code": "music_lyrics_generated", "category": "Roteiros", "label": "Letra de música gerada", "description": "Quando uma letra de música independente terminar de ser gerada."},
    {"code": "script_stage_completed", "category": "Pipeline", "label": "Etapa de roteiro concluída", "description": "Quando a etapa de roteiro de uma tarefa terminar."},
    {"code": "title_generation_completed", "category": "Pipeline", "label": "Títulos gerados", "description": "Quando o pacote de títulos terminar de ser gerado."},
    {"code": "thumbnail_generation_completed", "category": "Pipeline", "label": "Thumbnail gerada", "description": "Quando a imagem final da thumbnail for criada."},
    {"code": "influencer_content_completed", "category": "AI Influencers", "label": "Conteúdo de Influencer concluído", "description": "Quando uma imagem ou vídeo de AI Influencers terminar de ser gerado."},
    {"code": "influencer_content_failed", "category": "AI Influencers", "label": "Conteúdo de Influencer falhou", "description": "Quando uma imagem ou vídeo de AI Influencers terminar com erro."},
    {"code": "blueprint_completed", "category": "Pipeline", "label": "Blueprint criado ou importado", "description": "Quando um Blueprint for criado, importado ou guardado."},
    {"code": "branding_completed", "category": "Pipeline", "label": "Branding criado ou importado", "description": "Quando um Branding for criado, importado ou guardado."},
    {"code": "niche_analysis_completed", "category": "Pipeline", "label": "Análise de nicho concluída", "description": "Quando uma análise Kaggle ou Apify terminar com resultados."},
    {"code": "cuts_completed", "category": "Edição", "label": "Cortes concluídos", "description": "Quando a geração de cortes terminar com um manifesto completo."},
    {"code": "metadata_cleaning_completed", "category": "Edição", "label": "Metadados limpos", "description": "Quando uma cópia com metadados limpos for criada."},
    {"code": "python_edit_completed", "category": "Edição", "label": "Edição Python concluída", "description": "Quando uma operação do Editor Python guardar o artefacto."},
    {"code": "media_download_completed", "category": "Edição", "label": "Download Mídia concluído", "description": "Quando um vídeo ou áudio terminar de ser descarregado com sucesso."},
    {"code": "media_download_failed", "category": "Edição", "label": "Download Mídia falhou", "description": "Quando um download de vídeo ou áudio terminar com erro."},
    {"code": "automation_completed", "category": "Automação", "label": "Automação concluída", "description": "Quando o worker concluir o lote agendado de um canal."},
    {"code": "automation_failed", "category": "Automação", "label": "Automação falhou", "description": "Quando uma execução automática terminar com erro."},
    {"code": "subtitles_reapplied", "category": "Produção", "label": "Legendas reaplicadas", "description": "Quando a config de legendas do canal é reaplicada manualmente a um vídeo."},
    {"code": "activity_failed", "category": "Sistema", "label": "Actividade falhou", "description": "Quando uma tarefa ou operação persistida terminar em erro."},
    {"code": "session_info_expiring", "category": "Autenticação", "label": "SessionInfo a expirar", "description": "Quando o token sessionInfo de uma conta Google/YouTube se aproximar da expiração estimada."},
    {"code": "session_info_expired", "category": "Autenticação", "label": "SessionInfo expirado", "description": "Quando o token sessionInfo de uma conta Google/YouTube ultrapassar a expiração estimada."},
    {"code": "upload_youtube_success", "category": "Upload", "label": "Upload YouTube concluído", "description": "Quando um vídeo for publicado num canal YouTube."},
    {"code": "upload_tiktok_success", "category": "Upload", "label": "Upload TikTok concluído", "description": "Quando um vídeo for publicado numa conta TikTok."},
    {"code": "upload_instagram_success", "category": "Upload", "label": "Upload Instagram concluído", "description": "Quando um vídeo for publicado num perfil Instagram."},
    {"code": "upload_facebook_pages_success", "category": "Upload", "label": "Upload Facebook Pages concluído", "description": "Quando um vídeo for publicado numa Facebook Page."},
    {"code": "upload_postiz_success", "category": "Upload", "label": "Upload Postiz concluído", "description": "Quando um vídeo for enviado e publicado através do Postiz."},
    {"code": "upload_upload_post_success", "category": "Upload", "label": "Upload-Post concluído", "description": "Quando um vídeo for aceite pelo Upload-Post para publicação nas plataformas seleccionadas."},
    {"code": "mcp_operation_completed", "category": "Integrações", "label": "Operação MCP concluída", "description": "Quando uma operação mutável de integração MCP terminar com sucesso."},
)
EVENTS_BY_CODE = {item["code"]: item for item in EVENT_CATALOG}
LOGGER = logging.getLogger(__name__)

SENSITIVE_MARKERS = (
    "token",
    "secret",
    "api_key",
    "apikey",
    "cookie",
    "password",
    "authorization",
    "sessioninfo",
    "session_info",
    "access_token",
    "client_secret",
    "sid",
    "ssid",
    "hsid",
    "apisid",
)


def notification_event_catalog() -> list[dict[str, str]]:
    return [dict(item) for item in EVENT_CATALOG]


def default_notification_preferences() -> dict[str, bool]:
    return {item["code"]: True for item in EVENT_CATALOG}


def notification_preferences() -> dict[str, bool]:
    settings = storage.read_json("settings.json", {})
    raw = settings.get("notification_preferences", {}) if isinstance(settings, dict) else {}
    raw = raw if isinstance(raw, dict) else {}
    preferences = default_notification_preferences()
    for code in preferences:
        if code in raw:
            preferences[code] = bool(raw[code])
    return preferences


def save_notification_preferences(preferences: dict[str, Any]) -> dict[str, bool]:
    settings = storage.read_json("settings.json", {})
    existing = settings.get("notification_preferences", {}) if isinstance(settings, dict) else {}
    existing = dict(existing) if isinstance(existing, dict) else {}
    for code in EVENTS_BY_CODE:
        if code in preferences:
            existing[code] = bool(preferences[code])
    settings["notification_preferences"] = existing
    storage.write_json("settings.json", settings)
    return notification_preferences()


def _redact_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    pattern = r"(?i)(api[_ -]?key|client[_ -]?secret|access[_ -]?token|authorization|bearer|session[_ -]?info)\s*[:=]\s*[^\s,;]+"
    text = re.sub(pattern, r"\1=[redacted]", text)
    return re.sub(r"(?i)\bbearer\s+[^\s,;]+", "Bearer [redacted]", text)


def _safe_metadata(value: Any, *, key: str = "") -> Any:
    normalized_key = re.sub(r"[^a-z0-9_]", "", key.lower())
    if any(marker in normalized_key for marker in SENSITIVE_MARKERS):
        return "[redacted]"
    if isinstance(value, dict):
        return {str(item_key): _safe_metadata(item_value, key=str(item_key)) for item_key, item_value in value.items() if str(item_key).lower() not in {"payload", "response", "headers"}}
    if isinstance(value, list):
        return [_safe_metadata(item) for item in value[:50]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return _redact_text(value) if isinstance(value, str) else value
    return _redact_text(value)


def _history() -> list[dict[str, Any]]:
    saved = storage.read_json(NOTIFICATIONS_FILE, [])
    if not isinstance(saved, list):
        return []
    return [item for item in saved if isinstance(item, dict)]


def _dispatch_telegram_notification(entry: dict[str, Any]) -> None:
    """Deliver a persisted event to Telegram without affecting local flows."""
    try:
        settings = storage.read_json("settings.json", {})
        if not isinstance(settings, dict) or not bool(settings.get("telegram_enabled", False)):
            return
        from integrations.telegram_gateway import send_notification_to_telegram

        result = send_notification_to_telegram(entry, settings)
        if not result.ok:
            error_type = result.data.get("error_type") if isinstance(result.data, dict) else ""
            if error_type != "missing_configuration":
                LOGGER.warning("Telegram notification delivery failed (%s).", error_type or "unknown_error")
    except Exception as exc:
        # External notification delivery must never break production, uploads or UI.
        LOGGER.warning("Telegram notification delivery failed (%s).", type(exc).__name__)


def record_notification(
    event_type: str,
    title: str,
    message: str,
    *,
    metadata: dict[str, Any] | None = None,
    dedupe_key: str = "",
) -> dict[str, Any] | None:
    event = EVENTS_BY_CODE.get(str(event_type))
    if event is None:
        raise ValueError(f"Tipo de notificação desconhecido: {event_type}")
    if not notification_preferences().get(event_type, True):
        return None
    history = _history()
    if dedupe_key:
        for existing in history:
            if str(existing.get("dedupe_key") or "") == dedupe_key:
                return None
    created_at = datetime.now(timezone.utc).isoformat()
    entry = {
        "id": f"notification_{uuid.uuid4().hex[:12]}",
        "event_type": event_type,
        "category": event["category"],
        "label": event["label"],
        "title": _redact_text(title),
        "message": _redact_text(message),
        "created_at": created_at,
        "read": False,
        "metadata": _safe_metadata(metadata or {}),
        "dedupe_key": str(dedupe_key or ""),
    }
    storage.write_json(NOTIFICATIONS_FILE, [entry, *history][:MAX_NOTIFICATIONS])
    _dispatch_telegram_notification(entry)
    return entry


def list_notifications(*, limit: int = 200, category: str = "", unread_only: bool = False) -> list[dict[str, Any]]:
    entries = _history()
    if category:
        entries = [item for item in entries if item.get("category") == category]
    if unread_only:
        entries = [item for item in entries if not item.get("read")]
    entries.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return entries[: max(1, min(int(limit), MAX_NOTIFICATIONS))]


def unread_notification_count() -> int:
    return sum(1 for item in _history() if not item.get("read"))


def mark_notification_read(notification_id: str) -> bool:
    history = _history()
    changed = False
    for item in history:
        if str(item.get("id")) == str(notification_id):
            item["read"] = True
            changed = True
            break
    if changed:
        storage.write_json(NOTIFICATIONS_FILE, history)
    return changed


def mark_all_notifications_read() -> int:
    history = _history()
    changed = sum(1 for item in history if not item.get("read"))
    if changed:
        for item in history:
            item["read"] = True
        storage.write_json(NOTIFICATIONS_FILE, history)
    return changed


def clear_notifications() -> int:
    count = len(_history())
    storage.write_json(NOTIFICATIONS_FILE, [])
    return count


def _task_notifications() -> int:
    created = 0
    # 0.9.94: leitura migrada (import deferido — domain importa este módulo).
    from hermes_ui.domain import load_tasks

    tasks = load_tasks()
    if not isinstance(tasks, list):
        return 0
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("id") or "")
        if not task_id:
            continue
        state = str(task.get("state") or "")
        title = str(task.get("title") or task.get("topic") or "Actividade")
        channel = str(task.get("channel_name") or "Canal")
        if state == "failed":
            failure_api = str(task.get("failure_api") or "API não identificada (falha anterior)").strip()
            if record_notification(
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
            ):
                created += 1
            continue
        if state != "done":
            continue
        artifacts = task.get("artifacts") if isinstance(task.get("artifacts"), dict) else {}
        if bool(task.get("music_mode")) or str(task.get("style_wide") or "") == "music":
            event_type = "music_completed"
            label = "Música concluída"
        elif str(task.get("stage") or "") == "script" and not artifacts.get("video"):
            event_type = "script_stage_completed"
            label = "Roteiro concluído"
        else:
            event_type = "video_completed"
            label = "Vídeo concluído"
        if record_notification(event_type, f"{label}: {title}", f"A actividade de {channel} terminou com sucesso.", metadata={"task_id": task_id, "channel_name": channel, "stage": task.get("stage") or "", "creation_mode": task.get("creation_mode") or ""}, dedupe_key=f"task:{task_id}:{event_type}:done"):
            created += 1
        if isinstance(task.get("title_candidates"), list) and task.get("title_candidates"):
            if record_notification("title_generation_completed", f"Títulos gerados: {title}", f"O pacote de títulos para {channel} terminou de ser gerado.", metadata={"task_id": task_id, "channel_name": channel}, dedupe_key=f"task:{task_id}:titles"):
                created += 1
        if str(task.get("thumbnail_status") or "") == "generated" or artifacts.get("thumbnail"):
            if record_notification("thumbnail_generation_completed", f"Thumbnail gerada: {title}", f"A thumbnail de {channel} está pronta.", metadata={"task_id": task_id, "channel_name": channel}, dedupe_key=f"task:{task_id}:thumbnail"):
                created += 1
    return created


def _upload_notifications() -> int:
    created = 0
    uploads = storage.read_json("uploads.json", [])
    if not isinstance(uploads, list):
        return 0
    event_by_destination = {
        "youtube": "upload_youtube_success",
        "tiktok": "upload_tiktok_success",
        "instagram": "upload_instagram_success",
        "facebook pages": "upload_facebook_pages_success",
        "facebook_pages": "upload_facebook_pages_success",
        "postiz": "upload_postiz_success",
        "upload-post": "upload_upload_post_success",
        "upload_post": "upload_upload_post_success",
        "youtube direct frontend": "upload_youtube_success",
    }
    for upload in uploads:
        if not isinstance(upload, dict) or str(upload.get("status") or "").lower() not in {"published", "success", "done"}:
            continue
        upload_id = str(upload.get("id") or "")
        task_id = str(upload.get("task_id") or upload_id or uuid.uuid4().hex[:8])
        upload_created_at = str(upload.get("created_at") or "")
        destination = str(upload.get("destination") or "Upload").strip()
        event_type = event_by_destination.get(destination.lower(), "upload_youtube_success" if destination.lower().startswith("youtube") else "upload_postiz_success" if destination.lower().startswith("postiz") else "upload_youtube_success")
        target = upload.get("target") if isinstance(upload.get("target"), dict) else {}
        target_name = str(target.get("name") or target.get("label") or target.get("handle") or target.get("username") or "destino seleccionado")
        if record_notification(event_type, f"Upload concluído: {destination}", f"O vídeo foi enviado com sucesso para {target_name}.", metadata={"task_id": task_id, "destination": destination, "target": target, "route": (upload.get("data") or {}).get("route") if isinstance(upload.get("data"), dict) else ""}, dedupe_key=f"upload:{upload_id or task_id}:{destination.lower()}:{upload_created_at}"):
            created += 1
    return created


def _script_notifications() -> int:
    created = 0
    records = storage.read_json("scripts.json", [])
    if not isinstance(records, list):
        return 0
    for record in records:
        if not isinstance(record, dict) or not record.get("id"):
            continue
        event_type = "music_lyrics_generated" if str(record.get("document_type") or "") == "music_lyrics" else "standalone_script_generated"
        label = "Letra de música" if event_type == "music_lyrics_generated" else "Roteiro autónomo"
        document_id = str(record["id"])
        dedupe_key = str(record.get("notification_dedupe_key") or f"script:{document_id}:generated")
        if record_notification(event_type, f"{label} gerado: {record.get('title') or 'Documento'}", f"O documento foi guardado no histórico de roteiros.", metadata={"document_id": document_id, "document_type": record.get("document_type") or ""}, dedupe_key=dedupe_key):
            created += 1
    return created


def _automation_notifications() -> int:
    created = 0
    worker = storage.read_json("automation_worker.json", {})
    last_runs = worker.get("last_runs", {}) if isinstance(worker, dict) else {}
    if isinstance(last_runs, dict):
        for channel_id, run in last_runs.items():
            if not isinstance(run, dict) or not run.get("batch_id"):
                continue
            if record_notification("automation_completed", "Automação concluída", f"O lote agendado do canal {channel_id} foi criado com sucesso.", metadata={"channel_id": channel_id, "batch_id": run.get("batch_id"), "time": run.get("time") or ""}, dedupe_key=f"automation:{run['batch_id']}"):
                created += 1
    return created


def _generic_completion_notifications() -> int:
    created = 0
    cuts = storage.read_json("cuts_runs.json", [])
    if isinstance(cuts, list):
        for run in cuts:
            if isinstance(run, dict) and str(run.get("status") or "") == "complete" and run.get("id"):
                if record_notification("cuts_completed", "Cortes concluídos", "A geração de cortes terminou com um manifesto completo.", metadata={"run_id": run.get("id")}, dedupe_key=f"cuts:{run['id']}"):
                    created += 1
    indexed_sources = (
        ("metadata_edits.json", "metadata_cleaning_completed", "Metadados limpos", "metadata edit"),
        ("python_editor_edits.json", "python_edit_completed", "Edição Python concluída", "Python edit"),
    )
    for filename, event_type, label, source_label in indexed_sources:
        records = storage.read_json(filename, [])
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict) or not record.get("id"):
                continue
            record_id = str(record["id"])
            output_name = str(record.get("output_name") or "artefacto guardado")
            if record_notification(event_type, f"{label}: {output_name}", f"A operação {source_label} terminou com sucesso.", metadata={"record_id": record_id, "output_name": output_name, "operation": record.get("operation") or ""}, dedupe_key=f"{event_type}:{record_id}"):
                created += 1
    apify_runs = storage.read_json("niche_apify_runs.json", [])
    if isinstance(apify_runs, list):
        for run in apify_runs:
            status = str(run.get("status") or "").lower() if isinstance(run, dict) else ""
            if status in {"succeeded", "success", "completed", "complete"} and run.get("run_id"):
                run_id = str(run["run_id"])
                if record_notification("niche_analysis_completed", "Análise de nicho concluída", f"A pesquisa Apify terminou com {run.get('item_count', 0)} vídeo(s) recebido(s).", metadata={"run_id": run_id, "item_count": run.get("item_count", 0)}, dedupe_key=f"niche:apify:{run_id}"):
                    created += 1
    return created


def reconcile_persisted_notifications() -> int:
    """Emit idempotent events for completions written by other local processes."""
    total = 0
    for resolver in (_task_notifications, _upload_notifications, _script_notifications, _automation_notifications, _generic_completion_notifications):
        try:
            total += resolver()
        except Exception:
            # Notifications must never prevent the main production/upload flow.
            continue
    return total
