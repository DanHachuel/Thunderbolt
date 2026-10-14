"""Gate estrutural (0.9.94, item 2): nenhum módulo do pipeline lê tasks.json
directamente — toda a leitura passa por domain.load_tasks, para que tarefas
antigas sejam sempre normalizadas antes de qualquer uso."""

from __future__ import annotations

import ast
from pathlib import Path

import hermes_ui.domain as domain

HERMES_UI_DIR = Path(domain.__file__).resolve().parent


def _direct_task_reads(path: Path) -> list[tuple[int, str]]:
    """Devolve (linha, função) de cada leitura directa de tasks.json no módulo."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    reads: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else (func.attr if isinstance(func, ast.Attribute) else "")
        if name not in {"read_json", "load_state"}:
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        if node.args[0].value != "tasks.json":
            continue
        reads.append((node.lineno, name))
    return reads


def _load_tasks_body_lines(path: Path) -> set[int]:
    """Linhas do corpo de load_tasks() — a única leitura directa sancionada."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "load_tasks":
            return set(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return set()


def test_all_critical_task_reads_go_through_load_tasks():
    """Nenhuma rota do pipeline (hermes_ui/*) pode ler tasks.json directamente.

    Excepções documentadas:
    - ``storage.py``: camada de armazenamento (mecânica própria de recuperação
      e migração de ficheiros) — não pode importar domain (import circular).
    - ``domain.load_tasks``: É a implementação da migração — a única leitura
      directa sancionada; todos os outros módulos têm de passar por ela.
    """
    sanctioned = _load_tasks_body_lines(HERMES_UI_DIR / "domain.py")
    violations: list[str] = []
    for path in sorted(HERMES_UI_DIR.glob("*.py")):
        if path.name == "storage.py":
            continue
        for lineno, func_name in _direct_task_reads(path):
            if path.name == "domain.py" and lineno in sanctioned:
                continue
            violations.append(f"{path.name}:{lineno} ({func_name})")
    assert not violations, (
        "leituras directas de tasks.json fora de load_tasks(): " + ", ".join(violations)
    )


def test_load_tasks_remains_the_only_sanctioned_direct_read_in_domain():
    """O domain só mantém UMA leitura directa de tasks.json (a do load_tasks)."""
    direct = _direct_task_reads(HERMES_UI_DIR / "domain.py")
    assert len(direct) == 1, f"esperado 1 leitura directa (load_tasks), encontradas: {direct}"
    assert direct[0][1] == "read_json"
    assert direct[0][0] in _load_tasks_body_lines(HERMES_UI_DIR / "domain.py")


def test_load_tasks_preserves_failure_markers_for_display(tmp_path, monkeypatch):
    """0.9.94: a migração em leitura é só de schema — error/failure_api
    pertencem à falha, não ao schema; as projecções (logs, notificações,
    MCP) e os write-backs precisam de ver e preservar a falha original."""
    monkeypatch.setenv("HERMES_STORAGE_DIR", str(tmp_path / "storage"))
    from hermes_ui import storage
    from hermes_ui.domain import load_tasks

    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.BLUEPRINTS = storage.STORAGE / "blueprints"
    storage.ensure_storage()
    storage.write_json("tasks.json", [{
        "id": "video_failed",
        "state": "failed",
        "stage": "edit",
        "error": "Timeout do Motor",
        "failure_api": "Pexels API",
        "failure_config_fields": "pexels_api_keys",
    }])

    tasks = load_tasks()

    assert tasks[0]["stage"] == "topic"  # schema normalizado
    assert tasks[0]["error"] == "Timeout do Motor"  # falha preservada
    assert tasks[0]["failure_api"] == "Pexels API"
    assert tasks[0]["failure_config_fields"] == "pexels_api_keys"


def test_migrate_task_for_requeue_still_clears_failure_markers():
    """Na re-fila (retry/remake) os marcadores de falha continuam a ser limpos."""
    from hermes_ui.domain import migrate_task

    task = {"id": "t", "state": "failed", "stage": "edit", "error": "x", "failure_api": "y"}
    migrated = migrate_task(task, for_requeue=True)

    assert "error" not in migrated
    assert "failure_api" not in migrated
    assert migrated["stage"] == "topic"
    assert migrated["schema_version"] == 1
