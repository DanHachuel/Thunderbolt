from pathlib import Path
from unittest.mock import patch

import pytest

from hermes_ui.facebook_automation import collect_images


def test_collect_images_requires_google_cards(tmp_path):
    post = {"id": "p1", "folder": str(tmp_path), "theme": "tema", "images": [{"search_query": "gatos"}]}
    with pytest.raises(ValueError, match="Google Images"):
        collect_images({"google_images_cards": []}, post)


def test_collect_images_uses_google_only(tmp_path):
    post = {"id": "p1", "folder": str(tmp_path), "theme": "tema", "images": [{"search_query": "gatos"}]}
    settings = {"google_images_cards": [{"id": "a", "api_key": "k", "cx": "cx"}]}
    with patch("hermes_ui.facebook_automation.search_google_images", return_value=[{"link": "https://img.test/a.jpg"}]), patch("hermes_ui.facebook_automation.download_google_image") as download:
        result = collect_images(settings, post)
    download.assert_called_once()
    assert result["images"][0]["source"] == "google_images"


def test_collect_images_has_no_ai_or_stock_fallback_in_source():
    source = Path("hermes_ui/facebook_automation.py").read_text(encoding="utf-8")
    assert "generate_image_for_card" not in source
    assert "search_google_images" in source
