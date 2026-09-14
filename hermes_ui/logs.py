"""Unified activity logs projected from Thunderbolt's persisted local state."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import storage
from .notifications import EVENTS_BY_CODE, list_notifications, reconcile_persisted_notifications

MAX_LOGS = 500

STATUS_LABELS = {
    "to_do": "Pendente",
    "pending": "Pendente",
    "queued": "Na fila",
    "doing": "Em execução",
    "running": "Em execução",
    "processing": "Em execução",
    "done": "Concluído",
    "completed": "Concluído",
    "complete": "Concluído",
    "success": "Concluído",
    "published": "Publicado",
    "failed": "Falha",
    "error": "Falha",
    "cancelled": "Cancelado",
    "canceled": "Cancelado",
    "blocked": "Bloqueado",
}

TASK_OPERATION_CODES = {
    "video": "video_completed",
    "music": "music_completed",
    "automation": "automation_completed",
}


def _status_label(value: Any) -> str:
    raw = str(value or "unknown").strip().lower()
    return STATUS_LABELS.get(raw, raw.replace("_", " ").capitalize() or "Desconhecido")


def _parse_datetime(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_log_date_time(value: Any) -> tuple[str, str]:
    """Return a stable local date and time for the Logs table."""
    parsed = _parse_datetime(value)
    if parsed == datetime.min.replace(tzinfo=timezone.utc):
        return "—", "—"
    local = parsed.astimezone()
    return local.strftime("%d/%m/%Y"), local.strftime("%H:%M:%S")


def _task_operation_code(task: dict[str, Any]) -> str:
    if bool(task.get("music_mode")) or str(task.get("style_wide") or "").strip().lower() == "music":
        return TASK_OPERATION_CODES["music"]
    if str(task.get("creation_mode") or "").strip().lower() == "automation":
        return TASK_OPERATION_CODES["automation"]
    return TASK_OPERATION_CODES["video"]


def _operation_label(operation_code: str, fallback: str = "Operação") -> str:
    event = EVENTS_BY_CODE.get(operation_code)
    return str(event.get("label") if event else fallback or operation_code or "Operação")


def _fallback_task_failure_api(task: dict[str, Any]) -> str:
    """Infer a safe API label for legacy failed tasks without structured metadata."""
    route = str(task.get("material_source") or task.get("style_wide") or "").strip().casefold()
    if "pexels" in route and "pixabay" in route:
        return "Pexels/Pixabay API (fonte efectiva não registada)"
    if "pixabay" in route:
        return "Pixabay API"
    if "pexels" in route or "stock" in route:
        return "Pexels/Pixabay API (fonte efectiva não registada)"
    if route in {"full_ia", "full ia", "ia"}:
        return "FAL AI / KIE AI / Agnes AI"
    if route in {"music", "musica", "música"} or bool(task.get("music_mode")):
        return "Suno / Ficheiro local"
    stage = str(task.get("stage") or task.get("failed_stage") or "").strip().casefold()
    if stage in {"topic", "script", "title", "keywords", "thumbnail_prompt"}:
        return "LLM textual API (provider não registado)"
    if stage == "thumbnail":
        return "Pool de imagem API (provider não registado)"
    if stage == "upload":
        return "YouTube Upload API"
    return "API não identificada (falha anterior)"


def _task_log(task: dict[str, Any]) -> dict[str, Any] | None:
    task_id = str(task.get("id") or "").strip()
    if not task_id:
        return None
    operation_code = _task_operation_code(task)
    state = str(task.get("state") or "unknown").strip().lower()
    occurred_at = task.get("updated_at") or task.get("completed_at") or task.get("created_at")
    date, time = format_log_date_time(occurred_at)
    title = str(task.get("title") or task.get("topic") or "Actividade").strip()
    channel = str(task.get("channel_name") or "").strip()
    stage = str(task.get("stage") or "").strip()
    progress = task.get("progress")
    try:
        progress_value = max(0, min(100, int(progress))) if progress is not None else None
    except (TypeError, ValueError):
        progress_value = None
    details: list[str] = []
    if channel:
        details.append(channel)
    if stage:
        details.append(f"Etapa: {stage}")
    if progress_value is not None:
        details.append(f"Progresso: {progress_value}%")
    error = str(task.get("error") or "").strip()
    failure_api = str(task.get("failure_api") or "").strip()
    failure_provider = str(task.get("failure_provider") or "").strip()
    failure_service = str(task.get("failure_service") or "").strip()
    failure_fields = str(task.get("failure_config_fields") or "").strip()
    artifacts = task.get("artifacts") if isinstance(task.get("artifacts"), dict) else {}
    log_path = str(task.get("video_log") or artifacts.get("video_log") or task.get("log_file") or "").strip()
    filename = Path(log_path.replace("\\", "/")).name if log_path else ""
    api_provider = failure_api
    if state in {"failed", "error"}:
        api_provider = api_provider or _fallback_task_failure_api(task)
        details.append(f"API/provider: {api_provider}")
        if failure_provider:
            details.append(f"Provider: {failure_provider}")
        if failure_service:
            details.append(f"Serviço: {failure_service}")
        if failure_fields:
            details.append(f"Configuração: {failure_fields}")
    if error:
        details.append(error[:500])
    return {
        "id": f"task:{task_id}",
        "operation_code": operation_code,
        "operation": _operation_label(operation_code),
        "status_code": state,
        "status": _status_label(state),
        "occurred_at": str(occurred_at or ""),
        "date": date,
        "time": time,
        "source": "Tarefas",
        "record": title,
        "filename": filename,
        "details": " · ".join(details),
        "api_provider": api_provider or "",
        "progress": progress_value,
        "task_id": task_id,
    }


def _notification_status(entry: dict[str, Any]) -> str:
    metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
    explicit = metadata.get("status") or entry.get("status")
    if explicit:
        return str(explicit)
    event_type = str(entry.get("event_type") or "").lower()
    label = str(entry.get("label") or "").lower()
    return "failed" if event_type.endswith("_failed") or "falhou" in label or "erro" in label else "completed"


def _notification_log(entry: dict[str, Any]) -> dict[str, Any] | None:
    entry_id = str(entry.get("id") or "").strip()
    if not entry_id:
        return None
    event_type = str(entry.get("event_type") or "").strip()
    if not event_type:
        return None
    status_code = _notification_status(entry).strip().lower()
    occurred_at = entry.get("created_at") or ""
    date, time = format_log_date_time(occurred_at)
    metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
    public_metadata = [f"{key}: {value}" for key, value in metadata.items() if value not in (None, "")]
    api_provider = str(metadata.get("failure_api") or metadata.get("api_provider") or "").strip()
    log_path = str(metadata.get("video_log") or metadata.get("log_file") or metadata.get("filename") or "").strip()
    if status_code in {"failed", "error"}:
        api_provider = api_provider or "API não identificada (falha anterior)"
    return {
        "id": f"notification:{entry_id}",
        "operation_code": event_type,
        "operation": str(entry.get("label") or _operation_label(event_type)),
        "status_code": status_code,
        "status": _status_label(status_code),
        "occurred_at": str(occurred_at),
        "date": date,
        "time": time,
        "source": "Notificações",
        "record": str(entry.get("title") or entry.get("label") or "Notificação"),
        "filename": Path(log_path.replace("\\", "/")).name if log_path else "",
        "details": " · ".join([str(entry.get("message") or "").strip(), *public_metadata]).strip(" ·")[:1000],
        "api_provider": api_provider,
        "progress": None,
        "task_id": str(metadata.get("task_id") or ""),
    }


def _should_skip_notification(entry: dict[str, Any], task_ids: set[str]) -> bool:
    """Avoid duplicating the canonical task completion/failure with its notification."""
    event_type = str(entry.get("event_type") or "")
    metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
    task_id = str(metadata.get("task_id") or "")
    return bool(task_id and task_id in task_ids and event_type in {"video_completed", "music_completed", "activity_failed"})


def list_logs(*, operation: str = "", query: str = "", status: str = "", limit: int = MAX_LOGS) -> list[dict[str, Any]]:
    """Return a unified, newest-first projection of local activity records."""
    try:
        reconcile_persisted_notifications()
    except Exception:
        # A diagnostic page must remain available even if one source is malformed.
        pass
    tasks = storage.read_json("tasks.json", [])
    tasks = [item for item in tasks if isinstance(item, dict)] if isinstance(tasks, list) else []
    task_ids = {str(item.get("id") or "") for item in tasks if item.get("id")}
    records = [item for item in (_task_log(task) for task in tasks) if item]
    notifications = list_notifications(limit=MAX_LOGS)
    records.extend(
        item
        for entry in notifications
        if not _should_skip_notification(entry, task_ids)
        for item in [_notification_log(entry)]
        if item
    )
    operation_filter = str(operation or "").strip().casefold()
    query_filter = str(query or "").strip().casefold()
    status_filter = str(status or "").strip().casefold()
    if operation_filter:
        records = [item for item in records if str(item.get("operation") or "").casefold() == operation_filter]
    if status_filter:
        records = [item for item in records if str(item.get("status") or "").casefold() == status_filter]
    if query_filter:
        records = [
            item
            for item in records
            if query_filter in " ".join(str(item.get(key) or "") for key in ("operation", "status", "record", "filename", "details", "source")).casefold()
        ]
    records.sort(key=lambda item: _parse_datetime(item.get("occurred_at")), reverse=True)
    try:
        requested_limit = int(limit)
    except (TypeError, ValueError):
        requested_limit = MAX_LOGS
    return records[: max(1, min(requested_limit, MAX_LOGS))]


def log_operation_options() -> list[str]:
    records = list_logs(limit=MAX_LOGS)
    return ["Todas"] + sorted({str(item.get("operation") or "Operação") for item in records})


def log_status_options() -> list[str]:
    records = list_logs(limit=MAX_LOGS)
    return ["Todos"] + sorted({str(item.get("status") or "Desconhecido") for item in records})


def logs_to_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert the internal projection into safe scalar rows for Streamlit."""
    return [
        {
            "Operação": item.get("operation") or "Operação",
            "Estado": item.get("status") or "Desconhecido",
            "Data": item.get("date") or "—",
            "Hora": item.get("time") or "—",
            "Registo": item.get("record") or "—",
            "Ficheiro": item.get("filename") or "—",
            "Origem": item.get("source") or "—",
            "Progresso": f"{item['progress']}%" if item.get("progress") is not None else "—",
            "API/Provider": item.get("api_provider") or "—",
            "Detalhes": item.get("details") or "—",
        }
        for item in records
    ]
