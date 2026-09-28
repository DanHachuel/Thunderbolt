from __future__ import annotations

from types import SimpleNamespace

from hermes_ui import proxy_manager
from hermes_ui import storage


def _storage(tmp_path, monkeypatch):
    root = tmp_path / "storage"
    monkeypatch.setattr(storage, "STORAGE", root)
    monkeypatch.setattr(storage, "STATE", root / "state")
    monkeypatch.setattr(storage, "BLUEPRINTS", root / "blueprints")
    monkeypatch.setattr(storage, "TIKTOK_PROMPT_MASTERS", root / "tiktok" / "prompts_master")
    monkeypatch.setattr(storage, "MEDIA_DOWNLOADS", root / "media_downloads")
    monkeypatch.setattr(storage, "NICHES_DATA", root / "data" / "niches")
    storage.ensure_storage()


def test_proxy_crud_and_empty_list(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    assert proxy_manager.list_proxies() == []
    created = proxy_manager.add_proxy("Proxy A", "proxy.example:8080", username="user", password="secret")
    assert created["label"] == "Proxy A"
    assert "password" not in created
    assert proxy_manager.set_active_proxy(created["id"])
    assert proxy_manager.get_active_proxy()["password"] == "secret"
    safe = proxy_manager.list_proxies()[0]
    assert "password" not in safe
    assert safe["has_credentials"] is True
    assert "secret" not in str(safe)
    assert proxy_manager.remove_proxy(created["id"])
    assert proxy_manager.get_active_proxy() is None


def test_proxy_test_uses_ipify_timeout_and_returns_schema(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    card = proxy_manager.add_proxy("Proxy", "http://proxy.example:8080")
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"ip": "203.0.113.9"})

    monkeypatch.setattr(proxy_manager.requests, "get", fake_get)
    result = proxy_manager.test_proxy(card["id"])
    assert captured["url"] == "https://api.ipify.org?format=json"
    assert captured["timeout"] == 10
    assert result == {"status": "ok", "ip": "203.0.113.9", "message": "Proxy acessível."}


def test_proxy_auth_failure_message_does_not_leak_credentials(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    def fake_get(*args, **kwargs):
        raise RuntimeError("bad auth password=private-secret")

    monkeypatch.setattr(proxy_manager.requests, "get", fake_get)
    result = proxy_manager.test_proxy({"id": "p1", "server": "http://proxy.example:8080", "username": "user", "password": "private-secret"})
    assert result["status"] == "error"
    assert result["message"] == proxy_manager.AUTH_FAILURE_MESSAGE
    assert "private-secret" not in str(result)


def test_normalize_proxy_keeps_auth_separate_and_handles_socks5():
    result = proxy_manager.normalize_proxy({"scheme": "socks5", "host": "127.0.0.1", "port": 1080, "username": "u", "password": "p"})
    assert result == {"server": "socks5://127.0.0.1:1080", "username": "u", "password": "p"}


def test_list_proxies_masks_credentials_embedded_in_server(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    storage.write_json("settings.json", {
        "proxies_cards": [{"id": "proxy1", "label": "Legacy", "server": "http://user:private-secret@proxy.example:8080"}],
        "proxy_active_id": "",
    })
    safe = proxy_manager.list_proxies()[0]
    assert "private-secret" not in str(safe)
    assert safe["server"] == "http://***@proxy.example:8080"
