"""1.0.83 - a versão tem de aparecer na sidebar, mesmo a correr do `.runtime`.

Regressão: com o runtime permanente (1.0.81) o `package.json` não era copiado
para `.runtime`. Como `app/main.py` lê a versão dele, a sidebar ficava sem o
número — o utilizador deixou de saber que versão está a correr.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
CLI = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")

WORKER_BLOCK = MAIN.split("def _pyproject_version", 1)[1].split("\ndef ", 1)[0]


@pytest.fixture(scope="module")
def version_reader():
    """A função real `_pyproject_version`, extraída por ast."""
    tree = ast.parse(MAIN)
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_pyproject_version"
    )
    namespace: dict = {"re": re, "ROOT": ROOT}
    exec(compile(ast.unparse(function), "<main.py:_pyproject_version>", "exec"), namespace)
    return namespace["_pyproject_version"]


def _read_version_from(root: Path) -> str:
    """Executa `_pyproject_version` real com um ROOT dado."""
    tree = ast.parse(MAIN)
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_pyproject_version"
    )
    namespace: dict = {"re": re, "ROOT": root}
    exec(compile(ast.unparse(function), "<main.py:_pyproject_version>", "exec"), namespace)
    return namespace["_pyproject_version"]()


def test_version_falls_back_to_pyproject_when_package_json_is_missing():
    """O runtime pode não ter package.json — a versão continua a ser lida."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "1.0.83"\n', encoding="utf-8"
        )
        assert _read_version_from(root) == "1.0.83"


def test_version_reader_returns_empty_when_nothing_is_available():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        assert _read_version_from(Path(tmp)) == ""


def test_sidebar_renders_the_version_span():
    """O título da sidebar tem o span da versão (não pode desaparecer)."""
    assert 'st.markdown(f\'<div class="tb-brand"><span class="tb-brand-name">Thunderbolt</span>{version_markup}</div>\', unsafe_allow_html=True)' in MAIN
    assert 'version_markup = f\'<span class="tb-brand-version">{APP_VERSION_LABEL}</span>\'' in MAIN
    assert 'class="tb-brand-version"' in MAIN
    assert "opacity:.62" in MAIN  # cinza/atenuado, como pedido


def test_app_version_reads_environment_then_files():
    """A leitura da versão tem 3 fontes, começando pelo ambiente (1.0.88)."""
    assert "def _app_version() -> str:" in MAIN
    assert "THUNDERBOLT_VERSION" in MAIN
    assert "APP_VERSION = _app_version()" in MAIN
    # e o package.json/pyproject continuam como fallback
    assert "package.json" in MAIN
    assert "def _pyproject_version" in MAIN


def test_runtime_copy_includes_package_json():
    """O `package.json` é código: tem de ser copiado para o `.runtime`."""
    targets = CLI.split("const RUNTIME_COPY_TARGETS = [", 1)[1].split("];", 1)[0]
    assert '"package.json"' in targets, "package.json fora da whitelist: a versão desaparece no runtime"
    assert '"pyproject.toml"' in targets
