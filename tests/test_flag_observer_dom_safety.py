"""Segurança de DOM do substituto de bandeiras (1.1.08).

Relato do utilizador: `NotFoundError: Failed to execute 'removeChild' on
'Node': The node to be removed is not a child of this node` no console, na aba
"Criação de Shorts".

Causa raiz (confirmada por leitura do react-dom 1.65 empacotado): o
`MutationObserver` de `_FLAG_RENDER_BOOTSTRAP` fazia `node.replaceWith(fragment)`
sobre nós de TEXTO criados pelo React. Ao remover a subárvore — fecho do
dropdown, troca de aba, rerun completo — o react-dom chamava
`parent.removeChild(filho)` num nó já desanexado pelo `replaceWith`.

A rota "Criação de Shorts" dispara o caminho porque
`render_video_generation_settings` monta o selectbox "Script Language" com
`format_func=video_language_label`, cujas opções são "Português (pt) 🇧🇷" etc.
Essas opções vivem em `div[role=option]` (listbox customizada do Streamlit), que
o guarda antigo (`closest(..., option)`) não cobria.

Os testes abaixo são de CONTRATO (skill testes-contrato): travam o desenho que
elimina a excepção, para nenhuma sessão futura reintroduzir a remoção.
"""

import io
import re
import tokenize
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def _strip_js_comments(source: str) -> str:
    """Só o que EXECUTA interessa: linhas de comentário saem da comparação."""
    return "\n".join(line for line in source.splitlines() if not line.strip().startswith("//"))


def _strip_python_comments(source: str) -> str:
    """Remove comentários Python reais (via tokenize, sem tocar em strings)."""
    lines = source.splitlines()
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                row = token.start[0]
                lines[row - 1] = lines[row - 1][: token.start[1]]
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return source
    return "\n".join(lines)


def _flag_bootstrap() -> str:
    """O JS do substituto de bandeiras (o que corre no documento do app)."""
    start = MAIN_SOURCE.index("_FLAG_RENDER_BOOTSTRAP = ")
    return _strip_js_comments(MAIN_SOURCE[start:MAIN_SOURCE.index("st.html(_FLAG_RENDER_BOOTSTRAP")])


def _theme_bootstrap() -> str:
    """O JS do detector de tema claro."""
    start = MAIN_SOURCE.index("_THEME_BOOTSTRAP = ")
    return _strip_js_comments(MAIN_SOURCE[start:MAIN_SOURCE.index("_FLAG_RENDER_BOOTSTRAP")])


# --------------------------------------------------------------------------
# 1. O observer nunca desanexa um nó que o React possui
# --------------------------------------------------------------------------

def test_flag_observer_never_removes_the_text_node_it_decorates():
    bootstrap = _flag_bootstrap()
    # `replaceWith` (e qualquer variante que desandeixe o nó) está proibida.
    assert "replaceWith" not in bootstrap
    assert "removeChild" not in bootstrap
    assert "node.remove()" not in bootstrap
    # Em vez disso: insere o fragmento ANTES e esvazia o nó — o React continua
    # a conseguir removê-lo e a bandeira aparece no mesmo sítio.
    assert "node.parentNode.insertBefore(fragment, node)" in bootstrap
    assert 'node.nodeValue = ""' in bootstrap


def test_flag_observer_keeps_out_of_react_list_containers():
    """Dropdown/menus são reconciliados por LISTA: nada de nós Injectados lá."""
    bootstrap = _flag_bootstrap()
    guard = re.search(r"closest\('([^']*)'\)", bootstrap)
    assert guard, "o guarda do replaceTextNode deixou de existir"
    for selector in ("option", 'role="listbox"', 'role="option"', 'role="menu"'):
        assert selector in guard.group(1), selector


def test_flag_observer_is_idempotent_after_emptying_the_node():
    """Nó esvaziado tem de ser ignorado na varredura seguinte (sem ciclo)."""
    bootstrap = _flag_bootstrap()
    assert "if (!node.nodeValue" in bootstrap


def test_flag_observer_stays_registered_only_once():
    bootstrap = _flag_bootstrap()
    assert "window.__thunderboltFlagObserver" in bootstrap


# --------------------------------------------------------------------------
# 2. O timer do tema não se acumula a cada rerun
# --------------------------------------------------------------------------

def test_theme_timer_is_cleared_before_a_new_one_is_created():
    theme = _theme_bootstrap()
    assert "window.clearInterval(window.__thunderboltThemeTimer)" in theme
    assert "window.__thunderboltThemeTimer = window.setInterval(applyTheme, 500)" in theme
    # e já não existe um setInterval "nu" a acumular
    assert not re.search(r"(?<![.\w])setInterval\((?!.*__thunderboltThemeTimer)", theme)


# --------------------------------------------------------------------------
# 3. Nenhum JS inline do projecto mexe nos nós do React
# --------------------------------------------------------------------------

def _project_python_sources() -> list[Path]:
    sources = []
    for folder in ("app", "hermes_ui", "integrations", "scripts"):
        base = ROOT / folder
        if not base.is_dir():
            continue
        sources.extend(
            path for path in base.rglob("*.py")
            if ".venv" not in path.parts and "node_modules" not in path.parts
        )
    return sources


def test_no_inline_script_removes_or_moves_react_owned_nodes():
    """Contrato geral: JS inline não pode remover/mover nós do documento.

    `existing.remove()` no detector de tema fica de fora da lista: esse <style>
    tem ID próprio e foi criado pelo mesmo script — o React nunca o possui.
    O que está prohibido é mexer em nós que o react-dom criou (foi o que
    produzia o NotFoundError).
    """
    forbidden = ("replaceWith", "removeChild", "replaceChild", "document.body.removeChild")
    for path in _project_python_sources():
        # Os bootstrap JS vivem dentro de strings Python: comments desses dois
        # mundos saem antes da comparação, para o contrato ser sobre o que
        # EXECUTA e não sobre o que o comentário explica.
        source = _strip_python_comments(_strip_js_comments(path.read_text(encoding="utf-8")))
        for snippet in forbidden:
            assert snippet not in source, f"{path.name} ainda usa {snippet}"


# --------------------------------------------------------------------------
# 4. Prova funcional: a lógica do guarda reconhece os contentores do Streamlit
# --------------------------------------------------------------------------

class _FakeElement:
    """Elemento mínimo para o `closest` do guarda (sem browser)."""

    def __init__(self, tag: str, *, role: str | None = None, parent: "_FakeElement | None" = None, node_value: str = "Português (pt) 🇧🇷"):
        self.tag = tag
        self.role = role
        self.parent = parent
        self.node_value = node_value
        self.replaced: list[str] = []

    def closest(self, selector: str) -> bool:
        wanted = [part.strip() for part in selector.split(",")]
        current = self
        while current is not None:
            for part in wanted:
                if part.startswith("[") and "=" in part:
                    attribute, value = part[1:-1].split("=", 1)
                    if attribute.strip() == "role" and current.role == value.strip('"'):
                        return True
                elif current.tag == part:
                    return True
            current = current.parent
        return False

    def insert_before(self, _fragment, _node) -> None:
        self.replaced.append("insert_before")


_GUARD_SELECTOR = 'img,script,style,noscript,textarea,input,option,[role="listbox"],[role="option"],[role="menu"],[role="menuitem"]'


@pytest.mark.parametrize("ancestors", [
    [("div", "listbox"), ("div", "option")],   # dropdown do selectbox
    [("div", "listbox")],
    [("div", "menu"), ("div", "menuitem")],
    [("input", None), ("div", None)],
    [("img", None)],
])
def test_guard_blocks_the_containers_the_react_reconciles_by_list(ancestors):
    element = _FakeElement("div")
    chain = element
    for tag, role in ancestors:
        chain.parent = _FakeElement(tag, role=role)
        chain = chain.parent
    assert element.closest(_GUARD_SELECTOR), ancestors


def test_guard_lets_plain_text_through():
    element = _FakeElement("div")
    chain = element
    for _ in range(3):
        chain.parent = _FakeElement("div")
        chain = chain.parent
    assert not element.closest(_GUARD_SELECTOR)