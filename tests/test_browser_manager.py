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
    monkeypatch.setattr(browser_manager, "_module_available", lambda name: False)
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
