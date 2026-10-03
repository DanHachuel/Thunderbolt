from pathlib import Path


MAIN = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
MEDIA_SOURCE = (Path(__file__).resolve().parents[1] / "hermes_ui" / "media_generation.py").read_text(encoding="utf-8")


def _web_images_renderer_block() -> str:
    """Bloco da função actual do pool de fornecedores de imagens web."""
    start = MAIN.index("def render_web_images_cards(")
    end = MAIN.index("\ndef ", start + 1)
    return MAIN[start:end]


def test_google_images_cards_ui_has_required_actions_and_fields():
    # Desde a332304 ("prioritized web image scraping providers") o Google Images
    # é um fornecedor (google_images) do pool "Scrapt de Imagens na Web", junto
    # de SerpApi/Bright Data; as ações e campos equivalentes continuam presentes
    # e a contabilidade de quota (queries_used_today) vive agora no backend.
    assert "Adicionar fornecedor" in MAIN
    assert "Testar chamada API" in MAIN
    assert 'key="google_images_cards"' not in MAIN
    for field in ("api_key", "cx", "daily_limit"):
        assert field in MAIN
    assert "Remover card" in MAIN
    assert "queries_used_today" in MEDIA_SOURCE


def test_google_images_actions_use_form_submit_buttons_inside_settings_form():
    block = _web_images_renderer_block()
    assert "st.button(" not in block
    # ↑, ↓, Testar chamada API, Salvar, Remover card, Adicionar fornecedor.
    assert block.count("st.form_submit_button(") >= 6


def test_google_images_fields_have_half_width_columns_and_programmable_search_link():
    block = _web_images_renderer_block()
    # O layout dos campos passou a três colunas por cartão (nome/activo,
    # prioridade+API key, CX+limite diário); o link do Programmable Search
    # Engine foi removido no redesign do pool (a332304).
    assert "field_cols = st.columns(3)" in block
    assert 'st.text_input("Custom Search Engine ID (CX)"' in block
    assert 'st.text_input("API Key"' in block
    assert 'st.number_input("Limite diário"' in block


def test_google_images_ui_has_copyright_warning_and_source_unblocked():
    assert "GOOGLE_IMAGES_COPYRIGHT_WARNING" in MAIN
    assert 'UNAVAILABLE_VIDEO_SOURCES = {"remotion", "music_clips"}' in MAIN
    assert 'channel_video_source_storage(wide_style_label) == "google_images"' in MAIN
