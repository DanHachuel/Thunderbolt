from __future__ import annotations

import asyncio
import json
import logging
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock

from hermes_ui import storage as storage_module
from hermes_ui.browser_manager import BrowserLaunchError, has_gui_environment, launch_browser, launch_browser_async
from hermes_ui.proxy_manager import get_active_proxy, get_proxy_for_browser
from integrations.platforms import IntegrationResult

logger = logging.getLogger(__name__)
YOUTUBE_LOGIN_URL = "https://studio.youtube.com"
YOUTUBE_UPLOAD_UNCERTAIN = "upload_uncertain"
TERMINAL_CHECKPOINTS = {"upload_confirmed", "upload_failed_clean"}


def session_directory() -> Path:
    return storage_module.STORAGE / "state" / "social_auto_upload"


def session_state_path() -> Path:
    return session_directory() / "storage_state.json"


def upload_lock_path() -> Path:
    return storage_module.STORAGE / "state" / "social_auto_upload.lock"


def checkpoint_path(task_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(task_id or "").strip())
    if not safe_id or safe_id in {".", ".."}:
        raise ValueError("task_id inválido para checkpoint de upload.")
    return session_directory() / f"{safe_id}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def session_cookies_for_domain(state: Any, domain: str = "youtube.com") -> list[dict[str, Any]]:
    if not isinstance(state, dict) or not isinstance(state.get("cookies"), list):
        return []
    suffix = str(domain or "").strip().casefold().lstrip(".")
    cookies = []
    for cookie in state["cookies"]:
        if not isinstance(cookie, dict) or not str(cookie.get("name") or "").strip() or not str(cookie.get("value") or "").strip():
            continue
        cookie_domain = str(cookie.get("domain") or "").strip().casefold().lstrip(".")
        if cookie_domain == suffix or cookie_domain.endswith(f".{suffix}"):
            cookies.append(cookie)
    return cookies


def validate_storage_state(path: str | Path, domain: str = "youtube.com") -> tuple[bool, str]:
    payload = _read_json_file(Path(path))
    if payload is None:
        return False, "O ficheiro storage_state.json não existe ou não contém JSON válido."
    if not session_cookies_for_domain(payload, domain):
        return False, f"O storage_state.json não contém cookies de sessão não vazios para {domain}."
    return True, "Sessão válida."


def has_valid_youtube_session() -> bool:
    return validate_storage_state(session_state_path(), "youtube.com")[0]


def login_youtube_session(
    *, browser_type: str = "camoufox", proxy_id: str | None = None, timeout_seconds: int = 300,
) -> dict[str, Any]:
    """Open a visible login, wait up to five minutes and persist only validated cookies."""
    if not has_gui_environment():
        return {"success": False, "status": "no_gui", "message": "O login visível requer GUI. Inicie o login num ambiente com GUI ou VNC/X11 e copie storage_state.json para storage/state/social_auto_upload/."}
    timeout_seconds = min(300, max(1, int(timeout_seconds)))
    deadline = time.monotonic() + timeout_seconds
    browser = context = page = None
    target = session_state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_state = target.with_name(f".storage_state.{uuid.uuid4().hex}.tmp.json")
    proxy = get_proxy_for_browser(proxy_id) if proxy_id else get_active_proxy()
    try:
        browser = launch_browser(browser_type, headless=False, proxy=proxy, geoip=browser_type == "camoufox")
        context = browser.new_context()
        page = context.new_page()
        remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
        try:
            page.goto(YOUTUBE_LOGIN_URL, wait_until="domcontentloaded", timeout=remaining_ms)
        except Exception:
            if page.is_closed():
                return {"success": False, "status": "closed", "message": "O browser foi fechado antes de concluir o login; nenhuma sessão parcial foi guardada."}
            if time.monotonic() >= deadline:
                return {"success": False, "status": "timeout", "message": "O login não foi concluído em 5 minutos; nenhuma sessão parcial foi guardada."}
            raise
        authenticated = False
        while time.monotonic() < deadline:
            try:
                if page.is_closed():
                    return {"success": False, "status": "closed", "message": "O browser foi fechado antes de concluir o login; nenhuma sessão parcial foi guardada."}
                current_url = str(page.url or "")
                if "studio.youtube.com" in current_url.casefold():
                    authenticated = True
                    break
                page.wait_for_timeout(500)
            except Exception:
                if page is not None:
                    try:
                        if page.is_closed():
                            return {"success": False, "status": "closed", "message": "O browser foi fechado antes de concluir o login; nenhuma sessão parcial foi guardada."}
                    except Exception:
                        pass
                time.sleep(0.5)
        if not authenticated:
            return {"success": False, "status": "timeout", "message": "O login não foi concluído em 5 minutos; nenhuma sessão parcial foi guardada."}
        context.storage_state(path=str(temp_state))
        valid, message = validate_storage_state(temp_state, "youtube.com")
        if not valid:
            return {"success": False, "status": "invalid_session", "message": message}
        os.replace(temp_state, target)
        return {"success": True, "status": "logged_in", "message": "Login validado e sessão guardada localmente."}
    except Exception as exc:
        safe_message = str(exc)
        for secret in (str((proxy or {}).get("username") or ""), str((proxy or {}).get("password") or "")):
            if secret:
                safe_message = safe_message.replace(secret, "***")
        safe_message = safe_message[:500]
        return {"success": False, "status": "failed", "message": f"Não foi possível concluir o login visível: {safe_message}"}
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        try:
            temp_state.unlink()
        except FileNotFoundError:
            pass


def write_checkpoint(task_id: str, status: str, **details: Any) -> Path:
    payload = {
        "task_id": str(task_id),
        "status": str(status),
        "updated_at": _now(),
        **details,
    }
    path = checkpoint_path(task_id)
    _atomic_json(path, payload)
    return path


def _safe_failure(exc: BaseException, proxy: Any) -> str:
    message = str(exc) or type(exc).__name__
    if isinstance(proxy, dict):
        for secret in (str(proxy.get("username") or ""), str(proxy.get("password") or "")):
            if secret:
                message = message.replace(secret, "***")
    message = re.sub(r"(://)[^/@\s]+:[^/@\s]+@", r"\1***:***@", message)
    return message[:700]


class _UploadTrace:
    def __init__(self) -> None:
        self.session = None
        self.file_upload_started = False
        self.publish_clicked = False
        self.video_url = ""


class _LocatorProxy:
    def __init__(self, locator: Any, selector: str, trace: _UploadTrace):
        self._locator = locator
        self._selector = selector
        self._trace = trace

    @property
    def first(self):
        return _LocatorProxy(self._locator.first, self._selector, self._trace)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._locator, name)

    async def click(self, *args: Any, **kwargs: Any) -> Any:
        result = await self._locator.click(*args, **kwargs)
        if "#done-button" in self._selector:
            self._trace.publish_clicked = True
        return result

    async def set_input_files(self, *args: Any, **kwargs: Any) -> Any:
        if "input[type=\"file\"]" in self._selector or "input[type='file']" in self._selector:
            self._trace.file_upload_started = True
        return await self._locator.set_input_files(*args, **kwargs)

    async def get_attribute(self, name: str, *args: Any, **kwargs: Any) -> Any:
        value = await self._locator.get_attribute(name, *args, **kwargs)
        if name == "href" and value and ("youtu.be/" in value or "watch?v=" in value):
            self._trace.video_url = str(value)
        return value


class _PageProxy:
    def __init__(self, page: Any, trace: _UploadTrace):
        self._page = page
        self._trace = trace

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._page, name)
        if name == "url" and value and ("youtu.be/" in str(value) or "watch?v=" in str(value)):
            self._trace.video_url = str(value)
        return value

    def locator(self, selector: str, *args: Any, **kwargs: Any) -> _LocatorProxy:
        return _LocatorProxy(self._page.locator(selector, *args, **kwargs), selector, self._trace)


class _ContextProxy:
    def __init__(self, context: Any, trace: _UploadTrace):
        self._context = context
        self._trace = trace

    def __getattr__(self, name: str) -> Any:
        return getattr(self._context, name)

    async def new_page(self) -> _PageProxy:
        return _PageProxy(await self._context.new_page(), self._trace)


class _BrowserProxy:
    def __init__(self, browser: Any, trace: _UploadTrace):
        self._browser = browser
        self._trace = trace

    def __getattr__(self, name: str) -> Any:
        return getattr(self._browser, name)

    async def new_context(self, *args: Any, **kwargs: Any) -> _ContextProxy:
        return _ContextProxy(await self._browser.new_context(*args, **kwargs), self._trace)


class _BrowserTypeBridge:
    def __init__(self, browser_type: str, proxy: Any, geoip: bool, trace: _UploadTrace):
        self.browser_type = browser_type
        self.proxy = proxy
        self.geoip = geoip
        self.trace = trace

    async def launch(self, *args: Any, **kwargs: Any) -> _BrowserProxy:
        # Upstream hardcodes chromium/channel=chrome; this bridge applies the user's
        # browser choice, keeps uploads headless, and replaces its unconfigurable proxy.
        kwargs.pop("channel", None)
        kwargs.pop("proxy", None)
        self.trace.session = await launch_browser_async(
            self.browser_type,
            headless=True,
            proxy=self.proxy,
            geoip=self.geoip,
        )
        return _BrowserProxy(self.trace.session, self.trace)


class _PlaywrightBridge:
    def __init__(self, browser_type: str, proxy: Any, geoip: bool, trace: _UploadTrace):
        self.chromium = _BrowserTypeBridge(browser_type, proxy, geoip, trace)
        self.firefox = self.chromium
        self.webkit = self.chromium


async def _run_upstream_upload(
    *, state_file: Path, video_path: str, title: str, description: str, tags: list[str],
    thumbnail_path: str, visibility: str, browser_type: str, proxy: Any, geoip: bool,
) -> _UploadTrace:
    try:
        from uploader.youtube_uploader.main import YouTubeVideo
    except ImportError as exc:
        raise RuntimeError("A dependência pinned do social-auto-upload não está instalada corretamente.") from exc
    trace = _UploadTrace()
    upload = YouTubeVideo(
        title=title,
        file_path=video_path,
        tags=tags,
        account_file=str(state_file),
        description=description,
        thumbnail_path=thumbnail_path or None,
        visibility=visibility,
        headless=True,
    )
    try:
        await upload.upload(_PlaywrightBridge(browser_type, proxy, geoip, trace))
        return trace
    except Exception as exc:
        try:
            setattr(exc, "_social_auto_upload_trace", trace)
        except Exception:
            pass
        raise
    finally:
        if trace.session is not None:
            try:
                await trace.session.close()
            except Exception:
                pass


def upload_youtube_video(
    *, task_id: str, video_path: str, title: str, description: str = "", tags: list[str] | None = None,
    thumbnail_path: str = "", visibility: str = "unlisted", browser_type: str | None = None,
    proxy_id: str | None = None, geoip: bool = True,
) -> IntegrationResult:
    """Run one serialized SAU upload and record a crash-safe terminal checkpoint."""
    state_file = session_state_path()
    valid, validation_message = validate_storage_state(state_file, "youtube.com")
    if not valid:
        return IntegrationResult(False, validation_message, {"route": "social-auto-upload", "status": "skipped", "reason": "session_unavailable"})
    selected_browser = str(browser_type or "camoufox").strip().casefold()
    if selected_browser not in {"camoufox", "chromium", "firefox"}:
        selected_browser = "camoufox"
    proxy = get_proxy_for_browser(proxy_id) if proxy_id else get_active_proxy()
    task_checkpoint = checkpoint_path(task_id)
    task_checkpoint.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(upload_lock_path()))
    with lock:
        write_checkpoint(task_id, "upload_started", route="social-auto-upload", platform="youtube", browser=selected_browser, started_at=_now())
        temp_session = task_checkpoint.with_name(f".{task_checkpoint.stem}.session.{uuid.uuid4().hex}.json")
        terminal_state = "upload_failed_clean"
        trace = _UploadTrace()
        message = ""
        data: dict[str, Any] = {"route": "social-auto-upload", "checkpoint": str(task_checkpoint)}
        try:
            shutil.copyfile(state_file, temp_session)
            try:
                trace = asyncio.run(_run_upstream_upload(
                    state_file=temp_session,
                    video_path=video_path,
                    title=title,
                    description=description,
                    tags=list(tags or []),
                    thumbnail_path=thumbnail_path,
                    visibility=visibility,
                    browser_type=selected_browser,
                    proxy=proxy,
                    geoip=bool(geoip),
                ))
            except BrowserLaunchError as exc:
                if selected_browser != "chromium":
                    try:
                        trace = asyncio.run(_run_upstream_upload(
                            state_file=temp_session,
                            video_path=video_path,
                            title=title,
                            description=description,
                            tags=list(tags or []),
                            thumbnail_path=thumbnail_path,
                            visibility=visibility,
                            browser_type="chromium",
                            proxy=proxy,
                            geoip=False,
                        ))
                        selected_browser = "chromium"
                        message = f"Browser preferido indisponível; upload executado com Chromium. Motivo: {_safe_failure(exc, proxy)}"
                    except Exception as fallback_exc:
                        trace = getattr(fallback_exc, "_social_auto_upload_trace", trace)
                        raise RuntimeError(f"Não foi possível iniciar o browser seleccionado nem Chromium: {_safe_failure(fallback_exc, proxy)}") from fallback_exc
                else:
                    raise
            if trace.publish_clicked and trace.video_url:
                valid_new, _ = validate_storage_state(temp_session, "youtube.com")
                if valid_new:
                    os.replace(temp_session, state_file)
                terminal_state = "upload_confirmed"
                data.update({"browser": selected_browser, "video_url": trace.video_url, "checkpoint_state": terminal_state})
                message = message or "Upload confirmado no YouTube via social-auto-upload."
            elif trace.file_upload_started:
                terminal_state = YOUTUBE_UPLOAD_UNCERTAIN
                message = "O envio começou, mas não foi possível confirmar a publicação. Verifique manualmente o YouTube antes de tentar novamente."
            else:
                terminal_state = "upload_failed_clean"
                message = "O upload não chegou a enviar o ficheiro; é seguro tentar novamente depois de corrigir a sessão ou o browser."
        except Exception as exc:
            trace = getattr(exc, "_social_auto_upload_trace", trace)
            if trace.publish_clicked and trace.video_url:
                valid_new, _ = validate_storage_state(temp_session, "youtube.com")
                if valid_new:
                    os.replace(temp_session, state_file)
                terminal_state = "upload_confirmed"
                data.update({"browser": selected_browser, "video_url": trace.video_url, "checkpoint_state": terminal_state})
                message = "A publicação foi confirmada pelo YouTube, apesar de uma falha posterior no processo."
            elif getattr(trace, "file_upload_started", False):
                terminal_state = YOUTUBE_UPLOAD_UNCERTAIN
                message = "O processo falhou depois do início do envio. Verifique manualmente o YouTube antes de tentar novamente."
            else:
                terminal_state = "upload_failed_clean"
                message = f"O upload falhou antes de iniciar a transferência: {_safe_failure(exc, proxy)}"
        finally:
            if temp_session.exists():
                try:
                    temp_session.unlink()
                except OSError:
                    pass
            details = {"route": "social-auto-upload", "platform": "youtube", "finished_at": _now()}
            if terminal_state == YOUTUBE_UPLOAD_UNCERTAIN:
                details["reason"] = YOUTUBE_UPLOAD_UNCERTAIN
            if terminal_state == "upload_confirmed":
                details.update({"browser": selected_browser, "video_url": trace.video_url})
            write_checkpoint(task_id, terminal_state, **details)
        data["checkpoint_state"] = terminal_state
        if terminal_state == "upload_confirmed":
            return IntegrationResult(True, message, data)
        if terminal_state == YOUTUBE_UPLOAD_UNCERTAIN:
            data["reason"] = YOUTUBE_UPLOAD_UNCERTAIN
            return IntegrationResult(False, message, data)
        return IntegrationResult(False, message, data)


def reconcile_uncertain_uploads() -> list[str]:
    """Turn interrupted upload_started checkpoints into blocked tasks, under the upload lock."""
    from hermes_ui.domain import update_task

    directory = session_directory()
    if not directory.exists():
        return []
    recovered: list[str] = []
    with FileLock(str(upload_lock_path())):
        for path in directory.glob("*.json"):
            payload = _read_json_file(path)
            if not payload or payload.get("status") != "upload_started":
                continue
            task_id = str(payload.get("task_id") or path.stem)
            message = "O processo terminou durante o upload. Verifique manualmente na plataforma antes de retentar; não foi feito retry automático."
            update_task(task_id, {
                "state": "blocked",
                "stage": "upload",
                "error": message,
                "stop_reason": YOUTUBE_UPLOAD_UNCERTAIN,
                "upload_uncertain": True,
            })
            payload.update({"status": YOUTUBE_UPLOAD_UNCERTAIN, "reason": YOUTUBE_UPLOAD_UNCERTAIN, "recovered_at": _now(), "updated_at": _now()})
            _atomic_json(path, payload)
            recovered.append(task_id)
    return recovered


# The upstream social-auto-upload package is intentionally invoked through its
# documented ``sau`` CLI. Its uploaders import ``conf.BASE_DIR``; it does not
# consume a BASE_DIR environment variable, so a private runtime conf.py is used.
SAU_PLATFORM_ROWS = (
    {"platform": "douyin", "label": "Douyin", "browser": "Patchright / Chromium", "login_mode": "headed"},
    {"platform": "kuaishou", "label": "Kuaishou", "browser": "Patchright / Chromium", "login_mode": "headed"},
    {"platform": "xiaohongshu", "label": "Xiaohongshu", "browser": "Patchright / Chromium", "login_mode": "headed"},
    {"platform": "bilibili", "label": "Bilibili", "browser": "CLI upstream", "login_mode": "terminal"},
    {"platform": "tencent", "label": "Tencent / WeChat Channels", "browser": "Patchright / Chromium", "login_mode": "headed"},
    {"platform": "baijiahao", "label": "Baijiahao", "browser": "Patchright / Chromium", "login_mode": "headed"},
    {"platform": "alipay", "label": "Alipay", "browser": "Patchright / Chromium", "login_mode": "headed"},
    {"platform": "weibo", "label": "Weibo", "browser": "Patchright / Chromium", "login_mode": "headed"},
    {"platform": "hupu", "label": "Hupu", "browser": "Patchright / Chromium", "login_mode": "headed"},
    {"platform": "youtube", "label": "YouTube (CLI opcional)", "browser": "Patchright / Chromium", "login_mode": "headed"},
)
SAU_UNSUPPORTED_PLATFORMS = {
    "tiktok": "TikTok não é suportado pela CLI upstream; use uma integração TikTok já existente no Thunderbolt.",
}
SAU_THUMBNAIL_PLATFORMS = {"douyin", "kuaishou", "xiaohongshu", "tencent", "baijiahao", "alipay", "weibo", "hupu", "youtube"}
SAU_ACCOUNT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def get_platform_uploaders() -> list[dict[str, str]]:
    """Return the platforms documented by the pinned upstream CLI."""
    return [dict(row) for row in SAU_PLATFORM_ROWS]


def _normalise_sau_platform(platform: str) -> str:
    value = str(platform or "").strip().casefold().replace("-", "_")
    if value in SAU_UNSUPPORTED_PLATFORMS:
        raise ValueError(SAU_UNSUPPORTED_PLATFORMS[value])
    if value not in {row["platform"] for row in SAU_PLATFORM_ROWS}:
        raise ValueError(f"A CLI social-auto-upload não declara suporte à plataforma {value or 'vazia'}.")
    return value


def _validate_sau_account_name(account_name: str) -> str:
    value = str(account_name or "").strip()
    if not SAU_ACCOUNT_NAME_RE.fullmatch(value) or value in {".", ".."}:
        raise ValueError("O nome da conta deve usar 1–64 caracteres: letras, números, ponto, hífen ou underscore; não pode conter caminhos.")
    return value


def _sau_base_directory() -> Path:
    settings = storage_module.read_json("settings.json", {})
    configured = str(settings.get("sau_base_dir") or "").strip() if isinstance(settings, dict) else ""
    if not configured:
        return session_directory().resolve()
    candidate = Path(configured).expanduser()
    if not candidate.is_absolute():
        candidate = session_directory() / candidate
    return candidate.resolve()


def _sau_runtime_directory() -> Path:
    return session_directory() / "runtime"


def _write_sau_runtime_config() -> Path:
    runtime = _sau_runtime_directory()
    runtime.mkdir(parents=True, exist_ok=True)
    base = _sau_base_directory()
    base.mkdir(parents=True, exist_ok=True)
    source = (
        "from pathlib import Path\n"
        f"BASE_DIR = Path({str(base)!r}).resolve()\n"
        "XHS_SERVER = 'http://127.0.0.1:11901'\n"
        "LOCAL_CHROME_PATH = ''\n"
        "LOCAL_CHROME_HEADLESS = True\n"
        "DEBUG_MODE = False\n"
        "YT_PROXY = None\n"
    )
    config_path = runtime / "conf.py"
    if not config_path.exists() or config_path.read_text(encoding="utf-8") != source:
        temporary = config_path.with_name(f".conf.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(source, encoding="utf-8")
            os.replace(temporary, config_path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    (base / "cookies").mkdir(parents=True, exist_ok=True)
    return runtime


def _sau_environment() -> tuple[dict[str, str], Path]:
    runtime = _write_sau_runtime_config()
    env = dict(os.environ)
    old_pythonpath = str(env.get("PYTHONPATH") or "").strip()
    env["PYTHONPATH"] = str(runtime) + (os.pathsep + old_pythonpath if old_pythonpath else "")
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env, runtime


def _sau_command_prefix() -> list[str] | None:
    scripts_dir = Path(sys.executable).resolve().parent
    candidates = [scripts_dir / ("sau.exe" if os.name == "nt" else "sau"), scripts_dir / "sau"]
    for candidate in candidates:
        if candidate.is_file():
            return [str(candidate)]
    found = shutil.which("sau")
    if found:
        return [found]
    module_path = scripts_dir.parent / "Lib" / "site-packages" / "sau_cli.py" if os.name == "nt" else None
    if module_path is not None and module_path.is_file():
        return [sys.executable, "-m", "sau_cli"]
    if shutil.which(sys.executable):
        # The pinned source distribution exposes ``sau_cli`` as a module even
        # in virtualenvs where console-script generation was interrupted.
        return [sys.executable, "-m", "sau_cli"]
    return None


def _sanitise_sau_output(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)([\"']?(?:cookie|token|sessdata|bili_jct|access_token|refresh_token)[\"']?\s*[:=]\s*[\"']?)([^\"'\s,;}]+)([\"']?)", r"\1***\3", text)
    text = re.sub(r"(://)[^/@\s]+:[^/@\s]+@", r"\1***:***@", text)
    return text[-1800:].strip()


def _run_sau_cli(arguments: list[str], *, timeout_seconds: int = 30) -> dict[str, Any]:
    prefix = _sau_command_prefix()
    if prefix is None:
        return {"status": "not_installed", "returncode": None, "stdout": "", "stderr": "", "message": "A CLI `sau` não foi encontrada no ambiente Python do Thunderbolt."}
    env, runtime = _sau_environment()
    command = [*prefix, *[str(item) for item in arguments]]
    try:
        completed = subprocess.run(
            command,
            cwd=str(runtime),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, int(timeout_seconds)),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _sanitise_sau_output(exc.stdout)
        stderr = _sanitise_sau_output(exc.stderr)
        return {"status": "timeout", "returncode": None, "stdout": stdout, "stderr": stderr, "message": f"A CLI excedeu o limite de {int(timeout_seconds)} segundos."}
    except OSError as exc:
        return {"status": "error", "returncode": None, "stdout": "", "stderr": "", "message": f"Não foi possível iniciar a CLI: {type(exc).__name__}: {exc}"}
    stdout = _sanitise_sau_output(completed.stdout)
    stderr = _sanitise_sau_output(completed.stderr)
    return {
        "status": "ok" if completed.returncode == 0 else "failed",
        "returncode": int(completed.returncode),
        "stdout": stdout,
        "stderr": stderr,
        "message": stderr or stdout or ("CLI concluída." if completed.returncode == 0 else "A CLI terminou com erro sem mensagem."),
    }


def get_sau_install_status() -> dict[str, Any]:
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if not (sys.version_info >= (3, 10) and sys.version_info < (3, 13)):
        return {"status": "error", "installed": False, "python": version, "message": "social-auto-upload requer Python >=3.10 e <3.13."}
    result = _run_sau_cli(["--help"], timeout_seconds=10)
    if result["status"] == "not_installed":
        return {"status": "not_installed", "installed": False, "python": version, "message": result["message"]}
    if result["status"] != "ok":
        return {"status": "error", "installed": False, "python": version, "message": result["message"]}
    return {"status": "installed", "installed": True, "python": version, "message": "CLI social-auto-upload disponível; as plataformas suportadas usam a rota upstream Patchright/Chromium."}


def get_sau_cookie_path(platform: str, account_name: str) -> Path:
    normalised = _normalise_sau_platform(platform)
    account = _validate_sau_account_name(account_name)
    return _sau_base_directory() / "cookies" / f"{normalised}_{account}.json"


def list_sau_accounts(platform: str | None = None) -> list[dict[str, str]]:
    settings = storage_module.read_json("settings.json", {})
    raw = settings.get("sau_accounts", []) if isinstance(settings, dict) else []
    if not isinstance(raw, list):
        return []
    selected_platform = _normalise_sau_platform(platform) if platform else None
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            item_platform = _normalise_sau_platform(str(item.get("platform") or ""))
            account_name = _validate_sau_account_name(str(item.get("account_name") or ""))
        except ValueError:
            continue
        if selected_platform and item_platform != selected_platform:
            continue
        result.append({"platform": item_platform, "account_name": account_name, "label": str(item.get("label") or account_name)})
    return sorted(result, key=lambda item: (item["platform"], item["label"].casefold(), item["account_name"].casefold()))


def add_sau_account(platform: str, account_name: str, label: str = "") -> dict[str, str]:
    normalised = _normalise_sau_platform(platform)
    account = _validate_sau_account_name(account_name)
    item = {"platform": normalised, "account_name": account, "label": str(label or account).strip()[:100] or account}

    def mutate(settings: Any) -> None:
        if not isinstance(settings, dict):
            return
        accounts = settings.get("sau_accounts")
        if not isinstance(accounts, list):
            accounts = []
        replaced = False
        for index, current in enumerate(accounts):
            if isinstance(current, dict) and str(current.get("platform") or "").casefold() == normalised and str(current.get("account_name") or "").casefold() == account.casefold():
                accounts[index] = item
                replaced = True
                break
        if not replaced:
            accounts.append(item)
        settings["sau_accounts"] = accounts

    storage_module.update_json("settings.json", {}, mutate)
    return item


def remove_sau_account(platform: str, account_name: str) -> bool:
    normalised = _normalise_sau_platform(platform)
    account = _validate_sau_account_name(account_name)
    removed = False

    def mutate(settings: Any) -> None:
        nonlocal removed
        if not isinstance(settings, dict) or not isinstance(settings.get("sau_accounts"), list):
            return
        kept = []
        for item in settings["sau_accounts"]:
            if isinstance(item, dict) and str(item.get("platform") or "").casefold() == normalised and str(item.get("account_name") or "").casefold() == account.casefold():
                removed = True
            else:
                kept.append(item)
        settings["sau_accounts"] = kept

    storage_module.update_json("settings.json", {}, mutate)
    return removed


def _restore_cookie_file(path: Path, previous: bytes | None) -> None:
    if previous is None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(previous)


def _launch_bilibili_login(command: list[str], *, runtime: Path, env: dict[str, str]) -> dict[str, Any]:
    try:
        if os.name == "nt":
            process = subprocess.Popen(command, cwd=str(runtime), env=env, creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
            return {"success": True, "status": "terminal_opened", "message": "Foi aberta uma consola separada para concluir o login Bilibili. Depois, use Verificar sessão.", "process_id": process.pid}
        terminal = shutil.which("x-terminal-emulator") or shutil.which("xterm")
        if terminal and has_gui_environment():
            args = [terminal, "-e", *command] if Path(terminal).name != "x-terminal-emulator" else [terminal, "-e", *command]
            process = subprocess.Popen(args, cwd=str(runtime), env=env)
            return {"success": True, "status": "terminal_opened", "message": "Foi aberta uma consola separada para concluir o login Bilibili. Depois, use Verificar sessão.", "process_id": process.pid}
    except OSError as exc:
        return {"success": False, "status": "terminal_error", "message": f"Não foi possível abrir a consola interactiva: {type(exc).__name__}: {exc}"}
    return {"success": False, "status": "terminal_required", "message": "O login Bilibili exige uma consola interactiva. Execute o login num desktop/terminal com GUI ou copie o cookie obtido para o caminho local indicado.", "cookie_path": str(_sau_base_directory() / "cookies")}


def login_platform(platform: str, account_name: str, *, timeout_seconds: int = 300) -> dict[str, Any]:
    normalised = _normalise_sau_platform(platform)
    account = _validate_sau_account_name(account_name)
    deadline = time.monotonic() + min(300, max(1, int(timeout_seconds)))
    status = get_sau_install_status()
    if not status.get("installed"):
        return {"success": False, "status": status.get("status", "error"), "message": status.get("message", "CLI indisponível.")}
    env, runtime = _sau_environment()
    args = [normalised, "login", "--account", account]
    cookie_path = get_sau_cookie_path(normalised, account)
    cookie_path.parent.mkdir(parents=True, exist_ok=True)
    if normalised == "bilibili":
        prefix = _sau_command_prefix()
        if prefix is None:
            return {"success": False, "status": "not_installed", "message": "A CLI `sau` não foi encontrada no ambiente Python do Thunderbolt."}
        result = _launch_bilibili_login([*prefix, *args], runtime=runtime, env=env)
        result.setdefault("cookie_path", str(cookie_path))
        return result
    if not has_gui_environment():
        return {"success": False, "status": "no_gui", "message": "O login exige browser visível. Inicie-o num desktop com GUI; em servidor headless, copie o cookie validado para o caminho indicado.", "cookie_path": str(cookie_path)}
    args.append("--headed")
    try:
        previous = cookie_path.read_bytes() if cookie_path.is_file() else None
    except OSError:
        previous = None
    remaining_seconds = int(deadline - time.monotonic())
    if remaining_seconds <= 0:
        return {"success": False, "status": "timeout", "message": "O login excedeu o limite de 5 minutos antes de iniciar. Nenhuma sessão parcial foi guardada.", "cookie_path": str(cookie_path)}
    result = _run_sau_cli(args, timeout_seconds=remaining_seconds)
    if result["status"] == "timeout":
        _restore_cookie_file(cookie_path, previous)
        return {"success": False, "status": "timeout", "message": "O login expirou após 5 minutos. A sessão anterior foi preservada e cookies parciais não foram guardados.", "cookie_path": str(cookie_path)}
    if result["status"] != "ok":
        _restore_cookie_file(cookie_path, previous)
        return {"success": False, "status": result["status"], "message": _sanitise_sau_output(result["message"]), "cookie_path": str(cookie_path)}
    remaining_seconds = int(deadline - time.monotonic())
    if remaining_seconds <= 0:
        _restore_cookie_file(cookie_path, previous)
        return {"success": False, "status": "timeout", "message": "O login excedeu o limite de 5 minutos durante a validação. Nenhuma sessão parcial foi guardada.", "cookie_path": str(cookie_path)}
    checked = check_platform_session(normalised, account, timeout_seconds=remaining_seconds)
    if checked.get("status") == "timeout":
        _restore_cookie_file(cookie_path, previous)
        return {"success": False, "status": "timeout", "message": "O login excedeu o limite de 5 minutos durante a validação. A sessão anterior foi preservada.", "cookie_path": str(cookie_path)}
    if not checked.get("valid"):
        _restore_cookie_file(cookie_path, previous)
        return {"success": False, "status": "invalid_session", "message": f"O login terminou, mas a sessão não passou na verificação do upstream: {checked.get('message')}", "cookie_path": str(cookie_path)}
    return {"success": True, "status": "logged_in", "message": "Login visível concluído e sessão validada pela CLI upstream.", "cookie_path": str(cookie_path), "output": _sanitise_sau_output(result.get("stdout"))}


def check_platform_session(platform: str, account_name: str, *, timeout_seconds: int = 45) -> dict[str, Any]:
    normalised = _normalise_sau_platform(platform)
    account = _validate_sau_account_name(account_name)
    cookie_path = get_sau_cookie_path(normalised, account)
    if not cookie_path.is_file() or cookie_path.stat().st_size == 0:
        return {"valid": False, "status": "missing", "message": "Cookie ausente; inicie o login visível para esta conta.", "cookie_path": str(cookie_path)}
    result = _run_sau_cli([normalised, "check", "--account", account], timeout_seconds=timeout_seconds)
    if result["status"] != "ok":
        return {"valid": False, "status": result["status"], "message": _sanitise_sau_output(result.get("message")), "cookie_path": str(cookie_path)}
    return {"valid": True, "status": "valid", "message": "Sessão confirmada pela verificação upstream.", "cookie_path": str(cookie_path), "output": _sanitise_sau_output(result.get("stdout"))}


def sau_upload_checkpoint_id(task_id: str, platform: str, account_name: str, video_path: str | Path) -> str:
    normalised = _normalise_sau_platform(platform)
    account = _validate_sau_account_name(account_name)
    # One task may publish at most once to a given platform/account, even if
    # the same asset is renamed or its filesystem timestamp changes.
    digest = hashlib.sha256(f"{task_id}\0{normalised}\0{account}".encode("utf-8")).hexdigest()[:16]
    safe_task = re.sub(r"[^A-Za-z0-9_.-]", "_", str(task_id or "task"))[:48] or "task"
    return f"sau-{safe_task}-{normalised}-{digest}"


def get_sau_upload_checkpoint(checkpoint_id: str) -> dict[str, Any] | None:
    try:
        return _read_json_file(checkpoint_path(checkpoint_id))
    except ValueError:
        return None


def _write_sau_checkpoint(checkpoint_id: str, status: str, *, task_id: str, **details: Any) -> Path:
    payload = {"task_id": str(task_id), "status": str(status), "updated_at": _now(), **details}
    path = checkpoint_path(checkpoint_id)
    _atomic_json(path, payload)
    return path


def _set_task_uncertain(task_id: str, message: str) -> None:
    if not task_id:
        return

    def mutate(tasks: Any) -> None:
        if not isinstance(tasks, list):
            return
        for task in tasks:
            if isinstance(task, dict) and str(task.get("id") or "") == str(task_id):
                task.update({"state": "blocked", "stage": "upload", "error": message, "stop_reason": YOUTUBE_UPLOAD_UNCERTAIN, "upload_uncertain": True, "upload_status": YOUTUBE_UPLOAD_UNCERTAIN, "updated_at": _now()})
                break

    storage_module.update_json("tasks.json", [], mutate)


def confirm_sau_upload_not_published(checkpoint_id: str, task_id: str, *, manual_confirmation: bool = False) -> bool:
    if not manual_confirmation:
        raise ValueError("A confirmação manual de que a plataforma foi verificada é obrigatória.")
    payload = get_sau_upload_checkpoint(checkpoint_id)
    if not payload or payload.get("status") != YOUTUBE_UPLOAD_UNCERTAIN or str(payload.get("task_id") or "") != str(task_id):
        return False
    _atomic_json(checkpoint_path(checkpoint_id), {**payload, "status": "upload_failed_clean", "reason": "manual_verified_not_published", "manual_verified_at": _now(), "updated_at": _now()})

    def mutate(tasks: Any) -> None:
        if not isinstance(tasks, list):
            return
        for task in tasks:
            if isinstance(task, dict) and str(task.get("id") or "") == str(task_id):
                task.update({"state": "done", "stage": "ready_upload", "error": None, "upload_uncertain": False, "upload_status": "pending", "updated_at": _now()})
                task.pop("stop_reason", None)
                break

    storage_module.update_json("tasks.json", [], mutate)
    return True


def upload_video_via_sau(
    *, task_id: str, platform: str, account_name: str, video_path: str | Path,
    title: str, description: str = "", tags: list[str] | None = None,
    thumbnail_path: str | Path | None = None, category_id: int = 249,
    timeout_seconds: int = 600,
) -> IntegrationResult:
    """Upload through the documented upstream CLI, serialised and checkpointed."""
    try:
        normalised = _normalise_sau_platform(platform)
        account = _validate_sau_account_name(account_name)
    except ValueError as exc:
        return IntegrationResult(False, str(exc), {"route": "social-auto-upload-cli", "status": "skipped", "reason": "invalid_configuration"})
    video = Path(video_path).expanduser()
    if not video.is_file() or video.stat().st_size <= 0:
        return IntegrationResult(False, "O ficheiro de vídeo não existe ou está vazio.", {"route": "social-auto-upload-cli", "status": "skipped", "reason": "video_unavailable"})
    clean_title = str(title or "").strip()
    if not clean_title:
        return IntegrationResult(False, "O título do vídeo é obrigatório.", {"route": "social-auto-upload-cli", "status": "skipped", "reason": "title_required"})
    if normalised == "youtube" and len(clean_title) > 100:
        return IntegrationResult(False, "O título YouTube não pode exceder 100 caracteres.", {"route": "social-auto-upload-cli", "status": "skipped", "reason": "invalid_title"})
    if normalised == "weibo" and len(clean_title) > 30:
        return IntegrationResult(False, "O título Weibo não pode exceder 30 caracteres.", {"route": "social-auto-upload-cli", "status": "skipped", "reason": "invalid_title"})
    if normalised == "hupu" and not 4 <= len(clean_title) <= 40:
        return IntegrationResult(False, "O título Hupu deve ter entre 4 e 40 caracteres.", {"route": "social-auto-upload-cli", "status": "skipped", "reason": "invalid_title"})
    install_status = get_sau_install_status()
    if not install_status.get("installed"):
        return IntegrationResult(False, str(install_status.get("message") or "CLI indisponível."), {"route": "social-auto-upload-cli", "status": "skipped", "reason": "cli_unavailable"})
    session = check_platform_session(normalised, account)
    if not session.get("valid"):
        return IntegrationResult(False, str(session.get("message") or "A sessão não está válida."), {"route": "social-auto-upload-cli", "status": "skipped", "reason": "session_unavailable", "platform": normalised, "account": account})

    checkpoint_id = sau_upload_checkpoint_id(task_id, normalised, account, video)
    checkpoint = get_sau_upload_checkpoint(checkpoint_id)
    if checkpoint and checkpoint.get("status") == YOUTUBE_UPLOAD_UNCERTAIN:
        return IntegrationResult(False, "Já existe uma tentativa de upload sem confirmação. Verifique manualmente a plataforma antes de tentar novamente.", {"route": "social-auto-upload-cli", "status": "blocked", "reason": YOUTUBE_UPLOAD_UNCERTAIN, "checkpoint_state": checkpoint.get("status"), "checkpoint_id": checkpoint_id})
    if checkpoint and checkpoint.get("status") == "upload_confirmed":
        return IntegrationResult(False, "Esta publicação já foi confirmada para a mesma tarefa, conta e ficheiro; o Thunderbolt não repetiu o envio.", {"route": "social-auto-upload-cli", "status": "blocked", "reason": "already_confirmed", "checkpoint_state": "upload_confirmed", "checkpoint_id": checkpoint_id})

    args = [normalised, "upload-video", "--account", account, "--file", str(video.resolve()), "--title", clean_title, "--desc", str(description or "")]
    clean_tags = [str(tag).strip() for tag in (tags or []) if str(tag).strip()]
    if clean_tags:
        args.extend(["--tags", ",".join(clean_tags)])
    thumbnail = Path(thumbnail_path).expanduser() if thumbnail_path else None
    if thumbnail and thumbnail.is_file() and normalised in SAU_THUMBNAIL_PLATFORMS:
        args.extend(["--thumbnail", str(thumbnail.resolve())])
    if normalised == "bilibili":
        args.extend(["--tid", str(max(1, int(category_id or 249)))])
    else:
        args.append("--headless")

    lock = FileLock(str(upload_lock_path()))
    try:
        with lock:
            latest = get_sau_upload_checkpoint(checkpoint_id)
            if latest and latest.get("status") == "upload_started":
                recovery_message = "A operação anterior terminou sem checkpoint final. Verifique manualmente a plataforma antes de retentar."
                _write_sau_checkpoint(checkpoint_id, YOUTUBE_UPLOAD_UNCERTAIN, task_id=str(task_id), route="social-auto-upload-cli", platform=normalised, account=account, reason=YOUTUBE_UPLOAD_UNCERTAIN, recovered_at=_now())
                _set_task_uncertain(str(task_id), recovery_message)
                return IntegrationResult(False, recovery_message, {"route": "social-auto-upload-cli", "status": "blocked", "reason": YOUTUBE_UPLOAD_UNCERTAIN, "checkpoint_state": YOUTUBE_UPLOAD_UNCERTAIN, "checkpoint_id": checkpoint_id})
            if latest and latest.get("status") in {YOUTUBE_UPLOAD_UNCERTAIN, "upload_confirmed"}:
                return IntegrationResult(False, "A operação já foi iniciada ou concluída; confirme o histórico antes de repetir.", {"route": "social-auto-upload-cli", "status": "blocked", "reason": latest.get("status"), "checkpoint_id": checkpoint_id})
            _write_sau_checkpoint(checkpoint_id, "upload_started", task_id=str(task_id), route="social-auto-upload-cli", platform=normalised, account=account, backend="sau-cli + patchright/chromium", started_at=_now())
            terminal = "upload_uncertain"
            result_data: dict[str, Any] = {"route": "social-auto-upload-cli", "platform": normalised, "account": account, "backend": "sau-cli + patchright/chromium", "checkpoint_id": checkpoint_id}
            try:
                result = _run_sau_cli(args, timeout_seconds=max(1, int(timeout_seconds)))
                result_data.update({"returncode": result.get("returncode"), "output": _sanitise_sau_output(result.get("stdout") or result.get("stderr"))})
                if result.get("status") == "ok":
                    terminal = "upload_confirmed"
                    message = _sanitise_sau_output(result.get("stdout")) or f"Upload concluído pela CLI upstream para {normalised}."
                else:
                    terminal = YOUTUBE_UPLOAD_UNCERTAIN
                    message = f"A CLI falhou ou excedeu o timeout depois de iniciar a operação. Verifique {normalised} manualmente antes de tentar novamente. Detalhe: {_sanitise_sau_output(result.get('message'))}"
            except Exception as exc:
                terminal = YOUTUBE_UPLOAD_UNCERTAIN
                message = f"A operação CLI terminou inesperadamente; confirme manualmente {normalised} antes de retentar. {type(exc).__name__}: {_sanitise_sau_output(exc)}"
            finally:
                result_data["checkpoint_state"] = terminal
                details = {"task_id": str(task_id), "route": "social-auto-upload-cli", "platform": normalised, "account": account, "backend": "sau-cli + patchright/chromium", "finished_at": _now()}
                if terminal == YOUTUBE_UPLOAD_UNCERTAIN:
                    details["reason"] = YOUTUBE_UPLOAD_UNCERTAIN
                _write_sau_checkpoint(checkpoint_id, terminal, task_id=str(task_id), **{key: value for key, value in details.items() if key != "task_id"})
                if terminal == YOUTUBE_UPLOAD_UNCERTAIN:
                    _set_task_uncertain(str(task_id), message)
            if terminal == "upload_confirmed":
                return IntegrationResult(True, message, result_data)
            result_data["reason"] = YOUTUBE_UPLOAD_UNCERTAIN
            return IntegrationResult(False, message, result_data)
    except Exception as exc:
        return IntegrationResult(False, f"Não foi possível adquirir o lock de upload: {_sanitise_sau_output(exc)}", {"route": "social-auto-upload-cli", "status": "error", "reason": "upload_lock_error", "checkpoint_id": checkpoint_id})
