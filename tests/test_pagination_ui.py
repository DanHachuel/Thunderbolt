"""Paginação: selectbox «Página X de Y» -> barra de botões numéricos (1.1.09).

Relato do utilizador: o menu suspenso dava dois cliques para chegar a uma
página longe. Passa a ser uma barra horizontal `❮ 1 2 3 4 5 … 9 ❯`, no mesmo
sítio, com a página activa destacada e reticências quando há mais de 7 páginas.

Metade dos testes é de contrato sobre a fonte; a outra metade **corre** a
barra com o Streamlit substituído, para provar que devolve a página certa e que
nada rerunna sozinho.
"""

import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# 1. O componente existe e é reutilizável
# --------------------------------------------------------------------------

def _function(name: str) -> ast.FunctionDef:
    tree = ast.parse(MAIN_SOURCE)
    node = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name),
        None,
    )
    assert node is not None, f"{name} não existe em app/main.py"
    return node


def test_render_pagination_exists_with_the_requested_signature():
    node = _function("render_pagination")
    positional = [arg.arg for arg in node.args.posonlyargs + node.args.args]
    assert positional == ["current_page", "total_pages", "key_prefix"], positional


def test_pagination_logic_is_pure_and_testable():
    """A lógica de números/reticências vive fora do Streamlit."""
    assert "def _pagination_page_numbers(current_page: int, total_pages: int)" in MAIN_SOURCE
    source = ast.get_source_segment(MAIN_SOURCE, _function("render_pagination"))
    assert "_pagination_page_numbers(" in source


def test_pagination_buttons_are_isolated_by_key_prefix():
    source = ast.get_source_segment(MAIN_SOURCE, _function("render_pagination"))
    assert 'key=f"{key_prefix}_prev"' in source
    assert 'key=f"{key_prefix}_next"' in source
    assert 'key=f"{key_prefix}_page_{page}"' in source


def test_pagination_highlights_the_active_page_and_disables_the_ends():
    source = ast.get_source_segment(MAIN_SOURCE, _function("render_pagination"))
    assert 'type="primary" if page == current_page else "secondary"' in source
    assert "disabled=current_page <= 1" in source
    assert "disabled=current_page >= total_pages" in source


def test_pagination_has_no_blocking_loop_or_sleep():
    node = _function("render_pagination")
    for inner in ast.walk(node):
        if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute):
            assert inner.func.attr != "sleep", "espera bloqueante proibida na paginação"
        assert not isinstance(inner, (ast.While, ast.AsyncFor)), "laço bloqueante proibido na paginação"
    source = ast.get_source_segment(MAIN_SOURCE, node)
    assert "sleep(" not in source


# --------------------------------------------------------------------------
# 2. Lógica de números e reticências (pura, sem Streamlit)
# --------------------------------------------------------------------------

EXPECTED_NUMBERS = [
    (1, 1, []),                                     # uma página: nada a mostrar
    (1, 2, [1, 2]),
    (3, 6, [1, 2, 3, 4, 5, 6]),                     # até 7: todas
    (1, 7, [1, 2, 3, 4, 5, 6, 7]),
    (1, 8, [1, 2, 3, 4, 5, "…", 8]),                # início
    (5, 8, [1, "…", 3, 4, 5, 6, 7, 8]),             # meio/curto: sem reticência interna
    (8, 8, [1, "…", 3, 4, 5, 6, 7, 8]),             # fim
    (5, 10, [1, "…", 4, 5, 6, "…", 10]),            # o exemplo do pedido
    (10, 10, [1, "…", 5, 6, 7, 8, 9, 10]),
]


@pytest.mark.parametrize("current,total,expected", EXPECTED_NUMBERS)
def test_pagination_page_numbers(current, total, expected):
    main = pytest.importorskip("app.main", reason="app.main precisa das dependências da app")
    assert main._pagination_page_numbers(current, total) == expected, current


def test_pagination_never_lists_the_same_number_twice_or_shows_duplicated_ellipsis():
    main = pytest.importorskip("app.main", reason="app.main precisa das dependências da app")
    for total in range(1, 30):
        for current in range(1, total + 1):
            numbers = main._pagination_page_numbers(current, total)
            if not numbers:
                continue  # uma página só: a barra nem é desenhada
            numeric = [n for n in numbers if isinstance(n, int)]
            assert numeric == sorted(numeric), (current, total, numbers)
            assert len(numeric) == len(set(numeric)), (current, total, numbers)
            # a activa está sempre na lista
            assert current in numeric, (current, total, numbers)
            # reticências nunca seguidas
            assert "……" not in "".join(str(n) for n in numbers), (current, total, numbers)


def test_pagination_with_more_than_seven_pages_keeps_ellipsis():
    """Só a partir de 8 páginas (o pedido fala em «mais de 7»)."""
    main = pytest.importorskip("app.main", reason="app.main precisa das dependências da app")
    assert "…" not in main._pagination_page_numbers(4, 7)
    assert "…" in main._pagination_page_numbers(5, 10)


# --------------------------------------------------------------------------
# 3. O selectbox desapareceu dos dois pontos que paginavam
# --------------------------------------------------------------------------

def test_automation_list_no_longer_uses_the_page_dropdown():
    automation = MAIN_SOURCE.split("def _render_youtube_automation_task_list(", 1)[1].split("\ndef ", 1)[0]
    assert "st.selectbox(" not in automation, "o selectbox de paginação voltou à Automação"
    assert '"Página de vídeos cadastrados"' not in MAIN_SOURCE
    assert 'format_func=lambda value: f"Página {value} de {page_count}"' not in MAIN_SOURCE
    assert '_render_page_navigation(requested_page, page_count, "youtube_automation_page")' in automation
    # a fatiação dos vídeos ficou igual (só UI mudou)
    assert "visible_tasks = tasks[start : start + page_size]" in MAIN_SOURCE
    assert "page_size = 12" in MAIN_SOURCE


def test_thumbnail_gallery_no_longer_uses_the_page_dropdown():
    thumbnails = MAIN_SOURCE.split("def render_thumbnails():", 1)[1].split("\ndef ", 1)[0]
    assert "st.selectbox(" not in thumbnails, "o selectbox de paginação voltou às thumbnails"
    assert '"Página de thumbnails"' not in MAIN_SOURCE
    assert '_render_page_navigation(requested_page, page_count, "thumbnail_gallery_page")' in thumbnails
    assert "visible_records = records[start : start + page_size]" in MAIN_SOURCE
    assert "page_size = 24" in MAIN_SOURCE


def test_page_state_keys_are_preserved_for_the_slicing_functions():
    for state_key in ("youtube_automation_page", "thumbnail_gallery_page"):
        assert f'"{state_key}"' in MAIN_SOURCE, state_key
    helper = ast.get_source_segment(MAIN_SOURCE, _function("_render_page_navigation"))
    # o clamp é escrito de volta ao session_state (a chave deixou de ser de widget)
    assert "st.session_state[state_key] = page" in helper
    assert "st.session_state[state_key] = chosen" in helper
    assert "return chosen" in helper
    # M5 (1.0.96): o componente em si NUNCA chama rerun — o escopo é de quem
    # chama. Verificado pelo AST (o docstring pode falar de rerun; o código não).
    reruns = [
        n for n in ast.walk(_function("_render_page_navigation"))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "rerun"
    ]
    assert not reruns, "o componente não pode decidir o escopo do rerun"


def test_each_caller_reruns_in_its_own_scope():
    """Galeria = página normal; lista da Automação = dentro de um fragmento."""
    thumbnails = MAIN_SOURCE.split("def render_thumbnails():", 1)[1].split("\ndef ", 1)[0]
    assert '_render_page_navigation(requested_page, page_count, "thumbnail_gallery_page")' in thumbnails
    assert "if current_page != requested_page:" in thumbnails
    assert "st.rerun()" in thumbnails
    assert 'st.rerun(scope="fragment")' not in thumbnails

    automation = MAIN_SOURCE.split("def _render_youtube_automation_task_list(", 1)[1].split("\ndef ", 1)[0]
    assert '_render_page_navigation(requested_page, page_count, "youtube_automation_page")' in automation
    assert 'st.rerun(scope="fragment")' in automation


# --------------------------------------------------------------------------
# 4. Prova funcional: a barra corre e devolve a página certa
# --------------------------------------------------------------------------

class _FakeColumn:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _FakeSessionState(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)


class _FakeStreamlit:
    """Streamlit mínimo: botões nunca premidos, nada é desenhado."""

    def __init__(self, session_state=None):
        self.session_state = _FakeSessionState(session_state or {})
        self.buttons: list[tuple[str, str, bool]] = []
        self.markdowns: list[str] = []
        self.reruns = 0

    def columns(self, weights, gap=None):
        self.column_count = len(weights)
        return [_FakeColumn() for _ in range(len(weights))]

    def button(self, label, key=None, type=None, disabled=False, help=None):
        self.buttons.append((str(key), str(label), bool(disabled)))
        return False

    def markdown(self, value, **_kwargs):
        self.markdowns.append(str(value))
        return None

    def rerun(self, **_kwargs):
        self.reruns += 1
        raise _StopRender()


class _StopRender(Exception):
    """Marca o st.rerun() dentro do fake."""


def _run_bar(current: int, total: int, prefix: str):
    main = pytest.importorskip("app.main", reason="app.main precisa das dependências da app")
    original_st = main.st
    fake_st = _FakeStreamlit({prefix: current})
    try:
        main.st = fake_st
        chosen = main.render_pagination(current, total, prefix)
    finally:
        main.st = original_st
    return chosen, fake_st


def test_bar_returns_the_current_page_when_nothing_is_clicked():
    chosen, fake_st = _run_bar(5, 10, "youtube_automation_page")
    assert chosen == 5
    assert fake_st.reruns == 0


def test_bar_draws_the_arrows_and_every_visible_number():
    _chosen, fake_st = _run_bar(5, 10, "youtube_automation_page")
    keys = [key for key, _label, _disabled in fake_st.buttons]
    assert "youtube_automation_page_prev" in keys
    assert "youtube_automation_page_next" in keys
    for page in (1, 4, 5, 6, 10):
        assert f"youtube_automation_page_page_{page}" in keys, page
    # as reticências NÃO são botões (não há chave para elas)
    assert not [key for key in keys if key.endswith("_page_…")]
    # setas desactivadas nos extremos
    disabled = {key: value for key, _label, value in fake_st.buttons}
    assert disabled["youtube_automation_page_prev"] is False
    assert disabled["youtube_automation_page_next"] is False


def test_bar_disables_the_arrows_on_the_first_and_last_page():
    _chosen, fake_st = _run_bar(1, 3, "prefix_first")
    disabled = {key: value for key, _label, value in fake_st.buttons}
    assert disabled["prefix_first_prev"] is True
    assert disabled["prefix_first_next"] is False

    _chosen, fake_st = _run_bar(3, 3, "prefix_last")
    disabled = {key: value for key, _label, value in fake_st.buttons}
    assert disabled["prefix_last_prev"] is False
    assert disabled["prefix_last_next"] is True


def test_bar_uses_one_column_per_slot():
    _chosen, fake_st = _run_bar(5, 10, "cols_probe")
    # 7 números/reticências + 2 setas
    assert fake_st.column_count == 9


def test_helper_records_the_chosen_page_and_lets_the_caller_rerun():
    """O componente grava e devolve; o rerun é de quem chama (regra M5)."""
    main = pytest.importorskip("app.main", reason="app.main precisa das dependências da app")
    original_st = main.st

    class _ClickingStreamlit(_FakeStreamlit):
        def button(self, label, key=None, type=None, disabled=False, help=None):
            self.buttons.append((str(key), str(label), bool(disabled)))
            return key == "youtube_automation_page_page_3"

    clicking = _ClickingStreamlit({"youtube_automation_page": 1})
    try:
        main.st = clicking
        chosen = main._render_page_navigation(1, 5, "youtube_automation_page")
    finally:
        main.st = original_st
    # a página nova foi gravada e devolvida, e NADA rerunnou aqui dentro
    assert chosen == 3
    assert clicking.session_state["youtube_automation_page"] == 3
    assert clicking.reruns == 0


def test_helper_clamps_an_out_of_range_page_instead_of_breaking():
    main = pytest.importorskip("app.main", reason="app.main precisa das dependências da app")
    original_st = main.st
    fake_st = _FakeStreamlit({"youtube_automation_page": 99})
    try:
        main.st = fake_st
        chosen = main._render_page_navigation(99, 4, "youtube_automation_page")
    finally:
        main.st = original_st
    assert chosen == 4
    assert fake_st.session_state["youtube_automation_page"] == 4
    assert fake_st.reruns == 0


def test_helper_draws_nothing_when_there_is_a_single_page():
    main = pytest.importorskip("app.main", reason="app.main precisa das dependências da app")
    original_st = main.st
    fake_st = _FakeStreamlit()
    try:
        main.st = fake_st
        chosen = main._render_page_navigation(1, 1, "single_page")
    finally:
        main.st = original_st
    assert chosen == 1
    assert fake_st.buttons == []
