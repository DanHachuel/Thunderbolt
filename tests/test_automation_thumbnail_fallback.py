"""Prova de comportamento do fallback de thumbnail (sem Streamlit).

Extrai `_render_task_thumbnail` por ast e corre-a com um `st` falso que
regista o que foi renderizado — assim o teste sabe se saiu imagem, placeholder
ou nada.
"""
from __future__ import annotations

import ast
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


class _FakeStreamlit:
    def __init__(self):
        self.calls = []

    def image(self, path, **kwargs):
        self.calls.append(("image", str(path), kwargs))

    def markdown(self, markup, **kwargs):
        self.calls.append(("markdown", markup, kwargs))

    def caption(self, text):
        self.calls.append(("caption", text))


def _render_task_thumbnail(streamlit):
    """A função real do main.py, com o `st` injectado."""
    tree = ast.parse(MAIN_SOURCE)
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_render_task_thumbnail"
    )
    namespace = {"st": streamlit, "Path": Path}
    exec(compile(ast.unparse(function), "<main.py:_render_task_thumbnail>", "exec"), namespace)
    return namespace["_render_task_thumbnail"]


@pytest.fixture()
def render():
    streamlit = _FakeStreamlit()
    return _render_task_thumbnail(streamlit), streamlit


def test_missing_path_shows_the_placeholder(render):
    function, streamlit = render
    function(None)
    assert len(streamlit.calls) == 1
    kind, markup, _ = streamlit.calls[0]
    assert kind == "markdown"
    assert "Thumbnail não gerada" in markup
    assert "#F0F2F6" in markup  # bloco cinza: não fica buraco branco


def test_path_that_does_not_exist_shows_the_placeholder(render):
    function, streamlit = render
    function(Path(tempfile.gettempdir()) / "thumbnail-que-nao-existe-1081.png")
    assert streamlit.calls[0][0] == "markdown"
    assert "Thumbnail não gerada" in streamlit.calls[0][1]


def test_empty_file_still_shows_the_placeholder(render):
    """Ficheiro de 0 bytes: melhor o placeholder do que uma imagem partida."""
    function, streamlit = render
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
        empty = Path(handle.name)
    try:
        function(empty)
        # 0 bytes é ficheiro existente: o st.image é chamado (o Streamlit
        # comunica o erro), mas nunca se deixa a coluna sem nada.
        assert streamlit.calls, "nada foi renderizado"
        assert streamlit.calls[0][0] in {"image", "markdown"}
    finally:
        empty.unlink(missing_ok=True)


def test_real_file_renders_the_image_not_the_placeholder(render):
    function, streamlit = render
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
        handle.write(b"\x89PNG\r\n\x1a\n" + b"0" * 2048)
        real = Path(handle.name)
    try:
        function(real)
        kind, path, kwargs = streamlit.calls[0]
        assert kind == "image", "um ficheiro existente tem de renderizar a imagem"
        assert path == str(real)
        assert kwargs.get("width") == "stretch"
        assert not any(call[0] == "markdown" for call in streamlit.calls)
    finally:
        real.unlink(missing_ok=True)


def test_placeholder_is_never_a_blank_hole(render):
    function, streamlit = render
    for path in (None, Path("nao-existe.png"), Path(tempfile.gettempdir()) / ".thunderbolt-falta.png"):
        function(path)
    for call in streamlit.calls:
        assert call[0] == "markdown", f"caso sem imagem deixou a coluna vazia: {call}"
        assert "Thumbnail não gerada" in call[1]
