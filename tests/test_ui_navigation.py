"""Navegação da Automação: submenus da sidebar -> botões coloridos no topo.

1.1.02 — as 8 sub-páginas de Automação (YouTube, TikTok, Instagram, Facebook,
Músicas, UGC, Influencer, Bilibili) estavam aninhadas no menu lateral. Passaram
a ser UMA página («Automação») com uma barra de botões horizontais coloridos no
topo, e o conteúdo troca por session_state + st.rerun().

Os testes são de CONTRATO (skill testes-contrato): metade corre o AST real do
`render_automation_hub` para provar que cada aba chama o renderizador certo, e
não apenas que uma string existe na fonte.
"""

import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

PLATFORM_TABS = (
    ("youtube", "YouTube", "#ff0000"),
    ("tiktok", "TikTok", "#000000"),
    ("instagram", "Instagram", "linear-gradient(45deg,#f09433 0%,#e6683c 25%,#dc2743 50%,#cc2366 75%,#bc1888 100%)"),
    ("facebook", "Facebook", "#1877f2"),
    ("musicas", "Músicas", "#1db954"),
    ("ugc", "UGC", "#8a2be2"),
    ("influencer", "Influencer", "#ffd700"),
    ("bilibili", "Bilibili", "#00a1d6"),
)


def _hub_function() -> ast.FunctionDef:
    """O AST real de render_automation_hub (não uma cópia de string)."""
    tree = ast.parse(MAIN_SOURCE)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "render_automation_hub":
            return node
    raise AssertionError("render_automation_hub não existe em app/main.py")


def _hub_source() -> str:
    start = MAIN_SOURCE.index("def render_automation_hub(")
    return MAIN_SOURCE[start:MAIN_SOURCE.index("\ndef main():")]


def _dispatch_branches():
    """{valor da aba: [funções chamadas nesse ramo]} lido do if/elif real."""
    hub = _hub_function()
    chain = None
    for stmt in hub.body:
        test = stmt.test if isinstance(stmt, ast.If) else None
        if (
            test is not None
            and isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "active_tab"
            # só a comparação por igualdade (active_tab == "youtube"), não o
            # "active_tab not in AUTOMATION_TAB_KEYS" que vem antes.
            and test.ops
            and isinstance(test.ops[0], ast.Eq)
        ):
            chain = stmt
            break
    assert chain is not None, "render_automation_hub não tem if/elif sobre active_tab"
    branches = {}
    node = chain
    while isinstance(node, ast.If):
        comparator = node.test.comparators[0]
        key = comparator.value if isinstance(comparator, ast.Constant) else None
        branches[key] = sorted(
            call.func.id
            # só o corpo do ramo: ast.walk desceria também para os elif seguintes
            for call in ast.walk(ast.Module(body=node.body, type_ignores=[]))
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
        )
        node = node.orelse[0] if node.orelse else None
    return branches


# --------------------------------------------------------------------------
# 1. Sidebar limpa
# --------------------------------------------------------------------------

def test_sidebar_has_no_automation_children_anymore():
    """Os submenus de Automação saíram do menu lateral."""
    assert "automation_items = []" in MAIN_SOURCE
    # o grupo deixou de mapear a categoria para filhos (senão aparecia um
    # expansível vazio na sidebar)
    assert '"Automação": automation_items' not in MAIN_SOURCE
    for label in (
        "Automação Youtube", "Automação Tiktok", "Automação Instagram",
        "Automação Facebook", "Automação Musicas", "Automação UGC",
        "Automação Influencer Content", "Automação Bilibili",
    ):
        assert f'("{label}", ":material/schedule:"' not in MAIN_SOURCE, label


def test_automation_stays_in_the_same_sidebar_position():
    """A categoria principal continua no menu, na MESMA posição (regra de UI)."""
    top_block = MAIN_SOURCE.split("    top_pages = [", 1)[1].split("    ]", 1)[0]
    order = [label for label in ("Início", "Automação", "Niche Finder", "Canais/Perfis (Vídeos)", "Pipeline Vídeos", "Pipeline Música", "AI Influencers", "Blueprints", "Edição", "Growth", "Configurações") if f'"{label}"' in top_block]
    positions = [top_block.index(f'"{label}"') for label in order]
    assert positions == sorted(positions)
    assert '("Automação", ":material/schedule:", "Automação")' in MAIN_SOURCE
    # os outros grupos continuam com os seus filhos na sidebar
    assert '"Niche Finder": niche_finder_items' in MAIN_SOURCE
    assert '"Growth": growth_items' in MAIN_SOURCE
    assert '"Configurações": settings_items' in MAIN_SOURCE


# --------------------------------------------------------------------------
# 2. Barra de botões coloridos
# --------------------------------------------------------------------------

def test_all_eight_platform_buttons_are_rendered_at_the_top():
    hub = _hub_source()
    assert "st.columns(len(AUTOMATION_TAB_SPECS)" in hub
    for key, label, _color in PLATFORM_TABS:
        assert f'("{key}", "{label}"' in MAIN_SOURCE
    # uma chave de widget por plataforma, gerada a partir da lista de specs
    assert 'key=f"tb_automation_nav_{tab_key}"' in hub
    assert len({spec[0] for spec in PLATFORM_TABS}) == len(PLATFORM_TABS) == 8


def test_each_button_has_its_platform_color():
    css = MAIN_SOURCE.split("AUTOMATION_NAV_CSS = ", 1)[1].split('"""', 2)[1]
    for key, _label, color in PLATFORM_TABS:
        assert f":has(.tb-automation-chip-{key}) button" in css, key
        assert color in css, f"{key}: {color}"
    # TikTok precisa de borda branca para contrastar com o fundo preto
    assert "has(.tb-automation-chip-tiktok) button { background:#000000 !important; color:#ffffff !important; border:1px solid #ffffff !important; }" in css
    # Influencer é dourado: texto preto para legibilidade
    assert "has(.tb-automation-chip-influencer) button { background:#ffd700 !important; color:#000000 !important;" in css


def test_active_tab_is_highlighted_with_a_white_border():
    css = MAIN_SOURCE.split("AUTOMATION_NAV_CSS = ", 1)[1].split('"""', 2)[1]
    assert ".tb-automation-chip.is-active" in css
    assert "border:2px solid #ffffff !important" in css
    hub = _hub_source()
    # a classe is-active só aparece no chip da aba activa
    assert '" is-active" if tab_key == active_tab else ""' in hub


def test_color_css_is_scoped_and_cannot_paint_other_buttons():
    """O selector exige a coluna do chip: nenhum botão do resto da app muda."""
    css = MAIN_SOURCE.split("AUTOMATION_NAV_CSS = ", 1)[1].split('"""', 2)[1]
    for rule in css.splitlines():
        if rule.startswith("[data-testid=\"stColumn\"]:has(.tb-automation-chip-"):
            assert " button {" in rule, rule
    # o marcador invisível não ocupa espaço na página
    assert ".tb-automation-chip { display:none; }" in css


# --------------------------------------------------------------------------
# 3. Estado e roteamento interno
# --------------------------------------------------------------------------

def test_active_tab_lives_in_session_state_and_defaults_to_youtube():
    assert 'st.session_state.get("active_automation_tab", "youtube")' in MAIN_SOURCE
    hub = _hub_source()
    assert 'st.session_state["active_automation_tab"] = tab_key' in hub
    # valor fora da lista conhecida cai sempre no YouTube
    assert "if active_tab not in AUTOMATION_TAB_KEYS:" in hub
    assert "AUTOMATION_TAB_KEYS = {spec[0] for spec in AUTOMATION_TAB_SPECS}" in MAIN_SOURCE


def test_clicking_a_button_updates_state_and_reruns_exactly_once():
    """Um clique -> um rerun; clicar na aba activa não dispara nada (sem loop)."""
    hub = _hub_function()
    reruns = [
        node
        for node in ast.walk(hub)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "rerun"
    ]
    assert len(reruns) == 1
    # o rerun está dentro do handler do botão e protegido pela comparação de aba
    handler = _hub_source().split('if st.button(label, key=f"tb_automation_nav_{tab_key}", width="stretch"):', 1)[1]
    assert "if tab_key != active_tab:" in handler
    assert "st.rerun()" in handler.split("elif active_tab")[0]


def test_the_url_keeps_the_active_tab_across_a_refresh():
    assert 'st.query_params["tab"] = tab_key' in _hub_source()
    assert 'requested_tab = str(st.query_params.get("tab") or "").strip().lower()' in MAIN_SOURCE
    assert 'st.session_state["active_automation_tab"] = requested_tab' in MAIN_SOURCE
    assert 'st.session_state.setdefault("active_automation_tab", "youtube")' in MAIN_SOURCE


def test_legacy_automation_links_still_open_the_right_tab():
    """?page=Automação Tiktok continua a funcionar: colapsa no pai e semeia a aba."""
    assert '"Automação Tiktok": "Automação"' in MAIN_SOURCE
    assert 'seeded_automation_tab = AUTOMATION_TAB_BY_PAGE.get(stored_page)' in MAIN_SOURCE
    expected = {
        "Automação Youtube": "youtube", "Automação Tiktok": "tiktok",
        "Automação Instagram": "instagram", "Automação Facebook": "facebook",
        "Automação Musicas": "musicas", "Automação UGC": "ugc",
        "Automação Influencer Content": "influencer", "Automação Bilibili": "bilibili",
    }
    seed_block = MAIN_SOURCE.split("AUTOMATION_TAB_BY_PAGE = {", 1)[1].split("}", 1)[0]
    for page, key in expected.items():
        assert f'"{page}": "{key}"' in seed_block, page


# --------------------------------------------------------------------------
# 4. Roteamento real (AST): cada aba chama o seu renderizador
# --------------------------------------------------------------------------

def test_each_tab_calls_the_renderer_it_always_called():
    branches = _dispatch_branches()
    expected = {
        "youtube": ["render_automation"],
        "tiktok": ["render_tiktok_automation"],
        "instagram": ["render_instagram_automation", "read_json"],
        "facebook": ["render_facebook_automation"],
        "musicas": ["render_music_automation"],
        "bilibili": ["render_bilibili_automation"],
        "ugc": ["render_edit_placeholder"],
        "influencer": ["render_edit_placeholder"],
    }
    for key, calls in expected.items():
        assert key in branches, f"aba {key} não tem ramo no dispatch"
        for call in calls:
            assert call in branches[key], f"aba {key} não chama {call}: {branches[key]}"


def test_ugc_and_influencer_keep_a_reserved_placeholder_page():
    """Eram `lambda: None` (página em branco); agora têm lugar reservado visível."""
    branches = _dispatch_branches()
    assert branches["ugc"] == ["render_edit_placeholder"]
    assert branches["influencer"] == ["render_edit_placeholder"]
    assert 'render_edit_placeholder("Automação UGC"' in _hub_source()
    assert 'render_edit_placeholder("Automação Influencer"' in _hub_source()


def test_business_logic_functions_are_untouched_and_still_wired():
    """Nenhuma função de dados/worker foi renomeada ou mudada de assinatura."""
    for definition in (
        "def render_automation():",
        "def render_tiktok_automation():",
        "def render_facebook_automation",
        "def render_music_automation",
        "def render_bilibili_automation",
    ):
        assert definition in MAIN_SOURCE, definition
    # a Instagram vive noutro módulo e continua importada como sempre
    assert "from app.social_networks_ui import render_instagram_automation" in MAIN_SOURCE
    assert '"Automação": render_automation_hub' in MAIN_SOURCE
    # uma única página de Automação no mapa de renderizadores
    assert MAIN_SOURCE.count('"Automação": render_automation_hub') == 1


def test_hub_has_no_blocking_loop_or_sleep():
    """Skill streamlit-estado: nenhuma espera bloqueante na thread da UI."""
    hub = _hub_function()
    for node in ast.walk(hub):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr != "sleep", "espera bloqueante proibida na aba de Automação"
        assert not isinstance(node, (ast.While, ast.AsyncFor)), "laço bloqueante proibido no hub"
    assert "sleep(" not in _hub_source()


# --------------------------------------------------------------------------
# 5. Prova funcional: o hub chama mesmo o renderizador da aba activa
# --------------------------------------------------------------------------

class _FakeColumn:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _FakeSessionState(dict):
    """Basta o .get que o hub usa (sem o runtime do Streamlit)."""


class _FakeStreamlit:
    """Streamlit mínimo para o hub: botões nunca premidos, nada é desenhado."""

    session_state = _FakeSessionState()

    def markdown(self, *_args, **_kwargs):
        return None

    def container(self):
        return _FakeColumn()

    def columns(self, count, gap=None):
        return [_FakeColumn() for _ in range(count)]

    def button(self, label, key=None, **_kwargs):
        self.pressed_labels.append(label)
        return False

    pressed_labels = []


def _hub_dispatch(tab: str) -> list[str]:
    """Corre o hub de verdade com o Streamlit substituído e devolve o que chamou."""
    main = pytest.importorskip("app.main", reason="app.main precisa das dependências da app")

    original_st = main.st
    called: list[str] = []
    stubs = {
        "render_automation": "render_automation",
        "render_tiktok_automation": "render_tiktok_automation",
        "render_instagram_automation": "render_instagram_automation",
        "render_facebook_automation": "render_facebook_automation",
        "render_music_automation": "render_music_automation",
        "render_bilibili_automation": "render_bilibili_automation",
        "render_edit_placeholder": "render_edit_placeholder",
    }
    saved = {name: getattr(main, name, None) for name in stubs}
    fake_st = _FakeStreamlit()
    fake_st.session_state = _FakeSessionState({"active_automation_tab": tab})

    def make_stub(name):
        def stub(*_args, **_kwargs):
            called.append(name)

        return stub

    try:
        main.st = fake_st
        for name in stubs:
            setattr(main, name, make_stub(stubs[name]))
        main.render_automation_hub()
    finally:
        main.st = original_st
        for name, value in saved.items():
            setattr(main, name, value)
    return called


@pytest.mark.parametrize("tab,expected", [
    ("youtube", "render_automation"),
    ("tiktok", "render_tiktok_automation"),
    ("instagram", "render_instagram_automation"),
    ("facebook", "render_facebook_automation"),
    ("musicas", "render_music_automation"),
    ("ugc", "render_edit_placeholder"),
    ("influencer", "render_edit_placeholder"),
    ("bilibili", "render_bilibili_automation"),
])
def test_hub_renders_exactly_the_content_of_the_active_tab(tab, expected):
    """Não é assert de string: o hub corre e chamou o renderizador certo."""
    called = _hub_dispatch(tab)
    assert called == [expected], f"aba {tab} chamou {called}"
    # e só UM renderizador corre por rerun (nada de renderizar as 8 abas juntas)
    assert len(called) == 1


def test_hub_falls_back_to_youtube_when_the_tab_is_unknown():
    called = _hub_dispatch("plataforma-inexistente")
    assert called == ["render_automation"]