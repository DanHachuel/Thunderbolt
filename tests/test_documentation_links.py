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
    # 1.0.52 — a página «Documentação» deixou o menu lateral; os tutoriais
    # passaram a ser aba INTERNA da página Configurações (render_settings).
    assert "with documentation_tab:" in MAIN_SOURCE
    assert "render_documentation_pages" not in MAIN_SOURCE  # função morta removida
    assert "top_pages" in MAIN_SOURCE and '("Documentação", ":material/menu_book:"' not in MAIN_SOURCE
    # os 7 tutoriais continuam registados como sub-tabs da aba
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
