from __future__ import annotations

import os
import signal
import subprocess
from types import SimpleNamespace

import pytest

from hermes_ui import pipeline_worker


class FakeProcess:
    def __init__(self, pid=4242):
        self.pid = pid
        self.returncode = None
        self.killed = False
        self.wait_calls = []

    def poll(self):
        return None if not self.killed else -9

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        if not self.killed:
            raise subprocess.TimeoutExpired("fake", timeout)
        return self.returncode


class FakeChild:
    def __init__(self, pid):
        self.pid = pid
        self.terminated = False
        self.killed = False

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class FakePsutilProcess:
    def __init__(self, children):
        self._children = children
        self.terminated = False
        self.killed = False

    def children(self, recursive=True):
        assert recursive is True
        return self._children

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        assert timeout == 3
        if not self.terminated:
            raise pipeline_worker.psutil.TimeoutExpired(4242, timeout)

    def kill(self):
        self.killed = True


def test_stop_process_windows_only_terminates_mpt_descendants(monkeypatch):
    process = FakeProcess()
    children = [FakeChild(10), FakeChild(11)]
    root = FakePsutilProcess(children)
    writes = []
    monkeypatch.setattr(pipeline_worker.os, "name", "nt")
    monkeypatch.setattr(pipeline_worker.psutil, "Process", lambda pid: root)
    monkeypatch.setattr(pipeline_worker.psutil, "wait_procs", lambda items, timeout: (items, [children[1]]))
    monkeypatch.setattr(pipeline_worker, "_write_worker_state", lambda **updates: writes.append(updates))
    monkeypatch.setattr(pipeline_worker.subprocess, "run", lambda *args, **kwargs: pytest.fail("taskkill não deve ser usado"))

    pipeline_worker._stop_process(process)

    assert children[0].terminated is True
    assert children[0].killed is False
    assert children[1].terminated is True
    assert children[1].killed is True
    assert root.terminated is True
    assert writes[0]["last_stop_process"]["root_pid"] == 4242
    assert writes[0]["last_stop_process"]["children_terminated"] == 2
    assert writes[0]["last_stop_process"]["children_killed"] == 1


def test_stop_process_posix_keeps_killpg_path(monkeypatch):
    process = FakeProcess(5151)
    calls = []
    monkeypatch.setattr(pipeline_worker.os, "name", "posix")
    monkeypatch.setattr(pipeline_worker.os, "getpgid", lambda pid: calls.append(("getpgid", pid)) or 5151)
    monkeypatch.setattr(pipeline_worker.os, "killpg", lambda pgid, sig: calls.append(("killpg", pgid, sig)))
    monkeypatch.setattr(pipeline_worker, "_write_worker_state", lambda **updates: calls.append(("state", updates)))
    monkeypatch.setattr(pipeline_worker.psutil, "Process", lambda pid: SimpleNamespace(children=lambda recursive=True: []))

    pipeline_worker._stop_process(process)

    assert ("getpgid", 5151) in calls
    assert ("killpg", 5151, signal.SIGKILL) in calls
    assert any(item[0] == "state" for item in calls)


def test_pexels_short_key_fails_before_popen(monkeypatch):
    task = {"id": "pexels-short", "topic": "Tema de teste"}
    monkeypatch.setattr(pipeline_worker, "material_api_keys", lambda settings, route: ["short-key"])
    monkeypatch.setattr(pipeline_worker.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("Popen não deve ser chamado"))

    with pytest.raises(pipeline_worker.PipelineError, match="pelo menos 20 caracteres"):
        pipeline_worker._run_video_helper_once(task, settings={"media_provider_priority": ["pexels"]})


def test_video_stale_timeout_with_two_routes_is_at_most_25_minutes(monkeypatch):
    monkeypatch.setattr(pipeline_worker, "_material_video_routes", lambda task, settings: ["pexels", "pixabay"])
    task = {"stage": "video", "video_script": "texto"}

    assert pipeline_worker._task_stale_timeout_seconds(task) <= 25 * 60


def test_cleanup_diagnostics_is_non_fatal_in_contract():
    source = open("hermes_ui/pipeline_worker.py", encoding="utf-8").read()
    assert "try:\n            reader.join(timeout=2)" in source
    assert "try:\n            _persist_video_diagnostics(task, _output_text())" in source
