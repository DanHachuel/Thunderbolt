"""Runtime partilhado dos workers de fila (thumbnails/imagens) — 1.0.11.

Fornece o padrão comum aos dois workers dedicados: lock por PID (um worker de
cada tipo por máquina), heartbeat em ficheiro próprio com estado `alive`,
detecção de Rate Limit (HTTP 429) e retry com backoff exponencial. O limite de
paralelismo vem sempre de `motor_limits(settings)` — `settings.json` é relido
a cada tick, logo mudar o Motor aplica-se sem restart.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from hermes_ui.storage import read_json, write_json

RATE_LIMIT_MARKERS = ("429", "rate limit", "ratelimit", "too many requests", "quota exceeded")


def _pid_alive(pid: int, expect_marker: str) -> bool:
    if pid <= 0:
        return False
    try:
        import psutil

        process = psutil.Process(int(pid))
        cmdline = " ".join(process.cmdline()).casefold()
    except Exception:
        return False
    return expect_marker.casefold() in cmdline


def acquire_pid_lock(path: Path, expect_marker: str) -> Path | None:
    """Lock exclusivo por ficheiro com validação de PID (um worker por máquina).

    O próprio PID é aceito: os workers de fila mantêm o lock entre ticks
    enquanto há tarefas em voo — o próximo tick do MESMO processo continua
    a deter o lock em vez de se bloquear a si próprio.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            old_pid = int(path.read_text(encoding="utf-8").strip().removeprefix("pid=").strip())
        except (OSError, ValueError):
            old_pid = 0
        if old_pid == os.getpid():
            return path
        if _pid_alive(old_pid, expect_marker):
            return None
        try:
            path.unlink()
        except OSError:
            return None
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return None
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
    finally:
        os.close(descriptor)
    return path


def write_queue_heartbeat(state_filename: str, **updates: Any) -> None:
    state = read_json(state_filename, {})
    if not isinstance(state, dict):
        state = {}
    state.update(updates)
    state["worker_pid"] = os.getpid()
    state["last_heartbeat_at"] = datetime.now(timezone.utc).isoformat()
    state["updated_at"] = state["last_heartbeat_at"]
    write_json(state_filename, state)


def load_queue_worker_status(state_filename: str, *, timeout_seconds: int = 90) -> dict[str, Any]:
    """Heartbeat persistido + flag `alive` (para dashboards e KPIs)."""
    status = read_json(state_filename, {})
    if not isinstance(status, dict):
        status = {}
    try:
        heartbeat_at = datetime.fromisoformat(str(status.get("last_heartbeat_at") or ""))
    except ValueError:
        heartbeat_at = None
    if heartbeat_at and not heartbeat_at.tzinfo:
        heartbeat_at = heartbeat_at.replace(tzinfo=timezone.utc)
    status["alive"] = bool(
        heartbeat_at
        and (datetime.now(timezone.utc) - heartbeat_at).total_seconds() <= timeout_seconds
    )
    return status


def is_rate_limit(exc: BaseException) -> bool:
    """429/Rate Limit detectável na mensagem (os providers o deixam no texto)."""
    text = str(exc).casefold()
    return any(marker in text for marker in RATE_LIMIT_MARKERS)


def run_with_rate_limit_backoff(
    operation: Callable[[], Any],
    *,
    attempts: int = 3,
    base_delay: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """Retry com backoff exponencial (30s, 60s, 120s) SÓ para Rate Limit.

    Outros erros propagam imediatamente — o backoff não pode mascarar falhas
    de configuração ou de sessão.
    """
    last_exc: BaseException | None = None
    for attempt in range(max(1, attempts)):
        try:
            return operation()
        except Exception as exc:
            if not is_rate_limit(exc):
                raise
            last_exc = exc
            if attempt < attempts - 1:
                sleep(base_delay * (2**attempt))
    raise last_exc  # type: ignore[misc]
