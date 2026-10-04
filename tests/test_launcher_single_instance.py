"""Testes do single-instance guard e da telemetria de saída do launcher (0.9.48).

Cobre as correções do ciclo "servidor encerra sozinho":
- guard de instância única (launcher.lock + scripts/kill_tree.py) que termina
  a stack anterior antes de qualquer bind/spawn;
- reposição (restartExitCode) que para a árvore antiga ANTES de spawnar a nova;
- evento launcher_exiting com motivo em todos os caminhos de saída.

Nota: os testes funcionais usam apenas o modo --pid do helper (sem scan
global) para nunca tocar em instâncias reais do Thunderbolt durante a suíte.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CLI_SOURCE = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")
WORKFLOW_SOURCE = (ROOT / ".github" / "workflows" / "publish-npm.yml").read_text(encoding="utf-8")
KILL_TREE_PATH = ROOT / "scripts" / "kill_tree.py"


def _load_kill_tree():
    spec = importlib.util.spec_from_file_location("thunderbolt_kill_tree", KILL_TREE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeProcess:
    def __init__(self, pid, cmdline):
        self.pid = pid
        # psutil devolve sempre uma LISTA de argumentos; o fake tem de imitar.
        self._cmdline = cmdline if isinstance(cmdline, list) else [cmdline]

    def cmdline(self):
        return self._cmdline


def test_cli_claims_a_launcher_lock_in_the_state_directory():
    assert 'const launcherLockPath = join(diagnosticsDir, "launcher.lock")' in CLI_SOURCE
    assert "function claimLauncherLock()" in CLI_SOURCE
    assert "function launcherExiting(reason)" in CLI_SOURCE
    assert "rmSync(launcherLockPath" in CLI_SOURCE


def test_cli_guard_runs_before_the_public_port_bind_and_any_spawn():
    # A ordem é a essência do fix: guard -> lock -> bind -> workers/streamlit.
    guard_index = CLI_SOURCE.index("stopPreviousThunderboltStacks();")
    claim_index = CLI_SOURCE.index("claimLauncherLock();")
    listen_index = CLI_SOURCE.index("proxy.listen(publicPort")
    streamlit_index = CLI_SOURCE.index("startStreamlit();\n")
    assert guard_index < claim_index < listen_index < streamlit_index


def test_cli_guard_uses_the_psutil_helper_with_cleanup_mode():
    assert 'runKillTreeHelper(["--cleanup", String(process.pid)])' in CLI_SOURCE
    assert 'const killTreeHelper = resolve(root, "scripts", "kill_tree.py")' in CLI_SOURCE
    # O venv tem sempre psutil; o Python de sistema pode não ter.
    assert "const candidates = [venvPython, python]" in CLI_SOURCE


def test_ci_kill_tree_helper_accepts_survivor_exit_codes_and_retries_cleanup():
    # 0.9.49: o helper devolve exit 1 quando há sobreviventes (o JSON continua
    # válido); exigir status 0 fazia o guard registar falsos "indisponível" e
    # tentar de novo com um interpretador sem psutil. O resultado é aceite
    # sempre que o stdout é JSON, e sobreviventes repetem a limpeza uma vez.
    assert "if (result.stdout) {" in CLI_SOURCE
    assert "result.status === 0" not in CLI_SOURCE
    assert "summary = runKillTreeHelper" in CLI_SOURCE
    retry_block = CLI_SOURCE.split("if (Array.isArray(summary.survivors)", 1)[1].split("}", 1)[0]
    assert "runKillTreeHelper" in retry_block


def test_ci_registries_previous_instance_and_guard_errors():
    assert 'diagnostic("previous_instance_stopped"' in CLI_SOURCE
    assert 'diagnostic("single_instance_guard_error"' in CLI_SOURCE
    # 0.9.49: o guard inclui a causa do falhanço do helper (exit status/stderr).
    assert "helper_failure" in CLI_SOURCE


def test_cli_lifecycle_instrumentation_was_removed_but_exit_telemetry_stays():
    # 0.9.49 (Remover a instrumentação de diagnóstico): os eventos de
    # baseline/crash/lifecycle saíram; permanecem apenas a telemetria de saída
    # (launcher_exiting) e os eventos do single-instance guard.
    for removed in (
        "captureBaselineSnapshot",
        "captureCrashSnapshot",
        'diagnostic("streamlit_started"',
        'diagnostic("streamlit_exited"',
        'diagnostic("worker_started"',
        'diagnostic("worker_exited"',
        'diagnostic("restart_triggered"',
    ):
        assert removed not in CLI_SOURCE, removed


def test_ci_replacement_stops_the_old_stack_before_spawning_the_new_one():
    replacement_block = CLI_SOURCE.split('if (code === restartExitCode) {', 1)[1].split("if (streamlitStableTimer)", 1)[0]
    stop_index = replacement_block.index("stopStackComponents();")
    spawn_index = replacement_block.index('spawn(executable, ["--yes", "--prefer-online", "@danhachuel/thunderbolt"]')
    exit_index = replacement_block.index('launcherExiting("update");')
    assert stop_index < spawn_index, "a árvore antiga tem de parar antes do spawn da reposição"
    assert spawn_index < exit_index < replacement_block.index("process.exit(0);")


def test_ci_logs_launcher_exiting_on_every_exit_path_with_reason():
    # O shutdown pelos sinais grava o motivo e o launcher_exiting corre no
    # finishShutdown do stopWorker; crash cobre uncaughtException e o bind
    # falhado; update cobre a reposição.
    assert 'process.on("SIGINT", () => stopWorker("ctrl+c"));' in CLI_SOURCE
    assert 'process.on("SIGTERM", () => stopWorker("external_kill"));' in CLI_SOURCE
    assert 'launcherExiting(shutdownReason);' in CLI_SOURCE
    assert 'launcherExiting("update");' in CLI_SOURCE
    assert CLI_SOURCE.count('launcherExiting("crash")') >= 2
    assert 'process.on("uncaughtException"' in CLI_SOURCE
    assert 'diagnostic("launcher_exiting", { reason' in CLI_SOURCE


def test_ci_streamlit_exit_during_shutdown_logs_before_exiting():
    block = CLI_SOURCE.split("if (shuttingDown) {", 1)[1].split("if (code === restartExitCode)", 1)[0]
    assert "launcherExiting(shutdownReason" in block
    assert "process.exit(code" in block


def test_workflow_enforces_the_double_version_bump():
    assert "Sync pyproject.toml version with package.json" in WORKFLOW_SOURCE
    assert "node scripts/sync_pyproject_version.mjs --check" in WORKFLOW_SOURCE
    sync_source = (ROOT / "scripts" / "sync_pyproject_version.mjs").read_text(encoding="utf-8")
    assert '--check' in sync_source
    assert 'pyproject.toml' in sync_source


def test_kill_tree_marker_matching_covers_the_real_stack_shapes():
    kill_tree = _load_kill_tree()
    cases = {
        r"C:\venv\Scripts\python.exe -m hermes_ui.pipeline_worker": True,
        "/usr/bin/python3 -m hermes_ui.automation_worker": True,
        r"C:\app\scripts\streamlit_bootstrap.py run app\main.py": True,
        "node C:/cache/node_modules/@danhachuel/thunderbolt/scripts/cli.mjs": True,
        "npx.cmd --yes --prefer-online @danhachuel/thunderbolt": True,
        r"C:\MoneyPrinterTurbo\mpt_agent.py --root X": True,
        r"C:\cache\@danhachuel\thunderbolt\scripts\kill_tree.py --cleanup 1": False,
        r"C:\Windows\System32\notepad.exe readme.md": False,
        "": False,
    }
    for index, (cmdline, expected) in enumerate(cases.items()):
        process = _FakeProcess(9000 + index, cmdline)
        assert kill_tree.is_thunderbolt_process(process) is expected, cmdline


def test_kill_tree_pid_mode_kills_a_two_process_tree(tmp_path):
    # Teste funcional seguro: o modo --pid nunca faz scan global, alveja apenas
    # a árvore dummy criada aqui (o modo --cleanup é validado pelas asserções
    # de fonte do cli.mjs e pela arrancada real de uma única instância).
    parent = subprocess.Popen(
        [
            sys.executable, "-c",
            "import subprocess,sys,time\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)', 'hermes_ui.pipeline_worker'])\n"
            "print(child.pid, flush=True)\n"
            "time.sleep(60)",
            "hermes_ui.automation_worker",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        cwd=tmp_path,
    )
    try:
        child_pid = int(parent.stdout.readline().strip())
        completed = subprocess.run(
            [sys.executable, str(KILL_TREE_PATH), "--pid", str(parent.pid)],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        summary = json.loads(completed.stdout)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and (parent.poll() is None):
            time.sleep(0.2)
        assert not summary["survivors"], f"o helper reporta sobreviventes: {summary}"
        assert parent.poll() is not None, "o processo pai terminou"
        # O filho foi morto junto com a árvore (o comando não fica órfão).
        try:
            import psutil

            child_alive = psutil.Process(child_pid).is_running()
        except Exception:
            child_alive = False
        assert not child_alive, "o filho foi terminado com a árvore"
    finally:
        if parent.poll() is None:
            parent.kill()


def test_kill_tree_pid_mode_reports_a_missing_pid_gracefully():
    completed = subprocess.run(
        [sys.executable, str(KILL_TREE_PATH), "--pid", "999999999"],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    summary = json.loads(completed.stdout)
    assert summary["killed"] == []
    assert summary["survivors"] == []
