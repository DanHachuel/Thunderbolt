from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _restore_storage_globals():
    """Desfaz as atribuições directas a globals do storage feitas pelos testes
    abaixo (sem monkeypatch); sem isto os globals ficam apontando para tmp dirs
    mortos durante o resto da sessão."""
    from hermes_ui import storage

    before = (storage.STORAGE, storage.STATE, storage.BLUEPRINTS, storage.TIKTOK_PROMPT_MASTERS, storage.MEDIA_DOWNLOADS)
    yield
    storage.STORAGE, storage.STATE, storage.BLUEPRINTS, storage.TIKTOK_PROMPT_MASTERS, storage.MEDIA_DOWNLOADS = before


def test_telegram_adapter_status_is_disabled_without_network():
    from integrations.telegram_gateway import TelegramGatewayAdapter

    adapter = TelegramGatewayAdapter({"telegram_enabled": False, "telegram_bot_token": "token", "telegram_chat_id": "chat"})
    result = adapter.status()
    assert result.ok is False
    assert result.data["error_type"] == "disabled"


def test_telegram_adapter_sends_notification_with_chat_id():
    from integrations.telegram_gateway import TelegramGatewayAdapter

    class Response:
        status_code = 200

        @staticmethod
        def json() -> dict[str, Any]:
            return {"ok": True, "result": {"message_id": 42}}

    calls: list[dict[str, Any]] = []

    class Client:
        @staticmethod
        def post(url: str, **kwargs: Any) -> Response:
            calls.append({"url": url, **kwargs})
            return Response()

    adapter = TelegramGatewayAdapter(
        {
            "telegram_enabled": True,
            "telegram_bot_token": "123:secret-token",
            "telegram_chat_id": "-100123",
        },
        request_client=Client,
    )
    result = adapter.send_notification(
        {
            "title": "Vídeo concluído",
            "message": "A actividade terminou.",
            "category": "Produção",
            "created_at": "2026-08-25T12:00:00+00:00",
            "metadata": {"task_id": "task-1"},
        }
    )

    assert result.ok is True
    assert result.data["message_ids"] == ["42"]
    assert len(calls) == 1
    assert calls[0]["url"].endswith("/bot123:secret-token/sendMessage")
    assert calls[0]["json"]["chat_id"] == "-100123"
    assert calls[0]["json"]["text"].startswith("Vídeo concluído")
    assert calls[0]["json"]["text"].endswith("task_id: task-1")
    assert "parse_mode" not in calls[0]["json"]


def test_telegram_adapter_splits_long_messages_on_line_boundaries():
    from integrations.telegram_gateway import TelegramGatewayAdapter

    chunks = TelegramGatewayAdapter.split_message("linha\n" * 2000, max_length=100)
    assert len(chunks) > 1
    assert all(len(chunk) <= 100 for chunk in chunks)
    assert "" not in chunks


def test_telegram_credentials_check_requires_both_values(monkeypatch):
    from hermes_ui import api_key_tests

    called = False

    def fail_if_called(*args: Any, **kwargs: Any):
        nonlocal called
        called = True
        raise AssertionError("não deve contactar o Telegram sem configuração")

    monkeypatch.setattr(api_key_tests, "_get", fail_if_called)
    result = api_key_tests.test_telegram_credentials("", "123")
    assert result["status"] == "missing"
    assert called is False


def test_record_notification_dispatches_telegram_after_local_persistence(tmp_path, monkeypatch):
    from hermes_ui import notifications

    storage = notifications.storage
    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.BLUEPRINTS = storage.STORAGE / "blueprints"
    storage.TIKTOK_PROMPT_MASTERS = storage.STORAGE / "tiktok" / "prompts_master"
    storage.ensure_storage()
    storage.write_json("settings.json", {"telegram_enabled": True, "telegram_bot_token": "token", "telegram_chat_id": "chat"})
    sent: list[dict[str, Any]] = []

    def fake_send(entry: dict[str, Any], settings: dict[str, Any]) -> Any:
        sent.append({"entry": entry, "settings": settings})
        return type("Result", (), {"ok": True, "data": {}})()

    monkeypatch.setattr("integrations.telegram_gateway.send_notification_to_telegram", fake_send)
    entry = notifications.record_notification("video_completed", "Vídeo", "Concluído", dedupe_key="task:telegram")

    assert entry is not None
    assert len(sent) == 1
    assert sent[0]["entry"]["id"] == entry["id"]
    assert notifications.list_notifications()[0]["id"] == entry["id"]


def test_telegram_delivery_failure_does_not_break_notification_recording(tmp_path, monkeypatch):
    from hermes_ui import notifications

    storage = notifications.storage
    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.BLUEPRINTS = storage.STORAGE / "blueprints"
    storage.TIKTOK_PROMPT_MASTERS = storage.STORAGE / "tiktok" / "prompts_master"
    storage.ensure_storage()
    storage.write_json("settings.json", {"telegram_enabled": True, "telegram_bot_token": "token", "telegram_chat_id": "chat"})

    def broken_send(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("network unavailable")

    monkeypatch.setattr("integrations.telegram_gateway.send_notification_to_telegram", broken_send)
    entry = notifications.record_notification("activity_failed", "Falha", "Detalhes", dedupe_key="task:failure")

    assert entry is not None
    assert notifications.list_notifications()[0]["event_type"] == "activity_failed"


def test_notification_tab_labels_have_translations_for_all_supported_languages():
    from hermes_ui.languages import LANGUAGE_CODES, ui_text

    for language in LANGUAGE_CODES:
        assert ui_text("Geral", language).strip()
        assert ui_text("Telegram", language).strip()


def test_notifications_page_has_general_and_telegram_tabs():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    source = (root / "app" / "main.py").read_text(encoding="utf-8")
    assert 'render_localized_tabs(["Geral", "Telegram"])' in source
    assert 'with telegram_tab:' in source
    assert 'st.form("telegram_notifications_form")' in source
    assert '"telegram_bot_token"' in source
    assert '"telegram_chat_id"' in source
    assert 'widget_key="api_test_telegram"' in source
