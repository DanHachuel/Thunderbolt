from __future__ import annotations

import json
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

import psutil

from .storage import STATE, STORAGE

_DIAGNOSTICS_LOCK = Lock()


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _diagnostic_path(filename: str) -> Path:
    STATE.mkdir(parents=True, exist_ok=True)
    return STATE / filename


def append_diagnostic_event(filename: str, event: str, **payload: Any) -> None:
    """Append one bounded, JSON-serialisable diagnostic event without raising."""
    record = {"timestamp": _timestamp(), "event": str(event), **payload}
    try:
        line = json.dumps(record, ensure_ascii=False, default=str, separators=(",", ":")) + "\n"
        path = _diagnostic_path(filename)
        with _DIAGNOSTICS_LOCK:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
    except (OSError, TypeError, ValueError):
        # Diagnostics must never change the functional outcome of a task.
        return


def _system_snapshot() -> dict[str, Any]:
    processes: list[dict[str, Any]] = []
    for process in psutil.process_iter(["name", "cmdline"]):
        try:
            name = str(process.info.get("name") or "")
            cmdline = " ".join(str(item) for item in (process.info.get("cmdline") or []))
            if "python" not in name.lower() and "python" not in cmdline.lower():
                continue
            processes.append({
                "pid": process.pid,
                "name": name,
                "rss_mb": round(process.memory_info().rss / (1024 * 1024), 2),
                "cmdline": cmdline[-500:],
            })
        except (psutil.Error, OSError):
            continue
    memory = psutil.virtual_memory()
    return {
        "python_processes": processes,
        "memory_total_mb": round(memory.total / (1024 * 1024), 2),
        "memory_available_mb": round(memory.available / (1024 * 1024), 2),
        "memory_used_mb": round(memory.used / (1024 * 1024), 2),
        "memory_percent": memory.percent,
    }


def save_baseline_snapshot() -> None:
    """Record a pre-run system baseline; failures are intentionally ignored."""
    try:
        append_diagnostic_event("mpt_diagnostics.jsonl", "baseline_snapshot", **_system_snapshot())
    except (psutil.Error, OSError, TypeError, ValueError):
        return


def _last_lines(path: Path, limit: int = 100) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except OSError:
        return []


def save_diagnostics_zip(limit: int = 100) -> Path:
    """Export the latest diagnostic events to a timestamped storage ZIP."""
    STORAGE.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    destination = STORAGE / f"diagnostics_{stamp}.zip"
    with tempfile.TemporaryDirectory(prefix="thunderbolt-diagnostics-") as temporary:
        temporary_path = Path(temporary)
        for filename in ("mpt_diagnostics.jsonl", "launcher_diagnostics.jsonl"):
            target = temporary_path / filename
            lines = _last_lines(_diagnostic_path(filename), limit)
            target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for filename in ("mpt_diagnostics.jsonl", "launcher_diagnostics.jsonl"):
                archive.write(temporary_path / filename, arcname=filename)
    return destination
