from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def test_google_images_source_is_available_but_later_sources_remain_unavailable():
    assert 'UNAVAILABLE_VIDEO_SOURCES = {"remotion", "music_clips"}' in MAIN_SOURCE
    assert 'channel_video_source_storage(wide_style_label) == "google_images"' in MAIN_SOURCE
    assert 'style in UNAVAILABLE_VIDEO_SOURCES' in MAIN_SOURCE


def test_google_images_card_has_settings_actions():
    # Bloco da função do pool de web images (a332304).
    start = MAIN_SOURCE.index("def render_web_images_cards(")
    end = MAIN_SOURCE.index("\ndef ", start + 1)
    block = MAIN_SOURCE[start:end]
    assert "Adicionar fornecedor" in block
    assert "Testar chamada API" in block
    assert "Salvar" in block
    assert "Remover card" in block
    assert "web_images_cards" in block


def test_google_images_copyright_warning_is_present():
    assert "GOOGLE_IMAGES_COPYRIGHT_WARNING" in MAIN_SOURCE
    assert "WEB_IMAGES_COPYRIGHT_WARNING" in MAIN_SOURCE
    # "Quota ≥ 80%" saiu com o redesign do pool; a contabilidade de quota
    # (queries_used_today) passou a viver no backend de media_generation.
    media_source = (ROOT / "hermes_ui" / "media_generation.py").read_text(encoding="utf-8")
    assert "queries_used_today" in media_source


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__]))
