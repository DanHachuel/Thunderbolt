from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
UI = (ROOT / "app" / "influencers_ui.py").read_text(encoding="utf-8")
SCHEMA = (ROOT / "seed" / "references" / "ai_influencers_schema.sql").read_text(encoding="utf-8")


def test_api_configuration_adds_ai_influencers_tab_and_supabase_card():
    assert 'render_localized_tabs(["API Keys", "API Keys Upload", "Legendas", "FFmpeg", "AI Influencers", "Teste de Voz"])' in MAIN
    assert 'st.subheader("AI Influencers")' in MAIN
    assert 'Estado do backend usado por Personagens e Geração de Conteúdo IA. O selector e as credenciais são editados nesta aba, em Banco de Dados Influencers.' in MAIN
    assert 'key="settings_influencer_db_backend"' in MAIN
    assert 'st.subheader("Supabase")' in MAIN
    assert 'with st.form("influencer_database_settings_form"):' in MAIN
    assert 'Supabase Project URL' in MAIN
    assert 'Supabase API key' in MAIN
    assert 'Supabase Storage bucket' not in MAIN
    assert 'SQLite ficheiro local' not in MAIN
    assert 'SQLite local funciona sem credenciais externas' not in MAIN
    assert 'Se o selector estiver em Supabase mas faltar qualquer credencial, o backend activo permanece SQLite.' in MAIN
    assert '"influencer_db_backend": influencer_db_backend' in MAIN
    assert '"influencer_supabase_url": influencer_supabase_url.strip()' in MAIN
    assert '"influencer_supabase_key": influencer_supabase_key.strip()' in MAIN
    assert '"influencer_sqlite_path": influencer_sqlite_path.strip()' not in MAIN
    assert 'test_backend_clicked = st.form_submit_button("Testar ligação do backend"' in MAIN
    assert 'save_backend_clicked = st.form_submit_button("Guardar configuração do backend"' in MAIN
    assert 'render_ai_influencers_api_status(effective_settings)' in MAIN
    assert 'A configuração do backend AI Influencers, incluindo o selector entre SQLite e Supabase e as credenciais, está na aba AI Influencers.' not in MAIN


def test_ai_influencers_selector_is_immediately_below_backend_state_caption():
    block_start = MAIN.index('    with ai_influencers_tab:')
    block_end = MAIN.index('    with voice_test_tab:', block_start)
    block = MAIN[block_start:block_end]
    caption_position = block.index('st.caption("Estado do backend usado por Personagens e Geração de Conteúdo IA.')
    selector_position = block.index('st.selectbox(\n            "Backend da base de dados de AI Influencers"')
    assert caption_position < selector_position
    assert 'st.subheader("Supabase")' in block
    assert block.index('st.subheader("Supabase")') > selector_position


def test_ai_influencers_routes_are_real_and_workflows_are_standalone():
    assert '"Personagens": lambda: render_ai_influencer_characters' in MAIN
    assert '"Geração de Conteúdo IA": lambda: render_ai_influencer_content' in MAIN
    assert 'language_options=VIDEO_LANGUAGE_SELECTION_OPTIONS' in MAIN
    assert 'language_formatter=video_language_label' in MAIN
    assert 'language_normalizer=normalize_video_language' in MAIN
    assert '"Motion Control": lambda: render_motion_control' in MAIN
    assert '"UGC Products": lambda: render_ugc_products' in MAIN
    assert '("Motion Control", ":material/motion_photos_on:", "Motion Control")' in MAIN
    assert 'st.tabs(["Novo personagem", "Personagens criados"])' in UI
    assert 'with new_character_tab:' in UI
    assert 'with created_characters_tab:' in UI
    assert 'with st.expander(f"Card do personagem · {selected.get(\'name\') or selected_id}", expanded=False):' in UI
    created_position = UI.index('with created_characters_tab:')
    card_position = UI.index('with st.expander(f"Card do personagem · {selected.get(\'name\') or selected_id}", expanded=False):')
    assets_position = UI.index('st.subheader(f"Assets de referência · {selected.get(\'name\') or selected_id}")')
    assert created_position < card_position < assets_position
    assert 'st.tabs(["Imagens", "Vídeos"])' in UI
    assert 'def render_motion_control(settings: dict[str, Any])' in UI
    assert 'def render_ugc_products(settings: dict[str, Any])' in UI
    assert 'Vídeo original de movimento' in UI
    assert 'Imagem de referência' in UI
    assert 'Prompt (opcional)' in UI
    assert 'Imagem do produto' in UI
    assert 'Roteiro de vídeo' in UI
    assert 'upload_kie_file' in UI
    assert 'telegram": False' in UI
    assert 'social_publish": False' in UI
    assert 'language_options: list[str] | None = None' in UI
    assert 'language = st.selectbox(' in UI
    assert 'edit_language = st.selectbox(' in UI
    assert 'format_func=language_formatter' in UI
    assert 'st.text_input("Idioma"' not in UI
    assert 'accept_multiple_files=True' in UI
    assert '".md"' in UI and '".json"' in UI
    assert 'st.file_uploader' in UI


def test_new_character_form_clears_fields_after_save():
    assert 'with st.form("influencer_create_form", clear_on_submit=True):' in UI
    assert 'key="influencer_new_name"' in UI
    assert 'key="influencer_new_language"' in UI
    assert 'key="influencer_new_instagram_id"' in UI
    assert 'key="influencer_new_bio"' in UI
    assert 'key="influencer_new_assets"' in UI


def test_video_ui_uses_active_video_pool_instead_of_hardcoded_veo():
    assert '_provider_options(settings, "video")' in UI
    assert 'media_cards_for_pool(settings, pool)' in UI
    assert 'Provider / modelo de vídeo' in UI
    assert 'Não existem providers activos no pool de vídeo' in UI
    assert 'Veo 3.1' not in UI


def test_ugc_products_uses_generic_video_provider_and_model():
    block = UI.split("def render_ugc_products", 1)[1].split("def render_ai_influencer_content", 1)[0]
    assert "video_cards = _workflow_provider_cards(settings, provider=None)" in block
    assert "Provider / modelo de vídeo" in block
    assert "upload_kie_file" not in block
    assert "KIE AI com modelo VEO3" not in block
    assert "clips VEO3" not in block


def test_ugc_products_has_character_product_generation_and_ready_media_controls():
    block = UI.split("def render_ugc_products", 1)[1].split("def render_ai_influencer_content", 1)[0]
    assert '"Personagem (opcional)"' not in block
    assert '"Personagem"' in block
    assert '"name": ""' in block
    assert 'influencer_options = [""]' in block
    assert "influencers[0]" in block
    for label in ("Personagem", "Nome do produto", "Informação do Produto ou link do produto", "Gerar roteiro com IA", "Gerar Foto", "Gerar Video", "Duração de cada clip (MM:SS)", "Midias Prontas"):
        assert label in block
    assert 'st.button("Gerar Mídia (Foto/Vídeo)"' in block
    assert 'st.radio("Geração"' not in block
    assert 'value="1:20"' in block
    assert 'key="ugc_products_duration_text"' in block
    assert 'if generation_mode == "Gerar Foto":' in block
    assert 'else:\n            video_provider_id = st.selectbox("Provider / modelo de vídeo"' in block
    assert '"aspect_ratio": "9:16"' in block
    assert 'icon=":material/edit:"' in block
    assert "st.download_button(\"Download\"" in block


def test_ai_content_history_renders_downloadable_cards_for_images_and_videos():
    history = UI.split("def _render_content_history", 1)[1].split("def _store_uploaded_file", 1)[0]

    assert "with st.container(border=True):" in history
    assert 'if artifact.is_file() and content_type == "image"' in history
    assert 'elif artifact.is_file() and content_type == "video"' in history
    assert 'f"Descarregar {type_label.casefold()}"' in history
    assert 'key=f"influencer_content_download_{content_type}_{content_id}"' in history


def test_supabase_schema_contains_legacy_entities_and_content_indexes():
    for table in ("influencers", "influencer_assets", "influencer_weekly_plans", "influencer_content"):
        assert f"create table if not exists public.{table}" in SCHEMA
    assert "unique (influencer_id, sha256)" in SCHEMA
    assert "idx_influencer_content_state" in SCHEMA
    assert "enable row level security" in SCHEMA
