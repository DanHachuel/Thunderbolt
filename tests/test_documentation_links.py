from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def test_documentation_renderers_do_not_expose_added_source_buttons():
    block = MAIN_SOURCE.split("def render_models_ai_tutorial():", 1)[1].split("def render_mcp():", 1)[0]
    assert "Abrir fonte original" not in block
    assert "Abrir referência técnica" not in block
    assert "Abrir documento fonte" not in block
    assert "drive.google.com" not in block
    assert "ai_agents_az" not in block


def test_added_drive_and_source_references_are_removed_without_removing_useful_links():
    data_api = (ROOT / "seed/references/tutorial-youtube-data-api-key.md").read_text(encoding="utf-8")
    instagram = (ROOT / "seed/references/guide-instagram.md").read_text(encoding="utf-8")
    supabase = (ROOT / "seed/references/guide-supabase.md").read_text(encoding="utf-8")
    frontend = (ROOT / "seed/references/youtube-video-upload-frontend.md").read_text(encoding="utf-8")

    assert "Google Drive" not in data_api
    assert "drive.google.com" not in data_api
    assert "# Tutorial YouTube Data API Key (Public Data)" not in data_api
    assert "https://console.cloud.google.com/" in data_api
    assert "https://developers.google.com/youtube/v3" in data_api

    assert "Source:" not in instagram
    assert "Fonte original:" not in supabase
    assert "## Referência técnica" not in frontend
    assert "https://www.facebook.com/pages/create" in instagram
    assert "https://developers.facebook.com/apps" in instagram


def test_documentation_renderers_keep_local_tutorial_content():
    assert "st.markdown(tutorial_content, unsafe_allow_html=True)" in MAIN_SOURCE
    assert "st.markdown(tutorial_content, unsafe_allow_html=False)" in MAIN_SOURCE
    assert "st.markdown(tutorial_body(tutorial_kind, ui_language), unsafe_allow_html=False)" in MAIN_SOURCE


def test_documentation_parent_page_uses_real_tutorial_renderer():
    # 1.0.56 — correcção de roteamento: a Documentação voltou a ser sub-item
    # AUTÓNOMO do grupo «Configurações» no menu lateral, com página própria
    # (render_documentation_pages: título + as 7 abas de tutoriais). A 1.0.53
    # tinha errado ao metê-la como aba interna da Configuração API.
    assert '"Documentação": render_documentation_pages,' in MAIN_SOURCE
    assert "def render_documentation_pages" in MAIN_SOURCE
    assert '("Documentação", ":material/menu_book:", "Documentação")' in MAIN_SOURCE
    assert "with documentation_tab:" not in MAIN_SOURCE  # não vive dentro da Configuração API
    # os 7 tutoriais continuam registados como sub-tabs da página
    assert '"Meta", "Supabase", "Kaggle", "Apify", "YouTube Video-Upload Frontend",' in MAIN_SOURCE.replace("\n", " ")
    assert '"OAuth do Google", "YouTube Data API Key (Public Data)",' in MAIN_SOURCE.replace("\n", " ")
    for filename in (
        "guide-instagram.md",
        "guide-supabase.md",
        "tutorial-oauth-google.md",
        "youtube-video-upload-frontend.md",
        "tutorial-youtube-data-api-key.md",
    ):
        assert (ROOT / "seed" / "references" / filename).is_file()
