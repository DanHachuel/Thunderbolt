from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hermes_ui import facebook_automation


def test_collect_images_uses_only_google_images(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(facebook_automation, "google_images_search", lambda settings, query, **kwargs: calls.append(query) or [{"link": "https://img.example/image.jpg"}])
    monkeypatch.setattr(facebook_automation, "_download_image", lambda url, destination: destination.parent.mkdir(parents=True, exist_ok=True) or destination.write_bytes(b"jpeg") or destination)
    post = {"id": "p1", "folder": str(tmp_path), "theme": "tema", "images": [{"search_query": "pessoa"}]}
    result = facebook_automation.collect_images({"google_images_cards": [{"id": "one", "api_key": "k", "cx": "c"}]}, post)
    assert calls == ["pessoa"]
    assert result["images"][0]["source"] == "google_images"
    assert result["images"][0]["status"] == "imagem_baixada"


def test_collect_images_warns_when_no_cards(tmp_path):
    post = {"id": "p1", "folder": str(tmp_path), "images": [{"search_query": "tema"}]}
    try:
        facebook_automation.collect_images({"google_images_cards": []}, post)
    except ValueError as exc:
        assert "Google Images" in str(exc)
    else:
        raise AssertionError("expected missing card warning")
