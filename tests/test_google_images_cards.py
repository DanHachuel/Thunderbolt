from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hermes_ui import media_generation


def test_card_creation_edit_removal_and_reordering():
    settings = {"google_images_cards": [media_generation.new_google_images_card("a", 2), media_generation.new_google_images_card("b", 1)]}
    migrated, changed = media_generation.ensure_google_images_cards(settings)
    assert changed
    assert [item["id"] for item in migrated["google_images_cards"]] == ["b", "a"]
    assert [item["priority"] for item in migrated["google_images_cards"]] == [1, 2]
    edited = dict(migrated["google_images_cards"][0], label="Conta editada")
    remaining = [edited]
    assert media_generation.google_images_cards({"google_images_cards": remaining})[0]["label"] == "Conta editada"


def test_daily_reset():
    card = {"id": "x", "queries_used_today": 99, "last_reset_date": "2000-01-01"}
    normalized = media_generation.normalize_google_images_card(card)
    assert normalized["queries_used_today"] == 0
    assert normalized["last_reset_date"] == media_generation._google_today()


def test_fallback_between_cards_and_quota(monkeypatch, tmp_path):
    settings = {"google_images_cards": [
        {"id": "first", "api_key": "bad", "cx": "cx1", "priority": 1},
        {"id": "second", "api_key": "good", "cx": "cx2", "priority": 2},
    ]}
    class Response:
        def __init__(self, status, payload=None): self.status_code, self.payload = status, payload or {}
        def raise_for_status(self):
            if self.status_code >= 400: raise RuntimeError("http")
        def json(self): return self.payload
    responses = iter([Response(429), Response(200, {"items": [{"link": "https://img.example/a.jpg"}]})])
    monkeypatch.setattr(media_generation.requests, "get", lambda *args, **kwargs: next(responses))
    result = media_generation.google_images_search(settings, "tema")
    assert result[0]["link"].endswith("a.jpg")


def test_http_403_and_network_errors_fallback(monkeypatch):
    settings = {"google_images_cards": [
        {"id": "first", "api_key": "bad", "cx": "cx1", "priority": 1},
        {"id": "second", "api_key": "good", "cx": "cx2", "priority": 2},
    ]}
    class Response:
        def __init__(self, status): self.status_code = status
        def raise_for_status(self): raise RuntimeError("http")
        def json(self): return {}
    responses = iter([Response(403), media_generation.requests.RequestException("network")])
    def fake_get(*args, **kwargs):
        value = next(responses)
        if isinstance(value, Exception): raise value
        return value
    monkeypatch.setattr(media_generation.requests, "get", fake_get)
    try:
        media_generation.google_images_search(settings, "tema")
    except media_generation.MediaGenerationError as exc:
        assert "falharam" in str(exc)
    else:
        raise AssertionError("expected fallback failure")
