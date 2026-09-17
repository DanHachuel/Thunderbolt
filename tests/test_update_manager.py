from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from hermes_ui import update_manager


class _Response:
    def __init__(self, version: str):
        self.version = version

    def raise_for_status(self):
        return None

    def json(self):
        return {"version": self.version}


def test_check_version_reports_an_available_registry_release():
    status = update_manager.check_version("0.3.96", get=lambda *args, **kwargs: _Response("0.3.97"))

    assert status.current_version == "0.3.96"
    assert status.latest_version == "0.3.97"
    assert status.update_available is True


def test_zero_padded_versions_are_not_reported_as_newer():
    status = update_manager.check_version("0.6.05", get=lambda *args, **kwargs: _Response("0.6.5"))

    assert status.update_available is False


def test_lower_registry_version_is_not_reported_as_an_update():
    status = update_manager.check_version("0.6.05", get=lambda *args, **kwargs: _Response("0.6.4"))

    assert status.update_available is False


def test_update_uses_npx_install_without_passing_settings_or_secrets():
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0)

    result = update_manager.update_to_latest(
        "0.3.96",
        get=lambda *args, **kwargs: _Response("0.3.97"),
        run=fake_run,
    )

    assert result.ok is True
    assert result.latest_version == "0.3.97"
    assert result.restart_required is True
    assert captured["command"][-2:] == ["@danhachuel/thunderbolt", "install"]
    assert "settings" not in " ".join(captured["command"]).lower()
    assert captured["kwargs"]["stdout"] is update_manager.subprocess.DEVNULL
    assert captured["kwargs"]["stderr"] is update_manager.subprocess.DEVNULL


def test_restart_current_process_reexecutes_the_same_python_command(monkeypatch):
    calls = []
    monkeypatch.setattr(update_manager.sys, "executable", "/python")
    monkeypatch.setattr(update_manager.sys, "argv", ["-m", "streamlit", "run", "app/main.py"])

    update_manager.restart_current_process(exec_fn=lambda executable, argv: calls.append((executable, argv)))

    assert calls == [("/python", ["/python", "-m", "streamlit", "run", "app/main.py"])]


def test_restart_current_process_requests_launcher_restart(monkeypatch):
    monkeypatch.setenv("THUNDERBOLT_LAUNCHER_RESTART", "1")
    exit_codes = []

    update_manager.restart_current_process(exit_fn=exit_codes.append)

    assert exit_codes == [update_manager.LAUNCHER_RESTART_EXIT_CODE]


def test_update_does_not_run_when_the_package_is_already_current():
    result = update_manager.update_to_latest(
        "0.3.97",
        get=lambda *args, **kwargs: _Response("0.3.97"),
        run=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("não deve instalar")),
    )

    assert result.ok is True
    assert "já está" in result.message


def test_home_is_the_only_page_that_renders_the_update_button():
    source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    home_controls = source.split("def render_home_update_controls() -> None:", 1)[1].split("def render_dashboard():", 1)[0]
    dashboard = source.split("def render_dashboard():", 1)[1].split("def render_blueprints():", 1)[0]

    assert 'key="home_update_version"' in home_controls
    assert source.count('key="home_update_version"') == 1
    assert 'button[kind="primary"]' in home_controls
    assert 'key="home_update_version", width="stretch"' not in home_controls
    assert 'if current_page == "Início":\n        render_home_update_controls()' in source
    assert 'restart_current_process()' in home_controls
    assert 'update_result.ok and update_result.restart_required' in home_controls
    assert 'key="home_update_version"' not in dashboard


def test_home_update_notice_is_compact_and_next_to_the_update_button():
    source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    home_controls = source.split("def render_home_update_controls() -> None:", 1)[1].split("def render_dashboard():", 1)[0]

    assert 'st.columns([1.45, 3.55, 0.42], gap="small")' in home_controls
    assert 'width: fit-content;' in home_controls
    assert 'max-width: 100%;' in home_controls
    assert 'key="home_update_notice_close"' in home_controls
    assert 'home_update_notice_dismissed' in home_controls
    assert 'help="Fechar este aviso"' in home_controls


def test_home_update_notice_hides_no_update_status():
    source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    home_controls = source.split("def render_home_update_controls() -> None:", 1)[1].split("def render_dashboard():", 1)[0]

    assert 'if update_result is not None and (not update_result.ok or update_result.restart_required):' in home_controls
    assert 'elif version_status.update_available:' in home_controls
    assert "já está actualizada" not in home_controls
    assert "verificação de actualização indisponível" not in home_controls


def test_version_label_keeps_the_two_digit_patch_convention():
    source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")

    assert "def display_version(version: str)" in source
    assert 'f"{int(parts[0])}.{int(parts[1])}.{int(parts[2]):02d}"' in source
    assert "APP_VERSION_LABEL = display_version(APP_VERSION)" in source


def test_launcher_restarts_from_the_new_npm_package_after_update():
    source = (Path(__file__).resolve().parents[1] / "scripts" / "cli.mjs").read_text(encoding="utf-8")
    assert 'THUNDERBOLT_LAUNCHER_RESTART: "1"' in source
    assert "const restartExitCode = 75;" in source
    assert '"--prefer-online", "@danhachuel/thunderbolt"' in source
    assert "detached: true" in source
    assert "replacement.unref()" in source


def test_launcher_disables_browser_cache_for_streamlit_proxy_responses():
    source = (Path(__file__).resolve().parents[1] / "scripts" / "cli.mjs").read_text(encoding="utf-8")
    assert 'responseHeaders["cache-control"] = "no-store, no-cache, must-revalidate, max-age=0"' in source
    assert "delete responseHeaders.etag" in source
    assert 'delete responseHeaders["last-modified"]' in source


def test_launcher_closes_all_proxy_sockets_before_streamlit_restart():
    source = (Path(__file__).resolve().parents[1] / "scripts" / "cli.mjs").read_text(encoding="utf-8")
    assert "const proxySockets = new Set();" in source
    assert 'proxy.on("connection"' in source
    assert "for (const socket of proxySockets) socket.destroy();" in source


def test_launcher_cleans_aborted_http_requests_without_affecting_other_tabs():
    source = (Path(__file__).resolve().parents[1] / "scripts" / "cli.mjs").read_text(encoding="utf-8")
    assert 'request.on("aborted", () => upstream.destroy())' in source
    assert 'response.on("close", () => {' in source
    assert 'if (response.headersSent || response.writableEnded) return;' in source


def test_launcher_isolates_each_streamlit_websocket_and_has_handshake_timeout():
    source = (Path(__file__).resolve().parents[1] / "scripts" / "cli.mjs").read_text(encoding="utf-8")
    assert "let upstreamSocket;" in source
    assert "clientSocket.setTimeout(15000, closeBridge);" in source
    assert "upstreamSocket.setTimeout(15000, closeBridge);" in source
    assert "clientSocket.on(\"close\", () => {" in source
    assert "upstreamSocket.on(\"close\", () => {" in source
    assert "clientSocket.pipe(upstreamSocket).pipe(clientSocket);" in source


def test_sigint_handlers_are_silent_to_avoid_terminal_message_loop():
    launcher = (Path(__file__).resolve().parents[1] / "scripts" / "cli.mjs").read_text(encoding="utf-8")
    bootstrap = (Path(__file__).resolve().parents[1] / "scripts" / "streamlit_bootstrap.py").read_text(encoding="utf-8")
    assert 'process.on("SIGINT", () => {});' in launcher
    assert "SIGINT ignorado: o Thunderbolt continua activo" not in bootstrap
    assert "return None" in bootstrap


def test_pipeline_worker_only_runs_when_work_is_pending():
    source = (Path(__file__).resolve().parents[1] / "scripts" / "cli.mjs").read_text(encoding="utf-8")
    start = source.index("function startPipelineWorker()")
    end = source.index("function monitorWorkers()", start)
    block = source[start:end]
    assert "|| !hasPendingPipelineWork()" in block
    assert "if (hasPendingPipelineWork())" in block
    assert "startPipelineWorker();" in source[source.index("function monitorWorkers()"):]
    assert "else stopPipelineWorker();" in source[source.index("function monitorWorkers()"):]
