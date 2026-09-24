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


def test_google_images_actions_use_form_submit_buttons_inside_settings_form():
    start = MAIN.index('with st.expander("Google Imagem API", expanded=False)')
    end = MAIN.index('with st.expander("Voz, TTS e música — Azure Speech, restantes serviços e Suno", expanded=False)', start)
    block = MAIN[start:end]
    assert "st.button(" not in block
    assert block.count("st.form_submit_button(") >= 7


def test_google_images_fields_have_half_width_columns_and_programmable_search_link():
    start = MAIN.index('with st.expander("Google Imagem API", expanded=False)')
    end = MAIN.index('with st.expander("Voz, TTS e música — Azure Speech, restantes serviços e Suno", expanded=False)', start)
    block = MAIN[start:end]
    assert "https://programmablesearchengine.google.com/" in block
    assert "Programmable Search Engine" in block
    assert "name_col, _name_spacer = st.columns([1, 1])" in block
    assert "cx_col, cx_link_col = st.columns([1, 1])" in block
    assert "daily_col, _daily_spacer = st.columns([1, 1])" in block


def test_google_images_ui_has_copyright_warning_and_source_unblocked():
    assert "GOOGLE_IMAGES_COPYRIGHT_WARNING" in MAIN
    assert 'UNAVAILABLE_VIDEO_SOURCES = {"remotion", "music_clips"}' in MAIN
    assert 'channel_video_source_storage(wide_style_label) == "google_images"' in MAIN
