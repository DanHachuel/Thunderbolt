from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hermes_ui import media_generation


def test_cards_migrate_legacy_google_and_order_by_priority():
    settings = {"google_images_cards": [{"id": "g2", "api_key": "k", "cx": "c", "priority": 2}, {"id": "g1", "api_key": "k", "cx": "c", "priority": 1}]}
    migrated, changed = media_generation.ensure_web_images_cards(settings)
    assert changed
    assert [item["id"] for item in migrated["web_images_cards"]] == ["g1", "g2"]
    assert all(item["provider"] == "google_images" for item in migrated["web_images_cards"])
    assert [item["priority"] for item in migrated["web_images_cards"]] == [1, 2]


def test_fallback_across_providers_by_priority(monkeypatch):
    settings = {"web_images_cards": [
        {"id": "serp", "provider": "serpapi", "api_key": "bad", "priority": 1},
        {"id": "bright", "provider": "brightdata", "customer_id": "c", "zone_name": "z", "zone_password": "p", "priority": 2},
    ]}
    class Response:
        def __init__(self, status, payload): self.status_code, self.payload = status, payload
        def raise_for_status(self):
            if self.status_code >= 400: raise RuntimeError("http")
        def json(self): return self.payload
    responses = iter([Response(429, {}), Response(200, {"images": [{"title": "x", "original_image": "https://img.example/x.jpg"}]})])
    monkeypatch.setattr(media_generation.requests, "get", lambda *args, **kwargs: next(responses))
    result = media_generation.web_images_search(settings, "tema", num_results=1)
    assert result[0]["source"] == "brightdata"
    assert result[0]["url"].endswith("x.jpg")


def test_serpapi_parsing(monkeypatch):
    class Response:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"images_results": [{"title": "cat", "original": "https://img/cat.jpg", "thumbnail": "https://thumb/cat.jpg"}]}
    monkeypatch.setattr(media_generation.requests, "get", lambda *args, **kwargs: Response())
    result = media_generation.web_images_search({"web_images_cards": [{"provider": "serpapi", "api_key": "k"}]}, "cat")
    assert result == [{"url": "https://img/cat.jpg", "thumbnail": "https://thumb/cat.jpg", "title": "cat", "source": "serpapi"}]


def test_brightdata_proxy_contract(monkeypatch):
    captured = {}
    class Response:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"images": [{"title": "cat", "image": "https://thumb/cat.jpg", "original_image": "https://img/cat.jpg"}]}
    def fake_get(*args, **kwargs):
        captured.update(kwargs)
        return Response()
    monkeypatch.setattr(media_generation.requests, "get", fake_get)
    media_generation.web_images_search({"web_images_cards": [{"provider": "brightdata", "customer_id": "123", "zone_name": "serp", "zone_password": "secret"}]}, "cat")
    assert "fserp.brd.superproxy.io:44445" in captured["proxies"]["https"]
    assert captured["headers"]["x-unblock-data-format"] == "parsed_light"
