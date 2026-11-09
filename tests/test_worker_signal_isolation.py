"""1.0.71 — isolamento dos workers dos sinais do console (fim do 0xC000013A).

O relato: `image_worker` e `thumbnail_worker` a morrerem repetidamente com o
código **3221225786** (= 0xC000013A, `STATUS_CONTROL_C_EXIT`) e o loop de
reinício cancelado pelo circuit breaker. Esse código é a assinatura de um
processo que recebeu CTRL_C_EVENT/CTRL_BREAK_EVENT e não o tratou: o
terminal (MobaXterm/PowerShell) entrega o Ctrl+C a **todos os processos do
grupo** e os workers — criados sem grupo próprio pelo launcher — morriam com
o sinal do utilizador.

Contratos cobertos:
- o launcher cria cada worker num grupo de processos PRÓPRIO no Windows
  (`creationFlags: CREATE_NEW_PROCESS_GROUP` = 0x00000200), para o sinal do
  console não os atingir; POSIX fica em 0 (o isolamento é noutra camada);
- o stdin continua `ignore` e a saída em pipes — nada de funcionamento
  alterado; o encerramento continua a ser o do launcher (`child.kill()`);
- o subprocesso de render do worker (`_run_video_helper_once`) também leva
  o grupo próprio, sem perder o `CREATE_NO_WINDOW` nem o `start_new_session`
  de POSIX;
- o cancelamento de tarefa (`_stop_process`) não depende de grupos — usa
  psutil terminate/kill (o contrato tem de sobreviver à mudança).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CLI_SOURCE = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")
WORKER_SOURCE = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")

STATUS_CONTROL_C_EXIT = 3221225786
CREATE_NEW_PROCESS_GROUP = 0x00000200


# ---------------------------------------------------------------------------
# Launcher (Node) — grupo próprio em cada spawn de worker
# ---------------------------------------------------------------------------


def test_launcher_defines_the_isolation_constant():
    assert "const WINDOWS_CREATE_NEW_PROCESS_GROUP = 0x00000200;" in CLI_SOURCE
    assert CREATE_NEW_PROCESS_GROUP == 512  # 0x00000200
    assert "function workerCreationFlags()" in CLI_SOURCE
    assert "process.platform === \"win32\"" in CLI_SOURCE
    # O comentário documenta o sintoma exacto do relato.
    assert "0xC000013A" in CLI_SOURCE or "STATUS_CONTROL_C_EXIT" in CLI_SOURCE


def test_every_supervised_worker_spawn_uses_the_isolation_flag():
    for module in ("automation_worker", "pipeline_worker", "thumbnail_worker", "image_worker"):
        marker = f'spawn(python, ["-m", "hermes_ui.{module}"]'
        assert marker in CLI_SOURCE, f"spawn de {module} não encontrado"
        block = CLI_SOURCE.split(marker, 1)[1].split("});", 1)[0]
        assert "creationFlags: workerCreationFlags()," in block, (
            f"{module} continua sem grupo próprio (morria com Ctrl+C do console)"
        )


def test_worker_isolation_helper_semantics():
    """O helper devolve o grupo novo no Windows e 0 no POSIX (nunca undefined)."""
    helper_body = CLI_SOURCE.split("function workerCreationFlags()", 1)[1].split("\n}", 1)[0]
    assert "WINDOWS_CREATE_NEW_PROCESS_GROUP" in helper_body
    assert "0" in helper_body  # retorno POSIX


def test_worker_isolation_does_not_break_the_stdin_contract():
    """O isolamento NÃO mexe no stdin/stdout: os pipes ficam como estavam."""
    for module in ("thumbnail_worker", "image_worker", "pipeline_worker"):
        marker = f'spawn(python, ["-m", "hermes_ui.{module}"]'
        block = CLI_SOURCE.split(marker, 1)[1].split("});", 1)[0]
        assert 'stdio: ["ignore", "pipe", "pipe"]' in block


# ---------------------------------------------------------------------------
# Worker (Python) — subprocesso de render isolado
# ---------------------------------------------------------------------------


def _fake_os(name: str):
    """Namespace mínimo com ``name`` — evita corromper o ``os`` global.

    Patchar ``pipeline_worker.os.name`` mexia no módulo ``os`` REAL e o
    ``pathlib`` dos fixtures seguintes passava a instalar ``PosixPath`` em
    Windows (INTERNALERROR no gate). O helper só lê ``os.name``.
    """
    from types import SimpleNamespace

    return SimpleNamespace(name=name)


def test_render_spawn_flags_isolate_the_render_on_windows(monkeypatch):
    from hermes_ui import pipeline_worker

    # POSIX primeiro: o isolamento é 0 (camada do start_new_session).
    monkeypatch.setattr(pipeline_worker, "os", _fake_os("posix"))
    assert pipeline_worker._render_spawn_creationflags() == 0
    if os.name != "nt":
        # As constantes de criação são Windows-only; em POSIX não existem e
        # macará-las seria um AttributeError (foi o crash do gate no Linux).
        assert not hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP")
        return
    monkeypatch.setattr(pipeline_worker, "os", _fake_os("nt"))
    flags = pipeline_worker._render_spawn_creationflags()
    assert flags & subprocess.CREATE_NEW_PROCESS_GROUP
    assert flags & subprocess.CREATE_NO_WINDOW


def test_render_spawn_uses_the_helper_flags():
    assert "creationflags=_render_spawn_creationflags()," in WORKER_SOURCE
    assert "start_new_session=os.name != \"nt\"," in WORKER_SOURCE  # POSIX intacto


def test_stop_process_does_not_depend_on_process_groups():
    """O cancelamento tem de continuar a funcionar com o grupo próprio.

    `_stop_process` mata por psutil (terminate/kill = TerminateProcess), que
    actua sobre a árvore de processos e não sobre grupos de console.
    """
    block = WORKER_SOURCE.split("def _stop_process(", 1)[1].split("\ndef ", 1)[0]
    assert "root.terminate()" in block
    assert "root.kill()" in block
    assert "os.killpg" in block  # caminho POSIX (start_new_session) intacto
    assert "GenerateConsoleCtrlEvent" not in block  # ninguém depende de sinais de console


# ---------------------------------------------------------------------------
# Provas reais e valor do código do relato
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name != "nt", reason="as constantes Windows só existem em Windows")
def test_windows_child_spawns_with_new_process_group(tmp_path: Path):
    """Um filho criado com CREATE_NEW_PROCESS_GROUP arranca e responde normal.

    Prova de que a flag de isolamento não quebra o spawn no Windows (o launcher
    passa-a nos 4 workers supervisionados).
    """
    script = tmp_path / "child.js"
    script.write_text("process.stdout.write('alive');", encoding="utf-8")
    result = subprocess.run(
        ["node", str(script)],
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        timeout=60,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "alive"


def test_status_control_c_exit_value_is_documented():
    """O código do relato (3221225786) fica gravado no contrato do teste."""
    assert STATUS_CONTROL_C_EXIT == 0xC000013A
    assert "STATUS_CONTROL_C_EXIT" in CLI_SOURCE
    assert sys.platform in {"win32", "linux", "darwin"}  # sanity do import


# ---------------------------------------------------------------------------
# 1.0.80 — consola morta não mata Worker: sem stdout herdado + CREATE_NO_WINDOW
# ---------------------------------------------------------------------------
#
# O keep-alive do launcher resolveu o terminal desvinculado, mas os workers
# secundários continuavam a cair com 3221225786 (0xC000013A) na
# inicialização: o spawn herdava stdout da consola (`inherit`) e o primeiro
# write do worker — depois de o terminal morrer — matava o processo. Duas
# camadas de defesa, cravadas aqui:
#   1. launcher: nenhum filho supervisionado herda stdout; todos ganham
#      CREATE_NO_WINDOW (0x08000000) além do grupo próprio;
#   2. Python: cada worker ignora SIGINT no arranque (antes dos imports
#      pesados), para um evento de console tardio não o matar.


SUPERVISED_MODULES = ("automation_worker", "pipeline_worker", "thumbnail_worker", "image_worker")


def _spawn_block(module: str) -> str:
    marker = f'spawn(python, ["-m", "hermes_ui.{module}"]'
    return CLI_SOURCE.split(marker, 1)[1].split("});", 1)[0]


def _stdio_line(block: str) -> str:
    """A linha ``stdio: [...]`` do bloco (comentários podem citar 'inherit')."""
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("stdio:"):
            return stripped
    return ""


def test_no_supervised_worker_inherits_the_console_streams():
    """Nenhum spawn de worker pode usar `inherit` (a consola morre com o terminal).

    O automation_worker era o último com `stdio: ["ignore", "inherit", "pipe"]`
    — o vector documentado do 0xC000013A pós-desvinculação.
    """
    for module in SUPERVISED_MODULES:
        stdio = _stdio_line(_spawn_block(module))
        assert "inherit" not in stdio, f"{module} ainda herda uma stream da consola: {stdio}"
        assert stdio.startswith('stdio: ["ignore"'), f"{module}: o stdin nunca pode ser herdado ({stdio})"
    # os workers de fila mantêm o contrato stdio-seguro (pipe + log próprio).
    for module in ("pipeline_worker", "thumbnail_worker", "image_worker"):
        assert 'stdio: ["ignore", "pipe", "pipe"]' in _spawn_block(module)


def test_worker_flags_include_create_no_window():
    """workerCreationFlags() leva CREATE_NO_WINDOW (0x08000000) no Windows."""
    assert "const WINDOWS_CREATE_NO_WINDOW = 0x08000000;" in CLI_SOURCE
    helper_body = CLI_SOURCE.split("function workerCreationFlags()", 1)[1].split("\n}", 1)[0]
    assert "WINDOWS_CREATE_NO_WINDOW" in helper_body
    # o grupo próprio NÃO sai (0xC000013A pelo sinal do console).
    assert "WINDOWS_CREATE_NEW_PROCESS_GROUP" in helper_body
    # PROIBIDO DETACHED_PROCESS (0x00000008) — ver tests/test_no_detached_process.py.
    assert "0x00000008" not in helper_body


def test_supervised_spawns_hide_the_windows_console():
    for module in SUPERVISED_MODULES:
        assert "windowsHide: true" in _spawn_block(module), f"{module} pode abrir janela de consola"
    streamlit_block = CLI_SOURCE.split('child = spawn(python, [streamlitBootstrap', 1)[1].split("});", 1)[0]
    assert "windowsHide: true" in streamlit_block


def test_python_workers_ignore_sigint_at_startup():
    """Cada worker blinda o SIGINT no Windows ANTES dos imports pesados."""
    heavy_markers = ("import psutil", "import requests", "import logging", "import argparse", "from hermes_ui", "from .")
    for module in ("pipeline_worker", "automation_worker", "image_worker", "thumbnail_worker"):
        source = (ROOT / "hermes_ui" / f"{module}.py").read_text(encoding="utf-8")
        guard = "signal.signal(signal.SIGINT, signal.SIG_IGN)"
        assert guard in source, f"{module} não ignora SIGINT no arranque"
        assert 'if sys.platform == "win32":' in source
        # a blindagem corre antes de qualquer import pesado/logging.
        heavy_positions = [source.index(marker) for marker in heavy_markers if marker in source]
        assert source.index(guard) < min(heavy_positions), (
            f"{module}: a blindagem de sinais tem de correr antes dos imports pesados"
        )
