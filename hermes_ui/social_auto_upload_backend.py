from __future__ import annotations

import asyncio
import importlib.util
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
import types
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from filelock import FileLock

from hermes_ui import storage as storage_module
from hermes_ui.browser_manager import BrowserLaunchError, has_gui_environment, launch_browser, launch_browser_async
from hermes_ui.proxy_manager import get_active_proxy, get_proxy_for_browser
from integrations.platforms import IntegrationResult

logger = logging.getLogger(__name__)
YOUTUBE_LOGIN_URL = "https://studio.youtube.com"

# 1.0.29 — multi-plataforma: alvo de login visível + cookies essenciais por
# plataforma. Os ESSENCIAIS são a única prova real de autenticação — a
# verificação por URL («studio.youtube.com in page.url») disparava logo após
# o goto (falso positivo: o browser abria e fechava com cookies de visitante
# e a UI anunciava «Login validado»). Plataformas fora do mapa validam com
# qualquer cookie não vazio do domínio (comportamento anterior).
PLATFORM_LOGIN_TARGETS: dict[str, dict[str, Any]] = {
    "youtube": {"url": YOUTUBE_LOGIN_URL, "domain": "youtube.com", "essential": ("SID", "HSID", "SSID")},
    "tiktok": {"url": "https://www.tiktok.com/login", "domain": "tiktok.com", "essential": ("sessionid",)},
    "douyin": {"url": "https://www.douyin.com/login", "domain": "douyin.com", "essential": ("sessionid",)},
    "bilibili": {"url": "https://passport.bilibili.com/login", "domain": "bilibili.com", "essential": ("SESSDATA",)},
    "kuaishou": {"url": "https://www.kuaishou.com", "domain": "kuaishou.com", "essential": ("passToken",)},
    "xiaohongshu": {"url": "https://www.xiaohongshu.com", "domain": "xiaohongshu.com", "essential": ("web_session",)},
    "instagram": {"url": "https://www.instagram.com/accounts/login", "domain": "instagram.com", "essential": ("sessionid",)},
    "weibo": {"url": "https://passport.weibo.com/signin/login", "domain": "weibo.com", "essential": ("SUB",)},
    "tencent": {"url": "https://channels.weixin.qq.com", "domain": "qq.com", "essential": ()},
    "baijiahao": {"url": "https://baijiahao.baidu.com", "domain": "baidu.com", "essential": ()},
    "alipay": {"url": "https://member.alipay.com", "domain": "alipay.com", "essential": ()},
    "hupu": {"url": "https://www.hupu.com", "domain": "hupu.com", "essential": ()},
}


def platform_login_target(platform: str) -> dict[str, Any]:
    """Alvo de login visível da plataforma (URL, domínio, cookies essenciais)."""
    return dict(PLATFORM_LOGIN_TARGETS.get(str(platform or "").strip().casefold(), {"url": "", "domain": "", "essential": ()}))


def missing_essential_cookies(state: Any, domain: str, essential: tuple[str, ...] = ()) -> list[str]:
    """Devolve os cookies essenciais em falta (lista vazia = sessão autêntica)."""
    names = {str(cookie.get("name") or "").strip() for cookie in session_cookies_for_domain(state, domain)}
    return [name for name in essential if name not in names]
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


def validate_storage_state(path: str | Path, domain: str = "youtube.com", *, essential_cookies: tuple[str, ...] | None = None) -> tuple[bool, str]:
    """Valida o storage_state — 1.0.29: exige os COOKIES ESSENCIAIS de sessão.

    Falso positivo corrigido: qualquer cookie de visitante (VISITOR_INFO1_LIVE
    etc.) passava na validação antiga e a UI anunciava «Login validado» de um
    browser que abriu e fechou sem login. Para o Google/YouTube os essenciais
    são SID, HSID e SSID — só existem depois de uma autenticação real.
    """
    payload = _read_json_file(Path(path))
    if payload is None:
        return False, "O ficheiro storage_state.json não existe ou não contém JSON válido."
    suffix = str(domain or "").strip().casefold().lstrip(".")
    # O login do YouTube/Google deixa os cookies essenciais em .google.com OU
    # em .youtube.com — o storage_state pode guardar apenas um dos lados.
    if not session_cookies_for_domain(payload, suffix) and suffix == "youtube.com" and session_cookies_for_domain(payload, "google.com"):
        suffix = "google.com"
    if not session_cookies_for_domain(payload, suffix):
        return False, f"O storage_state.json não contém cookies de sessão não vazios para {domain}."
    essential = tuple(essential_cookies or ())
    if not essential and suffix in ESSENTIAL_SESSION_COOKIES:
        essential = ESSENTIAL_SESSION_COOKIES[suffix]
    missing = missing_essential_cookies(payload, suffix, essential)
    if missing:
        return False, (
            "O login falhou ou foi cancelado. Tente novamente. "
            f"O storage_state não contém os cookies essenciais de sessão ({', '.join(essential)}) para {domain}."
        )
    return True, "Sessão válida."


ESSENTIAL_SESSION_COOKIES: dict[str, tuple[str, ...]] = {
    "youtube.com": ("SID", "HSID", "SSID"),
    "google.com": ("SID", "HSID", "SSID"),
    "bilibili.com": ("SESSDATA",),
    "douyin.com": ("sessionid",),
    "kuaishou.com": ("passToken",),
    "xiaohongshu.com": ("web_session",),
    "weibo.com": ("SUB",),
}


def has_valid_youtube_session() -> bool:
    return validate_storage_state(session_state_path(), "youtube.com")[0]


def _cookie_names_in_context(context: Any) -> set[str]:
    """Nomes dos cookies vivos do browser (poll de autenticação real)."""
    try:
        cookies = context.cookies()
    except Exception:
        return set()
    return {str(cookie.get("name") or "").strip() for cookie in cookies if isinstance(cookie, dict)}


def _wait_for_essential_cookies(
    *, page: Any, context: Any, essential: tuple[str, ...], domain: str, deadline: float,
) -> tuple[bool, str]:
    """Espera BLOQUEANTE pelos cookies essenciais de sessão (1.0.29).

    A detecção antiga por URL («studio.youtube.com in page.url») disparava
    logo após o goto — o alvo É studio — e um browser sem login passava por
    autenticado com cookies de visitante. Agora só sai do loop quando os
    cookies ESSENCIAIS existirem no contexto vivo; fecho da janela = falha
    «O login falhou ou foi cancelado. Tente novamente.», nunca falso
    positivo.
    """
    if not essential:
        while time.monotonic() < deadline:
            try:
                if page.is_closed():
                    return False, "O browser foi fechado antes de concluir o login; nenhuma sessão parcial foi guardada."
            except Exception:
                return False, "O browser foi fechado antes de concluir o login; nenhuma sessão parcial foi guardada."
            if session_cookies_for_domain({"cookies": _context_cookie_dicts(context)}, domain):
                return True, ""
            time.sleep(0.8)
        return False, "O login não foi concluído em 5 minutos; nenhuma sessão parcial foi guardada."
    while time.monotonic() < deadline:
        names = _cookie_names_in_context(context)
        if all(name in names for name in essential):
            return True, ""
        try:
            if page.is_closed():
                return False, "O browser foi fechado antes de concluir o login; nenhuma sessão parcial foi guardada."
        except Exception:
            if not names:
                return False, "O browser foi fechado antes de concluir o login; nenhuma sessão parcial foi guardada."
        time.sleep(0.8)
    return False, "O login não foi concluído em 5 minutos; nenhuma sessão parcial foi guardada."


def _context_cookie_dicts(context: Any) -> list[dict[str, Any]]:
    try:
        return [cookie for cookie in context.cookies() if isinstance(cookie, dict)]
    except Exception:
        return []


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
        # 1.0.29: autenticação provada por COOKIES ESSENCIAIS (SID/HSID/SSID)
        # no contexto vivo — nunca por URL (o alvo É studio.youtube.com, a
        # checagem antiga dava falso positivo imediato pós-goto).
        authenticated, auth_message = _wait_for_essential_cookies(
            page=page, context=context, essential=("SID", "HSID", "SSID"), domain="youtube.com", deadline=deadline,
        )
        if not authenticated:
            return {"success": False, "status": "timeout", "message": auth_message}
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


def _installed_upstream_root() -> Path | None:
    """Localiza a raiz do pacote upstream instalado SEM o importar.

    O import de `uploader` executa `uploader/__init__.py`, que faz
    `from conf import BASE_DIR` — ou seja, importar para descobrir onde está
    instalado seria circular. `find_spec` localiza o pacote sem o executar.
    `spec.origin` = `<raiz>/uploader/__init__.py`; o pacote `utils/` (com o
    stealth.min.js) é IRMÃO de `uploader/`, logo a raiz é `parent.parent`.
    """
    try:
        spec = importlib.util.find_spec("uploader")
    except (ImportError, AttributeError, ValueError):
        return None
    if spec is None or not spec.origin:
        return None
    return Path(spec.origin).resolve().parent.parent


def _ensure_upstream_stealth_asset(base: Path) -> None:
    """Garante `utils/stealth.min.js` no base dir da CLI (Rota B).

    Todos os uploaders de browser do upstream injectam
    `BASE_DIR/utils/stealth.min.js` via `set_init_script`; o sdist pinned
    instala o ficheiro apenas na raiz do pacote (site-packages), nunca no
    base dir configurável. Sem esta cópia, `sau <plataforma> check|login|
    upload-video` falham no `add_init_script` com o ficheiro em falta —
    excepção engolida pelo upstream e reportada como "sessão inválida".
    Nunca sobrescreve um ficheiro existente (um base dir apontado a um clone
    real do social-auto-upload mantém a sua própria versão).
    """
    target = base / "utils" / "stealth.min.js"
    if target.is_file() and target.stat().st_size > 0:
        return
    root = _installed_upstream_root()
    if root is None:
        return
    source = root / "utils" / "stealth.min.js"
    if not source.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _ensure_upstream_runtime_conf() -> Path:
    """1.0.06: provisiona o módulo `conf` do upstream in-process (Rota A).

    Regressão crítica: o import in-process de
    `uploader.youtube_uploader.main` (a ponte `_PlaywrightBridge`) exige um
    módulo `conf` top-level (`from conf import DEBUG_MODE` em cada uploader),
    mas o sdist pinned NÃO instala `conf.py` — o módulo só existia no
    subprocesso da CLI (runtime/conf.py via PYTHONPATH). Resultado: todo o
    upload directo YouTube falhava com `ModuleNotFoundError: No module named
    'conf'`, traduzido na mensagem enganosa "A dependência pinned do
    social-auto-upload não está instalada corretamente." → `upload_failed_clean`.

    O provisionamento injecta em `sys.modules` um módulo `conf` com o MESMO
    `BASE_DIR` da CLI (Rota B — `_sau_base_directory()`), garantindo `cookies/`
    e `utils/stealth.min.js` (o upstream lê `BASE_DIR/utils/stealth.min.js` no
    `set_init_script` e cria `BASE_DIR/logs` via loguru).
    """
    existing = sys.modules.get("conf")
    if existing is not None and getattr(existing, "BASE_DIR", None):
        return Path(existing.BASE_DIR)
    try:
        spec = importlib.util.find_spec("conf")
    except (ImportError, ValueError):
        spec = None
    if spec is not None:
        module = importlib.import_module("conf")
        base_dir = getattr(module, "BASE_DIR", None)
        if base_dir is not None:
            return Path(base_dir)
    if _installed_upstream_root() is None:
        raise RuntimeError("A dependência pinned do social-auto-upload não está instalada corretamente.")
    base = _sau_base_directory()
    base.mkdir(parents=True, exist_ok=True)
    (base / "cookies").mkdir(parents=True, exist_ok=True)
    _ensure_upstream_stealth_asset(base)
    conf_module = types.ModuleType("conf")
    conf_module.BASE_DIR = base.resolve()
    conf_module.XHS_SERVER = "http://127.0.0.1:11901"
    conf_module.LOCAL_CHROME_PATH = ""
    conf_module.LOCAL_CHROME_HEADLESS = True
    conf_module.DEBUG_MODE = False
    conf_module.YT_PROXY = None
    sys.modules["conf"] = conf_module
    return Path(conf_module.BASE_DIR)


async def _run_upstream_upload(
    *, state_file: Path, video_path: str, title: str, description: str, tags: list[str],
    thumbnail_path: str, visibility: str, browser_type: str, proxy: Any, geoip: bool,
) -> _UploadTrace:
    try:
        # 1.0.06: o provisionamento tem de acontecer ANTES do import — o
        # pacote pinned não instala `conf.py` e o import falhava sem ele.
        _ensure_upstream_runtime_conf()
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


def _write_sau_runtime_config(proxy_url: str | None = None) -> Path:
    runtime = _sau_runtime_directory()
    runtime.mkdir(parents=True, exist_ok=True)
    base = _sau_base_directory()
    base.mkdir(parents=True, exist_ok=True)
    # 1.0.29: proxy binding no upload — o conf da CLI recebe o proxy
    # ASSOCIADO à conta (login e upload da mesma conta saem pelo mesmo IP).
    proxy_literal = "None"
    clean_proxy = str(proxy_url or "").strip()
    if clean_proxy:
        proxy_literal = repr(clean_proxy)
    source = (
        "from pathlib import Path\n"
        f"BASE_DIR = Path({str(base)!r}).resolve()\n"
        "XHS_SERVER = 'http://127.0.0.1:11901'\n"
        "LOCAL_CHROME_PATH = ''\n"
        "LOCAL_CHROME_HEADLESS = True\n"
        "DEBUG_MODE = False\n"
        f"YT_PROXY = {proxy_literal}\n"
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
    # 1.0.06: a CLI upstream lê BASE_DIR/utils/stealth.min.js no
    # set_init_script de todos os uploaders de browser — sem esta cópia o
    # check/login/upload falhavam com "ficheiro em falta" mascarado de
    # "sessão inválida".
    _ensure_upstream_stealth_asset(base)
    return runtime


def _sau_environment(proxy_id: str | None = None) -> tuple[dict[str, str], Path]:
    """Ambiente da CLI — com o proxy da CONTA quando associado (1.0.29)."""
    proxy_url: str | None = None
    if proxy_id:
        normalized = get_proxy_for_browser(proxy_id)
        if normalized:
            creds = ""
            if normalized.get("username"):
                creds = f"{quote(str(normalized.get('username')), safe='')}:{quote(str(normalized.get('password') or ''), safe='')}@"
            host = str(normalized.get("server") or "").rstrip("/")
            proxy_url = f"{normalized.get('scheme') or 'http'}://{creds}{host}"
    runtime = _write_sau_runtime_config(proxy_url=proxy_url)
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
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
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
    normalised = _normalise_social_platform(platform)
    account = _validate_sau_account_name(account_name)
    return _sau_base_directory() / "cookies" / f"{normalised}_{account}.json"


def _normalise_social_platform(platform: str) -> str:
    """Plataforma válida para o registo de contas (login visível multi-plataforma).

    Aceita as plataformas da CLI upstream E as de login local (tiktok,
    instagram) — o cookie fica guardado no formato da CLI; o upload destas
    últimas usa as integrações existentes do Thunderbolt.
    """
    value = str(platform or "").strip().casefold().replace("-", "_")
    if value in PLATFORM_LOGIN_TARGETS:
        return value
    return _normalise_sau_platform(value)


def list_sau_accounts(platform: str | None = None) -> list[dict[str, str]]:
    settings = storage_module.read_json("settings.json", {})
    raw = settings.get("sau_accounts", []) if isinstance(settings, dict) else []
    if not isinstance(raw, list):
        return []
    selected_platform = _normalise_social_platform(platform) if platform else None
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            item_platform = _normalise_social_platform(str(item.get("platform") or ""))
            account_name = _validate_sau_account_name(str(item.get("account_name") or ""))
        except ValueError:
            continue
        if selected_platform and item_platform != selected_platform:
            continue
        result.append({
            "platform": item_platform,
            "account_name": account_name,
            "label": str(item.get("label") or account_name),
            "proxy_id": str(item.get("proxy_id") or ""),
        })
    return sorted(result, key=lambda item: (item["platform"], item["label"].casefold(), item["account_name"].casefold()))


def get_sau_account(platform: str, account_name: str) -> dict[str, str] | None:
    """Uma conta do registo (com o proxy associado), se existir."""
    wanted_platform = _normalise_social_platform(platform)
    wanted_account = _validate_sau_account_name(account_name)
    for item in list_sau_accounts():
        if item["platform"] == wanted_platform and item["account_name"].casefold() == wanted_account.casefold():
            return item
    return None


def add_sau_account(platform: str, account_name: str, label: str = "", proxy_id: str = "") -> dict[str, str]:
    normalised = _normalise_social_platform(platform)
    account = _validate_sau_account_name(account_name)
    item = {
        "platform": normalised,
        "account_name": account,
        "label": str(label or account).strip()[:100] or account,
        "proxy_id": str(proxy_id or "").strip(),
    }

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


def set_sau_account_proxy(platform: str, account_name: str, proxy_id: str) -> dict[str, str] | None:
    """Associa (ou limpa) o proxy da conta — login e upload usam o MESMO proxy.

    Consistência de IP: «Sem proxy» significa ligação DIRECTA explícita —
    nunca cai no proxy activo global.
    """
    normalised = _normalise_social_platform(platform)
    account = _validate_sau_account_name(account_name)
    clean_proxy = str(proxy_id or "").strip()

    def mutate(settings: Any) -> None:
        if not isinstance(settings, dict) or not isinstance(settings.get("sau_accounts"), list):
            return
        for item in settings["sau_accounts"]:
            if isinstance(item, dict) and str(item.get("platform") or "").casefold() == normalised and str(item.get("account_name") or "").casefold() == account.casefold():
                item["proxy_id"] = clean_proxy

    storage_module.update_json("settings.json", {}, mutate)
    return get_sau_account(normalised, account)


def sau_account_proxy_id(platform: str, account_name: str) -> str:
    """proxy_id associado à conta (vazio = ligação directa explícita)."""
    account = get_sau_account(platform, account_name)
    return str((account or {}).get("proxy_id") or "")


def remove_sau_account(platform: str, account_name: str) -> bool:
    normalised = _normalise_social_platform(platform)
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
            process = subprocess.Popen(args, cwd=str(runtime), env=env, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
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
    # 1.0.29: proxy binding — o login CLI da conta sai pelo MESMO proxy
    # associado à conta (consistência de IP com o upload).
    env, runtime = _sau_environment(sau_account_proxy_id(normalised, account))
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


def login_social_account(
    platform: str, account_name: str, *, browser_type: str = "camoufox", timeout_seconds: int = 300,
) -> dict[str, Any]:
    """Login visível POR CONTA no browser do Thunderbolt (1.0.29).

    Multi-plataforma + proxy binding: abre o Camoufox/Chromium com o proxy
    ASSOCIADO À CONTA (consistência de IP: o login e o upload da mesma conta
    usam sempre o mesmo proxy; «Sem proxy» = ligação directa explícita),
    espera BLOQUEANTE pelos cookies essenciais da plataforma e grava o
    storage_state NO CAMINHO/FORMATO QUE A CLI social-auto-upload espera
    (cookies/<plataforma>_<conta>.json). O falso positivo morre aqui: sem
    cookies essenciais, «O login falhou ou foi cancelado. Tente novamente.»
    """
    normalised = _normalise_social_platform(platform)
    account = _validate_sau_account_name(account_name)
    target = platform_login_target(normalised)
    if not target.get("url"):
        return {"success": False, "status": "unsupported", "message": f"Não há fluxo de login visível para a plataforma {normalised}."}
    if not has_gui_environment():
        return {
            "success": False, "status": "no_gui",
            "message": "O login visível requer GUI. Inicie o login num ambiente com GUI ou copie o cookie validado para o caminho indicado.",
            "cookie_path": str(get_sau_cookie_path(normalised, account)),
        }
    proxy_id = sau_account_proxy_id(normalised, account)
    proxy = get_proxy_for_browser(proxy_id) if proxy_id else None
    cookie_path = get_sau_cookie_path(normalised, account)
    cookie_path.parent.mkdir(parents=True, exist_ok=True)
    temp_state = cookie_path.with_name(f".{cookie_path.name}.{uuid.uuid4().hex}.tmp.json")
    browser = context = page = None
    try:
        browser = launch_browser(browser_type, headless=False, proxy=proxy, geoip=browser_type == "camoufox")
        context = browser.new_context()
        page = context.new_page()
        page.goto(str(target["url"]), wait_until="domcontentloaded", timeout=min(300, max(1, int(timeout_seconds))) * 1000)
        domain = str(target.get("domain") or "")
        essential = tuple(target.get("essential") or ())
        authenticated, auth_message = _wait_for_essential_cookies(
            page=page, context=context, essential=essential, domain=domain,
            deadline=time.monotonic() + min(300, max(1, int(timeout_seconds))),
        )
        if not authenticated:
            return {"success": False, "status": "timeout", "message": auth_message, "cookie_path": str(cookie_path)}
        context.storage_state(path=str(temp_state))
        if essential:
            valid, message = validate_storage_state(temp_state, domain, essential_cookies=essential)
        else:
            valid, message = validate_storage_state(temp_state, domain)
        if not valid:
            try:
                temp_state.unlink()
            except OSError:
                pass
            return {"success": False, "status": "invalid_session", "message": message, "cookie_path": str(cookie_path)}
        os.replace(temp_state, cookie_path)
        logging.getLogger("thunderbolt.browser").info(
            "[SAU-LOGIN-VISIVEL] conta %s_%s autenticada via browser %s com %s (cookie: %s)",
            normalised, account, browser_type, f"proxy {proxy_id}" if proxy_id else "ligação directa", cookie_path,
        )
        return {
            "success": True, "status": "logged_in",
            "message": f"Login de {account} validado (cookies essenciais presentes) e cookie guardado no formato da CLI.",
            "cookie_path": str(cookie_path), "proxy_id": proxy_id, "platform": normalised,
        }
    except Exception as exc:
        safe_message = str(exc)
        for secret in (str((proxy or {}).get("username") or ""), str((proxy or {}).get("password") or "")):
            if secret:
                safe_message = safe_message.replace(secret, "***")
        return {"success": False, "status": "error", "message": safe_message[:500], "cookie_path": str(cookie_path)}
    finally:
        for closer in (page, context, browser):
            try:
                if closer is not None:
                    closer.close()
            except Exception:
                pass


def sync_direct_youtube_session_to_cli(account_name: str) -> dict[str, Any]:
    """Herda a sessão directa YouTube (Rota A) para a conta CLI (Rota B).

    Evita login duplicado: a conta CLI `youtube_<conta>` passa a usar o
    `storage_state.json` validado pelo login visível da UI, sem exigir
    `sau youtube login`. Só copia quando a sessão directa é válida E mais
    recente que o cookie CLI existente — um login CLI próprio (mais fresco)
    nunca é sobrescrito, e um cookie CLI em falta herda a sessão directa.
    """
    account = _validate_sau_account_name(account_name)
    cli_cookie = get_sau_cookie_path("youtube", account)
    direct_state = session_state_path()
    valid, message = validate_storage_state(direct_state, "youtube.com")
    if not valid:
        return {"synced": False, "reason": "direct_session_unavailable", "message": message, "cookie_path": str(cli_cookie)}
    try:
        if cli_cookie.is_file() and cli_cookie.stat().st_size > 0 and cli_cookie.stat().st_mtime >= direct_state.stat().st_mtime:
            return {"synced": False, "reason": "cli_cookie_current", "message": "O cookie CLI já é tão recente quanto a sessão directa; nada foi sincronizado.", "cookie_path": str(cli_cookie)}
    except OSError:
        pass
    try:
        cli_cookie.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(direct_state, cli_cookie)
    except OSError as exc:
        return {"synced": False, "reason": "copy_failed", "message": f"Não foi possível herdar a sessão directa para a conta CLI: {type(exc).__name__}: {exc}", "cookie_path": str(cli_cookie)}
    logging.getLogger("thunderbolt.browser").info(
        "[SAU-SESSION-SYNC] conta CLI youtube_%s herdou a sessão directa YouTube (cookie: %s)", account, cli_cookie
    )
    return {"synced": True, "reason": "synced", "message": "Sessão directa YouTube herdada pela conta CLI; não é preciso login CLI.", "cookie_path": str(cli_cookie)}


def check_platform_session(platform: str, account_name: str, *, timeout_seconds: int = 45) -> dict[str, Any]:
    normalised = _normalise_sau_platform(platform)
    account = _validate_sau_account_name(account_name)
    if normalised == "youtube":
        # 1.0.06: a conta CLI youtube herda a sessão do login visível da UI
        # (Rota A) antes de qualquer verificação/upload — sem login duplicado.
        sync_direct_youtube_session_to_cli(account)
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
