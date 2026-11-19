"""Hubs de navegação: submenus da sidebar -> botões coloridos no topo (1.1.08).

Pedido do utilizador: um componente reutilizável de "hub" (botões coloridos no
topo da página) aplicado a Growth, Canais/Perfis, Blueprints, Niche Finder,
Edição, Pipeline Vídeos e Pipeline Música, limpando os submenus desses grupos na
sidebar. Cor roxa `#8a2be2` por omissão; cores específicas quando informadas
(Growth mantém as cores de cada plataforma).

Metade dos testes é de CONTRATO (skill testes-contrato) sobre o AST/fonte; a
outra metade CORRE o hub com o Streamlit substituído, para provar que cada botão
chama mesmo o renderizador certo — e não apenas que uma string existe.
"""

import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

# Os 7 hubs pedidos: página principal -> scope.
EXPECTED_HUB_PAGES = {
    "Growth": "growth",
    "Canais/Perfis (Vídeos)": "canais-perfis",
    "Blueprints": "blueprints",
    "Niche Finder": "niche-finder",
    "Edição": "edicao",
    "Pipeline Vídeos": "pipeline-videos",
    "Pipeline Música": "pipeline-musica",
}

# O que cada hub tem de oferecer (rótulo do botão -> página interna de sempre).
EXPECTED_HUB_BUTTONS = {
    "Growth": ["Youtube", "TikTok", "Instagram", "Facebook Pages", "Bilibili"],
    "Canais/Perfis (Vídeos)": ["YouTube", "TikTok", "Instagram", "Facebook Pages"],
    "Blueprints": ["Youtube", "Música", "Thumbnails", "Brandings", "Prompt-Masters", "Facebook"],
    "Niche Finder": ["Kaggle", "Apify"],
    "Edição": ["Limpador", "Cortes", "Editor Python", "Download Mídia"],
    # Pedido explícito: botões "Vídeos" e "Shorts", títulos internos intactos.
    "Pipeline Vídeos": ["Vídeos", "Shorts", "Backlog", "Roteiros", "Thumbnails", "Upload", "Update Youtube"],
    "Pipeline Música": ["Músicas", "Backlog", "Vozes", "Upload"],
}

DEFAULT_COLOR = "#8a2be2"


# --------------------------------------------------------------------------
# 1. O componente existe e é genérico
# --------------------------------------------------------------------------

def _hub_function() -> ast.FunctionDef:
    tree = ast.parse(MAIN_SOURCE)
    node = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "render_hub_navigation"),
        None,
    )
    assert node is not None, "render_hub_navigation não existe em app/main.py"
    return node


def test_reusable_hub_component_exists_with_the_requested_signature():
    node = _hub_function()
    positional = [arg.arg for arg in node.args.posonlyargs + node.args.args]
    assert positional[:3] == ["tabs_list", "active_tab", "colors"], positional
    # `colors` tem de ser opcional (None = roxo por omissão)
    assert node.args.defaults, "colors precisa de um valor por omissão"
    assert any(
        isinstance(default, ast.Constant) and default.value is None for default in node.args.defaults
    ), "colors tem de aceitar None"
    assert node.args.kwonlyargs, "o componente precisa de scope/state_key por keyword"
    assert {arg.arg for arg in node.args.kwonlyargs} >= {"scope", "state_key"}


def test_hub_component_paints_every_button_and_returns_the_active_renderer():
    node = _hub_function()
    source = ast.get_source_segment(MAIN_SOURCE, node)
    assert source is not None
    assert "DEFAULT_HUB_COLOR" in source
    assert "palette = {" in source
    # o renderizador da aba activa é devolvido a quem chama
    assert "return renderer" in source
    # clique -> um único rerun, e clicar na aba activa não dispara nada
    assert "if tab_key != active:" in source
    reruns = [
        inner for inner in ast.walk(node)
        if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute) and inner.func.attr == "rerun"
    ]
    assert len(reruns) == 1, f"o hub faz {len(reruns)} reruns; só pode haver um por clique"


def test_hub_css_is_scoped_per_group_and_cannot_paint_other_buttons():
    css_start = MAIN_SOURCE.index("def _hub_nav_css(")
    css_source = MAIN_SOURCE[css_start:MAIN_SOURCE.index("def render_hub_navigation(")]
    assert '[data-testid="stColumn"]:has(.tb-hub-chip-{scope}-{tab_key}) button' in css_source
    assert ".tb-hub-chip { display:none; }" in css_source
    # fundos muito escuros levam texto branco + borda clara (contraste)
    assert "DARK_HUB_COLORS" in css_source
    assert "border:1px solid #ffffff !important;" in css_source
    # a aba activa continua a ser destacada, como na Automação
    assert ".tb-hub-chip.is-active" in css_source
    assert "border:2px solid #ffffff !important" in css_source


def test_hub_component_has_no_blocking_loop_or_sleep():
    node = _hub_function()
    for inner in ast.walk(node):
        if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute):
            assert inner.func.attr != "sleep", "espera bloqueante proibida no hub"
        assert not isinstance(inner, (ast.While, ast.AsyncFor)), "laço bloqueante proibido no hub"


# --------------------------------------------------------------------------
# 2. Os 7 hubs pedidos
# --------------------------------------------------------------------------

HUB_SPEC_VARIABLES = {
    "Growth": "GROWTH_HUB_SPECS",
    "Canais/Perfis (Vídeos)": "CHANNEL_PROFILE_HUB_SPECS",
    "Blueprints": "BLUEPRINT_HUB_SPECS",
    "Niche Finder": "NICHE_FINDER_HUB_SPECS",
    "Edição": "EDITION_HUB_SPECS",
    "Pipeline Vídeos": "PIPELINE_VIDEO_HUB_SPECS",
    "Pipeline Música": "PIPELINE_MUSIC_HUB_SPECS",
}


@pytest.mark.parametrize("page,scope", sorted(EXPECTED_HUB_PAGES.items()))
def test_page_has_a_hub_with_the_requested_buttons(page, scope):
    assert f'("{page}", "{scope}"' in MAIN_SOURCE, f"{page} não tem hub com scope {scope}"
    variable = HUB_SPEC_VARIABLES[page]
    block = MAIN_SOURCE.split(f"{variable} = [", 1)[1].split("\n]", 1)[0]
    for label in EXPECTED_HUB_BUTTONS[page]:
        assert f'"{label}"' in block, f"{page}: botão {label} em falta"


def test_growth_keeps_the_platform_colors():
    colors = MAIN_SOURCE.split("GROWTH_HUB_COLORS = {", 1)[1].split("}", 1)[0]
    for key, color in (
        ("growth-youtube", "#ff0000"),
        ("growth-tiktok", "#000000"),
        ("growth-instagram", "linear-gradient(45deg,#f09433 0%,#e6683c 25%,#dc2743 50%,#cc2366 75%,#bc1888 100%)"),
        ("growth-facebook-pages", "#1877f2"),
        ("growth-bilibili", "#00a1d6"),
    ):
        assert f'"{key}": "{color}"' in colors, key


def test_every_hub_that_is_not_growth_falls_back_to_the_default_purple():
    """Colors None -> roxo #8a2be2 em todos os botões (nada de aba sem cor)."""
    pages_block = MAIN_SOURCE.split("HUB_PAGES: list[", 1)[1].split("\n]\n", 1)[0]
    for page, scope in EXPECTED_HUB_PAGES.items():
        if page == "Growth":
            assert f'("{page}", "{scope}"' in pages_block
            continue
        assert f'("{page}", "{scope}"' in pages_block
    # só o Growth passa paleta; os outros seis passam None
    assert pages_block.count(", None),") == len(EXPECTED_HUB_PAGES) - 1
    assert "DEFAULT_HUB_COLOR = \"#8a2be2\"" in MAIN_SOURCE
    # o palete resolved garante cor para toda aba, mesmo com colors=None
    assert '(colors or {}).get(key) or DEFAULT_HUB_COLOR' in MAIN_SOURCE


def test_pipeline_videos_buttons_keep_the_internal_page_titles():
    specs = MAIN_SOURCE.split("PIPELINE_VIDEO_HUB_SPECS = [", 1)[1].split("\n]", 1)[0]
    assert '("Criação de Vídeos", "Vídeos",' in specs
    assert '("Criação de Shorts", "Shorts",' in specs
    # o renderizador continua a receber o título e o prefixo internos de sempre
    assert 'render_new_video("Criação de Shorts", "new_shorts", channel_platform="tiktok", fixed_aspect_ratio="Portrait 9:16")' in specs
    assert 'render_new_video("Criação de Vídeos", "new_video")' in specs


def test_business_logic_renderers_are_untouched_and_still_wired():
    """Nenhuma função de negócio foi renomeada (assinatura intacta)."""
    for name in (
        "render_channels", "render_tiktok_channels", "render_blueprints", "render_music_blueprints",
        "render_thumbnail_blueprints", "render_youtube_brandings", "render_tiktok_prompt_masters",
        "render_facebook_blueprints", "render_facebook_pages", "render_niche_finder",
        "render_niche_finder_apify", "render_metadata_cleaner", "render_cuts", "render_python_editor",
        "render_media_download", "render_new_video", "render_videos", "render_scripts", "render_thumbnails",
        "render_upload", "render_update_youtube_videos", "render_music_creation", "render_music_backlog",
        "render_custom_music_voices", "render_music_upload",
    ):
        assert f"def {name}(" in MAIN_SOURCE, name
    # a assinatura que o hub do Pipeline usa tem de continuar igual
    assert 'def render_new_video(page_title: str = "Criação de Vídeos", prefix: str = "new_video", *, channel_platform: str = "youtube", fixed_aspect_ratio: str | None = None):' in MAIN_SOURCE


# --------------------------------------------------------------------------
# 3. Sidebar limpa (só o nome principal)
# --------------------------------------------------------------------------

def test_sidebar_keeps_only_the_group_names():
    """Os 7 grupos deixaram de ter filhos no menu lateral."""
    groups_block = MAIN_SOURCE.split("    groups = {", 1)[1].split("\n    }", 1)[0]
    for page in EXPECTED_HUB_PAGES:
        assert f'"{page}": ' not in groups_block, f"{page} ainda tem filhos na sidebar"
    # quem mantém submenus é só AI Influencers e Configurações
    assert '"AI Influencers": models_ai_items' in groups_block
    assert '"Configurações": settings_items' in groups_block
    # as listas de itens continuam a existir (ordem, nomes e links directos)
    for items in ("niche_finder_items", "channel_profile_items", "blueprint_items", "edition_items", "pipeline_video_items", "music_items", "growth_analysis_items"):
        assert f"    {items} = [" in MAIN_SOURCE, items


def test_group_positions_in_the_sidebar_are_unchanged():
    """Regra de UI «Inserção de Itens»: nenhuma posição do menu é alterada."""
    top_block = MAIN_SOURCE.split("    top_pages = [", 1)[1].split("    ]", 1)[0]
    order = [label for label in ("Início", "Automação", "Niche Finder", "Canais/Perfis (Vídeos)", "Pipeline Vídeos", "Pipeline Música", "AI Influencers", "Blueprints", "Edição", "Growth", "Configurações") if f'"{label}"' in top_block]
    positions = [top_block.index(f'"{label}"') for label in order]
    assert positions == sorted(positions)


def test_every_hub_page_has_its_own_renderer():
    """Páginas que caíam no dashboard passam a ter renderizador próprio."""
    assert '"Pipeline Vídeos": render_pipeline' in MAIN_SOURCE
    assert '"Growth": render_growth_pages' in MAIN_SOURCE
    for page, renderer in (
        ("Canais/Perfis (Vídeos)", "render_channel_profiles_hub"),
        ("Blueprints", "render_blueprints_hub"),
        ("Niche Finder", "render_niche_finder_hub"),
        ("Edição", "render_edition_hub"),
        ("Pipeline Música", "render_pipeline_music_hub"),
    ):
        assert f'"{page}": {renderer}' in MAIN_SOURCE, page


# --------------------------------------------------------------------------
# 4. Links directos e estado
# --------------------------------------------------------------------------

def test_direct_links_to_old_sub_pages_still_resolve_into_the_right_tab():
    assert "HUB_PAGE_ROUTES = {" in MAIN_SOURCE
    routes_block = MAIN_SOURCE.split("HUB_PAGE_ROUTES = {", 1)[1].split("\n}", 1)[0]
    # a rota é derivada das próprias specs: (página principal, scope, slug)
    assert "target: (parent, scope, _hub_slug(target))" in routes_block
    assert "HUB_TAB_KEYS = {" in MAIN_SOURCE
    assert "HUB_SCOPE_BY_PAGE = {" in MAIN_SOURCE
    # o alias colapsa a sub-página no pai
    assert "aliases.update(" in MAIN_SOURCE
    assert "child_page: parent for child_page, (parent, _scope, _tab) in HUB_PAGE_ROUTES.items()" in MAIN_SOURCE
    # ...e as sub-páginas continuam a ser alvos válidos de navegação
    assert "hub_child_items = [" in MAIN_SOURCE
    assert "+ hub_child_items" in MAIN_SOURCE


def test_active_tab_survives_a_refresh_through_the_url():
    assert 'st.query_params["hub"] = f"{scope}:{tab_key}"' in MAIN_SOURCE
    assert 'requested_hub = str(st.query_params.get("hub") or "").strip().lower()' in MAIN_SOURCE
    assert "HUB_TAB_KEYS.get(hub_scope, set())" in MAIN_SOURCE
    # o ?tab= continua exclusivo da Automação (contrato da 1.1.02 intacto)
    assert 'st.query_params["tab"] = tab_key' in MAIN_SOURCE
    assert 'st.session_state["active_automation_tab"] = requested_tab' in MAIN_SOURCE


# --------------------------------------------------------------------------
# 5. Prova funcional: o hub corre e chama o renderizador certo
# --------------------------------------------------------------------------

class _FakeColumn:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _FakeContainer:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _FakeSessionState(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)


class _FakeQueryParams(dict):
    def __setitem__(self, key, value):
        dict.__setitem__(self, key, value)


class _FakeStreamlit:
    """Streamlit mínimo: nada é desenhado, os botões nunca são premidos."""

    def __init__(self, session_state=None):
        self.session_state = _FakeSessionState(session_state or {})
        self.query_params = _FakeQueryParams()
        self.pressed: list[str] = []
        self.markdowns: list[str] = []
        self.reruns = 0

    # elementos
    def markdown(self, value, **_kwargs):
        self.markdowns.append(str(value))
        return None

    def title(self, *_args, **_kwargs):
        return None

    def caption(self, *_args, **_kwargs):
        return None

    def container(self, **_kwargs):
        return _FakeContainer()

    def columns(self, count, **_kwargs):
        return [_FakeColumn() for _ in range(count)]

    def button(self, label, key=None, **_kwargs):
        self.pressed.append(str(label))
        return False

    def rerun(self, **_kwargs):
        self.reruns += 1
        raise _StopRender()


class _StopRender(Exception):
    """Marca o st.rerun() dentro do fake (o hub nunca deve chamá-lo sozinho)."""


def _run_hub(hub_page: str, active: str | None = None):
    """Corre render_hub_page com st substituído e acusa a aba que foi chamada.

    Os renderizadores das abas são substituídos por stubs que registam a CHAVE
    da aba: provar que o hub chamou uma e uma só aba é o contrato. Quem é o
    renderizador de cada chave está travado pelo contrato de fonte
    (`test_business_logic_renderers_are_untouched_and_still_wired`).
    """
    main = pytest.importorskip("app.main", reason="app.main precisa das dependências da app")
    original_st = main.st
    original_tabs = main.HUB_TABS_BY_PAGE
    called: list[str] = []
    faked_tabs = {
        page: [(key, label, _make_tab_stub(key, called)) for key, label, _renderer in tabs]
        for page, tabs in original_tabs.items()
    }
    fake_st = _FakeStreamlit()

    def _seed_state():
        scope = EXPECTED_HUB_PAGES[hub_page]
        if active is not None:
            fake_st.session_state[f"active_hub_tab_{scope}"] = active

    _seed_state()
    try:
        main.st = fake_st
        main.HUB_TABS_BY_PAGE = faked_tabs
        main.render_hub_page(hub_page)
    except _StopRender:
        pass
    finally:
        main.st = original_st
        main.HUB_TABS_BY_PAGE = original_tabs
    return called, fake_st


def _make_tab_stub(tab_key, called):
    def stub(*_args, **_kwargs):
        called.append(tab_key)

    return stub


@pytest.mark.parametrize("hub_page", sorted(EXPECTED_HUB_PAGES))
def test_hub_page_renders_exactly_the_content_of_the_active_tab(hub_page):
    _called, fake_st = _run_hub(hub_page)
    main = pytest.importorskip("app.main", reason="app.main precisa das dependências da app")
    first_key = main.HUB_TABS_BY_PAGE[hub_page][0][0]
    assert _called == [first_key], f"{hub_page} chamou {_called}"
    assert len(_called) == 1, "só uma aba corre por rerun"
    # os botões foram desenhados, na ordem pedida, e nada rerunnou sozinho
    assert fake_st.pressed == EXPECTED_HUB_BUTTONS[hub_page]
    assert fake_st.reruns == 0


def test_hub_falls_back_to_the_first_tab_when_the_stored_tab_is_unknown():
    main = pytest.importorskip("app.main", reason="app.main precisa das dependências da app")
    first_key = main.HUB_TABS_BY_PAGE["Growth"][0][0]
    called, _fake_st = _run_hub("Growth", "aba-inexistente")
    assert called == [first_key]


def test_hub_switches_to_the_requested_tab():
    """A aba pedida no session_state é a que corre (ex.: Shorts)."""
    main = pytest.importorskip("app.main", reason="app.main precisa das dependências da app")
    shorts_key = main.HUB_TABS_BY_PAGE["Pipeline Vídeos"][1][0]
    called, _fake_st = _run_hub("Pipeline Vídeos", shorts_key)
    assert called == [shorts_key]


def test_hub_uses_the_requested_platform_colors_on_growth():
    _called, fake_st = _run_hub("Growth")
    css = "\n".join(fake_st.markdowns)
    assert "tb-hub-chip-growth-growth-youtube) button { background:#ff0000" in css
    assert "tb-hub-chip-growth-growth-tiktok) button { background:#000000" in css
    assert "tb-hub-chip-growth-growth-bilibili) button { background:#00a1d6" in css
    # e a aba activa leva o destacador
    assert "tb-hub-chip-growth-growth-youtube is-active" in css


def test_hub_without_colors_paints_every_button_purple():
    main = pytest.importorskip("app.main", reason="app.main precisa das dependências da app")
    _called, fake_st = _run_hub("Pipeline Música")
    css = "\n".join(fake_st.markdowns)
    for key, _label, _renderer in main.HUB_TABS_BY_PAGE["Pipeline Música"]:
        assert f"tb-hub-chip-pipeline-musica-{key}) button {{ background:#8a2be2" in css, key