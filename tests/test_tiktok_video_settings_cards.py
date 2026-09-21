from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def test_tiktok_channel_cards_render_video_settings_section():
    card_block = MAIN_SOURCE.split('def render_tiktok_channels():', 1)[1].split('def _refresh_tiktok_channel_metrics', 1)[0]
    assert 'st.expander("Configurações de vídeo"' in card_block
    assert 'tiktok_video_settings_source_' in card_block
    assert 'tiktok_video_settings_aspect_' in card_block
    assert 'tiktok_video_settings_format_' in card_block
    assert 'Guardar configurações de vídeo' in card_block
    assert 'channel_video_source_storage(video_source)' in card_block
