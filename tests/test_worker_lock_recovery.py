"""Recuperação dos locks dos workers depois de encerramentos (0.9.73).

Reproduzido em 09/10: o _pid_alive com ctypes.windll + GetLastError()
devolvia "vivo" para PIDs já mortos (valor obsoleto do last-error) e o
worker de automação recusava arrancar — "Já existe um worker de automação
activo (PID 7292)" num loop infinito de respawns do launcher, com o PID
7292 confirmadamente inexistente.

A verificação passa a usar psutil com verificação de identidade por
cmdline: um PID só bloqueia o arranque quando pertence realmente a um
worker do Thunderbolt (protege também contra reuso do número de PID por
processos alheios).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from hermes_ui import automation_worker, pipeline_worker

ROOT = Path(__file__).resolve().parents[1]


def _dummy_process(marker: str = "") -> subprocess.Popen:
    script = "import time; time.sleep(60)"
    if marker:
        script += f"  # {marker}"
    return subprocess.Popen([sys.executable, "-c", script])


def _isolate_automation_storage(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("HERMES_STORAGE_DIR", str(tmp_path / "storage"))
    from hermes_ui import storage

    root = tmp_path / "storage"
    monkeypatch.setattr(storage, "STORAGE", root)
    monkeypatch.setattr(storage, "STATE", root / "state")
    monkeypatch.setattr(storage, "BLUEPRINTS", root / "blueprints")
    storage.ensure_storage()
    return root / automation_worker.LOCK_FILENAME


def _isolate_pipeline_storage(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("HERMES_STORAGE_DIR", str(tmp_path / "storage"))
    from hermes_ui import storage

    root = tmp_path / "storage"
    monkeypatch.setattr(storage, "STORAGE", root)
    monkeypatch.setattr(storage, "STATE", root / "state")
    monkeypatch.setattr(storage, "BLUEPRINTS", root / "blueprints")
    monkeypatch.setattr(pipeline_worker, "STORAGE", root)
    storage.ensure_storage()
    return pipeline_worker._lock_path()


def test_pid_alive_requires_worker_identity_for_marker():
    dummy = _dummy_process()
    try:
        assert automation_worker._pid_alive(dummy.pid) is True
        assert automation_worker._pid_alive(dummy.pid, expect_marker="hermes_ui.automation_worker") is False
        assert pipeline_worker._pid_alive(dummy.pid, expect_marker="hermes_ui.pipeline_worker") is False
    finally:
        dummy.kill()
        dummy.wait()


def test_pid_alive_true_when_cmdline_matches_marker():
    dummy = _dummy_process(marker="hermes_ui.automation_worker")
    try:
        assert automation_worker._pid_alive(dummy.pid, expect_marker="hermes_ui.automation_worker") is True
    finally:
        dummy.kill()
        dummy.wait()


def test_pid_alive_false_for_dead_pid():
    dummy = _dummy_process()
    dummy.kill()
    dummy.wait()
    time.sleep(0.2)
    assert automation_worker._pid_alive(dummy.pid) is False
    assert automation_worker._pid_alive(dummy.pid, expect_marker="hermes_ui.automation_worker") is False
    assert pipeline_worker._pid_alive(dummy.pid, expect_marker="hermes_ui.pipeline_worker") is False


def test_stale_lock_with_dead_pid_is_recovered(tmp_path, monkeypatch):
    """O caso real de 09/10: PID morto no lock não pode bloquear o arranque."""
    dead = _dummy_process()
    dead.kill()
    dead.wait()
    time.sleep(0.2)

    lock_path = _isolate_automation_storage(tmp_path, monkeypatch)
    lock_path.write_text(f"pid={dead.pid}\n", encoding="utf-8")

    acquired = automation_worker._acquire_lock()
    try:
        assert acquired is not None
        assert lock_path.read_text(encoding="utf-8").strip() == f"pid={os.getpid()}"
    finally:
        if acquired is not None:
            acquired.unlink()


def test_stale_lock_with_unrelated_alive_pid_is_recovered(tmp_path, monkeypatch):
    """Reuso de PID: um processo vivo que não é o worker não pode bloquear."""
    dummy = _dummy_process()
    try:
        lock_path = _isolate_automation_storage(tmp_path, monkeypatch)
        lock_path.write_text(f"pid={dummy.pid}\n", encoding="utf-8")

        acquired = automation_worker._acquire_lock()
        try:
            assert acquired is not None
        finally:
            if acquired is not None:
                acquired.unlink()
    finally:
        dummy.kill()
        dummy.wait()


def test_lock_with_live_worker_pid_is_refused(tmp_path, monkeypatch):
    dummy = _dummy_process(marker="hermes_ui.automation_worker")
    try:
        lock_path = _isolate_automation_storage(tmp_path, monkeypatch)
        lock_path.write_text(f"pid={dummy.pid}\n", encoding="utf-8")
        with pytest.raises(RuntimeError, match="Já existe um worker de automação activo"):
            automation_worker._acquire_lock()
    finally:
        dummy.kill()
        dummy.wait()


def test_pipeline_lock_recovers_from_dead_pid(tmp_path, monkeypatch):
    dead = _dummy_process()
    dead.kill()
    dead.wait()
    time.sleep(0.2)

    lock_path = _isolate_pipeline_storage(tmp_path, monkeypatch)
    lock_path.write_text(f"pid={dead.pid}\n", encoding="utf-8")

    acquired = pipeline_worker._acquire_lock()
    try:
        assert acquired is not None
        assert lock_path.read_text(encoding="utf-8").strip() == f"pid={os.getpid()}"
    finally:
        if acquired is not None:
            acquired.unlink()
