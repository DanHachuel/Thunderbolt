"""1.0.85 — o launcher nunca devolve o prompt sozinho (stdin, sinais, npx.cmd).

Relato: o terminal (PowerShell/MobaXterm) continuava a devolver o prompt
`PS C:\...>` sozinho após alguns minutos, com a interface ainda viva — o
processo pai (`npx.cmd`) morria com o sinal de console e levava o Node do
launcher consigo, ou a stream de `stdin` era fechada sem ninguém a tratar.

Contratos:
- ``process.stdin.resume()`` está activo e os eventos de fim/erro do stdin
  NUNCA encerram o launcher (a paragem é deliberada);
- os sinais de console espúrios continuam absorvidos no Windows
  (``SIGINT``/``SIGHUP``) e os sinais de paragem legítima
  (``SIGTERM``/``SIGBREAK``) continuam a encerrar (regra AGENTS.md);
- existe o wrapper ``bin/start.js`` que corre o launcher no MESMO processo
  Node (sem a camada batch do ``npx.cmd``) e é distribuído no pacote;
- a guarda de consola (EPIPE/espelho) está aplicada a stdout **e** stderr.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI_SOURCE = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")
PACKAGE = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))


def test_stdin_is_resumed_and_never_stops_the_launcher():
    assert "process.stdin.resume();" in CLI_SOURCE
    # os eventos de stdin são registados e nunca chamam stopWorker/exit.
    assert 'for (const stdinEvent of ("end", "close", "error"))' in CLI_SOURCE
    assert "diagnostic(`stdin_${stdinEvent}`" in CLI_SOURCE
    # nenhum caminho de stdin encerra o processo (recorte do bloco 1.0.85).
    stdin_block = CLI_SOURCE.split("process.stdin.resume();", 1)[1].split("ordem de paragem", 1)[0]
    assert "process.exit" not in stdin_block
    assert "stopWorker" not in stdin_block
    assert "shuttingDown = true" not in stdin_block


def test_keep_alive_timer_and_console_guard_are_still_in_place():
    # 1.0.74 — handle referenciado (sem unref) impede o Node de esvaziar o loop.
    assert "const keepAliveTimer = setInterval(() => {}, 1000);" in CLI_SOURCE
    assert "void keepAliveTimer;" in CLI_SOURCE
    assert "keepAliveTimer.unref" not in CLI_SOURCE
    # espelho + guarda em stdout e stderr (consola morta não mata o launcher).
    assert 'guardConsoleStream(process.stdout, "stdout");' in CLI_SOURCE
    assert 'guardConsoleStream(process.stderr, "stderr");' in CLI_SOURCE
    assert "launcherConsoleDetached" in CLI_SOURCE


def test_spurious_console_signals_stay_absorbed_on_windows():
    assert 'process.on("SIGINT"' in CLI_SOURCE
    assert 'process.on("SIGHUP"' in CLI_SOURCE
    assert 'absorbTerminalSignal("SIGHUP")' in CLI_SOURCE
    assert "ignorado. Mantendo processo activo." in CLI_SOURCE


def test_legitimate_stop_signals_are_not_absorbed():
    """Regra AGENTS.md: SIGTERM/SIGBREAK são paragens legítimas em todas as
    plataformas — absorvê-los quebraria o encerramento deliberado."""
    assert 'process.on("SIGBREAK", () => stopWorker("ctrl+break"));' in CLI_SOURCE
    assert 'process.on("SIGTERM", () => stopWorker("external_kill"));' in CLI_SOURCE


def test_start_wrapper_runs_the_launcher_without_the_batch_layer():
    """O npx.cmd (batch) morre com o sinal de console antes de o Node absorver:
    o wrapper corre o launcher no MESMO processo Node."""
    wrapper = ROOT / "bin" / "start.js"
    assert wrapper.is_file(), "bin/start.js não existe"
    content = wrapper.read_text(encoding="utf-8")
    assert 'import "../scripts/cli.mjs";' in content
    assert "child_process" not in content  # zero spawn: mesmo processo
    assert "spawn(" not in content
    # distribuído no pacote (senão o wrapper não chega a quem instala)
    assert "bin/start.js" in PACKAGE["files"]
    # alternativa documentada no README
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "node bin/start.js" in readme
    assert "npm start" in readme


def test_detached_console_mirrors_logs_without_process_exit():
    """Consola desvinculada = daemon silencioso: escrita vai para o espelho e
    o processo NUNCA sai por causa do terminal."""
    assert "launcherConsoleMirrorPath" in CLI_SOURCE
    assert "appendFileSync(launcherConsoleMirrorPath" in CLI_SOURCE
    # uncaughtException só absorve falhas de escrita da consola; o resto é crash
    # real — mas o espelho guarda sempre o detalhe antes de qualquer saída.
    assert "mirrorConsoleOutput" in CLI_SOURCE
    assert 'process.on("uncaughtException"' in CLI_SOURCE
