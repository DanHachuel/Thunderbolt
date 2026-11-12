"""Blindagem do launcher contra sinais fantasma do terminal (0.9.86 → 1.0.94).

O Windows 11 entrega o MESMO SIGINT para Ctrl+C real e para CTRL_C_EVENT
espúrio (navegadores a abrir, subprocesso .cmd em thread secundária) — a
teleometria regista 17 717 eventos, muitos em rajadas de milissegundos.

1.0.94: **o SIGINT no Windows passou a confirmação em dois toques** (regra 2 do
AGENTS.md). O primeiro toque avisa e NÃO encerra — é o fantasma; o segundo, com
1 s–5 s de intervalo, encerra a stack inteira. Um eco de rajada (< 1 s) não
conta como confirmação. Absorver para sempre foi a solução de que o utilizador
não gostou (a app deixava de fechar); encerrar ao primeiro toque devolvia o
«fecha sozinho». Crava: `tests/test_launcher_ctrl_c_logic.py`.

O SIGHUP (o outro fantasma, 82 `console_closed` na telemetria) continua
**absorvido**: morre sem que ninguém feche nada.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI_SOURCE = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")


def test_windows_sigint_confirms_before_stopping():
    """1.0.94: no Windows o 1.º SIGINT avisa e o 2.º encerra a stack."""
    import re as _re

    _signals = _re.search(
        r"// 1\.0\.74 — SINAL DO TERMINAL ABSORVIDO.*?stopFileWatcher\.unref\(\);",
        CLI_SOURCE,
        flags=_re.DOTALL,
    )
    win_block = _signals.group(0).split("} else {", 1)[0]
    assert 'process.on("SIGINT"' in win_block
    assert "ctrl_c_absorbed_windows" in win_block
    # o handler Windows já sabe encerrar — mas só no SEGUNDO toque confirmado.
    assert 'stopWorker("ctrl+c")' in win_block
    # e continua a reconhecer o evento para a telemetria.
    assert "ctrl_c_absorbed_windows" in win_block


def test_windows_sighup_stays_absorbed():
    """O outro fantasma (CTRL_CLOSE/LOGOFF) continua absorvido no Windows."""
    import re as _re

    _signals = _re.search(
        r"// 1\.0\.74 — SINAL DO TERMINAL ABSORVIDO.*?stopFileWatcher\.unref\(\);",
        CLI_SOURCE,
        flags=_re.DOTALL,
    )
    win_block = _signals.group(0).split("} else {", 1)[0]
    assert 'process.on("SIGHUP"' in win_block
    assert "absorbTerminalSignal" in win_block
    sig_hup = win_block.split('process.on("SIGHUP"', 1)[1]
    assert "stopWorker" not in sig_hup.split("process.on(", 1)[0]


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


def test_sighup_stops_on_all_platforms():
    """Fecho da janela encerra o launcher (não deixa workers órfãos)."""
    assert 'process.on("SIGHUP", () => stopWorker("console_closed"));' in CLI_SOURCE


def test_sigterm_stops_on_all_platforms():
    """SIGTERM (kill externo) encerra o launcher."""
    assert 'process.on("SIGTERM", () => stopWorker("external_kill"));' in CLI_SOURCE


def test_stop_file_watcher_exists():
    """O watcher do .thunderbolt.stop existe e corre a cada 3 segundos."""
    assert ".thunderbolt.stop" in CLI_SOURCE
    assert "stop_file_detected" in CLI_SOURCE
    assert 'stopWorker("stop-file")' in CLI_SOURCE
    assert "3000" in CLI_SOURCE


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
        "launch_thunderbolt",
    ):
        assert removed not in CLI_SOURCE, removed
