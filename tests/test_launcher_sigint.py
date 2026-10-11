"""Launcher SIGINT absorption on Windows (0.9.86).

O Windows 11 entrega o MESMO SIGINT para Ctrl+C real e para CTRL_C_EVENT
espúrio (navegadores a abrir, subprocesso .cmd em thread secundária).
Não é possível distingui-los — o launcher absorve SIGINT incondicionalmente
no Windows e oferece Ctrl+Break + .thunderbolt.stop como paragem.
No Linux/macOS, Ctrl+C continua funcionando.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI_SOURCE = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")


def test_windows_absorbs_sigint():
    """No Windows o SIGINT é absorvido — o launcher NÃO encerra."""
    sigint_block = CLI_SOURCE.split('if (platform() === "win32")', 1)[1].split("} else {", 1)[0]
    assert 'process.on("SIGINT"' in sigint_block
    assert 'stopWorker' not in sigint_block  # o handler NÃO chama stopWorker
    assert "ctrl_c_absorbed_windows" in sigint_block


def test_unix_sigint_stops_normally():
    """No Linux/macOS o Ctrl+C encerra normalmente (padrão CLI)."""
    unix_block = CLI_SOURCE.split("} else {", 1)[1].split("process.on(\"SIGBREAK\"", 1)[0]
    assert 'process.on("SIGINT", () => stopWorker("ctrl+c"));' in unix_block


def test_sigbreak_stops_on_all_platforms():
    """Ctrl+Break encerra o launcher (paragem legítima)."""
    assert 'process.on("SIGBREAK", () => stopWorker("ctrl+break"));' in CLI_SOURCE


def test_stop_file_watcher_exists():
    """O watcher do .thunderbolt.stop existe e corre a cada 3 segundos."""
    assert ".thunderbolt.stop" in CLI_SOURCE
    assert "stop_file_detected" in CLI_SOURCE
    assert "stopWorker(\"stop-file\")" in CLI_SOURCE
    assert "3000" in CLI_SOURCE  # intervalo


def test_no_reverted_solutions_reintroduced():
    """Nenhuma das soluções revertidas pode voltar."""
    for removed in (
        "SetConsoleCtrlHandler",
        "ctrl_c_ignored",
        "ctrl_c_burst_ignored",
        "ctrl_c_echo_absorbed",
        "ctrl_c_shutdown",
        "_foregroundProcess",
        "TERMINAL_PROCESS_NAMES",
        "checkLauncherOrphan",
        "captureCtrlCForensics",
        "THUNDERBOLT_DETACHED",
    ):
        assert removed not in CLI_SOURCE, removed
