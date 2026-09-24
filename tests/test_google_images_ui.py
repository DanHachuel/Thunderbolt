from pathlib import Path

MAIN = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")


def test_google_images_cards_ui_has_required_actions_and_fields():
    assert "Adicionar nova API Key do Google Images" in MAIN
    assert "Testar chamada API" in MAIN
    assert 'key="google_images_cards"' not in MAIN
    for field in ("api_key", "cx", "daily_limit", "queries_used_today"):
        assert field in MAIN
    assert "Remover card" in MAIN
    assert "Quota ≥ 80%" in MAIN


def test_google_images_ui_has_copyright_warning_and_source_unblocked():
    assert "GOOGLE_IMAGES_COPYRIGHT_WARNING" in MAIN
    assert 'UNAVAILABLE_VIDEO_SOURCES = {"remotion", "music_clips"}' in MAIN
    assert 'channel_video_source_storage(wide_style_label) == "google_images"' in MAIN
