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


def _signals_block(source: str) -> str:
    """Bloco de handlers de sinais (âncora única no comentário 1.0.74)."""
    import re

    return re.search(
        r"// 1\.0\.74 — SINAL DO TERMINAL ABSORVIDO.*?stopFileWatcher\.unref\(\);",
        source,
        flags=re.DOTALL,
    ).group(0)


def test_windows_ctrl_c_shuts_down_with_confirmation():
    """1.0.94 — no Windows o Ctrl+C encerra, mas só no SEGUNDO toque.

    O primeiro toque avisa (absorve o fantasma); um eco de rajada (< 1 s) não
    conta como confirmação. A 0.9.86 absorvia sem excepção — o que o utilizador
    rejeitou ("quero carregar Ctrl+C e fechar").
    """
    import re as _re

    _signals = _re.search(
        r"// 1\.0\.74 — SINAL DO TERMINAL ABSORVIDO.*?stopFileWatcher\.unref\(\);",
        CLI_SOURCE,
        flags=_re.DOTALL,
    )
    sigint_block = _signals.group(0).split("} else {", 1)[0]
    assert 'process.on("SIGINT"' in sigint_block
    assert 'stopWorker("ctrl+c")' in sigint_block  # o segundo Ctrl+C encerra
    assert 'console.log("[LAUNCHER] Encerrando o Thunderbolt (Ctrl+C)...");' in sigint_block
    # confirmação: 1 s–5 s entre toques; eco de rajada não conta
    assert "intervalo > 1000 && intervalo <= 5000" in sigint_block
    assert "terminal_echo_ignored" in sigint_block
    assert "ctrl_c_absorbed_windows" in sigint_block  # telemetria 0.9.86 mantida


def test_unix_sigint_stops_normally():
    """No Linux/macOS o Ctrl+C encerra normalmente (padrão CLI)."""
    import re as _re

    _signals = _re.search(
        r"// 1\.0\.74 — SINAL DO TERMINAL ABSORVIDO.*?stopFileWatcher\.unref\(\);",
        CLI_SOURCE,
        flags=_re.DOTALL,
    )
    unix_block = "} else {\n" + _signals.group(0).split("} else {", 1)[1].split('process.on("SIGBREAK"', 1)[0]
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
