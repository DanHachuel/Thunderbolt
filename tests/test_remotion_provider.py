"""Testes unitários do provider Remotion (spec 11.1).

Cobre get_remotion_status (Node/FFmpeg/Chromium presentes e ausentes),
prepare_input_props (mock do subprocesso Node), run_remotion_render (mock do
subprocess.Popen com heartbeat simulado), timeout, cancelamento pelo
utilador e robustez do cleanup (reader/persist_diagnostics não propagam).
"""
from __future__ import annotations

import io
import json
import subprocess
import threading
import time
from pathlib import Path

import pytest

from hermes_ui import remotion_provider
from hermes_ui.pipeline_worker import PipelineStopped
from hermes_ui.remotion_provider import RemotionProviderError


class _FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _available_status() -> dict:
    return {
        "available": True,
        "reasons": [],
        "details": {"node": "v22.11.0", "chromium": "C:/chromium/chrome.exe", "ffmpeg": "C:/ffmpeg/ffmpeg.exe"},
    }


def _install_package(tmp_path: Path, monkeypatch) -> None:
    package_dir = tmp_path / "packages" / "remotion"
    package_dir.mkdir(parents=True)
    (package_dir / "render.mjs").write_text("// wrapper", encoding="utf-8")
    src = package_dir / "src"
    src.mkdir()
    (src / "index.ts").write_text("// entry", encoding="utf-8")
    monkeypatch.setattr(remotion_provider, "REMOTION_PACKAGE_DIR", package_dir)
    monkeypatch.setattr(remotion_provider, "REMOTION_RENDER_SCRIPT", package_dir / "render.mjs")
    monkeypatch.setattr(remotion_provider, "REMOTION_ENTRY_POINT", src / "index.ts")


# ─────────────────────────── get_remotion_status ─────────────────────────────


def test_status_reports_missing_node(monkeypatch, tmp_path):
    _install_package(tmp_path, monkeypatch)
    monkeypatch.setattr(remotion_provider, "_find_node_executable", lambda: None)
    monkeypatch.setattr(remotion_provider, "_ffmpeg_executable", lambda: "C:/ffmpeg/ffmpeg.exe")
    monkeypatch.setattr(remotion_provider, "_chromium_executable", lambda: "C:/chromium/chrome.exe")
    monkeypatch.setattr(remotion_provider, "_renderer_dependency_installed", lambda node: True)
    status = remotion_provider.get_remotion_status()
    assert status["available"] is False
    assert any("Node.js 18+" in reason for reason in status["reasons"])


def test_status_reports_missing_chromium_and_ffmpeg(monkeypatch, tmp_path):
    _install_package(tmp_path, monkeypatch)
    monkeypatch.setattr(remotion_provider, "_find_node_executable", lambda: "node")
    monkeypatch.setattr(remotion_provider, "_node_satisfiable_version", lambda node: (True, "v22.11.0"))
    monkeypatch.setattr(remotion_provider, "_ffmpeg_executable", lambda: None)
    monkeypatch.setattr(remotion_provider, "_chromium_executable", lambda: None)
    monkeypatch.setattr(remotion_provider, "_renderer_dependency_installed", lambda node: True)
    status = remotion_provider.get_remotion_status()
    assert status["available"] is False
    reasons = " ".join(status["reasons"])
    assert "Chromium do Playwright" in reasons
    assert "imageio-ffmpeg" in reasons


def test_status_reports_outdated_node(monkeypatch, tmp_path):
    _install_package(tmp_path, monkeypatch)
    monkeypatch.setattr(remotion_provider, "_find_node_executable", lambda: "node")
    monkeypatch.setattr(remotion_provider, "_node_satisfiable_version", lambda node: (False, "v16.20.0"))
    monkeypatch.setattr(remotion_provider, "_ffmpeg_executable", lambda: "C:/ffmpeg/ffmpeg.exe")
    monkeypatch.setattr(remotion_provider, "_chromium_executable", lambda: "C:/chromium/chrome.exe")
    monkeypatch.setattr(remotion_provider, "_renderer_dependency_installed", lambda node: True)
    status = remotion_provider.get_remotion_status()
    assert status["available"] is False
    assert any("detectado v16.20.0" in reason for reason in status["reasons"])


def test_status_reports_missing_package_and_dependencies(monkeypatch, tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.setattr(remotion_provider, "REMOTION_PACKAGE_DIR", empty_dir)
    monkeypatch.setattr(remotion_provider, "REMOTION_RENDER_SCRIPT", empty_dir / "render.mjs")
    monkeypatch.setattr(remotion_provider, "REMOTION_ENTRY_POINT", empty_dir / "src" / "index.ts")
    monkeypatch.setattr(remotion_provider, "_find_node_executable", lambda: "node")
    monkeypatch.setattr(remotion_provider, "_node_satisfiable_version", lambda node: (True, "v22.11.0"))
    monkeypatch.setattr(remotion_provider, "_ffmpeg_executable", lambda: "C:/ffmpeg/ffmpeg.exe")
    monkeypatch.setattr(remotion_provider, "_chromium_executable", lambda: "C:/chromium/chrome.exe")
    status = remotion_provider.get_remotion_status()
    assert status["available"] is False
    assert any("packages/remotion não está instalado" in reason for reason in status["reasons"])


def test_status_available_when_environment_is_complete(monkeypatch, tmp_path):
    _install_package(tmp_path, monkeypatch)
    monkeypatch.setattr(remotion_provider, "_find_node_executable", lambda: "node")
    monkeypatch.setattr(remotion_provider, "_node_satisfiable_version", lambda node: (True, "v22.11.0"))
    monkeypatch.setattr(remotion_provider, "_ffmpeg_executable", lambda: "C:/ffmpeg/ffmpeg.exe")
    monkeypatch.setattr(remotion_provider, "_chromium_executable", lambda: "C:/chromium/chrome.exe")
    monkeypatch.setattr(remotion_provider, "_renderer_dependency_installed", lambda node: True)
    status = remotion_provider.get_remotion_status()
    assert status["available"] is True
    assert status["reasons"] == []
    assert status["details"]["chromium"] == "C:/chromium/chrome.exe"


def test_chromium_resolved_from_disk_without_the_playwright_driver(monkeypatch, tmp_path):
    # 0.9.54: arrancar o driver do Playwright no thread do Streamlit deixava
    # no terminal "Task was destroyed but it is pending!" + TargetClosedError
    # quando um rerun interrompia a leitura de executable_path; o caminho
    # passa a ser lido directamente da pasta de browsers, sem driver.
    import inspect

    source = inspect.getsource(remotion_provider._chromium_executable)
    assert "from playwright" not in source, "o provider não pode importar a API do Playwright aqui"
    assert ".start()" not in source and "sync_api" not in source
    browsers = tmp_path / "ms-playwright"
    new_chromium = browsers / "chromium-1234" / "chrome-win64" / "chrome.exe"
    new_chromium.parent.mkdir(parents=True)
    new_chromium.write_bytes(b"chrome")
    old_chromium = browsers / "chromium-1208" / "chrome-win64" / "chrome.exe"
    old_chromium.parent.mkdir(parents=True)
    old_chromium.write_bytes(b"chrome")
    linux_layout = browsers / "chromium-1208" / "chrome-linux" / "chrome"
    linux_layout.parent.mkdir(parents=True)
    linux_layout.write_bytes(b"chrome")
    shell = browsers / "chromium_headless_shell-1234" / "chrome-win64" / "headless_shell.exe"
    shell.parent.mkdir(parents=True)
    shell.write_bytes(b"shell")
    monkeypatch.setattr(remotion_provider, "_playwright_browser_roots", lambda: [browsers])
    resolved = remotion_provider._chromium_executable()
    # A revisão mais alta ganha e o Chrome completo tem prioridade sobre o headless shell.
    assert resolved == str(new_chromium)


def test_chromium_returns_none_when_no_browsers_are_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(remotion_provider, "_playwright_browser_roots", lambda: [])
    assert remotion_provider._chromium_executable() is None


# ─────────────────────────── prepare_input_props ─────────────────────────────


def test_prepare_input_props_invokes_node_prepare_only(monkeypatch, tmp_path):
    monkeypatch.setattr(remotion_provider, "STORAGE", tmp_path / "storage")
    monkeypatch.setattr(remotion_provider, "_find_node_executable", lambda: "node")
    _install_package(tmp_path, monkeypatch)
    captured: dict = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return _FakeCompleted(0, json.dumps({"videoId": "v1", "scenes": []}), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    props = remotion_provider.prepare_input_props({"content": "## GANCHO\nNARRAÇÃO: oi"}, {"videoId": "v1"})
    assert props == {"videoId": "v1", "scenes": []}
    assert "--prepare-only" in captured["command"]
    assert remotion_provider.REMOTION_ROLE_MARKER in captured["command"]
    script_file = Path(str(captured["command"][captured["command"].index("--script-file") + 1]))
    assert script_file.is_file()
    assert script_file.read_text(encoding="utf-8").startswith("## GANCHO")


def test_prepare_input_props_accepts_raw_markdown(monkeypatch, tmp_path):
    monkeypatch.setattr(remotion_provider, "STORAGE", tmp_path / "storage")
    monkeypatch.setattr(remotion_provider, "_find_node_executable", lambda: "node")
    _install_package(tmp_path, monkeypatch)
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: _FakeCompleted(0, '{"scenes": []}', ""))
    props = remotion_provider.prepare_input_props("## GANCHO\nNARRAÇÃO: oi")
    assert props == {"scenes": []}


def test_prepare_input_props_failure_is_actionable(monkeypatch, tmp_path):
    monkeypatch.setattr(remotion_provider, "STORAGE", tmp_path / "storage")
    monkeypatch.setattr(remotion_provider, "_find_node_executable", lambda: "node")
    _install_package(tmp_path, monkeypatch)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **kwargs: _FakeCompleted(1, "", "ERROR=falha do adaptador"),
    )
    with pytest.raises(RemotionProviderError, match="falhou"):
        remotion_provider.prepare_input_props({"content": "roteiro"}, {})


def test_prepare_input_props_requires_node(monkeypatch, tmp_path):
    monkeypatch.setattr(remotion_provider, "STORAGE", tmp_path / "storage")
    monkeypatch.setattr(remotion_provider, "_find_node_executable", lambda: None)
    with pytest.raises(RemotionProviderError, match="Node.js"):
        remotion_provider.prepare_input_props({"content": "roteiro"}, {})


# ─────────────────────────── run_remotion_render ────────────────────────────


class _FakePopen:
    """Popen com stdout/stderr StringIO e término programado."""

    def __init__(self, stdout_lines=(), stderr_lines=(), exit_code=0, delay=0.1, never_exit=False):
        self.command = None
        self.pid = 4242
        self.returncode = None
        self.stdout = io.StringIO("".join(line + "\n" for line in stdout_lines))
        self.stderr = io.StringIO("".join(line + "\n" for line in stderr_lines))
        self.never_exit = never_exit
        if not never_exit:
            threading.Thread(target=self._finish, args=(delay, exit_code), daemon=True).start()

    def _finish(self, delay, code):
        time.sleep(delay)
        self.returncode = code

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        while self.returncode is None:
            time.sleep(0.02)
        return self.returncode


class _Hooks:
    def __init__(self, task_state="doing"):
        self.stops: list[str] = []
        self.updates: list[dict] = []
        self.heartbeats: list[dict] = []
        self.diagnostics: list[str] = []
        self.task_state = task_state

    def stop_process(self, process, **kwargs):
        self.stops.append(kwargs.get("reason", "unknown"))

    def update(self, task_id, **updates):
        self.updates.append(updates)
        return {}

    def heartbeat(self, **updates):
        self.heartbeats.append(updates)

    def task_by_id(self, task_id):
        return {"state": self.task_state} if self.task_state else None

    def persist_diagnostics(self, task, output):
        self.diagnostics.append(output)


def _render_setup(monkeypatch, tmp_path, hooks: _Hooks):
    monkeypatch.setattr(remotion_provider, "STORAGE", tmp_path / "storage")
    monkeypatch.setattr(remotion_provider, "get_remotion_status", lambda: _available_status())
    _install_package(tmp_path, monkeypatch)
    monkeypatch.setattr(remotion_provider, "_find_node_executable", lambda: "node")
    monkeypatch.setattr(remotion_provider, "REMOTION_HEARTBEAT_INTERVAL_SECONDS", 0)
    video_path = tmp_path / "videos" / "task-remotion.mp4"
    video_path.parent.mkdir(parents=True)
    return video_path


def test_run_remotion_render_success_with_progress_and_output(monkeypatch, tmp_path):
    hooks = _Hooks()
    video_path = _render_setup(monkeypatch, tmp_path, hooks)
    rendered_path = tmp_path / "videos" / "task-remotion.mp4"
    rendered_path.write_bytes(b"mp4-conteudo")
    fake = _FakePopen(
        stdout_lines=(f"OUTPUT={rendered_path}",),
        stderr_lines=("LOG=bundle ok", "PROGRESS=10", "PROGRESS=80"),
    )
    captured_command: list = []

    def fake_popen(command, **kwargs):
        captured_command.append(command)
        return fake

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    result = remotion_provider.run_remotion_render(
        {"id": "task"},
        video_path,
        "LongFormVideo",
        {"videoId": "task", "scenes": []},
        stop_process=hooks.stop_process,
        update=hooks.update,
        heartbeat=hooks.heartbeat,
        task_by_id=hooks.task_by_id,
        persist_diagnostics=hooks.persist_diagnostics,
    )
    assert Path(result["video_path"]) == rendered_path
    assert result["composition"] == "LongFormVideo"
    assert hooks.stops == []  # nenhuma paragem em sucesso
    assert hooks.updates, "heartbeat/_update devem ter corrido"
    assert all("video_helper_status" in update for update in hooks.updates)
    assert hooks.diagnostics, "diagnósticos do vídeo persistidos"
    # O marcador do guard viaja no cmdline do subprocesso (spec 5.4).
    assert remotion_provider.REMOTION_ROLE_MARKER in captured_command[0]
    assert "--thunderbolt-role=remotion-render" in " ".join(captured_command[0])


def test_run_remotion_render_timeout_stops_process(monkeypatch, tmp_path):
    hooks = _Hooks()
    video_path = _render_setup(monkeypatch, tmp_path, hooks)
    fake = _FakePopen(never_exit=True)
    monkeypatch.setattr(subprocess, "Popen", lambda command, **kwargs: fake)
    with pytest.raises(RemotionProviderError, match="excedeu o limite"):
        remotion_provider.run_remotion_render(
            {"id": "task"},
            video_path,
            "LongFormVideo",
            {"videoId": "task", "scenes": []},
            timeout_seconds=0,
            stop_process=hooks.stop_process,
            update=hooks.update,
            heartbeat=hooks.heartbeat,
            task_by_id=hooks.task_by_id,
            persist_diagnostics=hooks.persist_diagnostics,
        )
    assert "timeout" in hooks.stops


def test_run_remotion_render_cancellation_stops_process(monkeypatch, tmp_path):
    hooks = _Hooks(task_state="cancelled")
    video_path = _render_setup(monkeypatch, tmp_path, hooks)
    fake = _FakePopen(never_exit=True)
    monkeypatch.setattr(subprocess, "Popen", lambda command, **kwargs: fake)

    with pytest.raises(PipelineStopped):
        remotion_provider.run_remotion_render(
            {"id": "task"},
            video_path,
            "ShortVideo",
            {"videoId": "task", "scenes": []},
            stop_process=hooks.stop_process,
            update=hooks.update,
            heartbeat=hooks.heartbeat,
            task_by_id=hooks.task_by_id,
            persist_diagnostics=hooks.persist_diagnostics,
        )
    assert "cancelled" in hooks.stops


def test_run_remotion_render_cleanup_failures_do_not_propagate(monkeypatch, tmp_path):
    hooks = _Hooks()
    video_path = _render_setup(monkeypatch, tmp_path, hooks)
    rendered_path = tmp_path / "videos" / "task-remotion.mp4"
    rendered_path.write_bytes(b"mp4-conteudo")

    def broken_persist(task, output):
        raise RuntimeError("falha no persist")

    fake = _FakePopen(stdout_lines=(f"OUTPUT={rendered_path}",))
    monkeypatch.setattr(subprocess, "Popen", lambda command, **kwargs: fake)
    result = remotion_provider.run_remotion_render(
        {"id": "task"},
        video_path,
        "LongFormVideo",
        {"videoId": "task", "scenes": []},
        stop_process=hooks.stop_process,
        update=hooks.update,
        heartbeat=hooks.heartbeat,
        task_by_id=hooks.task_by_id,
        persist_diagnostics=broken_persist,
    )
    # O erro do _persist_video_diagnostics (ou do reader.join) não pode
    # mascarar um render bem sucedido.
    assert Path(result["video_path"]) == rendered_path


def test_run_remotion_render_failure_without_mp4(monkeypatch, tmp_path):
    hooks = _Hooks()
    video_path = _render_setup(monkeypatch, tmp_path, hooks)
    fake = _FakePopen(stdout_lines=(), stderr_lines=("ERROR=explodiu",), exit_code=1)
    monkeypatch.setattr(subprocess, "Popen", lambda command, **kwargs: fake)
    with pytest.raises(RemotionProviderError, match="falhou"):
        remotion_provider.run_remotion_render(
            {"id": "task"},
            video_path,
            "LongFormVideo",
            {"videoId": "task", "scenes": []},
            stop_process=hooks.stop_process,
            update=hooks.update,
            heartbeat=hooks.heartbeat,
            task_by_id=hooks.task_by_id,
            persist_diagnostics=hooks.persist_diagnostics,
        )
