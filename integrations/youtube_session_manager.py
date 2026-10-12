"""Safe, opt-in renewal of YouTube cookies and sessionInfo per account.

The module is deliberately one-shot: it never starts Streamlit, workers, or a
resident polling loop. Browser automation is best-effort and refuses Google
verification/CAPTCHA pages instead of attempting to bypass them.
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from integrations.session_info_health import check_account_session_info_health
from integrations.youtube_direct_credentials import (
    COOKIE_KEYS,
    account_directory,
    account_key,
    credentials_document_path,
    load_credentials_document,
)

logger = logging.getLogger(__name__)
LOCK_TIMEOUT_SECONDS = 300
LOCK_WAIT_SECONDS = 10
MAX_CAPTURE_ATTEMPTS = 2
TITLE_SELECTORS = [
    'input[aria-label="Título"]',
    'input[aria-label="Title"]',
    'input[name="title"]',
    'input[placeholder*="Título"]',
    'input[placeholder*="Title"]',
    'ytcp-text-input#title-text-input',
]
DESCRIPTION_SELECTORS = [
    'textarea[aria-label="Descrição"]',
    'textarea[aria-label="Description"]',
    'textarea[name="description"]',
    'textarea[placeholder*="Descrição"]',
    'textarea[placeholder*="Description"]',
    'ytcp-mention-drawer textarea',
]
BLOCKED_TEXT = ("verify", "verificação", "verification", "captcha", "confirme que você é humano", "confirm it's you", "confirme que é você")


class _BrowserUnavailableError(RuntimeError):
    """Raised when Playwright cannot find or prepare a usable browser."""


def _looks_like_missing_playwright_browser(error: BaseException) -> bool:
    message = str(error).lower()
    return "executable doesn't exist" in message or "executable does not exist" in message or "playwright was just installed" in message


def _install_playwright_chromium() -> bool:
    """Install the bundled Chromium once when Playwright reports it missing."""
    try:
        result = subprocess.run(
            [os.fspath(sys.executable), "-m", "playwright", "install", "chromium"],
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Não foi possível preparar o Chromium do Playwright: %s", _safe_error(exc))
        return False
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        logger.warning("A instalação automática do Chromium falhou: %s", detail[-1] if detail else "erro desconhecido")
        return False
    return True


def _launch_playwright_browser(playwright: Any) -> Any:
    """Launch the configured browser, recovering from a missing Playwright binary."""
    configured_path = str(os.environ.get("THUNDERBOLT_CHROME_PATH") or "").strip()
    launch_kwargs: dict[str, Any] = {"headless": True}
    if configured_path:
        if not Path(configured_path).is_file():
            raise _BrowserUnavailableError(f"Executável Chrome/Chromium não encontrado: {configured_path}")
        launch_kwargs["executable_path"] = configured_path

    try:
        return playwright.chromium.launch(**launch_kwargs)
    except Exception as initial_error:
        if configured_path or not _looks_like_missing_playwright_browser(initial_error):
            raise

        # Prefer an already installed Google Chrome before downloading another
        # browser. This is particularly useful on Windows machines where the
        # Playwright cache was removed but Chrome itself is still available.
        try:
            return playwright.chromium.launch(headless=True, channel="chrome")
        except Exception as chrome_error:
            if not _looks_like_missing_playwright_browser(initial_error):
                raise initial_error
            if not _install_playwright_chromium():
                raise _BrowserUnavailableError(
                    "O Chromium do Playwright não está instalado e não foi possível prepará-lo automaticamente."
                ) from chrome_error
            try:
                return playwright.chromium.launch(headless=True)
            except Exception as retry_error:
                raise _BrowserUnavailableError(
                    "O Chromium do Playwright continua indisponível depois da instalação automática."
                ) from retry_error

try:
    from yt_cm import YouTubeCookieManager  # type: ignore
    YT_CM_AVAILABLE = True
except ImportError:  # optional by design
    YouTubeCookieManager = None  # type: ignore
    YT_CM_AVAILABLE = False


def is_yt_cm_available() -> bool:
    """Return whether optional yt-cm can be imported."""
    return bool(YT_CM_AVAILABLE)


def validate_session_info(token: str | None) -> bool:
    """Validate the conservative Base64-like shape required by the plan."""
    value = str(token or "").strip()
    return bool(value and len(value) >= 50 and re.fullmatch(r"[A-Za-z0-9+/=]+", value))


def _safe_error(exc: BaseException) -> str:
    text = str(exc)
    for secret in ("sessionInfo", "SID", "SSID", "HSID", "APISID", "SAPISID"):
        text = text.replace(secret, "[redacted]")
    return text[:500]


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    except PermissionError:
        return True
    return True


@contextmanager
def account_lock(account_dir: Path, account_id: str, *, wait_seconds: int = 0) -> Iterator[None]:
    """Acquire an atomic per-account lock, removing only dead/expired locks."""
    account_dir.mkdir(parents=True, exist_ok=True)
    path = account_dir / f"{account_key({'id': account_id})}.lock"
    deadline = time.monotonic() + max(0, wait_seconds)
    acquired = False
    while not acquired:
        payload = {"pid": os.getpid(), "acquired_at": datetime.now(timezone.utc).isoformat(), "timeout_seconds": LOCK_TIMEOUT_SECONDS}
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            acquired = True
        except FileExistsError:
            stale = False
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
                pid = int(current.get("pid", 0))
                acquired_at = datetime.fromisoformat(str(current.get("acquired_at", "")).replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - (acquired_at if acquired_at.tzinfo else acquired_at.replace(tzinfo=timezone.utc))).total_seconds()
                stale = age > LOCK_TIMEOUT_SECONDS or not _pid_alive(pid)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                stale = True
            if stale:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError("lock de renovação já está activo")
            time.sleep(0.25)
    try:
        yield
    finally:
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
            if int(current.get("pid", -1)) == os.getpid():
                path.unlink(missing_ok=True)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass


def _rotate_backups(destination: Path) -> None:
    bak, bak1, bak2 = (destination.with_name(destination.name + suffix) for suffix in (".bak", ".bak1", ".bak2"))
    if bak1.exists():
        os.replace(bak1, bak2)
    if bak.exists():
        os.replace(bak, bak1)
    if destination.exists():
        shutil.copy2(destination, bak)


def _write_renewal_state(directory: Path, status: str) -> None:
    """Persist only non-secret renewal state for the UI/health check."""
    path = directory / "renewal_state.json"
    path.write_text(json.dumps({"status": status, "updated_at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")


def atomic_save_credentials(destination: Path, document: dict[str, Any]) -> None:
    """Rotate three backups, atomically replace, and restore on failure."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    _rotate_backups(destination)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        latest = destination.with_name(destination.name + ".bak")
        if latest.exists():
            os.replace(latest, destination)
        raise


def _blocked_page(page: Any) -> bool:
    try:
        body = str(page.locator("body").inner_text(timeout=2000)).lower()
        if any(marker in body for marker in BLOCKED_TEXT):
            return True
        if page.locator('input[type="email"], input[type="password"], iframe[src*="captcha"], iframe[title*="captcha" i]').count() > 0:
            return True
    except Exception:
        return False
    return False


def _first_selector(page: Any, selectors: list[str]) -> str | None:
    for selector in selectors:
        try:
            page.wait_for_selector(selector, timeout=3000)
            logger.debug("Selector YouTube utilizado: %s", selector)
            return selector
        except Exception:
            continue
    return None


def _capture_with_playwright(document: dict[str, Any], *, logs_dir: Path, video_id: str = "") -> tuple[str, str | None]:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        logger.warning("Playwright não instalado; captura sessionInfo indisponível.")
        return "browser_unavailable", None
    captured: list[str] = []
    logs_dir.mkdir(parents=True, exist_ok=True)
    cookies = [{"name": key, "value": str(document["cookies"][key]), "domain": ".youtube.com", "path": "/"} for key in COOKIE_KEYS if document.get("cookies", {}).get(key)]
    with sync_playwright() as playwright:
        try:
            browser = _launch_playwright_browser(playwright)
        except _BrowserUnavailableError as exc:
            logger.error("Browser Playwright indisponível: %s", _safe_error(exc))
            return "browser_unavailable", None
        context = browser.new_context()
        context.add_cookies(cookies)
        page = context.new_page()

        def on_response(response: Any) -> None:
            try:
                text = response.text()
                for match in re.findall(r"[A-Za-z0-9+/=]{50,}", text):
                    if validate_session_info(match):
                        captured.append(match)
                        break
            except Exception:
                pass

        page.on("response", on_response)
        try:
            url = "https://studio.youtube.com/"
            if video_id:
                url += f"video/{video_id}/edit"
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            if _blocked_page(page):
                logger.warning("🔒 Sessão bloqueada pelo Google. Renovação manual necessária.")
                return "blocked_by_google", None
            selector = _first_selector(page, TITLE_SELECTORS)
            if selector is None:
                selector = _first_selector(page, DESCRIPTION_SELECTORS)
            if selector is None:
                screenshot = logs_dir / f"failure_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.png"
                page.screenshot(path=str(screenshot), full_page=True)
                logger.error("Nenhum selector de título ou descrição do YouTube foi encontrado; screenshot: %s", screenshot)
                return "selector_failure", None
            try:
                page.locator(selector).focus()
                page.keyboard.press("Escape")
            except Exception:
                pass
            page.wait_for_timeout(1500)
            for token in captured:
                if validate_session_info(token):
                    return "captured", token
            return "invalid_format", None
        finally:
            context.close()
            browser.close()


def _try_renew_cookies(document: dict[str, Any], account: dict[str, Any]) -> dict[str, Any]:
    if not is_yt_cm_available():
        logger.warning("⚠️ yt-cm não encontrado. A renovação de cookies será pulada. Instale com: pip install yt-cm")
        return document
    manager = YouTubeCookieManager()  # type: ignore[operator]
    for method_name in ("renew", "refresh", "validate"):
        method = getattr(manager, method_name, None)
        if callable(method):
            result = method(document.get("cookies", {}), account=account)
            if isinstance(result, dict):
                document["cookies"] = {key: str(result.get(key, document["cookies"].get(key, ""))) for key in COOKIE_KEYS}
            break
    return document


@dataclass(frozen=True)
class RenewalResult:
    ok: bool
    status: str
    message: str
    account_id: str
    attempts: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "status": self.status, "message": self.message, "account_id": self.account_id, "attempts": self.attempts}


def renew_account_session(storage_root: Path, account: dict[str, Any], settings: dict[str, Any] | None = None, *, force: bool = False, wait_seconds: int = 0, logs_dir: Path | None = None) -> RenewalResult:
    settings = settings or {}
    account_id = str(account.get("id") or "").strip()
    if not account_id:
        return RenewalResult(False, "invalid_account", "Conta Google sem ID.", "")
    health = check_account_session_info_health(storage_root, account, settings)
    if not force and health.status not in {"expiring", "expired", "missing", "invalid_format"}:
        return RenewalResult(True, health.status, "Renovação não necessária.", account_id)
    directory = account_directory(storage_root, account)
    destination = credentials_document_path(storage_root, account)
    logs_dir = logs_dir or directory / "logs"
    try:
        with account_lock(directory, account_id, wait_seconds=wait_seconds):
            document = load_credentials_document(storage_root, account, settings, create=False)
            document = dict(document)
            try:
                document = _try_renew_cookies(document, account)
            except Exception as exc:
                return RenewalResult(False, "cookie_renewal_failed", f"Falha na renovação de cookies: {_safe_error(exc)}", account_id)
            for attempt in range(1, MAX_CAPTURE_ATTEMPTS + 1):
                capture_status, token = _capture_with_playwright(document, logs_dir=logs_dir, video_id=str(account.get("video_id") or ""))
                if capture_status == "browser_unavailable":
                    return RenewalResult(
                        False,
                        "browser_unavailable",
                        "Renovação falhou: o Chromium do Playwright não está disponível. Execute novamente a instalação do Thunderbolt e tente renovar outra vez.",
                        account_id,
                        attempt,
                    )
                if capture_status == "blocked_by_google":
                    _write_renewal_state(directory, "blocked_by_google")
                    return RenewalResult(False, "blocked_by_google", "🔒 Sessão bloqueada pelo Google. Renovação manual necessária.", account_id, attempt)
                if validate_session_info(token):
                    document["sessionInfo"] = token
                    now = datetime.now(timezone.utc).isoformat()
                    document["sessionInfoCapturedAt"] = now
                    document["expires_at"] = (datetime.now(timezone.utc) + timedelta(hours=19)).isoformat()
                    document["sessionInfoHealthStatus"] = ""
                    atomic_save_credentials(destination, document)
                    _write_renewal_state(directory, "healthy")
                    return RenewalResult(True, "healthy", "sessionInfo renovado com sucesso.", account_id, attempt)
                logger.warning("sessionInfo capturado, mas formato inválido. Descartando.")
            _write_renewal_state(directory, "invalid_format")
            return RenewalResult(False, "invalid_format", "Não foi possível capturar um sessionInfo válido.", account_id, MAX_CAPTURE_ATTEMPTS)
    except TimeoutError as exc:
        return RenewalResult(False, "lock_timeout", str(exc), account_id)
    except Exception as exc:
        return RenewalResult(False, "renewal_failed", f"Renovação falhou: {_safe_error(exc)}", account_id)


def _accounts_from_settings(settings: dict[str, Any]) -> list[dict[str, Any]]:
    accounts = settings.get("youtube_batch_accounts", [])
    return [item for item in accounts if isinstance(item, dict) and str(item.get("id") or "").strip()] if isinstance(accounts, list) else []


def run_all_accounts(storage_root: Path, settings: dict[str, Any]) -> int:
    renewed = failed = ignored = 0
    for account in _accounts_from_settings(settings):
        enabled = bool(account.get("auto_renew_enabled", settings.get("auto_renew_enabled", False)))
        if not enabled:
            ignored += 1
            continue
        health = check_account_session_info_health(storage_root, account, settings)
        if health.status not in {"expiring", "expired"}:
            ignored += 1
            continue
        result = renew_account_session(storage_root, account, settings)
        if result.ok:
            renewed += 1
        else:
            failed += 1
    logger.info("Renovadas: %s, Falhas: %s, Ignoradas: %s", renewed, failed, ignored)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Renovação única de sessões YouTube")
    parser.add_argument("--all-accounts", action="store_true")
    parser.add_argument("--account-id")
    parser.add_argument("--storage-root", default=os.environ.get("THUNDERBOLT_STORAGE_DIR", "storage"))
    args = parser.parse_args(argv)
    root = Path(args.storage_root)
    settings_path = root / "state" / "settings.json"
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
    except (OSError, json.JSONDecodeError):
        settings = {}
    if args.all_accounts:
        return run_all_accounts(root, settings)
    accounts = [a for a in _accounts_from_settings(settings) if str(a.get("id")) == str(args.account_id)]
    if not accounts:
        return 1
    result = renew_account_session(root, accounts[0], settings, force=True)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

__all__ = ["RenewalResult", "TITLE_SELECTORS", "account_lock", "atomic_save_credentials", "is_yt_cm_available", "renew_account_session", "run_all_accounts", "validate_session_info"]
