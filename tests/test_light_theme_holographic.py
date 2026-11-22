"""Fundo holografico (mesh gradient) no tema claro — contrato de fonte.

A implementação tem três peças que só o source apanha: a constante de CSS, o
JS de detecção do tema e o iframe que o entrega. Os dois temas são verificados
no browser à mão (medido: gradiente + sidebar branca + vidro no claro; tema
intacto no escuro) — aqui fica o contrato que impede a regressão.
"""

import ast
import html
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def _constantes() -> dict[str, object]:
    arvore = ast.parse(MAIN_SOURCE)
    valores: dict[str, object] = {}
    for node in arvore.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            nome = node.targets[0].id
            if nome in ("_HOLOGRAPHIC_MESH_CSS", "_HOLOGRAPHIC_THEME_JS"):
                valores[nome] = ast.literal_eval(node.value)
    return valores


def _iframe() -> str:
    """O HTML final do iframe, calculando a concatenação como o módulo faz."""
    consts = _constantes()
    js = consts["_HOLOGRAPHIC_THEME_JS"].replace(
        "__HOLOGRAPHIC_CSS__", consts["_HOLOGRAPHIC_MESH_CSS"]
    ).replace(chr(34), chr(38) + "quot;")
    return (
        '<iframe srcdoc="'
        + "<script>"
        + js
        + "</script>"
        + '" style="display:none" aria-hidden="true"></iframe>'
    )


CONSTANTES = _constantes()
CSS = CONSTANTES["_HOLOGRAPHIC_MESH_CSS"]
JS = CONSTANTES["_HOLOGRAPHIC_THEME_JS"]
IFRAME = _iframe()


# ---------------------------------------------------------------- o fundo pedido

def test_all_five_pastel_colours_are_in_the_mesh():
    """Cores exactas do pedido: rosa, azul, verde, amarelo e o azul do centro."""
    for cor in ("#ffc6ff", "#bde0fe", "#caffbf", "#fdffb6", "#a2d2ff"):
        assert cor in CSS, cor
    assert CSS.count("radial-gradient(") == 5


def test_the_mesh_is_animated_and_fixed():
    assert "@keyframes thunderbolt-holographic" in CSS
    assert "animation:thunderbolt-holographic 20s ease-in-out infinite alternate" in CSS
    assert "background-attachment:fixed" in CSS
    assert "background-size:150% 150%" in CSS


def test_sidebar_stays_white_and_readable():
    assert "[data-testid=\"stSidebar\"]" in CSS
    assert "background-color:#ffffff !important" in CSS
    assert "background-image:none !important" in CSS  # sem gradiente na sidebar
    assert "border-right" in CSS


def test_content_gets_the_glass_panel_for_legibility():
    assert "[data-testid=\"stMainBlockContainer\"]" in CSS
    assert "rgba(255,255,255,0.75)" in CSS
    assert "backdrop-filter:blur(12px)" in CSS
    assert "-webkit-backdrop-filter:blur(12px)" in CSS


def test_volatile_emotion_classes_are_not_used():
    """`.st-emotion-cache-*` é gerado por build — deixaria de corresponder."""
    assert "st-emotion-cache" not in CSS


def test_the_css_is_plain_css():
    """Armadilha real desta sessão: `//` não é comentário em CSS e calaria tudo."""
    assert "//" not in CSS
    assert CSS.lstrip().startswith("html,")


# ------------------------------------------------- detecção do tema (o iframe)

def test_the_iframe_carries_the_css_and_the_script():
    assert IFRAME.startswith('<iframe srcdoc="')
    assert IFRAME.endswith("</iframe>")
    assert "<script>" in IFRAME and "</script>" in IFRAME
    decodificado = html.unescape(IFRAME[IFRAME.index('srcdoc="') + 8 : IFRAME.index('" style=')])
    assert "radial-gradient(" in decodificado
    assert "placeholder__nao_existe" not in IFRAME
    assert "__HOLOGRAPHIC_CSS__" not in IFRAME


def test_double_quotes_are_escaped_or_the_attribute_would_close_early():
    """Sem `"` o atributo fechava a meio do CSS e o iframe nasceria vazio."""
    atributo = IFRAME[IFRAME.index('srcdoc="') + 8 : IFRAME.index('" style=')]
    assert chr(34) not in atributo
    assert (chr(38) + "quot;") in atributo


def test_the_script_detects_light_by_choice_or_by_rendered_text():
    assert "stActiveTheme-/-v2" in JS
    assert "=== 'Light'" in JS and "=== 'Dark'" in JS
    # sem escolha explícita: a cor do TEXTO (o holográfico nunca toca em texto)
    assert "getComputedStyle(parent.document.body).color" in JS
    assert "0.299 * r + 0.587 * g + 0.114 * b" in JS


def test_the_script_removes_the_css_when_the_theme_is_dark():
    """Tema escuro = CSS fora: o gradiente claro não pode tapar o escuro."""
    assert "if (theme() !== 'light')" in JS
    assert "existing.remove()" in JS
    assert "doc.getElementById(STYLE_ID)" in JS


def test_the_script_keeps_the_theme_fresh():
    """O React do Streamlit re-renderiza: o iframe re-aplica a cada 500 ms."""
    assert "setInterval(apply, 500)" in JS


def test_the_script_has_no_backslash_escapes():
    # Uma classe de escape (barra-d) dentro duma string não-raw do Python seria
    # comida; a cor é lida com uma classe de caracteres, sem nenhuma barra.
    assert "\\d" not in JS and "\\s" not in JS and "\\(" not in JS
    assert "replace(/[^0-9,]/g" in JS


# ------------------------------------------------------------- bloqueio da UI

def test_no_blocking_sleep_in_the_theme_block():
    bloco = MAIN_SOURCE.split("_HOLOGRAPHIC_MESH_CSS = ", 1)[1].split("\n_THEME_BOOTSTRAP", 1)[0]
    assert "time.sleep" not in bloco
    assert "while True" not in bloco


def test_the_iframe_is_injected_through_streamlit_markdown():
    assert "st.markdown(_HOLOGRAPHIC_THEME_IFRAME, unsafe_allow_html=True)" in MAIN_SOURCE
    # e não pelo `st.html`: o sanitizador retira-lhe os <script> (verificado)
    assert "st.html(_HOLOGRAPHIC" not in MAIN_SOURCE