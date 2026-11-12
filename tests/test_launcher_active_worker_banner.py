"""1.0.94 — fim do falso aviso «Worker de automação não está activo».

RELATO (5.ª regressão): com o launcher a correr em foreground o aviso voltou a
aparecer. A UI media «sistema operacional» por uma marca que só existia no modo
destacado; no foreground o ambiente do Streamlit não tinha NENHUMA marca e a
interface mandava o utilizador «iniciar pelo launcher» com o launcher à sua
frente.

CAUSA RAIZ: duas marcas diferentes a fingir a mesma coisa. `THUNDERBOLT_LAUNCHER_MODE`
descrevia o MODO (só destacado) e a UI usava-a como sinónimo de «launcher vivo».

FIX: o launcher injecta `THUNDERBOLT_LAUNCHER_ACTIVE=1` no ambiente de TODOS os
filhos (servidor Streamlit e os 4 workers, em qualquer modo) e a UI decide por
essa marca: sem launcher activo E sem worker vivo, aí sim vale o aviso — para
quem corre o Python à mão sem stack.

Este ficheiro substitui `tests/test_detached_worker_banner.py` (o contrato que
ele prendia era o do modo destacado, revertido na 1.0.94).
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

HELPERS = ("_launcher_activo", "_worker_automation_operacional", "_iniciar_worker_automacao_sob_demanda")
MARKER = "THUNDERBOLT_LAUNCHER_ACTIVE"
LOCK = ROOT / "storage" / "state" / "thunderbolt.pid"


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
    os.environ.pop(MARKER, None)
    yield
    os.environ.pop(MARKER, None)


@pytest.fixture
def sem_lock():
    """O lock global fora do caminho (guarda/restaura o que lá estiver)."""
    backup = LOCK.read_text(encoding="utf-8") if LOCK.is_file() else None
    LOCK.unlink(missing_ok=True)
    yield
    if backup is None:
        LOCK.unlink(missing_ok=True)
    else:
        LOCK.write_text(backup, encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. o launcher marca TODOS os filhos
# ---------------------------------------------------------------------------


def test_launcher_injects_the_active_marker_in_the_shared_environment():
    """A marca vive no `runtimeEnv` — o ambiente de TODOS os spawns."""
    bloco = CLI.split("const runtimeEnv = {", 1)[1].split("};", 1)[0]
    assert f'{MARKER}: "1"' in bloco


def test_the_marker_reaches_the_streamlit_server_and_every_worker():
    """Servidor da interface e os 4 workers herdam o ambiente marcado."""
    streamlit = CLI.split("function startStreamlit()", 1)[1].split("\nfunction ", 1)[0]
    assert "env: { ...runtimeEnv," in streamlit
    for modulo in ("automation_worker", "pipeline_worker", "thumbnail_worker", "image_worker"):
        spawns = [line for line in CLI.splitlines() if f"hermes_ui.{modulo}" in line and "spawn(" in line]
        assert spawns, f"o worker {modulo} não é lançado pelo launcher"
    assert CLI.count("env: runtimeEnv") >= 4


def test_the_marker_is_not_the_old_mode_variable():
    """A marca fala da ORIGEM (launcher), não do modo — nomes não se confundem."""
    assert MARKER in CLI
    assert f'{MARKER}: "detached"' not in CLI
    assert f'{MARKER}: "foreground"' not in CLI


# ---------------------------------------------------------------------------
# 2. a UI só acusa o utilizador quando não há launcher mesmo
# ---------------------------------------------------------------------------


def test_foreground_launcher_removes_the_false_warning(compiled_helpers, sem_lock):
    """O cenário do relato: launcher em foreground + worker morto = sistema activo."""
    os.environ[MARKER] = "1"
    assert compiled_helpers["_launcher_activo"]() is True
    assert compiled_helpers["_worker_automation_operacional"]({"alive": False}) is True


def test_manual_python_run_without_stack_still_warns(compiled_helpers, sem_lock):
    """`python app/main.py` sem launcher continua a precisar do aviso."""
    assert compiled_helpers["_launcher_activo"]() is False
    assert compiled_helpers["_worker_automation_operacional"]({"alive": False}) is False


def test_running_stack_without_the_environment_variable_is_forgiven(compiled_helpers):
    """Stack deixada por uma sessão anterior: o lock global é a segunda fonte."""
    backup = LOCK.read_text(encoding="utf-8") if LOCK.is_file() else None
    try:
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        LOCK.write_text(json.dumps({"server": 1, "workers": {"automation": 2}}), encoding="utf-8")
        assert compiled_helpers["_launcher_activo"]() is True
    finally:
        if backup is None:
            LOCK.unlink(missing_ok=True)
        else:
            LOCK.write_text(backup, encoding="utf-8")


def test_stale_lock_without_pids_does_not_silence_the_warning(compiled_helpers, sem_lock):
    """Lock vazio (stack morta) não pode servir de desculpa."""
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(json.dumps({"server": None, "workers": {}}), encoding="utf-8")
    assert compiled_helpers["_launcher_activo"]() is False


def test_alive_worker_is_always_operational(compiled_helpers, sem_lock):
    assert compiled_helpers["_worker_automation_operacional"]({"alive": True}) is True


# ---------------------------------------------------------------------------
# 3. uma única fonte de verdade para as abas de automação
# ---------------------------------------------------------------------------


def test_every_automation_tab_uses_the_shared_banner_helper():
    """Nenhuma aba volta a ter lógica própria do aviso (foi assim que regressou)."""
    assert "def _render_worker_automacao_status(" in MAIN
    for aba in ("render_tiktok_automation", "render_automation"):
        bloco = MAIN.split(f"def {aba}(", 1)[1].split("\ndef ", 1)[0]
        assert "_render_worker_automacao_status(worker_status)" in bloco, f"{aba} não usa o helper partilhado"
    # e o aviso existe num único sítio
    assert MAIN.count('st.warning("Worker de automação não está activo.') == 1


def test_the_helper_never_warns_when_the_launcher_is_active():
    """A ordem das verificações: vivo → launcher activo → aviso."""
    helper = MAIN.split("def _render_worker_automacao_status(", 1)[1].split("\ndef ", 1)[0]
    assert helper.index('if worker_status.get("alive")') < helper.index("if _launcher_activo():") < helper.index('st.warning("Worker de automação')
    assert 'os.environ.get("THUNDERBOLT_LAUNCHER_ACTIVE", "").strip() == "1"' in MAIN


def test_every_tab_tries_to_restore_the_worker_before_judging_it():
    """Ambas as abas repõem o worker sob demanda antes de mostrar o estado."""
    for aba in ("render_tiktok_automation", "render_automation"):
        bloco = MAIN.split(f"def {aba}(", 1)[1].split("\ndef ", 1)[0]
        assert "_iniciar_worker_automacao_sob_demanda()" in bloco, f"{aba} não tenta repor o worker"


# ---------------------------------------------------------------------------
# 4. a UI não duplica o trabalho do launcher
# ---------------------------------------------------------------------------


def test_ui_does_not_duplicate_the_launcher_job(compiled_helpers):
    """Com o launcher de pé, a UI não arranca o worker — evita dois workers."""
    os.environ[MARKER] = "1"
    assert compiled_helpers["_iniciar_worker_automacao_sob_demanda"]() is False


def test_ui_still_spawns_the_worker_on_its_own_without_a_launcher(compiled_helpers, sem_lock):
    """Corrida manual com demanda: a UI lança o worker em background."""
    helper = MAIN.split("def _iniciar_worker_automacao_sob_demanda", 1)[1].split("\ndef ", 1)[0]
    assert "subprocess.Popen(" in helper
    assert "hermes_ui.automation_worker" in helper
    assert "CREATE_NO_WINDOW" in helper
    assert "[SISTEMA] A iniciar worker de automação em background..." in helper


# ---------------------------------------------------------------------------
# 5. o lock do worker continua onde a UI o lê
# ---------------------------------------------------------------------------


def test_worker_lock_lives_in_state_and_accepts_legacy():
    worker = (ROOT / "hermes_ui" / "automation_worker.py").read_text(encoding="utf-8")
    assert "def _lock_paths()" in worker
    assert 'storage.STORAGE / "state" / LOCK_FILENAME' in worker
    assert "storage.STORAGE / LOCK_FILENAME" in worker  # legado


def test_worker_lock_release_cleans_every_location():
    worker = (ROOT / "hermes_ui" / "automation_worker.py").read_text(encoding="utf-8")
    release = worker.split("def _release_lock", 1)[1].split("\ndef ", 1)[0]
    assert "_lock_paths()" in release
