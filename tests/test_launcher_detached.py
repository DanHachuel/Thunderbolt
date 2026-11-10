"""1.0.89 — launcher descartável: servidor destacado, lock global, kill e logs.

Auditoria contra o PandaNews (2026-11-10) provou a diferença fundamental: lá o
backend é **destacado** e o launcher Node é descartável; aqui a stack estava
presa ao terminal e morria com ele. Estes contratos travam a arquitectura nova:

- spawn do servidor/workers: `detached: true` + `windowsHide: true` + `stdio` em
  ficheiro + `unref()` + `cwd: executionRoot` (runtime, nunca cache do npx);
- lock global `storage/state/thunderbolt.pid` (launcher + servidor + workers +
  porta), auto-kill no arranque e comando `thunderbolt kill` por código —
  sempre silencioso, nunca uma janela;
- Windows: interpretador BASE (pyvenv.cfg) + `PYTHONPATH` do venv — a armadilha
  do redirector, que abria uma consola nova para o neto;
- `--foreground` preserva o modo antigo (keep-alive, sinais, logs ao vivo);
- `thunderbolt logs` segue o ficheiro sem depender de `tail` no Windows.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI_SOURCE = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")


def test_default_run_is_detached_and_the_launcher_is_disposable():
    # a flag de foreground existe e é opt-in…
    assert 'args.includes("--foreground")' in CLI_SOURCE
    assert "THUNDERBOLT_FOREGROUND" in CLI_SOURCE
    # …mas o caminho por omissão é o destacado, que termina o launcher.
    block = CLI_SOURCE.split("if (!foregroundRequested) {", 1)[1].split("\nconst port =", 1)[0]
    assert "killServerInstances(" in block
    assert "spawnDetached(" in block
    assert "writeServerLock(" in block
    assert "esperarPorta(" in block
    assert "Servidor activo em background" in block
    assert "Para encerrar: npx thunderbolt kill" in block
    assert "Este terminal pode ser fechado" in block
    assert "process.exit(0);" in block


def test_detached_spawns_use_runtime_root_flags_and_unref():
    helper = CLI_SOURCE.split("function spawnDetached(", 1)[1].split("\nfunction detachedLogFd", 1)[0]
    assert "detached: true," in helper
    assert "windowsHide: true," in helper
    assert 'stdio: ["ignore", fd, fd]' in helper
    assert "filho.unref();" in helper
    assert "cwd: executionRoot," in helper
    assert "env: serverPythonEnv()," in helper


def test_server_and_workers_are_spawned_detached():
    block = CLI_SOURCE.split("if (!foregroundRequested) {", 1)[1].split("\nconst port =", 1)[0]
    # servidor da interface
    assert '[streamlitBootstrap, "run", main' in block
    # workers de fila (template string) + automação por demanda
    assert "`hermes_ui.${modulo}`" in block
    assert '"-m", `hermes_ui.${modulo}`' in block
    assert '"hermes_ui.automation_worker"' in block
    assert "hasScheduledAutomation() || hasPendingPipelineWork()" in block
    # cada um com log próprio em storage/logs (fora do .runtime)
    for nome in ("streamlit.log", "automation_worker.log", "pipeline_worker.log", "thumbnail_worker.log", "image_worker.log"):
        assert nome in block or nome in CLI_SOURCE


# ---------------------------------------------------------------------------
# Lock global + kill/auto-kill
# ---------------------------------------------------------------------------


def test_global_lock_lives_in_state_and_records_every_pid():
    assert 'const serverLockPath = join(diagnosticsDir, "thunderbolt.pid");' in CLI_SOURCE
    assert "function readServerLock()" in CLI_SOURCE
    assert "function writeServerLock(payload)" in CLI_SOURCE
    assert "function clearServerLock()" in CLI_SOURCE
    # o lock guarda o servidor E os workers (kill e auto-kill precisam de todos)
    write_block = CLI_SOURCE.split("function writeServerLock(payload)", 1)[1].split("\n}", 1)[0]
    assert "criado" in write_block
    lock_payload = CLI_SOURCE.split("writeServerLock({ launcher: null, server: serverPid", 1)[1].split("});", 1)[0]
    assert "workers" in lock_payload
    assert "port" in lock_payload


def test_kill_command_uses_code_never_signals_or_windows():
    assert 'args[0] === "kill" || args[0] === "stop"' in CLI_SOURCE
    assert "function comandoKill()" in CLI_SOURCE
    kill_block = CLI_SOURCE.split("function comandoKill()", 1)[1].split("\nfunction comandoLogs", 1)[0]
    assert "killTreeSilent(pid)" in kill_block
    assert "pidDaPorta(Number(serverPort))" in kill_block
    assert "clearServerLock()" in kill_block
    assert "process.exit(0);" in kill_block
    # taskkill sempre silencioso: windowsHide + stdio ignore (nenhuma janela)
    taskkill = CLI_SOURCE.split("function killTreeSilent(pid)", 1)[1].split("\n}", 1)[0]
    assert '"taskkill"' in taskkill or "taskkill" in taskkill
    assert '"/pid", String(pid), "/f", "/t"' in taskkill
    assert "windowsHide: true" in taskkill
    assert 'stdio: "ignore"' in taskkill
    assert "pid === process.pid" in taskkill  # nunca suicídio
    # POSIX: sinal no grupo (kill -pgid)
    assert "process.kill(-pid, \"SIGKILL\")" in taskkill


def test_auto_kill_runs_before_starting_the_new_instance():
    start_block = CLI_SOURCE.split("if (!foregroundRequested) {", 1)[1].split("\nconst port =", 1)[0]
    assert "killServerInstances(" in start_block
    auto = CLI_SOURCE.split("function killServerInstances(motivo", 1)[1].split("\nfunction comandoKill", 1)[0]
    assert "serverLockPids(lock)" in auto
    assert "pidDaPorta(Number(serverPort))" in auto
    assert "clearServerLock()" in auto
    # rede de segurança para o lock obsoleto: quem estiver dono da porta
    assert "donoPorta" in auto


# ---------------------------------------------------------------------------
# Windows: interpretador base + PYTHONPATH (armadilha do redirector do venv)
# ---------------------------------------------------------------------------


def test_windows_spawns_the_base_interpreter_with_venv_pythonpath():
    assert "function venvBasePython()" in CLI_SOURCE
    assert 'readFileSync(join(venvDir, "pyvenv.cfg"), "utf8")' in CLI_SOURCE
    assert "/^\\s*home\\s*=\\s*(.+)$/m" in CLI_SOURCE
    assert "function serverPython()" in CLI_SOURCE
    assert "function serverPythonEnv()" in CLI_SOURCE
    env_block = CLI_SOURCE.split("function serverPythonEnv()", 1)[1].split("\n}", 1)[0]
    assert 'join(venvDir, "Lib", "site-packages")' in env_block
    assert "PYTHONPATH" in env_block
    # o venv redirector NUNCA é usado directamente no Windows quando há base
    python_block = CLI_SOURCE.split("function serverPython()", 1)[1].split("\n}", 1)[0]
    assert "venvBasePython()" in python_block
    assert "resolve(base) !== resolve(venvPython)" in python_block


# ---------------------------------------------------------------------------
# Logs ao vivo (mitigação do risco B) — sem depender de `tail` no Windows
# ---------------------------------------------------------------------------


def test_logs_command_follows_the_file_without_tail():
    assert 'args[0] === "logs" || args[0] === "log"' in CLI_SOURCE
    assert "function comandoLogs(resto)" in CLI_SOURCE
    logs_block = CLI_SOURCE.split("function comandoLogs(resto)", 1)[1].split("\n// --- spawns destacados", 1)[0]
    assert 'join(storageDir, "logs", arquivo)' in logs_block
    assert "createReadStream(caminho" in logs_block
    assert "setInterval(seguir, 1000)" in logs_block
    assert "streamlit.log" in logs_block
    # atalhos por worker + launcher
    for nome in ("image_worker.log", "pipeline_worker.log", "thumbnail_worker.log", "automation_worker.log", "launcher_console.log"):
        assert nome in logs_block


def test_foreground_mode_keeps_the_old_supervised_stack():
    """`--foreground` = modo antigo: proxy, workers supervisionados, keep-alive."""
    assert "const foregroundRequested =" in CLI_SOURCE
    # o maquinario antigo continua depois do bloco destacado
    assert "stopPreviousThunderboltStacks();" in CLI_SOURCE
    assert "const keepAliveTimer = setInterval(() => {}, 1000);" in CLI_SOURCE
    assert "guardConsoleStream(process.stdout" in CLI_SOURCE
    assert "monitorWorkers();" in CLI_SOURCE


def test_storage_and_env_stay_out_of_the_runtime():
    """Mitigação do risco de dados: lock e logs vivem no storage da raiz."""
    assert 'const serverLockPath = join(diagnosticsDir, "thunderbolt.pid");' in CLI_SOURCE
    assert 'const streamlitLogPath = join(storageDir, "logs", "streamlit.log");' in CLI_SOURCE
    assert 'join(runtimeDir, "storage")' not in CLI_SOURCE
    assert "THUNDERBOLT_STORAGE_DIR: storageDir," in CLI_SOURCE
