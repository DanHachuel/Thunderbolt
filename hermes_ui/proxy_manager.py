from __future__ import annotations

import re
import uuid
from typing import Any
from urllib.parse import quote, unquote, urlsplit

import requests

from hermes_ui.storage import read_json, update_json

SUPPORTED_SCHEMES = {"http", "https", "socks5", "socks5h"}
IP_CHECK_URL = "https://api.ipify.org?format=json"
IP_CHECK_TIMEOUT_SECONDS = 10
AUTH_FAILURE_MESSAGE = "proxy requer credenciais válidas ou está inacessível"


def _settings() -> dict[str, Any]:
    value = read_json("settings.json", {})
    return value if isinstance(value, dict) else {}


def _cards(settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    values = (settings or _settings()).get("proxies_cards", [])
    return [dict(item) for item in values if isinstance(item, dict)] if isinstance(values, list) else []


def _parse_server(server: str, scheme: str = "http") -> tuple[str, str, int | None, str, str]:
    raw = str(server or "").strip()
    if not raw:
        raise ValueError("Informe o servidor do proxy.")
    candidate = raw if "://" in raw else f"{scheme}://{raw}"
    parsed = urlsplit(candidate)
    protocol = (parsed.scheme or scheme).casefold()
    if protocol not in SUPPORTED_SCHEMES:
        raise ValueError("Tipo de proxy não suportado. Use HTTP, HTTPS ou SOCKS5.")
    host = parsed.hostname or ""
    if not host:
        raise ValueError("O servidor do proxy não contém um host válido.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("A porta do proxy é inválida.") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("A porta do proxy deve estar entre 1 e 65535.")
    username = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    address = f"{host}:{port}" if port is not None else host
    return protocol, address, port, username, password


def normalize_proxy(proxy: Any) -> dict[str, str] | None:
    """Convert a saved proxy card or URL into Playwright/Camoufox's proxy schema."""
    if proxy is None or proxy == "":
        return None
    if isinstance(proxy, str):
        protocol, address, _, username, password = _parse_server(proxy)
    elif isinstance(proxy, dict):
        raw_server = str(proxy.get("server") or "").strip()
        raw_scheme = str(proxy.get("scheme") or proxy.get("type") or "http").strip().casefold()
        if raw_server:
            protocol, address, _, parsed_user, parsed_password = _parse_server(raw_server, raw_scheme)
        else:
            host = str(proxy.get("host") or "").strip()
            port_value = proxy.get("port")
            if not host:
                raise ValueError("O proxy não contém um host válido.")
            protocol = raw_scheme
            if protocol not in SUPPORTED_SCHEMES:
                raise ValueError("Tipo de proxy não suportado. Use HTTP, HTTPS ou SOCKS5.")
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            address = f"{host}:{int(port_value)}" if port_value not in (None, "") else host
            parsed_user = parsed_password = ""
        username = str(proxy.get("username") or parsed_user)
        password = str(proxy.get("password") or parsed_password)
    else:
        raise ValueError("Formato de proxy inválido.")
    result = {"server": f"{protocol}://{address}"}
    if username:
        result["username"] = username
    if password:
        result["password"] = password
    return result


def mask_secret(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 4:
        return "*" * len(text)
    return f"{text[:2]}{'*' * min(8, len(text) - 4)}{text[-2:]}"


def list_proxies() -> list[dict[str, Any]]:
    """Return proxy cards safe for rendering; passwords are never returned."""
    result = []
    for card in sorted(_cards(), key=lambda item: (int(item.get("priority") or 0), str(item.get("label") or "").casefold())):
        safe = {key: value for key, value in card.items() if key not in {"password", "username"}}
        safe["server"] = re.sub(r"(://)[^/@\s]+@", r"\1***@", str(card.get("server") or ""))
        safe["username_display"] = mask_secret(str(card.get("username") or ""))
        safe["has_credentials"] = bool(card.get("username") or card.get("password"))
        safe["active"] = str(card.get("id") or "") == str(_settings().get("proxy_active_id") or "")
        result.append(safe)
    return result


def _save_cards(cards: list[dict[str, Any]], active_id: str | None = None) -> None:
    def mutate(settings: Any) -> None:
        if not isinstance(settings, dict):
            return
        settings["proxies_cards"] = cards
        if active_id is not None:
            settings["proxy_active_id"] = active_id

    update_json("settings.json", {}, mutate)


def add_proxy(
    label: str,
    server: str,
    *,
    proxy_type: str = "http",
    username: str = "",
    password: str = "",
    priority: int | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    server_value = str(server or "").strip()
    if "://" in server_value:
        server_value = server_value.split("://", 1)[1]
    protocol, address, _, parsed_user, parsed_password = _parse_server(server_value, proxy_type)
    cards = _cards()
    card = {
        "id": f"proxy_{uuid.uuid4().hex[:12]}",
        "label": str(label or "Proxy").strip() or "Proxy",
        "scheme": protocol,
        "server": f"{protocol}://{address}",
        "username": str(username or parsed_user),
        "password": str(password or parsed_password),
        "priority": int(priority if priority is not None else len(cards)),
        "enabled": bool(enabled),
        "last_test": None,
    }
    cards.append(card)
    _save_cards(cards)
    return {key: value for key, value in card.items() if key not in {"username", "password"}}


def update_proxy(proxy_id: str, **changes: Any) -> dict[str, Any] | None:
    allowed = {"label", "server", "scheme", "proxy_type", "username", "password", "priority", "enabled"}
    clean = {key: value for key, value in changes.items() if key in allowed}
    cards = _cards()
    target = next((card for card in cards if str(card.get("id") or "") == str(proxy_id)), None)
    if target is None:
        return None
    if "server" in clean or "scheme" in clean or "proxy_type" in clean:
        new_server = str(clean.get("server") or target.get("server") or "")
        new_scheme = str(clean.get("scheme") or clean.get("proxy_type") or target.get("scheme") or "http")
        if "://" in new_server:
            new_server = new_server.split("://", 1)[1]
        protocol, address, _, parsed_user, parsed_password = _parse_server(new_server, new_scheme)
        target["scheme"] = protocol
        target["server"] = f"{protocol}://{address}"
        if parsed_user and "username" not in clean:
            target["username"] = parsed_user
        if parsed_password and "password" not in clean:
            target["password"] = parsed_password
    for key in ("label", "username", "password", "enabled"):
        if key in clean:
            target[key] = clean[key]
    if "priority" in clean:
        target["priority"] = int(clean["priority"])
    target.pop("last_test", None) if any(key in clean for key in ("server", "scheme", "proxy_type", "username", "password")) else None
    _save_cards(cards)
    return {key: value for key, value in target.items() if key not in {"username", "password"}}


def remove_proxy(proxy_id: str) -> bool:
    removed = False
    active_id = str(_settings().get("proxy_active_id") or "")
    cards = _cards()
    filtered = []
    for card in cards:
        if str(card.get("id") or "") == str(proxy_id):
            removed = True
        else:
            filtered.append(card)
    if removed:
        _save_cards(filtered, "" if active_id == str(proxy_id) else active_id)
    return removed


def get_active_proxy() -> dict[str, Any] | None:
    settings = _settings()
    active_id = str(settings.get("proxy_active_id") or "")
    return next((card for card in _cards(settings) if str(card.get("id") or "") == active_id and card.get("enabled", True)), None)


def set_active_proxy(proxy_id: str | None) -> bool:
    normalized = str(proxy_id or "").strip()
    cards = _cards()
    if normalized and not any(str(card.get("id") or "") == normalized and card.get("enabled", True) for card in cards):
        return False
    _save_cards(cards, normalized)
    return True


def get_proxy_for_browser(proxy_id: str | None = None) -> dict[str, str] | None:
    card = None
    if proxy_id:
        card = next((item for item in _cards() if str(item.get("id") or "") == str(proxy_id)), None)
    else:
        card = get_active_proxy()
    if not card or not card.get("enabled", True):
        return None
    return normalize_proxy(card)


def _requests_proxy_url(normalized: dict[str, str]) -> str:
    parts = urlsplit(normalized["server"])
    user = str(normalized.get("username") or "")
    password = str(normalized.get("password") or "")
    auth = f"{quote(user, safe='')}:{quote(password, safe='')}@" if user or password else ""
    return f"{parts.scheme}://{auth}{parts.netloc}"


def test_proxy(proxy: str | dict[str, Any] | None = None) -> dict[str, str]:
    """Test a proxy via ipify without returning or persisting its credentials."""
    selected: Any = proxy
    if isinstance(proxy, str) and not "://" in proxy:
        selected = next((item for item in _cards() if str(item.get("id") or "") == proxy), None)
    if selected is None:
        selected = get_active_proxy()
    try:
        normalized = normalize_proxy(selected)
        if not normalized:
            return {"status": "error", "ip": "", "message": "Nenhum proxy seleccionado."}
        proxy_url = _requests_proxy_url(normalized)
        response = requests.get(
            IP_CHECK_URL,
            proxies={"http": proxy_url, "https": proxy_url},
            timeout=IP_CHECK_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        ip = str(payload.get("ip") or "").strip() if isinstance(payload, dict) else ""
        if not ip:
            raise ValueError("Resposta de IP inválida.")
        result = {"status": "ok", "ip": ip, "message": "Proxy acessível."}
    except Exception as exc:
        response = getattr(exc, "response", None)
        is_auth_failure = bool(getattr(response, "status_code", None) == 407) or bool(
            isinstance(selected, dict) and (selected.get("username") or selected.get("password"))
        )
        result = {
            "status": "error",
            "ip": "",
            "message": AUTH_FAILURE_MESSAGE if is_auth_failure else "Não foi possível alcançar o proxy ou validar o IP de saída.",
        }
    if isinstance(selected, dict) and selected.get("id"):
        proxy_id = str(selected["id"])

        def mutate(settings: Any) -> None:
            if not isinstance(settings, dict) or not isinstance(settings.get("proxies_cards"), list):
                return
            for card in settings["proxies_cards"]:
                if isinstance(card, dict) and str(card.get("id") or "") == proxy_id:
                    card["last_test"] = dict(result)
                    break

        update_json("settings.json", {}, mutate)
    return result
