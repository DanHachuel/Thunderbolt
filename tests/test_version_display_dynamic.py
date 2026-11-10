"""1.0.88 — a versão da sidebar tem de ser dinâmica (nunca velha, nunca fixa).

RELATO: a sidebar mostrava `1.0.82` com o utilizador a correr a `1.0.87`.

CAUSA RAIZ (provada): com o runtime permanente (`.runtime`) a app corre de uma
CÓPIA do código. A versão era lida de `ROOT/package.json`, e como o utilizador
ainda não tinha corrido o `install` depois da actualização, o ficheiro dentro
do `.runtime` continuava em 1.0.82 — a cópia estava correcta, apenas velha.

FIX: a versão passa a ser injectada pelo launcher no ambiente
(`THUNDERBOLT_VERSION`), que sabe sempre a versão do pacote em execução. Os
ficheiros continuam como fallback (package.json e pyproject.toml).
"""
from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
CLI = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def compile_version_functions():
    """Compila as funções reais de versão contra uma raiz dada (sem importar a app)."""

    def build(root: Path):
        tree = ast.parse(MAIN)
        namespace: dict = {"re": re, "json": json, "os": os, "ROOT": root}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in ("_pyproject_version", "_app_version", "display_version"):
                exec(compile(ast.unparse(node), f"<{node.name}>", "exec"), namespace)
        return namespace

    return build


@pytest.fixture(autouse=True)
def _clean_version_environment():
    """Nenhum teste depende do ambiente herdado do shell."""
    os.environ.pop("THUNDERBOLT_VERSION", None)
    yield
    os.environ.pop("THUNDERBOLT_VERSION", None)


def _sandbox(compile_version_functions, tmp_path, *, env=None, package=None, pyproject=None):
    """Executa `_app_version` com raiz e ambiente controlados (raiz = tmp_path)."""
    os.environ.pop("THUNDERBOLT_VERSION", None)
    if env is not None:
        os.environ["THUNDERBOLT_VERSION"] = env
    if package is not None:
        (tmp_path / "package.json").write_text(json.dumps({"version": package}), encoding="utf-8")
    if pyproject is not None:
        (tmp_path / "pyproject.toml").write_text(f'[project]\nversion = "{pyproject}"\n', encoding="utf-8")
    namespace = compile_version_functions(tmp_path)
    return namespace["_app_version"]()


def test_environment_version_wins_over_stale_runtime_files(compile_version_functions, tmp_path):
    """O cenário do relato: .runtime velho + ambiente novo dá a versão nova."""
    assert _sandbox(compile_version_functions, tmp_path, env="1.0.87", package="1.0.82", pyproject="1.0.82") == "1.0.87"


def test_package_json_is_used_when_no_environment(compile_version_functions, tmp_path):
    assert _sandbox(compile_version_functions, tmp_path, env=None, package="1.0.99", pyproject="1.0.82") == "1.0.99"


def test_pyproject_is_the_last_file_fallback(compile_version_functions, tmp_path):
    assert _sandbox(compile_version_functions, tmp_path, env=None, package=None, pyproject="1.0.82") == "1.0.82"


def test_missing_everything_returns_empty(compile_version_functions, tmp_path):
    assert _sandbox(compile_version_functions, tmp_path, env=None, package=None, pyproject=None) == ""


def test_no_version_is_hardcoded_in_the_source():
    """Nenhuma versão pode estar escrita no código."""
    for literal in ('return "1.0.', 'APP_VERSION = "1.', 'version = "1.0.'):
        assert literal not in MAIN, f"versão fixa no código: {literal}"


def test_app_version_reads_the_environment_first():
    """A função nova existe e começa pelo ambiente."""
    assert "def _app_version() -> str:" in MAIN
    assert "THUNDERBOLT_VERSION" in MAIN
    helper = MAIN.split("def _app_version()", 1)[1].split("\ndef ", 1)[0]
    assert helper.index("THUNDERBOLT_VERSION") < helper.index("package.json")
    assert "APP_VERSION = _app_version()" in MAIN


def test_launcher_injects_the_version_into_the_environment():
    """O launcher injecta THUNDERBOLT_VERSION em TODOS os filhos."""
    assert "THUNDERBOLT_VERSION: packageVersion," in CLI
    assert 'const packageVersion' in CLI
    # e o runtimeEnv (que alimenta app, workers e bootstrap) leva a variável
    runtime_env = CLI.split("const runtimeEnv = {", 1)[1].split("};", 1)[0]
    assert "THUNDERBOLT_VERSION" in runtime_env


def test_runtime_copy_keeps_the_version_files():
    """package.json e pyproject.toml continuam na whitelist de cópia."""
    targets = CLI.split("const RUNTIME_COPY_TARGETS = [", 1)[1].split("];", 1)[0]
    assert '"package.json"' in targets
    assert '"pyproject.toml"' in targets


def test_version_files_are_copied_verbatim_no_template():
    """A cópia é directa (cpSync): o que está no pacote é o que vai para o runtime."""
    assert "cpSync(source, resolve(runtimeDir, target)" in CLI
    assert "force: true" in CLI
