"""1.0.56 — correção de roteamento: Documentação é sub-item do menu lateral.

A 1.0.53 tinha movido os tutoriais para uma aba INTERNA da página
«Configuração API» (render_settings) — o cliente exigia o contrário: a
«Documentação» é sub-item AUTÓNOMO do grupo «Configurações» no menu lateral
(ao lado de MCP, Notificações, Logs, Dependências e Configuração API), com
página própria: título «Documentação» + as 7 abas horizontais de tutoriais
(st.tabs), conteúdo e formato intactos.
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

SETTINGS_ORDER = (
    '("MCP", ":material/hub:"',
    '("Notificações", ":material/notifications:"',
    '("Logs", ":material/description:"',
    '("Dependências", ":material/extension:"',
    '("Configuração API", ":material/settings:"',
    '("Documentação", ":material/menu_book:"',
)


def test_documentation_is_sidebar_subitem_of_settings_group():
    """«Documentação» vive no grupo «Configurações», depois de Configuração API."""
    nav = MAIN_SOURCE.split("def main():", 1)[1]
    settings_block = nav.split("    settings_items = [", 1)[1].split("    ]", 1)[0]
    assert '("Documentação", ":material/menu_book:", "Documentação")' in settings_block
    # ordem pedida: MCP, Notificações, Logs, Dependências, Configuração API, Documentação
    positions = [settings_block.index(item) for item in SETTINGS_ORDER]
    assert positions == sorted(positions)
    # alimenta o grupo «Configurações» (não é página top-level)
    assert '"Configurações": settings_items' in nav
    top_block = nav.split("    top_pages = [", 1)[1].split("    ]", 1)[0]
    assert '("Documentação"' not in top_block


def test_documentation_page_renders_title_and_seven_tutorial_tabs():
    """A página própria: título «Documentação» + as 7 abas de tutoriais."""
    page = MAIN_SOURCE.split("def render_documentation_pages", 1)[1].split("def main():", 1)[0]
    assert 'st.title("Documentação")' in page
    assert "tutorial_subtabs = render_localized_tabs([" in page
    assert "tutorial_renderers = [" in page
    for label in TUTORIAL_LABELS:
        assert f'"{label}"' in page, f"aba {label} desapareceu"
    for renderer in (
        "render_models_ai_tutorial,",
        "render_supabase_tutorial,",
        'render_niche_tutorial("kaggle")',
        'render_niche_tutorial("apify")',
        "render_youtube_frontend_upload_tutorial,",
        "render_google_oauth_tutorial,",
        "render_youtube_data_api_key_tutorial,",
    ):
        assert renderer in page
    # roteada no router e com rota própria
    assert '"Documentação": render_documentation_pages,' in MAIN_SOURCE
    assert '"Documentação": "/configuracoes/documentacao"' in MAIN_SOURCE


def test_documentation_is_not_inside_settings_page():
    """Regressão da 1.0.53: nada de aba «Documentação» na Configuração API."""
    settings = MAIN_SOURCE.split("def render_settings():", 1)[1].split("def _render_telegram_notification_settings", 1)[0]
    assert "documentation_tab" not in settings
    assert "with documentation_tab:" not in settings
    assert '"Documentação"' not in settings
    assert 'voice_test_tab, browser_proxy_tab = render_localized_tabs(["API Keys", "API Keys Upload", "Legendas", "Motor", "FFmpeg", "AI Influencers", "Test Upload Videos", "Teste de Voz", "Navegador e Proxies"])' in settings


def test_root_pipeline_and_navigation_keep_working():
    """A navegação principal fica intacta (nenhuma rota quebrada)."""
    for label in ("Início", "Automação", "Pipeline Vídeos", "Configurações", "Growth", "Edição"):
        assert f'("{label}", ":material/' in MAIN_SOURCE
    assert "renderers.get(current_page, render_dashboard)()" in MAIN_SOURCE
    # sub-itens de Configurações continuam roteados
    assert '"Configurações": lambda: render_edit_placeholder' in MAIN_SOURCE
    assert '"Configuração API": render_settings' in MAIN_SOURCE
    assert '"MCP": render_mcp' in MAIN_SOURCE
    assert '"Notificações": render_notifications' in MAIN_SOURCE
    assert '"Logs": render_logs' in MAIN_SOURCE
    assert '"Dependências": render_dependencies_page' in MAIN_SOURCE
    # zero código morto das organizações anteriores
    assert "documentation_items" not in MAIN_SOURCE
    assert "tutorial_items" not in MAIN_SOURCE
    assert '"/documentacao' not in MAIN_SOURCE
