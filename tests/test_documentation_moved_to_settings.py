"""1.0.52 — tutoriais mudaram do menu lateral para a página Configurações.

A aba «Documentação» e seus sub-menus (Meta, Supabase, Kaggle, Apify, YouTube
Video-Upload Frontend, OAuth do Google, YouTube Data API Key) saíram da
sidebar; o mesmo `st.tabs` passa a viver como aba INTERNA da página
Configurações (`render_settings`), com o conteúdo dos tutoriais intacto.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

TUTORIAL_LABELS = (
    "Meta",
    "Supabase",
    "Kaggle",
    "Apify",
    "YouTube Video-Upload Frontend",
    "OAuth do Google",
    "YouTube Data API Key (Public Data)",
)


def test_sidebar_has_no_documentation_page():
    """A aba «Documentação» e os sub-itens desapareceram do menu lateral."""
    nav = MAIN_SOURCE.split("def main():", 1)[1]
    assert '("Documentação", ":material/menu_book:", "Documentação")' not in nav
    for label in TUTORIAL_LABELS:
        assert f'("{label}", ":material:' not in nav, f"{label} continua no menu lateral"
    assert '"/documentacao' not in MAIN_SOURCE  # nenhuma rota antiga
    assert '"Documentação": documentation_items' not in MAIN_SOURCE
    assert '"Tutoriais": tutorial_items' not in MAIN_SOURCE


def test_documentation_tabs_live_inside_settings_page():
    """Os tutoriais são aba «Documentação» dentro de render_settings, com as
    7 sub-tabs e os renderers reais (conteúdo intacto)."""
    settings = MAIN_SOURCE.split("def render_settings():", 1)[1].split("def _render_telegram_notification_settings", 1)[0]
    assert 'documentation_tab' in settings  # a aba nova na lista de tabs
    assert "with documentation_tab:" in settings
    assert "tutorial_subtabs = render_localized_tabs([" in settings
    assert "tutorial_renderers = [" in settings
    assert "render_models_ai_tutorial," in settings
    assert "render_supabase_tutorial," in settings
    assert 'render_niche_tutorial("kaggle")' in settings
    assert 'render_niche_tutorial("apify")' in settings
    assert "render_youtube_frontend_upload_tutorial," in settings
    assert "render_google_oauth_tutorial," in settings
    assert "render_youtube_data_api_key_tutorial," in settings
    for label in TUTORIAL_LABELS:
        assert f'"{label}"' in settings, f"sub-tab {label} desapareceu"


def test_dead_navigation_code_is_removed():
    """Limpeza: a página «Documentação» e os seus itens de menu morreram."""
    assert "render_documentation_pages" not in MAIN_SOURCE
    assert "documentation_items" not in MAIN_SOURCE
    assert "tutorial_items" not in MAIN_SOURCE
    assert "def render_documentation_pages" not in MAIN_SOURCE


def test_root_pipeline_and_navigation_keep_working():
    """A navegação principal fica intacta (nenhuma rota quebrada)."""
    for label in ("Início", "Automação", "Pipeline Vídeos", "Configurações", "Growth", "Edição"):
        assert f'("{label}", ":material/' in MAIN_SOURCE
    assert "renderers.get(current_page, render_dashboard)()" in MAIN_SOURCE
    # Configurações continua a ter os seus sub-itens e a nova aba no router
    assert '"Configurações": lambda: render_edit_placeholder' in MAIN_SOURCE
    assert '"Logs": render_logs' in MAIN_SOURCE
    assert '"MCP": render_mcp' in MAIN_SOURCE
    assert '"Configuração API": render_settings' in MAIN_SOURCE
    assert '"Dependências": render_dependencies_page' in MAIN_SOURCE
