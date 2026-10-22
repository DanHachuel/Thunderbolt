"""Worker da fila de THUMBNAILS (1.0.11) — 3 filas paralelas do Motor.

Polling a `tasks.json` por tarefas com `thumbnail_status == "thumbnail_queued"`
(marcadas instantaneamente pela UI) e geração das capas num pool próprio
limitado por `motor.max_parallel_thumbnails`. A geração usa
`generate_thumbnail_for_task` — o MESMO caminho (LLM + pool de imagem) que a
UI usava em síncrono, agora em background. Rate Limit (429) reza em backoff
exponencial. O estado do worker fica em `thumbnail_worker.json` (heartbeat
`alive` para os dashboards).
"""
import argparse
import json
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes_ui.queue_worker_runtime import (
    acquire_pid_lock,
    load_queue_worker_status,
    record_worker_crash,
    run_with_rate_limit_backoff,
    write_queue_heartbeat,
)
from hermes_ui.storage import read_json

STATE_FILENAME = "thumbnail_worker.json"
LOCK_FILENAME = "thumbnail_worker.lock"
WORKER_MARKER = "hermes_ui.thumbnail_worker"
ACTIVE_INTERVAL_SECONDS = 5
IDLE_INTERVAL_SECONDS = 15

_state_lock = threading.Lock()
_executor: ThreadPoolExecutor | None = None
_executor_workers = 0
_inflight: set[str] = set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_thumbnail_worker_status() -> dict[str, Any]:
    return load_queue_worker_status(STATE_FILENAME)


def _heartbeat(**updates: Any) -> None:
    write_queue_heartbeat(STATE_FILENAME, **updates)


def _lock_path() -> Path:
    from hermes_ui.storage import STATE

    return Path(STATE) / LOCK_FILENAME


def _settings() -> dict[str, Any]:
    value = read_json("settings.json", {})
    return value if isinstance(value, dict) else {}


def _queued_thumbnail_tasks() -> list[dict[str, Any]]:
    from hermes_ui.domain import load_tasks

    return [
        task
        for task in load_tasks()
        if isinstance(task, dict)
        and str(task.get("thumbnail_status") or "") == "thumbnail_queued"
        and str(task.get("id") or "").strip()
    ]


def _recover_claims_from_previous_process() -> list[str]:
    """Arranque: 'generating' sem processo vivo volta à fila (retry)."""
    from hermes_ui.domain import load_tasks, update_task

    recovered: list[str] = []
    for task in load_tasks():
        if not isinstance(task, dict) or str(task.get("thumbnail_status") or "") != "generating":
            continue
        task_id = str(task.get("id") or "")
        if task_id:
            update_task(task_id, {"thumbnail_status": "thumbnail_queued"})
            recovered.append(task_id)
    return recovered


def _process_thumbnail_task(task_id: str) -> dict[str, Any]:
    """Gera a thumbnail de UMA tarefa (claim 'generating' → 'generated'/'failed').

    Acções de fila (`thumbnail_queue_action`): vazio = gerar a imagem do
    prompt actual; `regenerate_prompt` = refazer o prompt (LLM) e gerar;
    `regenerate_lettering` = refazer só o lettering sobre a imagem existente.
    """
    from hermes_ui.notifications import record_notification
    from hermes_ui.domain import update_task
    from hermes_ui.thumbnails import (
        generate_thumbnail_for_task,
        regenerate_thumbnail_lettering,
        regenerate_thumbnail_prompt,
    )

    settings = _settings()
    try:
        from hermes_ui.domain import load_tasks

        task = next(
            (
                item
                for item in load_tasks()
                if isinstance(item, dict) and str(item.get("id") or "") == task_id
            ),
            {},
        )
        channel = {}
        channel_id = str(task.get("channel_id") or "")
        channels = read_json("channels.json", [])
        if isinstance(channels, list):
            channel = next((item for item in channels if isinstance(item, dict) and str(item.get("id") or "") == channel_id), {})
        action = str(task.get("thumbnail_queue_action") or "")
        if action == "regenerate_prompt":
            regenerate_thumbnail_prompt(task_id, settings, channel)
            _, image_path = run_with_rate_limit_backoff(lambda: generate_thumbnail_for_task(task_id, settings))
        elif action == "regenerate_lettering":
            _, image_path = run_with_rate_limit_backoff(
                lambda: regenerate_thumbnail_lettering(
                    task_id,
                    settings,
                    lettering_prompt=str(task.get("lettering_prompt") or ""),
                    language=str(task.get("language") or channel.get("language") or ""),
                    channel=channel,
                )
            )
        else:
            _, image_path = run_with_rate_limit_backoff(lambda: generate_thumbnail_for_task(task_id, settings))
        update_task(task_id, {"thumbnail_status": "generated", "thumbnail_queue_action": None, "thumbnail_queued_at": None, "thumbnail_error": None})
        record_notification(
            "thumbnail_generation_completed",
            f"Thumbnail gerada: {task.get('title') or task.get('topic') or 'Vídeo'}",
            "Thumbnail gerada com sucesso pela fila de thumbnails.",
            metadata={"task_id": task_id, "channel_name": channel.get("name") or "", "image_path": str(image_path)},
            dedupe_key=f"thumbnail-queue:generated:{task_id}:{image_path}",
        )
        return {"ok": True, "task_id": task_id, "image_path": str(image_path)}
    except Exception as exc:
        message = str(exc)[:1000]
        update_task(task_id, {"thumbnail_status": "failed", "thumbnail_queue_action": None, "thumbnail_error": message})
        record_notification(
            "thumbnail_generation_failed",
            "Falha na geração de thumbnail",
            f"A thumbnail da tarefa {task_id} falhou na fila: {message[:300]}",
            metadata={"task_id": task_id},
            dedupe_key=f"thumbnail-queue:failed:{task_id}:{message[:80]}",
        )
        return {"ok": False, "task_id": task_id, "error": message}
    finally:
        with _state_lock:
            _inflight.discard(task_id)


def _ensure_executor(max_workers: int) -> ThreadPoolExecutor:
    global _executor, _executor_workers
    with _state_lock:
        if _executor is not None and _executor_workers != max_workers and not _inflight:
            _executor.shutdown(wait=False)
            _executor = None
        if _executor is None or _executor_workers != max_workers:
            _executor = ThreadPoolExecutor(max_workers=max(1, max_workers), thread_name_prefix="thumbnail-task")
            _executor_workers = max(1, max_workers)
        return _executor


def _future_done(future: Future) -> None:
    try:
        future.result()
    except Exception:
        pass  # _process_thumbnail_task persiste o erro na própria tarefa.


def run_once() -> dict[str, Any]:
    """Um tick da fila de thumbnails: claim + submissão ao pool limitado."""
    from hermes_ui.render_capacity import motor_limits

    lock = acquire_pid_lock(_lock_path(), WORKER_MARKER)
    if lock is None:
        return {"ok": True, "status": "busy"}
    try:
        settings = _settings()
        limit = max(1, int(motor_limits(settings)["thumbnails"]))
        with _state_lock:
            inflight_count = len(_inflight)
        _heartbeat(status="running", active_tasks=inflight_count, limit=limit, last_error="")
        queued = _queued_thumbnail_tasks()
        submitted: list[str] = []
        executor = _ensure_executor(limit)
        from hermes_ui.domain import update_task

        for task in queued:
            with _state_lock:
                if inflight_count >= limit:
                    break
            task_id = str(task.get("id") or "")
            # Claim imediata: o próximo tick não resubmete e a UI mostra o estado.
            update_task(task_id, {"thumbnail_status": "generating", "thumbnail_generation_started_at": _now()})
            with _state_lock:
                _inflight.add(task_id)
                inflight_count = len(_inflight)
            executor.submit(_process_thumbnail_task, task_id).add_done_callback(_future_done)
            submitted.append(task_id)
        if submitted or inflight_count:
            _heartbeat(status="running", active_tasks=inflight_count, submitted=submitted)
            return {"ok": True, "status": "running", "submitted": submitted, "inflight": inflight_count}
        _heartbeat(status="idle", active_tasks=0)
        return {"ok": True, "status": "idle"}
    except Exception as exc:
        _heartbeat(status="error", last_error=str(exc)[:1000])
        return {"ok": False, "status": "error", "error": str(exc)[:1000]}
    finally:
        with _state_lock:
            worker_idle = not _inflight
        try:
            if worker_idle:
                lock.unlink()
        except (FileNotFoundError, OSError):
            pass


def run_worker(interval_seconds: int = ACTIVE_INTERVAL_SECONDS) -> None:
    try:
        from hermes_ui.storage import ensure_storage

        ensure_storage()
        _heartbeat(status="starting")
        _recover_claims_from_previous_process()
        while True:
            result = run_once()
            idle = bool(result.get("ok")) and result.get("status") == "idle"
            sleep_seconds = max(2, int(interval_seconds))
            time.sleep(max(sleep_seconds, IDLE_INTERVAL_SECONDS) if idle else sleep_seconds)
    except KeyboardInterrupt:
        return
    except Exception:
        # 1.0.18: o crash deixa rasto em storage/logs/worker_crash.log antes
        # de sair — o launcher reinicia em 5s e sem isto não havia diagnóstico
        # do motivo (o loop parecia infinito e mudo).
        record_worker_crash("thumbnail_worker")
        raise SystemExit(1) from None


def main() -> None:
    parser = argparse.ArgumentParser(description="Executor da fila de thumbnails Thunderbolt")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=ACTIVE_INTERVAL_SECONDS)
    args = parser.parse_args()
    if args.once:
        print(json.dumps(run_once(), ensure_ascii=False), flush=True)
    else:
        run_worker(args.interval)


if __name__ == "__main__":
    main()
