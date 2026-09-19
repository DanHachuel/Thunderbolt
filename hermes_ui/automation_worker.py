import os
import sys
import io

os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"
_original_stdout, _original_stderr = sys.stdout, sys.stderr
if getattr(sys.stdout, "buffer", None) is not None and str(getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "_") != "utf_8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
if getattr(sys.stderr, "buffer", None) is not None and str(getattr(sys.stderr, "encoding", "") or "").lower().replace("-", "_") != "utf_8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

import argparse
import ctypes
import time
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Any

from . import storage
from .creative_generation import generate_title_and_keywords, generate_topic_for_channel
from .domain import create_batch, create_tasks_for_batch
from .languages import language_code
from .material_sources import selected_material_source
from .notifications import record_notification
from .video_length import length_generation_settings
from integrations.session_info_health import check_all_accounts_session_info_health, emit_session_info_health_alerts

WORKER_STATE_FILE = "automation_worker.json"
LOCK_FILENAME = "automation_worker.lock"
DEFAULT_INTERVAL_SECONDS = 10
DEFAULT_STATE: dict[str, Any] = {
    "worker_started_at": None,
    "worker_pid": None,
    "last_heartbeat_local": None,
    "last_tick_local": None,
    "last_error": "",
    "last_runs": {},
}


def _local_now() -> datetime:
    """Return the local wall-clock time of the computer running Thunderbolt."""
    return datetime.now().astimezone()


def _local_iso(value: datetime) -> str:
    return value.astimezone().isoformat(timespec="seconds")


def _state() -> dict[str, Any]:
    saved = storage.read_json(WORKER_STATE_FILE, DEFAULT_STATE)
    if not isinstance(saved, dict):
        saved = {}
    merged = {**DEFAULT_STATE, **saved}
    if not isinstance(merged.get("last_runs"), dict):
        merged["last_runs"] = {}
    return merged


def load_worker_status() -> dict[str, Any]:
    """Read status displayed by the Automação page without starting a worker."""
    status = _state()
    heartbeat = str(status.get("last_heartbeat_local") or "")
    status["alive"] = False
    if heartbeat:
        try:
            heartbeat_at = datetime.fromisoformat(heartbeat)
            status["alive"] = (datetime.now().astimezone() - heartbeat_at.astimezone()).total_seconds() <= 30
        except ValueError:
            status["alive"] = False
    return status


def _write_status(status: dict[str, Any]) -> None:
    storage.write_json(WORKER_STATE_FILE, {**DEFAULT_STATE, **status})


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            process_query_limited_information = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return ctypes.windll.kernel32.GetLastError() == 5
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, SystemError, ValueError):
        return False
    return True


def _acquire_lock() -> Path | None:
    lock_path = storage.STORAGE / LOCK_FILENAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            lock_contents = lock_path.read_text(encoding="utf-8").strip()
            old_pid_text = lock_contents.removeprefix("pid=").strip()
            old_pid = int(old_pid_text)
        except (OSError, ValueError):
            old_pid = 0
        if _pid_alive(old_pid):
            raise RuntimeError(f"Já existe um worker de automação activo para este storage do Thunderbolt (PID {old_pid}).")
        try:
            lock_path.unlink()
        except OSError:
            return None
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return None
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
    finally:
        os.close(descriptor)
    return lock_path


def _release_lock(lock_path: Path | None) -> None:
    if lock_path is not None:
        try:
            lock_path.unlink()
        except OSError:
            pass


def _valid_schedule(value: Any) -> bool:
    text = str(value or "").strip()
    if len(text) != 5 or text[2] != ":":
        return False
    try:
        hour, minute = (int(part) for part in text.split(":"))
    except ValueError:
        return False
    return 0 <= hour <= 23 and 0 <= minute <= 59


def _scheduled_time(current: datetime, value: Any) -> datetime | None:
    """Return today's scheduled local time, allowing a late worker tick to catch up."""
    text = str(value or "").strip()
    if not _valid_schedule(text):
        return None
    hour, minute = (int(part) for part in text.split(":"))
    return current.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _daily_quantity(channel: dict[str, Any]) -> int:
    try:
        return max(1, min(100, int(channel.get("daily_limit", 1))))
    except (TypeError, ValueError):
        return 1


def _blueprint_for_channel(channel: dict[str, Any]) -> dict[str, Any]:
    blueprint_id = str(channel.get("default_blueprint_id") or channel.get("blueprint_id") or "").strip()
    if not blueprint_id:
        return {}
    for path in storage.list_blueprint_files():
        try:
            data = storage.load_blueprint_file(path)
        except (OSError, ValueError):
            continue
        identifiers = {str(data.get("id") or ""), path.stem, str(data.get("name") or "")}
        if blueprint_id in identifiers:
            return data
    return {}


def _length_settings(channel: dict[str, Any], blueprint: dict[str, Any]) -> dict[str, Any]:
    prompt_content = ""
    prompt_id = str(channel.get("default_prompt_master") or channel.get("prompt_master") or "").strip()
    if prompt_id:
        prompt_path = storage.TIKTOK_PROMPT_MASTERS / prompt_id
        if prompt_path.is_file():
            try:
                prompt_content = storage.load_prompt_master_file(prompt_path)
            except (OSError, ValueError):
                prompt_content = ""
    return length_generation_settings(channel, blueprint, prompt_content)


def _creative_payload(channel: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    settings = storage.read_json("settings.json", {})
    blueprint = _blueprint_for_channel(channel)
    user_context = str(channel.get("automation_topic") or "").strip()
    topic_package = generate_topic_for_channel(settings, channel, blueprint, user_context=user_context)
    editorial = generate_title_and_keywords(
        settings,
        channel,
        topic_package["topic"],
        blueprint,
        language=str(channel.get("language") or "Português"),
    )
    style_wide = str(channel.get("style_wide") or "pexels").strip().casefold()
    material_source = selected_material_source(settings) if style_wide in {"pexels", "pexels/pixabay", "stock"} else ""
    payload = {
        "topic": topic_package["topic"],
        "topic_source": "llm",
        "title": editorial["title"],
        "title_candidates": editorial["title_candidates"],
        "thumbnail_variant": {},
        "thumbnail_variants": [],
        "thumbnail_prompt": "",
        "thumbnail_text": "",
        "thumbnail_status": "pending_prompt",
        "blueprint_id": str(channel.get("default_blueprint_id") or channel.get("blueprint_id") or ""),
        "blueprint_name": str(blueprint.get("name") or "SEM BLUEPRINT CONFIGURADO"),
        "thumbnail_blueprint_id": str(channel.get("default_thumbnail_blueprint_id") or channel.get("thumbnail_blueprint_id") or ""),
        "voice": str(channel.get("default_voice") or channel.get("voice") or ""),
        "material_source": material_source,
        "generation_settings": {"video_keywords": editorial.get("keywords", []), "material_source": material_source, **_length_settings(channel, blueprint)},
        "ai_generation": {"topic": topic_package, "editorial": editorial},
    }
    return topic_package["topic"], payload


def _batch_for_day(channel_id: str, day: str) -> dict[str, Any] | None:
    batches = storage.read_json("batches.json", [])
    if not isinstance(batches, list):
        return None
    for batch in reversed(batches):
        if not isinstance(batch, dict) or channel_id not in (batch.get("channel_ids") or []):
            continue
        options = batch.get("options") or {}
        if options.get("automation_worker") is True and options.get("automation_date") == day:
            return batch
    return None


def _tasks_for_batch(batch_id: str) -> list[dict[str, Any]]:
    tasks = storage.read_json("tasks.json", [])
    return [task for task in tasks if isinstance(task, dict) and task.get("batch_id") == batch_id]


def _pending_payload(channel: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Build the lightweight scheduled payload; creative work runs in the pipeline."""
    settings = storage.read_json("settings.json", {})
    blueprint = _blueprint_for_channel(channel)
    style_wide = str(channel.get("style_wide") or "pexels").strip().casefold()
    material_source = selected_material_source(settings) if style_wide in {"pexels", "pexels/pixabay", "stock"} else ""
    language = language_code(channel.get("language") or "pt")
    payload = {
        "topic": "",
        "topic_source": "llm_pending",
        "title": "",
        "title_candidates": [],
        "thumbnail_variant": {},
        "thumbnail_variants": [],
        "thumbnail_prompt": "",
        "thumbnail_text": "",
        "thumbnail_status": "pending_prompt",
        "language": language,
        "blueprint_id": str(channel.get("default_blueprint_id") or channel.get("blueprint_id") or ""),
        "blueprint_name": str(blueprint.get("name") or "SEM BLUEPRINT CONFIGURADO"),
        "thumbnail_blueprint_id": str(channel.get("default_thumbnail_blueprint_id") or channel.get("thumbnail_blueprint_id") or ""),
        "voice": str(channel.get("default_voice") or channel.get("voice") or ""),
        "material_source": material_source,
        "generation_settings": {"material_source": material_source, **_length_settings(channel, blueprint)},
        "ai_generation": {},
    }
    return "", payload


def _create_channel_batch(channel: dict[str, Any], when: datetime, quantity: int | None = None, manual_create: bool = False) -> dict[str, Any]:
    channel_id = str(channel["id"])
    date_key = when.date().isoformat()
    style_wide = str(channel.get("style_wide") or "pexels")
    music_mode = style_wide == "music"
    topic, payload = _pending_payload(channel)
    options = {
        "language": payload.get("language") or channel.get("language") or "pt",
        "format": "portrait" if channel.get("platform") == "tiktok" else "wide",
        "platform": channel.get("platform", "youtube"),
        "queue": "tiktok_shorts" if channel.get("platform") == "tiktok" else "youtube",
        "style_wide": style_wide,
        "style_ia": channel.get("style_ia") or "",
        "material_source": payload.get("material_source") or "",
        "music_mode": music_mode,
        "background_mode": "none" if music_mode else ("ai" if style_wide == "full_ia" else "stock"),
        "music_path": channel.get("music_path") or "",
        "music_source": channel.get("music_source") or "",
        "topic_source": payload.get("topic_source") or "llm_pending",
        "channel_payloads": {channel_id: payload},
        "automation_worker": True,
        "manual_create": manual_create,
        "automation_date": date_key,
        "automation_scheduled_at": _local_iso(when),
    }
    batch = create_batch("single", [channel_id], topic, max(1, int(quantity if quantity is not None else _daily_quantity(channel))), options)
    tasks = create_tasks_for_batch(batch)
    return {"batch": batch, "tasks": tasks, "channel_id": channel_id}


def create_video_now_for_channel(channel: dict[str, Any]) -> dict[str, Any]:
    """Create one immediately runnable video task without requiring a schedule."""
    channel_id = str(channel.get("id") or "").strip()
    if not channel_id:
        raise ValueError("O canal precisa de um identificador para criar um vídeo.")
    return _create_channel_batch(channel, _local_now(), quantity=1, manual_create=True)


def run_once(when: datetime | None = None) -> dict[str, Any]:
    """Run one deterministic local-time tick; safe to call from tests or a worker loop."""
    current = when.astimezone() if when is not None and when.tzinfo else (when or _local_now())
    current_minute = current.strftime("%H:%M")
    day = current.date().isoformat()
    status = _state()
    status["last_tick_local"] = _local_iso(current)
    status["last_heartbeat_local"] = _local_iso(current)
    status["last_error"] = ""
    try:
        session_health = check_all_accounts_session_info_health(storage.STORAGE, storage.read_json("settings.json", {}))
        session_alerts = emit_session_info_health_alerts(session_health, now=current.astimezone())
        status["session_info_health"] = [item.as_dict() for item in session_health]
        status["session_info_alerts"] = len(session_alerts)
    except Exception as exc:
        # Session monitoring must never stop creation of a scheduled batch.
        status["session_info_health_error"] = type(exc).__name__
    created: list[dict[str, Any]] = []
    skipped: list[str] = []
    channels = storage.read_json("channels.json", [])
    if not isinstance(channels, list):
        channels = []
    try:
        for channel in channels:
            if not isinstance(channel, dict):
                continue
            channel_id = str(channel.get("id") or "")
            if not channel_id or not bool(channel.get("active", True)) or not bool(channel.get("automation_on", False)):
                continue
            scheduled_at = _scheduled_time(current, channel.get("automation_time"))
            if scheduled_at is None or current < scheduled_at:
                continue
            existing = _batch_for_day(channel_id, day)
            if existing:
                existing_tasks = _tasks_for_batch(str(existing.get("id") or ""))
                if not existing_tasks:
                    existing_tasks = create_tasks_for_batch(existing)
                skipped.append(channel_id)
                continue
            created.append(_create_channel_batch(channel, scheduled_at))
        for item in created:
            batch = item["batch"]
            scheduled_at_value = str((batch.get("options") or {}).get("automation_scheduled_at") or "")
            scheduled_time = scheduled_at_value[11:16] if len(scheduled_at_value) >= 16 else current_minute
            status["last_runs"][item["channel_id"]] = {
                "date": day,
                "time": scheduled_time,
                "batch_id": batch["id"],
                "task_ids": [task["id"] for task in item["tasks"]],
            }
            record_notification(
                "automation_completed",
                "Automação concluída",
                f"O lote agendado do canal {item['channel_id']} foi criado com sucesso.",
                metadata={"channel_id": item["channel_id"], "batch_id": batch["id"], "time": scheduled_time},
                dedupe_key=f"automation:{batch['id']}",
            )
        _write_status(status)
        return {
            "ok": True,
            "local_time": _local_iso(current),
            "scheduled_time": current_minute,
            "created": created,
            "skipped": skipped,
        }
    except Exception as exc:
        status["last_error"] = str(exc)
        _write_status(status)
        record_notification(
            "automation_failed",
            "Automação falhou",
            f"A execução automática das {current_minute} terminou com erro: {exc}",
            metadata={"date": day, "time": current_minute},
            dedupe_key=f"automation:failed:{day}:{current_minute}",
        )
        return {"ok": False, "local_time": _local_iso(current), "error": str(exc), "created": created}


def run_worker(interval_seconds: int = DEFAULT_INTERVAL_SECONDS) -> None:
    lock_path = None
    try:
        storage.ensure_storage()
        lock_path = _acquire_lock()
        if lock_path is None:
            raise RuntimeError("Já existe um worker de automação activo para este storage do Thunderbolt.")
        started = _local_now()
        status = _state()
        status.update({"worker_started_at": _local_iso(started), "worker_pid": os.getpid(), "last_error": ""})
        _write_status(status)
        while True:
            result = run_once()
            if not result.get("ok"):
                print(f"Thunderbolt worker: erro: {result.get('error')}", flush=True)
            elif result.get("created"):
                print(f"Thunderbolt worker: {len(result['created'])} canal(is) agendado(s) às {result['scheduled_time']}.", flush=True)
            time.sleep(max(2, int(interval_seconds)))
    except KeyboardInterrupt:
        # Shutdown por Ctrl+C: sair sem gravar estado nem mostrar traceback.
        return
    finally:
        if lock_path is not None:
            try:
                current = _state()
                current["worker_pid"] = None
                current["last_heartbeat_local"] = None
                try:
                    _write_status(current)
                except (KeyboardInterrupt, OSError, PermissionError):
                    pass
            except (KeyboardInterrupt, OSError, PermissionError):
                pass
            try:
                _release_lock(lock_path)
            except (KeyboardInterrupt, OSError, PermissionError):
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Worker local de automação diária do Thunderbolt")
    parser.add_argument("--once", action="store_true", help="Executa apenas um tick usando o relógio local")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SECONDS, help="Intervalo de verificação em segundos")
    args = parser.parse_args()
    if args.once:
        storage.ensure_storage()
        print(run_once(), flush=True)
        return
    run_worker(args.interval)


if __name__ == "__main__":
    main()
