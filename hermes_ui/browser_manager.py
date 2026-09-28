from __future__ import annotations

import importlib.util
import logging
import os
import re
import subprocess
import sys
from typing import Any

from hermes_ui.proxy_manager import normalize_proxy

logger = logging.getLogger(__name__)
CAMOUFOX_FETCH_HINT = "Execute python -m camoufox fetch para descarregar o browser Camoufox."


class BrowserLaunchError(RuntimeError):
    """Safe, actionable error raised when a browser cannot be started."""


class BrowserSession:
    def __init__(self, browser: Any, cleanup: Any = None):
        self._browser = browser
        self._cleanup = cleanup
        self._closed = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._browser, name)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._browser.close()
        finally:
            if self._cleanup:
                self._cleanup()


class AsyncBrowserSession:
    def __init__(self, browser: Any, cleanup: Any = None):
        self._browser = browser
        self._cleanup = cleanup
        self._closed = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._browser, name)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._browser.close()
        finally:
            if self._cleanup:
                result = self._cleanup()
                if hasattr(result, "__await__"):
                    await result


def _module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _proxy_scheme(proxy: Any) -> str:
    if isinstance(proxy, dict):
        server = str(proxy.get("server") or proxy.get("scheme") or proxy.get("type") or "").casefold()
        return server.split(":", 1)[0]
    return str(proxy or "").split(":", 1)[0].casefold()


def _sanitize_error(exc: BaseException, proxy: Any = None) -> str:
    message = str(exc) or type(exc).__name__
    if isinstance(proxy, dict):
        for secret in (str(proxy.get("username") or ""), str(proxy.get("password") or "")):
            if secret:
                message = message.replace(secret, "***")
    message = re.sub(r"(://)[^/@\s]+:[^/@\s]+@", r"\1***:***@", message)
    message = re.sub(r"(://)[^/@\s]+@", r"\1***@", message)
    return message[:700]


def get_available_browsers() -> list[dict[str, str]]:
    return [
        {"type": "camoufox", "label": "Camoufox"},
        {"type": "chromium", "label": "Chromium (Patchright)"},
        {"type": "firefox", "label": "Firefox (Playwright)"},
    ]


def has_gui_environment() -> bool:
    return os.name == "nt" or sys.platform == "darwin" or bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _camoufox_browser_downloaded() -> bool:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "camoufox", "version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    return re.search(r"(?mi)^\s*Installed\s+(?:yes|true)\s*$", result.stdout) is not None


def get_browser_status(browser_type: str) -> dict[str, str]:
    """Check browser import, binary availability and a real test launch."""
    name = str(browser_type or "").strip().casefold()
    if name not in {"camoufox", "chromium", "firefox"}:
        return {"status": "error", "message": "Tipo de browser desconhecido."}
    if name == "camoufox":
        if not _module_available("camoufox"):
            return {"status": "not_installed", "message": f"O pacote Camoufox não está instalado. {CAMOUFOX_FETCH_HINT}"}
        if not _camoufox_browser_downloaded():
            return {"status": "not_installed", "message": f"O binário Firefox do Camoufox não está descarregado. {CAMOUFOX_FETCH_HINT}"}
    elif name == "firefox":
        if not _module_available("playwright"):
            return {"status": "not_installed", "message": "Playwright não está instalado para Firefox."}
    elif not (_module_available("patchright") or _module_available("playwright")):
        return {"status": "not_installed", "message": "Patchright e Playwright não estão instalados para Chromium."}
    try:
        browser = launch_browser(name, headless=True, geoip=False)
        browser.close()
        provider = "Patchright" if name == "chromium" and _module_available("patchright") else "Playwright"
        return {"status": "installed", "message": f"{name.capitalize()} iniciou e fechou correctamente ({provider})."}
    except Exception as exc:
        message = _sanitize_error(exc)
        if name == "camoufox":
            message = f"Camoufox não iniciou: {message}. {CAMOUFOX_FETCH_HINT}"
        return {"status": "error", "message": message}


def launch_browser(browser_type: str = "camoufox", headless: bool = True, proxy: Any = None, geoip: bool = True) -> BrowserSession:
    name = str(browser_type or "camoufox").strip().casefold()
    if name not in {"camoufox", "chromium", "firefox"}:
        raise BrowserLaunchError("Tipo de browser desconhecido.")
    try:
        proxy_config = normalize_proxy(proxy)
    except Exception as exc:
        raise BrowserLaunchError(_sanitize_error(exc, proxy)) from exc
    if name == "camoufox":
        try:
            from camoufox.sync_api import Camoufox
        except ImportError as exc:
            raise BrowserLaunchError(f"O pacote Camoufox não está instalado. {CAMOUFOX_FETCH_HINT}") from exc
        def start_camoufox(use_geoip: bool) -> BrowserSession:
            manager = Camoufox(headless=headless, proxy=proxy_config, geoip=use_geoip)
            try:
                browser = manager.__enter__()
            except Exception:
                manager.__exit__(*sys.exc_info())
                raise
            return BrowserSession(browser, cleanup=lambda: manager.__exit__(None, None, None))
        try:
            return start_camoufox(bool(geoip))
        except Exception as exc:
            if geoip and proxy_config and _proxy_scheme(proxy_config) in {"socks5", "socks5h"}:
                logger.warning("Camoufox GeoIP falhou com SOCKS5; a iniciar sem spoofing geográfico. Credenciais ocultas.")
                try:
                    return start_camoufox(False)
                except Exception as retry_exc:
                    raise BrowserLaunchError(_sanitize_error(retry_exc, proxy_config)) from retry_exc
            raise BrowserLaunchError(_sanitize_error(exc, proxy_config)) from exc
    if name == "firefox":
        module_name = "playwright.sync_api"
    else:
        module_name = "patchright.sync_api" if _module_available("patchright") else "playwright.sync_api"
    if not _module_available(module_name.split(".", 1)[0]):
        raise BrowserLaunchError(f"{module_name.split('.', 1)[0]} não está instalado.")
    runtime = None
    try:
        if name == "chromium" and module_name.startswith("patchright"):
            from patchright.sync_api import sync_playwright
        else:
            from playwright.sync_api import sync_playwright
        runtime = sync_playwright().start()
        browser_type_obj = runtime.chromium if name == "chromium" else runtime.firefox
        browser = browser_type_obj.launch(headless=bool(headless), **({"proxy": proxy_config} if proxy_config else {}))
        return BrowserSession(browser, cleanup=runtime.stop)
    except Exception as exc:
        if runtime is not None:
            try:
                runtime.stop()
            except Exception:
                pass
        raise BrowserLaunchError(_sanitize_error(exc, proxy_config)) from exc


async def launch_browser_async(browser_type: str = "camoufox", headless: bool = True, proxy: Any = None, geoip: bool = True) -> AsyncBrowserSession:
    """Async counterpart used by the upstream social-auto-upload uploader."""
    name = str(browser_type or "camoufox").strip().casefold()
    if name not in {"camoufox", "chromium", "firefox"}:
        raise BrowserLaunchError("Tipo de browser desconhecido.")
    try:
        proxy_config = normalize_proxy(proxy)
    except Exception as exc:
        raise BrowserLaunchError(_sanitize_error(exc, proxy)) from exc
    if name == "camoufox":
        try:
            from camoufox.async_api import AsyncCamoufox
        except ImportError as exc:
            raise BrowserLaunchError(f"O pacote Camoufox não está instalado. {CAMOUFOX_FETCH_HINT}") from exc
        async def start_camoufox(use_geoip: bool) -> AsyncBrowserSession:
            manager = AsyncCamoufox(headless=headless, proxy=proxy_config, geoip=use_geoip)
            try:
                browser = await manager.__aenter__()
            except Exception:
                await manager.__aexit__(*sys.exc_info())
                raise
            return AsyncBrowserSession(browser, cleanup=lambda: manager.__aexit__(None, None, None))
        try:
            return await start_camoufox(bool(geoip))
        except Exception as exc:
            if geoip and proxy_config and _proxy_scheme(proxy_config) in {"socks5", "socks5h"}:
                logger.warning("Camoufox GeoIP falhou com SOCKS5; a iniciar sem spoofing geográfico. Credenciais ocultas.")
                try:
                    return await start_camoufox(False)
                except Exception as retry_exc:
                    raise BrowserLaunchError(_sanitize_error(retry_exc, proxy_config)) from retry_exc
            raise BrowserLaunchError(_sanitize_error(exc, proxy_config)) from exc
    use_patchright = name == "chromium" and _module_available("patchright")
    if name == "firefox" or not use_patchright:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise BrowserLaunchError("Playwright não está instalado.") from exc
    else:
        try:
            from patchright.async_api import async_playwright
        except ImportError as exc:
            raise BrowserLaunchError("Patchright está instalado mas o runtime não pôde ser importado.") from exc
    manager = async_playwright()
    runtime = await manager.start()
    try:
        browser_type_obj = runtime.chromium if name == "chromium" else runtime.firefox
        browser = await browser_type_obj.launch(headless=bool(headless), **({"proxy": proxy_config} if proxy_config else {}))
        return AsyncBrowserSession(browser, cleanup=runtime.stop)
    except Exception as exc:
        try:
            await runtime.stop()
        except Exception:
            pass
        raise BrowserLaunchError(_sanitize_error(exc, proxy_config)) from exc
