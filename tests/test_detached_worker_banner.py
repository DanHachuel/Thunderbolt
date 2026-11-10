"""1.0.90 — fim do falso aviso «Worker de automação não está activo».

RELATO: com a 1.0.89 (modelo destacado, launcher descartável) a interface
mostrava o banner amarelo a mandar o utilizador «iniciar pelo launcher»
mesmo depois de `npx thunderbolt` — porque o launcher já tinha saído e o
heartbeat do worker estava frio.

CAUSA RAIZ: a UI media «sistema operacional» por «launcher vivo». No modo
destacado o launcher cumpre o papel escrevendo o lock global e saindo: o
terminal pode fechar e o sistema continua. Exigir o launcher vivo é medir a
coisa errada.

FIX: a UI passa a reconhecer o modo destacado (`THUNDERBOLT_LAUNCHER_MODE=detached`, com o
lock global como segunda fonte) e, quando não há launcher a supervisionar mas
há demanda, repõe o `automation_worker` em background.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
CLI = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")
WORKER = (ROOT / "hermes_ui" / "automation_worker.py").read_text(encoding="utf-8")

HELPERS = ("_launcher_rodando_destacado", "_worker_automation_operacional", "_iniciar_worker_automacao_sob_demanda")


@pytest.fixture(scope="module")
def compiled_helpers():
    """Os helpers reais, extraídos por ast com as dependências mínimas."""
    namespace: dict = {
        "os": os, "json": json, "sys": sys, "Path": Path, "Any": Any,
        "subprocess": subprocess, "datetime": __import__("datetime").datetime,
        "STORAGE": ROOT / "storage", "ROOT": ROOT,
        "read_json": lambda name, default: default, "hasPendingPipelineWork": lambda: False,
    }
    for node in ast.parse(MAIN).body:
        if isinstance(node, ast.FunctionDef) and node.name in HELPERS:
            exec(compile(ast.unparse(node), f"<{node.name}>", "exec"), namespace)
    return namespace


@pytest.fixture(autouse=True)
def _clean_environment():
    os.environ.pop("THUNDERBOLT_LAUNCHER_MODE", None)
    yield
    os.environ.pop("THUNDERBOLT_LAUNCHER_MODE", None)


def test_detached_mode_removes_the_false_warning(compiled_helpers):
    """O cenário do relato: launcher destacado + worker morto = sistema operacional."""
    funcs = {name: compiled_helpers[name] for name in HELPERS}
    os.environ["THUNDERBOLT_LAUNCHER_MODE"] = "detached"
    assert funcs["_launcher_rodando_destacado"]() is True
    assert funcs["_worker_automation_operacional"]({"alive": False}) is True


def test_manual_python_run_without_stack_still_warns(compiled_helpers):
    """`python app.py` sem stack continua a precisar do aviso."""
    os.environ.pop("THUNDERBOLT_LAUNCHER_MODE", None)
    lock = ROOT / "storage" / "state" / "thunderbolt.pid"
    backup = lock.read_text(encoding="utf-8") if lock.is_file() else None
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(json.dumps({"server": None, "workers": {}}), encoding="utf-8")
        compiled_helpers["STORAGE"] = ROOT / "storage"
        assert compiled_helpers["_worker_automation_operacional"]({"alive": False}) is False
    finally:
        if backup is None:
            lock.unlink(missing_ok=True)
        else:
            lock.write_text(backup, encoding="utf-8")


def test_server_lock_alone_means_detached(compiled_helpers):
    """Stack de pé descoberta pelo lock global, mesmo sem a variável de ambiente."""
    lock = ROOT / "storage" / "state" / "thunderbolt.pid"
    backup = lock.read_text(encoding="utf-8") if lock.is_file() else None
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(json.dumps({"server": 1, "workers": {"automation": 2}}), encoding="utf-8")
        assert compiled_helpers["_launcher_rodando_destacado"]() is True
    finally:
        if backup is None:
            lock.unlink(missing_ok=True)
        else:
            lock.write_text(backup, encoding="utf-8")


def test_alive_worker_is_always_operational(compiled_helpers):
    assert compiled_helpers["_worker_automation_operacional"]({"alive": True}) is True


def test_launcher_injects_the_detached_marker():
    """O launcher marca o ambiente dos filhos como destacado."""
    assert 'env.THUNDERBOLT_LAUNCHER_MODE = "detached";' in CLI
    assert "serverPythonEnv" in CLI


def test_ui_starts_the_worker_on_demand():
    """A UI repõe o worker quando não há launcher a supervisionar."""
    assert "def _iniciar_worker_automacao_sob_demanda() -> bool:" in MAIN
    assert "_iniciar_worker_automacao_sob_demanda()" in MAIN
    assert "[SISTEMA] A iniciar worker de automação em background..." in MAIN
    assert "automation_on" in MAIN
    assert "hasPendingPipelineWork()" in MAIN


def test_ui_does_not_duplicate_the_launcher_job():
    """Com launcher destacado de pé, a UI não arranca o worker (evita duplicar)."""
    helper = MAIN.split("def _iniciar_worker_automacao_sob_demanda", 1)[1].split("\ndef ", 1)[0]
    assert "_launcher_rodando_destacado()" in helper
    assert "return False" in helper


def test_worker_lock_lives_in_state_and_accepts_legacy():
    """O lock passa a storage/state/ (onde a UI lê) e o local antigo é aceite."""
    assert 'def _lock_paths()' in WORKER
    assert 'storage.STORAGE / "state" / LOCK_FILENAME' in WORKER
    assert "storage.STORAGE / LOCK_FILENAME" in WORKER  # legado


def test_worker_lock_release_cleans_every_location():
    """Um lock velho na raiz não pode envenenar o próximo arranque."""
    release = WORKER.split("def _release_lock", 1)[1].split("\ndef ", 1)[0]
    assert "_lock_paths()" in release


def test_no_keep_alive_reintroduced_for_detached_mode():
    """O modo destacado não volta a prender o launcher (regra do AGENTS.md)."""
    detached = CLI.split("if (!foregroundRequested) {", 1)[1].split("\n}", 1)[0]
    assert "process.exit(0)" in detached
    assert "setInterval" not in detached
