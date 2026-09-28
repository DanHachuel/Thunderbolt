import json
from pathlib import Path

from PIL import Image

from hermes_ui import facebook_storytelling as story


def test_sqlite_isolates_used_themes_by_channel(monkeypatch, tmp_path):
    db = tmp_path / "facebook.db"
    monkeypatch.setattr(story, "DB_PATH", db)
    story.save_facebook_post({"id": "one", "channel_id": "page-a", "theme": "A", "tone": "História"})
    story.save_facebook_post({"id": "two", "channel_id": "page-b", "theme": "A", "tone": "História"})
    assert story.get_used_themes_for_channel("page-a") == ["A"]
    assert story.get_used_themes_for_channel("page-b") == ["A"]
    assert story.get_used_themes_for_channel("other") == []


def test_generate_storytelling_theme_does_not_persist_a_duplicate(monkeypatch, tmp_path):
    monkeypatch.setattr(story, "DB_PATH", tmp_path / "facebook.db")
    monkeypatch.setattr(story, "_chat_json", lambda settings, system, user: {"tema": "Tema novo", "tom": "Curiosidade Histórica"})
    generated = story.generate_storytelling_theme({}, {"id": "page-a", "name": "Page"})
    assert generated["theme"] == "Tema novo"
    assert story.list_facebook_posts() == []


def test_generate_storytelling_article_returns_exact_cards(monkeypatch):
    monkeypatch.setattr(story, "_chat_json", lambda settings, system, user: {"title": "Título", "article_text": "Uma linha.\nOutra linha.", "images": [{"search_query": f"foto {i}", "overlay_text": f"Gancho {i}"} for i in range(1, 4)]})
    result = story.generate_storytelling_article({}, {"id": "page"}, "Tema", "História", 3)
    assert len(result["images"]) == 3
    assert [item["index"] for item in result["images"]] == [1, 2, 3]
    assert all(item["search_query"] and item["overlay_text"] for item in result["images"])


def test_apply_overlay_with_pillow_uses_final_index_and_stroke(tmp_path):
    source = tmp_path / "image-2.jpg"
    Image.new("RGB", (640, 360), "blue").save(source)
    result = story.apply_overlay_with_pillow(source, "Texto de teste", Path("/missing/font.ttf"), 32)
    assert result == tmp_path / "final_2.png"
    assert result.is_file()
    assert Image.open(result).size == (640, 360)


def test_save_and_update_post_persist_images_and_status(monkeypatch, tmp_path):
    monkeypatch.setattr(story, "DB_PATH", tmp_path / "facebook.db")
    saved = story.save_facebook_post({"id": "post", "channel_id": "page", "theme": "Tema", "tone": "Tom", "images": [{"index": 1, "search_query": "x", "overlay_text": "y"}]})
    updated = story.update_facebook_post_status("post", "artigo_pronto", title="Título")
    assert saved["status"] == "tema_pendente"
    assert updated["status"] == "artigo_pronto"
    assert updated["title"] == "Título"
    with story.get_facebook_connection(tmp_path / "facebook.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM facebook_post_images").fetchone()[0] == 1


def test_migration_is_idempotent_and_renames_legacy_json(monkeypatch, tmp_path):
    monkeypatch.setattr(story, "DB_PATH", tmp_path / "facebook.db")
    legacy = tmp_path / "posts.json"
    legacy.write_text(json.dumps([{"id": "legacy", "page_id": "page", "theme": "Tema", "tone": "Tom", "status": "publicado"}], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(story, "POSTS_JSON", legacy)
    assert story.migrate_posts_json_to_sqlite() == 1
    assert legacy.with_name("posts.json.migrated").is_file()
    assert story.migrate_posts_json_to_sqlite() == 0
    assert story.get_facebook_post("legacy")["theme"] == "Tema"


def test_collect_web_images_marks_failed_cards_and_continues(monkeypatch, tmp_path):
    monkeypatch.setattr(story, "DB_PATH", tmp_path / "facebook.db")
    monkeypatch.setattr(story, "web_images_search", lambda settings, query, **kwargs: [{"url": "https://example/image.jpg", "source": "serpapi"}])
    monkeypatch.setattr(story, "_download", lambda url, destination: destination.write_bytes(b"image") or destination)
    post = {"id": "post", "channel_id": "page", "theme": "Tema", "image_count": 2, "folder": str(tmp_path), "images": [{"index": 1, "search_query": "a", "overlay_text": "a"}, {"index": 2, "search_query": "b", "overlay_text": "b"}]}
    result = story.collect_storytelling_images({}, post, source="web")
    assert result["status"] == "artigo_pronto"
    assert all(item["status"] == "downloaded" for item in result["images"])
