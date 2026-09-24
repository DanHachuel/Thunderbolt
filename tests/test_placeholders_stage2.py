from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def test_google_images_source_is_available_but_later_sources_remain_unavailable():
    assert 'UNAVAILABLE_VIDEO_SOURCES = {"remotion", "music_clips"}' in MAIN_SOURCE
    assert 'channel_video_source_storage(wide_style_label) == "google_images"' in MAIN_SOURCE
    assert 'style in UNAVAILABLE_VIDEO_SOURCES' in MAIN_SOURCE


def test_google_images_card_has_settings_actions():
    start = MAIN_SOURCE.index('with st.expander("Google Imagem API", expanded=False)')
    end = MAIN_SOURCE.index('with st.expander("Voz, TTS e música — Azure Speech, restantes serviços e Suno", expanded=False)', start)
    block = MAIN_SOURCE[start:end]
    assert "Adicionar nova API Key do Google Images" in block
    assert "Testar chamada API" in block
    assert "Salvar" in block
    assert "Remover card" in block
    assert "google_images_cards" in block


def test_google_images_copyright_warning_is_present():
    assert "GOOGLE_IMAGES_COPYRIGHT_WARNING" in MAIN_SOURCE
    assert "Quota ≥ 80%" in MAIN_SOURCE


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__]))
