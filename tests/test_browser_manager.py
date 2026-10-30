from __future__ import annotations

import asyncio
import sys
import types

import pytest

from hermes_ui import browser_manager


def test_firefox_always_uses_original_playwright(monkeypatch):
    calls = []

    class Browser:
        def close(self):
            calls.append("close")

    class BrowserType:
        def launch(self, **kwargs):
            calls.append(("firefox", kwargs))
            return Browser()

    class Runtime:
        firefox = BrowserType()

        def stop(self):
            calls.append("stop")

    monkeypatch.setattr(browser_manager, "_module_available", lambda name: name in {"playwright", "patchright"})
    playwright = types.ModuleType("playwright")
    playwright.__path__ = []
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: types.SimpleNamespace(start=lambda: Runtime())
    monkeypatch.setitem(sys.modules, "playwright", playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)

    session = browser_manager.launch_browser("firefox", proxy=None)
    session.close()

    assert ("firefox", {"headless": True}) in calls
    assert calls[-2:] == ["close", "stop"]


def test_camoufox_status_missing_package_includes_fetch_command(monkeypatch):
    # 1.0.42: o status passa pela checagem CENTRAL (camoufox_environment_ready)
    monkeypatch.setattr(
        browser_manager,
        "camoufox_environment_ready",
        lambda: {"ready": False, "module": False, "binary": False, "message": "O pacote Camoufox não está instalado. Execute python -m camoufox fetch para descarregar o browser Camoufox."},
    )
    result = browser_manager.get_browser_status("camoufox")
    assert result["status"] == "not_installed"
    assert "python -m camoufox fetch" in result["message"]


def test_chromium_status_reports_patchright_primary(monkeypatch):
    monkeypatch.setattr(browser_manager, "_module_available", lambda name: name in {"patchright", "playwright"})
    monkeypatch.setattr(browser_manager, "launch_browser", lambda *args, **kwargs: types.SimpleNamespace(close=lambda: None))
    result = browser_manager.get_browser_status("chromium")
    assert result["status"] == "installed"
    assert "Patchright" in result["message"]


def test_camoufox_socks5_geoip_failure_retries_without_spoof(monkeypatch):
    calls = []

    class Browser:
        def close(self):
            calls.append("close")

    class Manager:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            self.kwargs = kwargs

        def __enter__(self):
            if self.kwargs["geoip"]:
                raise RuntimeError("geoip lookup failed")
            return Browser()

        def __exit__(self, *args):
            calls.append("exit")

    camoufox = types.ModuleType("camoufox")
    camoufox.__path__ = []
    monkeypatch.setitem(sys.modules, "camoufox", camoufox)
    sync_api = types.ModuleType("camoufox.sync_api")
    sync_api.Camoufox = Manager
    monkeypatch.setitem(sys.modules, "camoufox.sync_api", sync_api)
    proxy = {"server": "socks5://127.0.0.1:1080"}

    session = browser_manager.launch_browser("camoufox", proxy=proxy, geoip=True)
    launches = [item for item in calls if isinstance(item, dict)]
    assert launches[0]["geoip"] is True
    assert launches[1]["geoip"] is False
    session.close()


DRIVER_CLOSED_MESSAGE = (
    "BrowserType.launch: Connection closed while reading from the driver"
)


def test_camoufox_binary_missing_pattern_detector():
    # O erro exacto reportado pelo utilizador (binário em falta)…
    assert browser_manager._camoufox_binary_missing_error(DRIVER_CLOSED_MESSAGE) is True
    assert browser_manager._camoufox_binary_missing_error("Executable doesn't exist at …/camoufox") is True
    # …e mensagens de outros problemas continuam a ser tratadas como tal.
    assert browser_manager._camoufox_binary_missing_error("geoip lookup failed") is False
    assert browser_manager._camoufox_binary_missing_error("proxy authentication failed") is False


def test_launch_browser_translates_the_missing_binary_error(monkeypatch):
    # 1.0.21: o erro genérico de driver (binário Firefox em falta) passa a
    # dizer AO UTILIZADOR o que fazer: correr o instalador de novo.
    class Manager:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            raise RuntimeError(DRIVER_CLOSED_MESSAGE)

        def __exit__(self, *args):
            pass

    camoufox = types.ModuleType("camoufox")
    camoufox.__path__ = []
    monkeypatch.setitem(sys.modules, "camoufox", camoufox)
    sync_api = types.ModuleType("camoufox.sync_api")
    sync_api.Camoufox = Manager
    monkeypatch.setitem(sys.modules, "camoufox.sync_api", sync_api)

    with pytest.raises(browser_manager.BrowserLaunchError) as excinfo:
        browser_manager.launch_browser("camoufox")

    assert browser_manager.CAMOUFOX_BINARY_MISSING_HINT in str(excinfo.value)
    assert "npx.cmd --yes --prefer-online @danhachuel/thunderbolt install" in str(excinfo.value)


def test_launch_browser_async_translates_the_missing_binary_error(monkeypatch):
    class Manager:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            raise RuntimeError(DRIVER_CLOSED_MESSAGE)

        async def __aexit__(self, *args):
            pass

    camoufox = types.ModuleType("camoufox")
    camoufox.__path__ = []
    monkeypatch.setitem(sys.modules, "camoufox", camoufox)
    async_api = types.ModuleType("camoufox.async_api")
    async_api.AsyncCamoufox = Manager
    monkeypatch.setitem(sys.modules, "camoufox.async_api", async_api)

    with pytest.raises(browser_manager.BrowserLaunchError) as excinfo:
        asyncio.run(browser_manager.launch_browser_async("camoufox"))

    assert browser_manager.CAMOUFOX_BINARY_MISSING_HINT in str(excinfo.value)


def test_get_browser_status_translates_the_missing_binary_error(monkeypatch):
    # 1.0.42: o status passa pela checagem CENTRAL — o módulo é simulado
    # presente (no CI o camoufox não está instalado: requirements-dev exclui
    # os motores pesados) e o binário também, para o teste chegar ao launch.
    monkeypatch.setattr(browser_manager, "_camoufox_module_importable", lambda: True)
    monkeypatch.setattr(browser_manager, "_camoufox_browser_downloaded", lambda: True)

    def raise_driver_error(*args, **kwargs):
        raise RuntimeError(DRIVER_CLOSED_MESSAGE)

    monkeypatch.setattr(browser_manager, "launch_browser", raise_driver_error)

    result = browser_manager.get_browser_status("camoufox")

    assert result["status"] == "not_installed"
    assert result["message"] == browser_manager.CAMOUFOX_BINARY_MISSING_HINT


def test_directory_has_bytes_requires_real_content(tmp_path):
    # 1.0.22: integridade — cache vazio/esqueleto não conta como instalado.
    from pathlib import Path

    empty = tmp_path / "cache-vazio"
    empty.mkdir()
    assert browser_manager._directory_has_bytes(empty) is False

    skeleton = tmp_path / "cache-esqueleto"
    (skeleton / "logs").mkdir(parents=True)
    assert browser_manager._directory_has_bytes(skeleton) is False

    real = tmp_path / "cache-real"
    (real / "browser").mkdir(parents=True)
    (real / "browser" / "camoufox.exe").write_bytes(b"binario")
    assert browser_manager._directory_has_bytes(real) is True

    assert browser_manager._directory_has_bytes(tmp_path / "nao-existe") is False


def test_camoufox_browser_downloaded_uses_the_path_integrity_probe(monkeypatch, tmp_path):
    from pathlib import Path

    real_cache = tmp_path / "camoufox"
    (real_cache / "browser").mkdir(parents=True)
    (real_cache / "browser" / "camoufox.exe").write_bytes(b"binario")
    empty_cache = tmp_path / "camoufox-vazio"
    empty_cache.mkdir()
    calls = []

    class FakeResult:
        def __init__(self, returncode, stdout=""):
            self.returncode = returncode
            self.stdout = stdout

    def fake_run(command, **kwargs):
        # command == [sys.executable, "-m", "camoufox", "path"|"version"]
        subcommand = command[-1]
        calls.append(subcommand)
        if subcommand == "path":
            return FakeResult(0, str(real_cache) + "\n")
        return FakeResult(1)

    monkeypatch.setattr(browser_manager.subprocess, "run", fake_run)
    assert browser_manager._camoufox_browser_downloaded() is True
    assert calls == ["path"]  # integridade responde; version nem é consultado

    def fake_run_empty(command, **kwargs):
        if command[-1] == "path":
            return FakeResult(0, str(empty_cache) + "\n")
        return FakeResult(1)

    monkeypatch.setattr(browser_manager.subprocess, "run", fake_run_empty)
    assert browser_manager._camoufox_browser_downloaded() is False


def test_camoufox_browser_downloaded_falls_back_to_version_probe(monkeypatch):
    # camoufox antigo sem subcomando path → «Installed: yes» decide.
    class FakeResult:
        def __init__(self, returncode, stdout=""):
            self.returncode = returncode
            self.stdout = stdout

    def fake_run(command, **kwargs):
        if command[-1] == "path":
            return FakeResult(1)
        return FakeResult(0, "Camoufox v0.4.0\n  Installed                   Yes\n")

    monkeypatch.setattr(browser_manager.subprocess, "run", fake_run)
    assert browser_manager._camoufox_browser_downloaded() is True


def test_chromium_uses_patchright_when_present_and_playwright_only_if_absent(monkeypatch):
    calls = []

    class Browser:
        def close(self):
            pass

    class BrowserType:
        def launch(self, **kwargs):
            calls.append(kwargs)
            return Browser()

    class Runtime:
        chromium = BrowserType()

        def stop(self):
            pass

    monkeypatch.setattr(browser_manager, "_module_available", lambda name: name in {"patchright", "playwright"})
    patchright_module = types.ModuleType("patchright")
    patchright_module.__path__ = []
    patchright_sync = types.ModuleType("patchright.sync_api")
    patchright_sync.sync_playwright = lambda: types.SimpleNamespace(start=lambda: Runtime())
    monkeypatch.setitem(sys.modules, "patchright", patchright_module)
    monkeypatch.setitem(sys.modules, "patchright.sync_api", patchright_sync)
    session = browser_manager.launch_browser("chromium")
    session.close()
    assert calls == [{"headless": True}]


def test_launch_browser_async_uses_playwright_for_firefox(monkeypatch):
    calls = []

    class Browser:
        async def close(self):
            calls.append("close")

    class BrowserType:
        async def launch(self, **kwargs):
            calls.append(kwargs)
            return Browser()

    class Runtime:
        firefox = BrowserType()

        async def stop(self):
            calls.append("stop")

    class RuntimeContext:
        async def start(self):
            return Runtime()

    monkeypatch.setattr(browser_manager, "_module_available", lambda name: name == "playwright")
    playwright = types.ModuleType("playwright")
    playwright.__path__ = []
    async_api = types.ModuleType("playwright.async_api")
    async_api.async_playwright = lambda: RuntimeContext()
    monkeypatch.setitem(sys.modules, "playwright", playwright)
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api)

    async def run():
        session = await browser_manager.launch_browser_async("firefox")
        await session.close()

    asyncio.run(run())
    assert calls == [{"headless": True}, "close", "stop"]


def _capture_launch_logger():
    import logging

    records = []

    class CaptureHandler(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = CaptureHandler()
    browser_manager.browser_launch_logger.addHandler(handler)
    return records, handler


def test_camoufox_launch_is_humanized_and_logs_launch_kwargs(monkeypatch):
    """1.0.06 (PARTE 1): humanize=True no Camoufox + log [BROWSER-LAUNCH]."""
    calls = []

    class Browser:
        def close(self):
            pass

    class Manager:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def __enter__(self):
            return Browser()

        def __exit__(self, *args):
            pass

    camoufox = types.ModuleType("camoufox")
    camoufox.__path__ = []
    monkeypatch.setitem(sys.modules, "camoufox", camoufox)
    sync_api = types.ModuleType("camoufox.sync_api")
    sync_api.Camoufox = Manager
    monkeypatch.setitem(sys.modules, "camoufox.sync_api", sync_api)

    records, handler = _capture_launch_logger()
    try:
        session = browser_manager.launch_browser(
            "camoufox", headless=True, proxy={"server": "http://127.0.0.1:7890"}, geoip=True
        )
        session.close()
    finally:
        browser_manager.browser_launch_logger.removeHandler(handler)

    assert calls and calls[0]["humanize"] is True
    assert calls[0]["geoip"] is True
    launch_log = "\n".join(records)
    assert "[BROWSER-LAUNCH]" in launch_log
    assert "engine=camoufox" in launch_log
    assert "headless=True" in launch_log
    assert "humanize=True" in launch_log
    assert "geoip=True" in launch_log
    assert "http://127.0.0.1:7890" in launch_log


def test_launch_browser_async_camoufox_is_humanized(monkeypatch):
    """A Rota A (upload headless) lança o Camoufox via launch_browser_async."""
    calls = []

    class Browser:
        async def close(self):
            pass

    class Manager:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        async def __aenter__(self):
            return Browser()

        async def __aexit__(self, *args):
            pass

    camoufox = types.ModuleType("camoufox")
    camoufox.__path__ = []
    monkeypatch.setitem(sys.modules, "camoufox", camoufox)
    async_api = types.ModuleType("camoufox.async_api")
    async_api.AsyncCamoufox = Manager
    monkeypatch.setitem(sys.modules, "camoufox.async_api", async_api)

    async def run():
        session = await browser_manager.launch_browser_async("camoufox", headless=True)
        await session.close()

    asyncio.run(run())
    assert calls and calls[0]["humanize"] is True


def test_launch_log_masks_proxy_credentials():
    described = browser_manager._describe_proxy_for_log({"server": "http://user:secret@host:8080"})
    assert "user:secret" not in described
    assert "***:***@" in described
    assert browser_manager._describe_proxy_for_log(None) == "sem proxy"
