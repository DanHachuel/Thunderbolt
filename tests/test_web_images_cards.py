from pathlib import Path
import sys
import types

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
    class FakeHTTPError(Exception):
        status_code = 429
    class FakeClient:
        def __init__(self, **kwargs): pass
        def search(self, params): raise FakeHTTPError("quota")
    fake_serpapi = types.SimpleNamespace(Client=FakeClient, HTTPError=FakeHTTPError, TimeoutError=type("TimeoutError", (Exception,), {}))
    monkeypatch.setitem(sys.modules, "serpapi", fake_serpapi)
    class Response:
        def __init__(self, status, payload): self.status_code, self.payload = status, payload
        def raise_for_status(self):
            if self.status_code >= 400: raise RuntimeError("http")
        def json(self): return self.payload
    responses = iter([Response(200, {"images": [{"title": "x", "original_image": "https://img.example/x.jpg"}]})])
    monkeypatch.setattr(media_generation.requests, "get", lambda *args, **kwargs: next(responses))
    result = media_generation.web_images_search(settings, "tema", num_results=1)
    assert result[0]["source"] == "brightdata"
    assert result[0]["url"].endswith("x.jpg")


def test_serpapi_parsing(monkeypatch):
    calls = {}
    class FakeClient:
        def __init__(self, **kwargs): calls["client"] = kwargs
        def search(self, params):
            calls["params"] = params
            return {"images_results": [{"title": "cat", "link": "https://link/cat", "original": "https://img/cat.jpg", "thumbnail": "https://thumb/cat.jpg"}]}
    fake_serpapi = types.SimpleNamespace(Client=FakeClient, HTTPError=type("HTTPError", (Exception,), {}), TimeoutError=type("TimeoutError", (Exception,), {}))
    monkeypatch.setitem(sys.modules, "serpapi", fake_serpapi)
    result = media_generation.web_images_search({"web_images_cards": [{"provider": "serpapi", "api_key": "k"}]}, "cat", num_results=7)
    assert result == [{"url": "https://img/cat.jpg", "thumbnail": "https://thumb/cat.jpg", "title": "cat", "source": "serpapi"}]
    assert calls["client"] == {"api_key": "k", "timeout": 30}
    assert calls["params"] == {"engine": "google_images", "q": "cat", "num": 7, "ijn": 0, "hl": "en", "gl": "us"}


def test_serpapi_paginates_150_results_with_page_indexes(monkeypatch):
    calls = []
    class FakeClient:
        def __init__(self, **kwargs): pass
        def search(self, params):
            calls.append(dict(params))
            first_index = params["ijn"] * 100
            return {"images_results": [
                {"title": f"image {index}", "original": f"https://img/{index}.jpg", "thumbnail": f"https://thumb/{index}.jpg"}
                for index in range(first_index, first_index + params["num"])
            ]}
    fake_serpapi = types.SimpleNamespace(Client=FakeClient, HTTPError=type("HTTPError", (Exception,), {}), TimeoutError=type("TimeoutError", (Exception,), {}))
    monkeypatch.setitem(sys.modules, "serpapi", fake_serpapi)

    result = media_generation.web_images_search({"web_images_cards": [{"provider": "serpapi", "api_key": "k"}]}, "cat", num_results=150)

    assert [call["ijn"] for call in calls] == [0, 1]
    assert [call["num"] for call in calls] == [100, 50]
    assert all("start" not in call for call in calls)
    assert len(result) == 150
    assert len({item["url"] for item in result}) == 150


def test_serpapi_paginates_250_results_with_three_pages(monkeypatch):
    calls = []
    class FakeClient:
        def __init__(self, **kwargs): pass
        def search(self, params):
            calls.append(dict(params))
            first_index = params["ijn"] * 100
            return {"images_results": [
                {"title": f"image {index}", "original": f"https://img/{index}.jpg", "thumbnail": f"https://thumb/{index}.jpg"}
                for index in range(first_index, first_index + params["num"])
            ]}
    fake_serpapi = types.SimpleNamespace(Client=FakeClient, HTTPError=type("HTTPError", (Exception,), {}), TimeoutError=type("TimeoutError", (Exception,), {}))
    monkeypatch.setitem(sys.modules, "serpapi", fake_serpapi)

    result = media_generation.web_images_search({"web_images_cards": [{"provider": "serpapi", "api_key": "k"}]}, "cat", num_results=250)

    assert [call["ijn"] for call in calls] == [0, 1, 2]
    assert [call["num"] for call in calls] == [100, 100, 50]
    assert len(result) == 250
    assert len({item["url"] for item in result}) == 250


def test_serpapi_stops_when_a_page_is_empty(monkeypatch):
    calls = []
    class FakeClient:
        def __init__(self, **kwargs): pass
        def search(self, params):
            calls.append(dict(params))
            if params["ijn"] == 1:
                return {"images_results": []}
            return {"images_results": [
                {"title": f"image {index}", "original": f"https://img/{index}.jpg", "thumbnail": f"https://thumb/{index}.jpg"}
                for index in range(100)
            ]}
    fake_serpapi = types.SimpleNamespace(Client=FakeClient, HTTPError=type("HTTPError", (Exception,), {}), TimeoutError=type("TimeoutError", (Exception,), {}))
    monkeypatch.setitem(sys.modules, "serpapi", fake_serpapi)

    result = media_generation.web_images_search({"web_images_cards": [{"provider": "serpapi", "api_key": "k"}]}, "cat", num_results=150)

    assert [call["ijn"] for call in calls] == [0, 1]
    assert len(result) == 100


def test_serpapi_http_429_uses_next_provider(monkeypatch):
    class FakeHTTPError(Exception):
        status_code = 429
    class FakeClient:
        def __init__(self, **kwargs): pass
        def search(self, params): raise FakeHTTPError("quota")
    fake_serpapi = types.SimpleNamespace(Client=FakeClient, HTTPError=FakeHTTPError, TimeoutError=type("TimeoutError", (Exception,), {}))
    monkeypatch.setitem(sys.modules, "serpapi", fake_serpapi)
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"images": [{"title": "fallback", "original_image": "https://img/fallback.jpg"}]}
    monkeypatch.setattr(media_generation.requests, "get", lambda *args, **kwargs: Response())
    settings = {"web_images_cards": [
        {"provider": "serpapi", "api_key": "k", "priority": 1},
        {"provider": "brightdata", "customer_id": "c", "zone_name": "z", "zone_password": "p", "priority": 2},
    ]}
    result = media_generation.web_images_search(settings, "cat")
    assert result[0]["source"] == "brightdata"


def test_serpapi_timeout_uses_next_provider(monkeypatch):
    class FakeTimeoutError(Exception): pass
    class FakeClient:
        def __init__(self, **kwargs): pass
        def search(self, params): raise FakeTimeoutError("slow")
    fake_serpapi = types.SimpleNamespace(Client=FakeClient, HTTPError=type("HTTPError", (Exception,), {}), TimeoutError=FakeTimeoutError)
    monkeypatch.setitem(sys.modules, "serpapi", fake_serpapi)
    monkeypatch.setattr(media_generation, "_search_web_images_card", lambda card, query, **kwargs: [{"url": "https://fallback/img.jpg", "source": "brightdata"}] if card["provider"] == "brightdata" else (_ for _ in ()).throw(RuntimeError("SerpApi timeout")))
    result = media_generation.web_images_search({"web_images_cards": [
        {"provider": "serpapi", "api_key": "k", "priority": 1},
        {"provider": "brightdata", "customer_id": "c", "zone_name": "z", "zone_password": "p", "priority": 2},
    ]}, "cat")
    assert result[0]["source"] == "brightdata"


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
