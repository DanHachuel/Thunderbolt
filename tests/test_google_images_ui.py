from pathlib import Path


def test_google_images_ui_has_card_actions_and_warning():
    source = Path("app/main.py").read_text(encoding="utf-8")
    for marker in ("render_google_images_cards", "Adicionar nova API Key do Google Images", "Testar chamada API", "Salvar", "Remover card", "GOOGLE_IMAGES_COPYRIGHT_WARNING"):
        assert marker in source


def test_google_images_source_is_available_in_video_options():
    source = Path("app/main.py").read_text(encoding="utf-8")
    assert '"Google Images"' in source
    assert "google_images" in source


def test_google_images_card_schema_is_visible_in_code():
    source = Path("hermes_ui/media_generation.py").read_text(encoding="utf-8")
    for marker in ("daily_limit", "queries_used_today", "usage_date", "search_google_images"):
        assert marker in source
