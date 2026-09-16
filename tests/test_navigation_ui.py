from pathlib import Path


MAIN_SOURCE = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")


def test_automation_is_an_expander_with_youtube_child_page():
    assert 'automation_items = [' in MAIN_SOURCE
    assert '("Automação Youtube", ":material/schedule:", "Automação Youtube")' in MAIN_SOURCE
    assert 'def render_nav_children(parent: str, children: list[tuple[str, str, str]]):' in MAIN_SOURCE
    assert '"Automação Youtube": render_automation' in MAIN_SOURCE
    assert 'st.title("Automação Youtube")' in MAIN_SOURCE


def test_navigation_highlights_only_the_exact_current_item():
    assert 'type="primary" if is_nav_item_active(target) else "secondary"' in MAIN_SOURCE
    assert 'return current_path == nav_paths.get(target)' in MAIN_SOURCE
    assert '[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] { background:#7c3aed !important;' in MAIN_SOURCE
    assert '[data-testid="stSidebar"] [data-testid="stExpander"] summary strong' not in MAIN_SOURCE
    assert 'expanded=has_active_descendant(target)' in MAIN_SOURCE
    assert 'startsWith' not in MAIN_SOURCE


def test_navigation_assigns_distinct_paths_to_parent_and_child():
    assert '"Automação": "/automacao"' in MAIN_SOURCE
    assert '"Automação Youtube": "/automacao/youtube"' in MAIN_SOURCE
    assert '"Pipeline Música": "/pipeline-musica"' in MAIN_SOURCE
    assert '"Music Backlog": "/pipeline-musica/backlog"' in MAIN_SOURCE


def test_navigation_persists_active_page_in_query_params_across_refreshes():
    assert 'query_page = str(st.query_params.get("page") or "").strip()' in MAIN_SOURCE
    assert 'stored_page = query_page or str(st.session_state.get("page", "Início"))' in MAIN_SOURCE
    assert 'st.query_params["page"] = current_page' in MAIN_SOURCE
    assert 'st.query_params["page"] = target' in MAIN_SOURCE


def test_youtube_navigation_labels_and_legacy_aliases_are_preserved():
    assert '("Canais YouTube", ":material/ondemand_video:", "Canais YouTube")' in MAIN_SOURCE
    assert '("Blueprints Youtube", ":material/library_books:", "Blueprints Youtube")' in MAIN_SOURCE
    assert '"Canais YouTube": render_channels' in MAIN_SOURCE
    assert '"Blueprints Youtube": render_blueprints' in MAIN_SOURCE
    assert '"Canais": "Canais YouTube"' in MAIN_SOURCE
    assert '"Canais Youtube": "Canais YouTube"' in MAIN_SOURCE
    assert '("Automação Youtube", ":material/schedule:", "Automação Youtube")' in MAIN_SOURCE


def test_settings_children_include_logs_between_notifications_and_api():
    settings_start = MAIN_SOURCE.index("settings_items = [")
    settings_end = MAIN_SOURCE.index("]", settings_start)
    settings_block = MAIN_SOURCE[settings_start:settings_end]
    assert '("Notificações", ":material/notifications:", "Notificações")' in settings_block
    assert '("Logs", ":material/description:", "Logs")' in settings_block
    assert '("Configuração API", ":material/settings:", "Configuração API")' in settings_block
    assert settings_block.index('("Notificações"') < settings_block.index('("Logs"') < settings_block.index('("Configuração API"')
    assert '"Contas Google": render_google_accounts' in MAIN_SOURCE
    assert '"Configuração API": render_settings' in MAIN_SOURCE
    assert '"Notificações": render_notifications' in MAIN_SOURCE
    assert '"Logs": render_logs' in MAIN_SOURCE
    assert '"Configurações Técnicas": "Configuração API"' in MAIN_SOURCE


def test_models_ai_has_meta_tutorial_renderer():
    assert '("Meta", ":material/menu_book:", "Meta")' in MAIN_SOURCE
    assert '"Meta": render_models_ai_tutorial' in MAIN_SOURCE
    assert 'https://github.com/gyoridavid/ai_agents_az/blob/main/episode_8/guide-instagram.md' in MAIN_SOURCE
    assert 'ROOT / "seed" / "references" / "guide-instagram.md"' in MAIN_SOURCE


def test_google_configuration_keeps_account_fields_and_api_page_does_not_duplicate_them():
    google_start = MAIN_SOURCE.index("def render_google_accounts(")
    settings_start = MAIN_SOURCE.index("def render_settings():")
    notifications_start = MAIN_SOURCE.index("def render_notifications():")
    google_page = MAIN_SOURCE[google_start:settings_start]
    api_page = MAIN_SOURCE[settings_start:notifications_start]
    assert "INNERTUBE_API_KEY" in google_page
    assert "sessionInfo" in google_page
    assert "google_global_api_settings_form" in google_page
    assert "google_page_youtube_api_key" in google_page
    assert "Configuração Global: YouTube Data API v3 (API Key)" in google_page
    assert "Directamente via OAuth das Contas Google/YouTube cadastradas" in google_page
    assert 'YouTube OAuth Client ID' not in api_page
    assert 'YouTube OAuth Client Secret' not in api_page
    assert 'YouTube Data API Key' not in api_page


def test_tutorial_reference_is_packaged_and_contains_meta_setup_sections():
    tutorial_path = Path(__file__).resolve().parents[1] / "seed" / "references" / "guide-instagram.md"
    tutorial = tutorial_path.read_text(encoding="utf-8")
    assert "# Setting up Instagram for automations with n8n" in tutorial
    assert "## Convert the Instagram account to a professional account" in tutorial
    assert "### 3. Create a Facebook application" in tutorial
    assert "pages_show_list" in tutorial
    assert "instagram_content_publish" in tutorial
    assert "https://github.com/gyoridavid/ai_agents_az/blob/main/episode_8/guide-instagram.md" in tutorial
    assert "Join our Skool community" not in tutorial
    assert "Be part of a growing community" not in tutorial


def test_ai_influencers_is_visible_with_real_character_and_content_renderers():
    assert '("AI Influencers", ":material/smart_toy:", "AI Influencers")' in MAIN_SOURCE
    assert 'with st.expander(ui_text(label, ui_language), expanded=has_active_descendant(target), icon=icon):' in MAIN_SOURCE
    assert '"Personagens": lambda: render_ai_influencer_characters' in MAIN_SOURCE
    assert '"Geração de Conteúdo IA": lambda: render_ai_influencer_content' in MAIN_SOURCE
    assert '("Motion Control", ":material/motion_photos_on:", "Motion Control")' in MAIN_SOURCE
    assert '"Motion Control": lambda: render_motion_control' in MAIN_SOURCE
    assert '("UGC Products", ":material/shopping_bag:", "UGC Products")' in MAIN_SOURCE
    assert '"UGC Products": lambda: render_ugc_products' in MAIN_SOURCE
    assert '("Models AI", ":material/smart_toy:", "Models AI")' not in MAIN_SOURCE


def test_edition_contains_media_download_page_and_controls():
    assert '("Download Mídia", ":material/download:", "Download Mídia")' in MAIN_SOURCE
    assert '"Download Mídia": render_media_download' in MAIN_SOURCE
    assert 'def render_media_download()' in MAIN_SOURCE
    for label in ("URLs para descarregar", "Tipo de mídia", "Qualidade", "Contentor", "Formato de áudio", "Permitir playlist", "Descarregar legendas", "Incorporar metadados", "Iniciar Download", "Histórico de downloads"):
        assert label in MAIN_SOURCE
    assert 'from hermes_ui.media_downloader import' in MAIN_SOURCE


def test_api_keys_contains_material_sources_expander_with_multi_key_controls():
    settings_start = MAIN_SOURCE.index("def render_settings():")
    settings_page = MAIN_SOURCE[settings_start:]
    material_sources_page = MAIN_SOURCE[MAIN_SOURCE.index("def render_material_source_api_keys("):]
    tabs_literal = 'api_keys_tab, upload_api_keys_tab, subtitles_tab, ai_influencers_tab, voice_test_tab = render_localized_tabs(["API Keys", "API Keys Upload", "Legendas", "AI Influencers", "Teste de Voz"])'
    assert tabs_literal in settings_page
    assert 'with material_sources_tab:' not in settings_page
    assert 'render_material_source_api_keys(settings, embedded=True)' in settings_page
    assert 'with ai_influencers_tab:' in settings_page
    assert 'render_ai_influencers_api_status(effective_settings)' in settings_page
    assert 'with tiktok_api_tab:' in settings_page
    assert 'render_tiktok_api_cards(settings)' in settings_page
    assert 'with st.expander("Imagem e Video Montagem/MoviePy", expanded=False):' in material_sources_page
    assert 'with st.expander("Imagem e Video IA", expanded=False):' in MAIN_SOURCE
    tiktok_page = MAIN_SOURCE[MAIN_SOURCE.index("def render_tiktok_api_cards("):]
    for label in ("API Tiktok", "Adicionar nova API", "TikTok Client ID", "TikTok Client Secret", "Testar chamada API", "Apagar card"):
        assert label in tiktok_page
    for label in ("Imagem e Video Montagem/MoviePy", "Adicionar fonte de materiais", "Configurar Nova Fonte de Materiais"):
        assert label in material_sources_page


def test_language_picker_uses_native_layout_without_touching_streamlit_toolbar():
    assert '"Language"' in MAIN_SOURCE
    assert "ui_language_menu_label" in MAIN_SOURCE
    assert "LANGUAGE_FLAG_DATA_URIS" in MAIN_SOURCE
    assert 'top_language_code_selector' in MAIN_SOURCE
    assert 'st.popover' not in MAIN_SOURCE
    assert 'stAppDeployButton' not in MAIN_SOURCE
    assert 'stMainMenu' not in MAIN_SOURCE
    assert 'right:1.5rem' not in MAIN_SOURCE


def test_supabase_tutorial_is_packaged_and_added_to_ai_influencers():
    tutorial_path = Path(__file__).resolve().parents[1] / "seed" / "references" / "guide-supabase.md"
    tutorial = tutorial_path.read_text(encoding="utf-8")
    assert "# Guia para criar e configurar uma conta Supabase" in tutorial
    assert "## 1. Criar as tabelas da base de dados" in tutorial
    assert "### Criar a tabela `plans`" in tutorial
    assert "### Criar a tabela `posts`" in tutorial
    assert "## 2. Criar o bucket de Storage" in tutorial
    assert "instagram-images" in tutorial
    assert "Join our Skool community" not in tutorial
    assert "Be part of a growing community" not in tutorial
    assert '("Tutorial Supabase", ":material/storage:", "Tutorial Supabase")' in MAIN_SOURCE
    assert '"Supabase": render_supabase_tutorial' in MAIN_SOURCE
    assert 'guide-supabase.md' in MAIN_SOURCE


def test_growth_pages_keep_other_placeholders_and_render_youtube_auditor():
    assert 'def render_growth_youtube():' in MAIN_SOURCE
    assert '"Growth Youtube": render_growth_youtube' in MAIN_SOURCE
    assert 'Canal a analisar' in MAIN_SOURCE
    assert 'Nota geral do canal' in MAIN_SOURCE
    assert '("Facebook Pages", ":material/analytics:", "Facebook Pages")' in MAIN_SOURCE
    assert '("Growth Bilibili", ":material/analytics:", "Growth Bilibili")' in MAIN_SOURCE
    assert '"Facebook Pages": render_growth_facebook_pages' in MAIN_SOURCE
    assert '"Growth Bilibili": render_growth_bilibili' in MAIN_SOURCE


def test_youtube_cards_format_large_counts_with_pt_separators():
    assert 'def _format_channel_count(value: Any) -> str:' in MAIN_SOURCE
    assert 'f"{int(value):,}".replace(",", ".")' in MAIN_SOURCE
    assert 'st.metric("Visualizações", _format_channel_count(channel.get("view_count")))' in MAIN_SOURCE


def test_youtube_cards_have_small_blue_open_channel_button():
    assert 'st.link_button("Abrir canal", channel_url, type="primary", width="content")' in MAIN_SOURCE
    assert 'channel.get("url") or ""' in MAIN_SOURCE


def test_tiktok_cards_use_shared_large_count_formatter():
    assert 'return f"{int(normalized):,}".replace(",", ".")' in MAIN_SOURCE
    assert 'st.metric("Seguidores", format_metric_number(channel.get("subscriber_count")))' in MAIN_SOURCE
    assert 'st.metric("Vídeos", format_metric_number(channel.get("video_count")))' in MAIN_SOURCE
