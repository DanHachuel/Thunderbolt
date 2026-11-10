"""1.0.52 — CIRCUIT BREAKER do launcher (fim do loop infinito de workers).

O utilizador reportou na 1.0.51: `thumbnail_worker`/`image_worker` a morrerem
instantaneamente no boot com KeyboardInterrupt (código 3221225786, durante
`import argparse`) e o launcher a reiniciar para sempre («a reiniciar em 5s»),
poluindo o terminal e prendo a consola. A detecção 1.0.20 (ImportError no
stderr) falhava porque não havia uma linha «No module named».

Contratos cobertos por este ficheiro:
- CIRCUIT BREAKER: morte MENOS de 10 s após o spawn = falha de boot; 3 falhas
  de boot seguidas cancelam o loop com `[ERRO FATAL] … Loop cancelado.`;
  vida >= 10 s zera o contador (era problema de execução, não de boot);
- o travão vale para CADA processo supervisionado: thumbnail, image, pipeline,
  automação e Streamlit (guarda + noteWorkerStarted + avaliador na saída);
- a detecção de dependências cobre KeyboardInterrupt e Fatal Python error;
- aviso amigável no `install` quando o lançamento vem de um PowerShell
  (ExecutionPolicy pode bloquear scripts) — e só nesse caso;
- prova de integração real: launcher arrancado com um intérprete que mata os
  workers no boot NÃO entra em loop e imprime a mensagem fatal.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CLI_SOURCE = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")

FATAL_MARKER = "[ERRO FATAL]"
FAST_FAIL_LIMIT = 3
FAST_FAIL_WINDOW_MS = 10_000


def _venv_python() -> Path | None:
    """Venv real do Thunderbolt (só com ele os probes de dependências passam)."""
    candidates = []
    override = os.environ.get("THUNDERBOLT_VENV") or os.environ.get("HERMES_VENV")
    if override:
        candidates.append(Path(override))
    candidates.append(
        Path(os.environ.get("LOCALAPPDATA", "")) / "THUNDERBOLT" / ".venv"
        if sys.platform == "win32"
        else Path.home() / ".thunderbolt" / ".venv"
    )
    for venv in candidates:
        python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        if python.is_file():
            return venv
    return None


# ---------------------------------------------------------------------------
# Contratos de source — a barra do CI para refactores do launcher
# ---------------------------------------------------------------------------


def test_circuit_breaker_contract_in_source():
    # Sintaxe literal do JS (10_000 tal como no launcher).
    assert f"const fastFailWindowMs = {FAST_FAIL_WINDOW_MS:_d};" in CLI_SOURCE
    assert f"const fastFailLimit = {FAST_FAIL_LIMIT};" in CLI_SOURCE
    assert "const workerBootTracker = new Map();" in CLI_SOURCE
    assert "function noteWorkerStarted(key)" in CLI_SOURCE
    assert "function workerBootFailedForGood(key)" in CLI_SOURCE
    assert "function reportFastFailLoop(" in CLI_SOURCE
    # A mensagem vermelha exigida pelo utilizador.
    assert "falhou ${fastFailLimit} vezes seguidas em menos de ${fastFailWindowMs / 1000}s" in CLI_SOURCE
    assert "Loop cancelado." in CLI_SOURCE
    assert "Verifique os logs ou execute" in CLI_SOURCE
    # Contador zera quando o processo viveu o suficiente (problema de execução).
    assert "if (lifetimeMs >= fastFailWindowMs) entry.fastFails = 0;" in CLI_SOURCE


def test_every_supervised_process_has_the_breaker():
    for start_fn, worker_key in (
        ("startQueueWorkers", "thumbnail"),
        # 1.0.73: o image worker passou a nascer em spawnImageWorker (respiro
        # de 500 ms depois do thumbnail) — a supervisão viajou com ele.
        ("spawnImageWorker", "image"),
        ("startPipelineWorker", "pipeline"),
        ("startAutomationWorker", "automation"),
        ("startStreamlit", "streamlit"),
    ):
        body = CLI_SOURCE.split(f"function {start_fn}(", 1)[1].split("\nfunction ", 1)[0]
        assert f'noteWorkerStarted("{worker_key}")' in body, f"{start_fn} não regista o arranque"
        assert f'workerBootFailedForGood("{worker_key}")' in body, f"{start_fn} não avalia o crash loop"
    # Flags de cancelamento: declaradas e respeitadas no guarda da SUA função
    # de arranque (um crash loop de um worker não pode ser desfeito pelo
    # monitor de 2 s).
    for flag, guard_fn in (
        ("queueWorkersFastFailDisabled", "startQueueWorkers"),
        ("pipelineFastFailDisabled", "startPipelineWorker"),
        ("automationFastFailDisabled", "startAutomationWorker"),
        ("streamlitFastFailDisabled", "startStreamlit"),
    ):
        assert f"let {flag} = false;" in CLI_SOURCE
        guard_body = CLI_SOURCE.split(f"function {guard_fn}(", 1)[1].split("\nfunction ", 1)[0]
        assert flag in guard_body, f"{flag} não trava o arranque em {guard_fn}"


def test_dependency_detection_covers_boot_deaths():
    # 1.0.52: KeyboardInterrupt junta-se ao padrão — o código 3221225786
    # (STATUS_DLL_INIT_FAILED) do relato do utilizador não deixava
    # «No module named» no stderr e a detecção 1.0.20 falhava.
    pattern_block = CLI_SOURCE.split("const dependencyFailurePattern = ", 1)[1].split("\n", 1)[0]
    for marker in ("ImportError", "ModuleNotFoundError", "Fatal Python error", "KeyboardInterrupt"):
        assert marker in pattern_block


def test_powershell_install_note_contract():
    assert '"Atenção: O PowerShell pode bloquear a instalação de scripts. Se falhar, use o CMD (Prompt de Comando)."' in CLI_SOURCE
    assert "function runningInsidePowerShell()" in CLI_SOURCE
    # Marcador rápido de ambiente + caminhada da cadeia de processos (CIM).
    assert "process.env.PSHOME" in CLI_SOURCE
    assert "Get-CimInstance Win32_Process" in CLI_SOURCE
    assert "POWERSHELL_PARENT" in CLI_SOURCE
    # A nota sai apenas no ramo do install.
    install_block = CLI_SOURCE.split('if (args[0] === "install" || args[0] === "--install")', 1)[1]
    assert "runningInsidePowerShell()" in install_block.split("run(process.execPath", 1)[0]


# ---------------------------------------------------------------------------
# Prova de integração real — o launcher NÃO entra em loop com workers mortos
# ---------------------------------------------------------------------------


def _write_shadow_argparse(directory: Path) -> Path:
    """argparse sombra: workers morrem no boot com o código do relato (3221225786).

    Qualquer outro processo (probes do launcher, kill_tree, Streamlit) recebe
    a argparse REAL da stdlib — a sombra só age nos workers.
    """
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "argparse.py").write_text(
        'import os, sys, sysconfig\n'
        'if "worker" in sys.argv[0] or "-m hermes_ui." in " ".join(sys.argv):\n'
        "    sys.stdout.flush()\n"
        "    sys.stderr.flush()\n"
        "    os._exit(3221225786)\n"
        '_stdlib = os.path.join(sysconfig.get_paths()["stdlib"], "argparse.py")\n'
        'with open(_stdlib, "r", encoding="utf-8") as _handle:\n'
        '    exec(compile(_handle.read(), _stdlib, "exec"), globals())\n',
        encoding="utf-8",
    )
    return directory


def _kill_process_tree(process: subprocess.Popen) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(process.pid)],
            capture_output=True,
            check=False,
        )
        return
    try:
        os.killpg(os.getpgid(process.pid), 9)
    except (ProcessLookupError, PermissionError, OSError):
        process.kill()


@pytest.mark.skipif(
    not shutil.which("node"),
    reason="node necessário para arrancar o launcher",
)
def test_launcher_cancels_crash_loop_instead_of_restarting_forever(tmp_path: Path):
    venv = _venv_python()
    if venv is None:
        pytest.skip("venv do Thunderbolt indisponível neste ambiente")
    shadow = _write_shadow_argparse(tmp_path / "shadow")
    home = tmp_path / "home"
    storage = home / "storage"
    out_path = tmp_path / "launcher.out"
    err_path = tmp_path / "launcher.err"

    environment = {
        **os.environ,
        "THUNDERBOLT_HOME": str(home),
        "THUNDERBOLT_STORAGE_DIR": str(storage),
        "THUNDERBOLT_VENV": str(venv),
        "PYTHONPATH": str(shadow),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }
    with out_path.open("wb") as out_file, err_path.open("wb") as err_file:
        process = subprocess.Popen(
            ["node", "scripts/cli.mjs", "--foreground"],
            cwd=str(ROOT),
            env=environment,
            stdout=out_file,
            stderr=err_file,
            start_new_session=sys.platform != "win32",
        )
        try:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                stderr_text = err_path.read_text(encoding="utf-8", errors="replace")
                if stderr_text.count(FATAL_MARKER) >= FAST_FAIL_LIMIT:
                    break  # thumbnail + image + pipeline já cancelaram
                time.sleep(1.0)
            stderr_text = err_path.read_text(encoding="utf-8", errors="replace")
        finally:
            _kill_process_tree(process)
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                pass

    # A mensagem fatal exigida, uma por processo supervisionado.
    assert stderr_text.count(FATAL_MARKER) >= FAST_FAIL_LIMIT
    assert "falhou 3 vezes seguidas em menos de 10s" in stderr_text
    assert "Loop cancelado." in stderr_text
    assert "O thumbnail worker falhou" in stderr_text
    assert "O image worker falhou" in stderr_text
    # SEM loop infinito: as duas primeiras mortes imprimem «terminou … a
    # reiniciar em 5s» e a TERCEIRA vai directo ao [ERRO FATAL] — nunca mais.
    assert stderr_text.count("thumbnail worker: terminou") == FAST_FAIL_LIMIT - 1
    assert stderr_text.count("image worker: terminou") == FAST_FAIL_LIMIT - 1
    assert stderr_text.count("a reiniciar em 5s") == (FAST_FAIL_LIMIT - 1) * 2
    # As mortes aconteceram no boot, durante o import do módulo do worker.
    assert stderr_text.count("thumbnail_worker.py") >= FAST_FAIL_LIMIT
    # Os logs próprios dos workers ficaram com o registo da morte.
    thumbnail_log = storage / "logs" / "thumbnail_worker.log"
    if thumbnail_log.is_file():
        assert "terminou" in thumbnail_log.read_text(encoding="utf-8", errors="replace")
