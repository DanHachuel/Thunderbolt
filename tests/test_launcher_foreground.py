"""1.0.94 — launcher em FOREGROUND: o terminal fica ocupado e o Ctrl+C encerra.

Reversão explícita do modelo destacado/descartável da 1.0.89–1.0.93, rejeitado
pelo utilizador (banner verde e prompt de volta não eram o comportamento
desejado). Estes contratos travam a arquitectura reposta:

- o launcher arranca o Streamlit e os workers como filhos NORMAIS e **não sai**
  depois de arrancar — nenhum `spawnDetached`, nenhum `unref()` na stack;
- os logs continuam a sair no terminal (stdio do Streamlit por pipes, impressos
  pelo launcher) e o keep-alive explícito impede que o Node esvazie o event
  loop e devolva o prompt;
- Ctrl+C encerra (com confirmação no Windows), e os sinais fantasmas do
  MobaXterm — SIGHUP e rajadas de SIGINT — continuam absorvidos;
- o lock global, o `thunderbolt kill` e o `thunderbolt logs` sobrevivem à
  reversão (são úteis nos dois modelos).
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI_SOURCE = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. um único modo: foreground (nada de destaque, nada de launcher descartável)
# ---------------------------------------------------------------------------

def _windows_signal_block() -> str:
    """O bloco de handlers de sinal do Windows (ancorado no comentário 1.0.94).

    `if (platform() === "win32")` aparece antes (no killTreeSilent), por isso a
    âncora é o comentário do próprio handler — não a primeira ocorrência.
    """
    anchor = 'if (platform() === "win32") {\n  // 1.0.94 - CTRL+C PASSA A ENCERRAR'
    start = CLI_SOURCE.index(anchor)
    return CLI_SOURCE[start:].split("} else {", 1)[0]



def test_there_is_no_detached_mode_anymore():
    """O bloco destacado e os seus helpers desapareceram do launcher."""
    for gone in (
        "spawnDetached(",
        "detachedLogFd(",
        "esperarPorta(",
        "portaTcpAbertaAtiva(",
        "serverPythonEnv(",
        "venvBasePython(",
        "foregroundRequested",
        "THUNDERBOLT_LAUNCHER_MODE",
    ):
        assert gone not in CLI_SOURCE, f"ainda existe código do modo destacado: {gone}"


def test_no_green_background_banner():
    """O banner verde/\"rodando em segundo plano\" foi removido."""
    for gone in ("SEGUNDO PLANO", "RODANDO EM SEGUNDO PLANO", "Servidor activo em background", "Este terminal pode ser fechado"):
        assert gone not in CLI_SOURCE, f"ainda existe texto do modo destacado: {gone}"


def test_launcher_never_exits_right_after_starting():
    """Nenhum `process.exit(0)` no arranque da stack — o terminal fica ocupado."""
    # o arranque foreground termina no bloco do sinal/keep-alive, não numa saída
    start_block = CLI_SOURCE.split('killServerInstances("arranque foreground")', 1)[1]
    start_block = start_block.split("const port = process.env.THUNDERBOLT_PORT", 1)[0]
    assert "process.exit(0)" not in start_block, "o launcher sai depois de arrancar (volta o prompt)"
    # e o keep-alive continua no fim do ficheiro
    assert "const keepAliveTimer = setInterval(() => {}, 1000);" in CLI_SOURCE
    tail = CLI_SOURCE.rsplit("const keepAliveTimer = setInterval(() => {}, 1000);", 1)[-1]
    assert "keepAliveTimer.unref" not in CLI_SOURCE


def test_streamlit_and_workers_are_normal_children():
    """O servidor e os 4 workers nascem como filhos supervisionados do launcher."""
    # spawn directo do bootstrap do Streamlit dentro de startStreamlit
    streamlit = CLI_SOURCE.split("function startStreamlit()", 1)[1].split("\nfunction ", 1)[0]
    assert "spawn(python, [streamlitBootstrap," in streamlit
    assert '"--server.port", String(backendPort)' in streamlit
    assert 'stdio: ["ignore", "pipe", "pipe"]' in streamlit  # logs vão para o launcher imprimir
    # os 4 workers com ambiente completo e grupo próprio
    for modulo in ("automation_worker", "pipeline_worker", "thumbnail_worker", "image_worker"):
        spawns = [line for line in CLI_SOURCE.splitlines() if f'hermes_ui.{modulo}' in line and "spawn(" in line]
        assert spawns, f"worker {modulo} não é lançado pelo launcher"
    assert "creationFlags: workerCreationFlags()," in CLI_SOURCE
    assert "env: runtimeEnv" in CLI_SOURCE


def test_launcher_prints_the_servers_logs():
    """O output do Streamlit e dos workers continua a ser impresso no terminal."""
    assert 'process.stdout.write(chunk)' in CLI_SOURCE
    assert 'process.stderr.write(chunk)' in CLI_SOURCE
    assert "if (!shuttingDown)" in CLI_SOURCE


# ---------------------------------------------------------------------------
# 2. Ctrl+C encerra; os fantasmas do MobaXterm não
# ---------------------------------------------------------------------------


def test_ctrl_c_shuts_down_with_confirmation_on_windows():
    win_block = _windows_signal_block()
    assert 'process.on("SIGINT"' in win_block
    assert 'stopWorker("ctrl+c")' in win_block  # o segundo Ctrl+C encerra
    assert 'console.log("[LAUNCHER] Encerrando o Thunderbolt (Ctrl+C)...");' in win_block
    # confirmação: eco de rajada (<1 s) não conta; 1 s–5 s conta
    assert "intervalo > 1000 && intervalo <= 5000" in win_block
    assert "terminal_echo_ignored" in win_block  # eco de rajada não conta


def test_ctrl_c_prints_a_warning_before_the_confirmation():
    """O primeiro toque avisa em vez de encerrar (é a blindagem anti-fantasma)."""
    win_block = _windows_signal_block()
    assert "Ctrl+C ignorado para não interromper execuções" in win_block
    assert "cague Ctrl+C novamente" not in win_block  # sem texto quebrado
    assert "Carregue Ctrl+C novamente dentro de 5 s para encerrar." in win_block


def test_unix_ctrl_c_still_stops_immediately():
    unix_block = CLI_SOURCE.split("} else {", 1)[1].split('process.on("SIGBREAK"', 1)[0]
    assert 'process.on("SIGINT", () => stopWorker("ctrl+c"));' in unix_block


def test_sighup_stays_absorbed_on_windows():
    """O fantasma do MobaXterm (SIGHUP sem ninguém fechar nada) não encerra."""
    win_block = _windows_signal_block()
    assert 'process.on("SIGHUP", () => absorbTerminalSignal("SIGHUP"));' in win_block
    assert "stopWorker" not in win_block.split('process.on("SIGINT"', 1)[0]
    assert "[LAUNCHER] Sinal ${signal} ignorado. Mantendo processo activo." in CLI_SOURCE


def test_sigterm_and_sigbreak_are_never_absorbed():
    assert 'process.on("SIGBREAK", () => stopWorker("ctrl+break"));' in CLI_SOURCE
    assert 'process.on("SIGTERM", () => stopWorker("external_kill"));' in CLI_SOURCE
    assert 'stopWorker("stop-file")' in CLI_SOURCE


# ---------------------------------------------------------------------------
# 3. o maquinário que sobreviveu à reversão
# ---------------------------------------------------------------------------


def test_global_lock_and_kill_command_still_exist():
    assert 'const serverLockPath = join(diagnosticsDir, "thunderbolt.pid");' in CLI_SOURCE
    assert "function readServerLock()" in CLI_SOURCE
    assert "function writeServerLock(payload)" in CLI_SOURCE
    assert "function clearServerLock()" in CLI_SOURCE
    assert 'args[0] === "kill" || args[0] === "stop"' in CLI_SOURCE
    assert "function comandoKill()" in CLI_SOURCE
    kill_block = CLI_SOURCE.split("function comandoKill()", 1)[1].split("\nfunction comandoLogs", 1)[0]
    assert "killTreeSilent(pid)" in kill_block
    assert "pidDaPorta(Number(serverPort))" in kill_block
    taskkill = CLI_SOURCE.split("function killTreeSilent(pid)", 1)[1].split("\n}", 1)[0]
    assert '"/pid", String(pid), "/f", "/t"' in taskkill
    assert "windowsHide: true" in taskkill
    assert 'stdio: "ignore"' in taskkill


def test_auto_kill_runs_before_the_foreground_start():
    assert 'killServerInstances("arranque foreground")' in CLI_SOURCE
    auto = CLI_SOURCE.split("function killServerInstances(motivo", 1)[1].split("\nfunction comandoKill", 1)[0]
    assert "serverLockPids(lock)" in auto
    assert "pidDaPorta(Number(serverPort))" in auto
    assert "donoPorta" in auto


def test_logs_command_follows_the_file_without_tail():
    assert 'args[0] === "logs" || args[0] === "log"' in CLI_SOURCE
    logs_block = CLI_SOURCE.split("function comandoLogs(resto)", 1)[1].split("\nfunction ", 1)[0]
    assert 'join(storageDir, "logs", arquivo)' in logs_block
    assert "createReadStream(caminho" in logs_block
    assert "setInterval(seguir, 1000)" in logs_block


def test_single_instance_guard_and_console_guard_are_intact():
    assert "stopPreviousThunderboltStacks();" in CLI_SOURCE
    assert "function guardConsoleStream(" in CLI_SOURCE
    assert 'guardConsoleStream(process.stdout, "stdout");' in CLI_SOURCE
    assert 'guardConsoleStream(process.stderr, "stderr");' in CLI_SOURCE
    assert 'join(storageDir, "logs", "launcher_console.log")' in CLI_SOURCE
    assert "if (launcherConsoleDetached && isConsoleWriteFailure(error))" in CLI_SOURCE
