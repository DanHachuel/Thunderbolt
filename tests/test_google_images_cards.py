from unittest.mock import Mock, patch

import pytest
import requests

from hermes_ui import media_generation as media


def response(status=200, payload=None):
    item = Mock(status_code=status)
    item.json.return_value = payload or {"items": [{"link": "https://img.test/a.jpg"}]}
    item.raise_for_status.return_value = None
    if status >= 400:
        error = requests.HTTPError(f"HTTP {status}")
        error.response = item
        item.raise_for_status.side_effect = error
    return item


def settings(cards):
    return {"google_images_cards": cards}


def test_card_lifecycle_and_reordering():
    value = settings([])
    with patch.object(media, "write_json"):
        first = media.add_google_images_card(value)
        second = media.add_google_images_card(value)
        assert first["priority"] == 1 and second["priority"] == 2
        media.move_google_images_card(value, second["id"], -1)
        assert media.google_images_cards(value)[0]["id"] == second["id"]
        media.remove_google_images_card(value, first["id"])
        assert len(media.google_images_cards(value)) == 1


def test_fallback_and_daily_reset():
    value = settings([
        {"id": "a", "api_key": "bad", "cx": "cx", "priority": 1, "usage_date": "2000-01-01", "queries_used_today": 99},
        {"id": "b", "api_key": "good", "cx": "cx", "priority": 2},
    ])
    with patch.object(media, "write_json"), patch.object(media.requests, "get", side_effect=[response(429), response(200)]) as request:
        result = media.search_google_images(value, "cats")
    assert result[0]["link"] == "https://img.test/a.jpg"
    assert request.call_count == 2
    assert value["google_images_cards"][0]["queries_used_today"] == 1


@pytest.mark.parametrize("status", [403, 429])
def test_http_errors_fall_back(status):
    value = settings([{"id": "a", "api_key": "a", "cx": "x"}, {"id": "b", "api_key": "b", "cx": "x", "priority": 2}])
    with patch.object(media, "write_json"), patch.object(media.requests, "get", side_effect=[response(status), response(200)]):
        assert media.search_google_images(value, "cats")
    if status == 403:
        assert value["google_images_cards"][0]["enabled"] is False


def test_network_error_falls_back():
    value = settings([{"id": "a", "api_key": "a", "cx": "x"}, {"id": "b", "api_key": "b", "cx": "x", "priority": 2}])
    with patch.object(media, "write_json"), patch.object(media.requests, "get", side_effect=[requests.ConnectionError("offline"), response(200)]):
        assert media.search_google_images(value, "cats")


def test_pagination_filters_and_query_count():
    value = settings([{ "id": "a", "api_key": "a", "cx": "x", "daily_limit": 3 }])
    first = response(200, {"items": [{"link": "https://img.test/1.jpg"}]})
    second = response(200, {"items": [{"link": "https://img.test/2.jpg"}]})
    with patch.object(media, "write_json"), patch.object(media.requests, "get", side_effect=[first, second]) as request:
        result = media.search_google_images(value, "cats", num_results=2, start=11, rights="cc_publicdomain", img_type="photo")
    assert len(result) == 2
    assert request.call_args_list[0].kwargs["params"]["rights"] == "cc_publicdomain"
    assert request.call_args_list[0].kwargs["params"]["imgType"] == "photo"
    assert request.call_args_list[1].kwargs["params"]["start"] == 12
    assert value["google_images_cards"][0]["queries_used_today"] == 2


def test_api_test_does_not_consume_quota_or_expose_key():
    card = {"id": "a", "api_key": "SECRET", "cx": "x", "queries_used_today": 8}
    with patch.object(media.requests, "get", side_effect=requests.Timeout("slow")):
        result = media.test_google_images_card(card)
    assert result["status"] == "error"
    assert "SECRET" not in result["message"]
    assert card["queries_used_today"] == 8


def test_schema_defaults_and_copyright_warning():
    card = media.normalize_google_images_card({}, 2)
    assert card["id"] == "google-images-3"
    assert card["daily_limit"] == 100
    assert card["queries_used_today"] == 0
    assert "direitos" in media.GOOGLE_IMAGES_COPYRIGHT_WARNING.lower()


def test_empty_cards_are_allowed_until_action_time():
    with patch.object(media.requests, "get") as request:
        assert media.google_images_cards(settings([])) == []
        with pytest.raises(media.MediaGenerationError):
            media.search_google_images(settings([]), "cats")
        request.assert_not_called()


def test_provider_catalog_and_source_contracts():
    from hermes_ui.media_providers import media_provider_definition
    from hermes_ui.pipeline_worker import _normalise_video_route
    assert media_provider_definition("google_images").api_style == "google_images"
    assert _normalise_video_route({"style_wide": "google_images"}, {}) == "google_images"


def test_search_uses_maximum_ten_results_per_request():
    value = settings([{ "id": "a", "api_key": "a", "cx": "x" }])
    with patch.object(media, "write_json"), patch.object(media.requests, "get", return_value=response(200)) as request:
        media.search_google_images(value, "cats", num_results=100)
    assert request.call_args.kwargs["params"]["num"] <= 10
