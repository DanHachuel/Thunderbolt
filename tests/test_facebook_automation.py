from pathlib import Path

from PIL import Image

from hermes_ui import facebook_automation as automation


def test_create_post_uses_local_storage_and_caps_image_count(monkeypatch, tmp_path):
    monkeypatch.setattr(automation, "POSTS_DIR", tmp_path / "facebook_automation")
    monkeypatch.setattr(automation, "_posts", lambda: [])
    saved = []
    monkeypatch.setattr(automation, "write_json", lambda name, value: saved.append((name, value)))
    post = automation.create_post({"id": "page-1", "name": "Page", "url": "https://facebook.com/page"}, image_count=9)
    assert post["image_count"] == 5
    assert post["status"] == "tema_pendente"
    assert post["folder"].replace("\\", "/").endswith("/images")
    assert saved[-1][0] == automation.POSTS_FILE


def test_generate_article_requests_650_to_900_words_and_normalizes_cards(monkeypatch):
    captured = {}

    def fake_chat(settings, system, user):
        captured["system"] = system
        return {"title": "História", "article_text": "Uma frase por linha.", "images": [{"search_query": "cidade antiga", "overlay_text": "A virada começou aqui."}]}

    monkeypatch.setattr(automation, "_chat_json", fake_chat)
    monkeypatch.setattr(automation, "save_post", lambda post: dict(post))
    result = automation.generate_article({}, {"theme": "Tema", "tone": "História", "image_count": 1}, {"name": "Page"})
    assert "650 a 900" in captured["system"]
    assert result["status"] == "imagens_pendentes"
    assert result["images"][0]["index"] == 1


def test_caption_images_writes_local_pillow_output(monkeypatch, tmp_path):
    source = tmp_path / "image.jpg"
    Image.new("RGB", (500, 300), "blue").save(source)
    post = {"id": "post", "images": [{"path": str(source), "overlay_text": "Texto complementar"}]}
    monkeypatch.setattr(automation, "save_post", lambda post: dict(post))
    result = automation.caption_images(post)
    output = Path(result["images"][0]["captioned_path"])
    assert output.is_file()
    assert result["status"] == "pronto_upload"
