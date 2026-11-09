"""Prova de COMPORTAMENTO do ícone de estado, sem Streamlit e sem stubs globais.

As duas funções são extraídas do `app/main.py` por `ast` e executadas num
namespace isolado, com um `_task_artifact_path` mínimo. Assim o teste corre o
código REAL (não uma cópia) sem precisar de importar a aplicação inteira.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def _extract_function(name: str) -> str:
    """Código-fonte de uma função de topo do main.py."""
    tree = ast.parse(MAIN_SOURCE)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.unparse(node)
    raise AssertionError(f"função {name} não encontrada em app/main.py")


@pytest.fixture(scope="module")
def status_icon():
    """`_video_task_status_icon` do main.py, com o catálogo real ao lado."""
    namespace: dict = {"Any": object}
    # caminho de artefactos mínimo: o teste controla quando o vídeo "existe"
    namespace["_task_artifact_path"] = lambda task, kind: (
        Path(task["artifacts"][kind]["path"]) if task.get("artifacts", {}).get(kind, {}).get("path") else None
    )
    exec(compile(_extract_function("_catalog_task_state"), "<main.py:_catalog_task_state>", "exec"), namespace)
    exec(compile(_extract_function("_video_task_status_icon"), "<main.py:_video_task_status_icon>", "exec"), namespace)
    return namespace["_video_task_status_icon"]


CASES = [
    # (tarefa, ícone esperado, porque)
    ({"state": "done"}, " ✅", "concluído"),
    ({"state": "failed"}, " ❌", "falhou"),
    ({"state": "error"}, " ❌", "erro"),
    ({"state": "doing"}, "", "a produzir"),
    ({"state": "to_do"}, "", "na fila"),
    ({"state": "standby"}, "", "em espera"),
    ({"state": "cancelled"}, "", "cancelado"),
    ({"state": "blocked"}, "", "bloqueado"),
    ({"state": ""}, "", "sem estado"),
    ({}, "", "tarefa vazia"),
    ({"state": "estado_desconhecido"}, "", "estado fora da lista"),
    # sinónimos que o catálogo normaliza para "done"
    ({"state": "completed"}, " ✅", "sinónimo de concluído"),
    ({"state": "published"}, " ✅", "já publicado"),
    ({"state": "finished"}, " ✅", "terminado"),
    # falhou só no upload, com o vídeo pronto: o card confirma "done"
    ({"state": "failed", "video_ready": True, "artifacts": {"video": {"path": "v.mp4"}}}, " ✅", "falhou no upload, vídeo pronto"),
    # done ainda sem Artefacto: o estado manda
    ({"state": "done", "artifacts": {}}, " ✅", "concluído sem artefacto"),
]


@pytest.mark.parametrize("task,expected,reason", CASES, ids=lambda value: str(value) if isinstance(value, str) else "-")
def test_status_icon_for_every_state(status_icon, task, expected, reason):
    assert status_icon(task) == expected, f"caso: {reason}"


def test_icon_is_appended_never_prefixed(status_icon):
    """O ícone tem de vir no FIM do título (com o espaço à esquerda)."""
    icon = status_icon({"state": "done"})
    assert icon.startswith(" ")
    assert icon.strip() == "✅"
    assert status_icon({"state": "failed"}).strip() == "❌"
