"""Blindagem da stack contra Ctrl+C espúdios da consola do Windows (0.9.71).

Evidência do incidente (08-09/10/2026): um CTRL_C_EVENT atingia toda a
consola partilhada (npx → launcher node → workers → uv/MPT/ffmpeg) sem
ninguém tocar no teclado — o launcher saía com reason "ctrl+c", o worker
de vídeo entrava em auto-pausa com a fila intacta e o MPT morria com
KeyboardInterrupt a meio da escrita dos frames (tarefa video_7c85d5e04d
interrompida duas vezes no mesmo padrão). A stack passa a ser imune:

- launcher: Ctrl+C isolado é registado e ignorado; encerrar exige duplo;
- workers: SetConsoleCtrlHandler(None, TRUE) ignora o CTRL_C_EVENT;
- árvore MPT: CREATE_NEW_PROCESS_GROUP isenta-a do grupo 0 da consola;
- streamlit: já ignorava SIGINT (streamlit_bootstrap.py, sem alterações).

Os encerramentos legítimos continuam a funcionar: kill_tree e o
worker.kill() do launcher usam TerminateProcess (não usam eventos de
consola), logo não são afectados por esta blindagem.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI_SOURCE = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")
AUTOMATION_SOURCE = (ROOT / "hermes_ui" / "automation_worker.py").read_text(encoding="utf-8")
PIPELINE_SOURCE = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")
MPT_AGENT_SOURCE = (ROOT / "seed" / "skills" / "mpt_agent.py").read_text(encoding="utf-8")
STREAMLIT_BOOTSTRAP_SOURCE = (ROOT / "scripts" / "streamlit_bootstrap.py").read_text(encoding="utf-8")


def test_workers_ignore_console_ctrl_c_on_windows():
    for source in (AUTOMATION_SOURCE, PIPELINE_SOURCE, MPT_AGENT_SOURCE):
        assert "def _ignore_console_ctrl_c" in source
        assert "SetConsoleCtrlHandler(None, True)" in source


def test_workers_armour_runs_on_entry():
    for source, marker in (
        (AUTOMATION_SOURCE, "def main() -> None:"),
        (PIPELINE_SOURCE, "def main() -> None:"),
    ):
        main_block = source.split(marker, 1)[1].split("def ", 1)[0]
        assert "_ignore_console_ctrl_c()" in main_block
    mpt_main_block = MPT_AGENT_SOURCE.split("def main(argv: list[str] | None = None) -> int:", 1)[1].split("def ", 1)[0]
    assert "_ignore_console_ctrl_c()" in mpt_main_block


def test_video_helper_tree_gets_its_own_windows_process_group():
    popen_block = PIPELINE_SOURCE.split("subprocess.Popen(", 1)[1][:2500]
    assert "creationflags" in popen_block
    assert "CREATE_NEW_PROCESS_GROUP" in popen_block
    assert "creationflags=_windows_process_group_flags()" in MPT_AGENT_SOURCE.split("def run_checked", 1)[1][:1500]
    assert MPT_AGENT_SOURCE.count("creationflags=_windows_process_group_flags()") >= 3


def test_launcher_ignores_single_ctrl_c_and_requires_double_press():
    assert 'diagnostic("ctrl_c_ignored"' in CLI_SOURCE
    assert 'diagnostic("ctrl_c_burst_ignored"' in CLI_SOURCE
    assert "CTRL_C_BURST_WINDOW_MS = 300" in CLI_SOURCE
    assert "gap <= CTRL_C_BURST_WINDOW_MS" in CLI_SOURCE
    assert 'stopWorker("ctrl+c")' in CLI_SOURCE


def test_launcher_warns_when_parents_die_and_it_becomes_orphan():
    # 0.9.72: a rajada externa mata a cadeia npx/cmd (que não ignora ^C);
    # o launcher sobrevive e tem de avisar que a app continua em segundo
    # plano com a interface activa.
    assert "function checkLauncherOrphan()" in CLI_SOURCE
    assert 'diagnostic("launcher_orphaned"' in CLI_SOURCE
    assert "http://localhost:3030/" in CLI_SOURCE
    monitor_block = CLI_SOURCE.split("function monitorWorkers()", 1)[1].split("}", 1)[0]
    assert "checkLauncherOrphan();" in monitor_block


def test_launcher_captures_console_forensics_on_ignored_ctrl_c():
    # 0.9.73: quando um Ctrl+C é ignorado, o launcher fotografa a consola
    # (registos de input, janela em primeiro plano, processos anexados) para
    # identificar a origem das rajadas — teclado/terminal vs. software.
    assert "function captureCtrlCForensics()" in CLI_SOURCE
    assert 'diagnostic("ctrl_c_forensics"' in CLI_SOURCE
    assert (ROOT / "scripts" / "ctrl_c_forensics.py").is_file()
    sigint_block = CLI_SOURCE.split('process.on("SIGINT"', 1)[1].split('process.on("SIGBREAK"', 1)[0]
    assert "captureCtrlCForensics();" in sigint_block


def test_launcher_stops_respawning_automation_worker_after_five_failures():
    # 0.9.73: o monitor de 2 s re-tentava o worker de automação para sempre
    # mesmo depois das 5 falhas — o lock obsoleto enchia o terminal de
    # "falhou 5 vezes seguidas" num loop infinito (reproduzido em 09/10).
    assert "let automationAutoRestartDisabled = false;" in CLI_SOURCE
    start_block = CLI_SOURCE.split("function startAutomationWorker()", 1)[1].split("}", 1)[0]
    assert "automationAutoRestartDisabled" in start_block
    schedule_block = CLI_SOURCE.split("function scheduleAutomationWorkerRestart()", 1)[1].split("function startAutomationWorker()", 1)[0]
    assert "automationAutoRestartDisabled = true;" in schedule_block
    stable_block = CLI_SOURCE.split("automationStableTimer = setTimeout(", 1)[1].split("}, 60000);", 1)[0]
    assert "automationAutoRestartDisabled = false;" in stable_block


def test_streamlit_bootstrap_keeps_ignoring_sigint():
    # Pré-existente (sem alterações nesta versão): o streamlit já era imune.
    assert "_custom_sigint_handler" in STREAMLIT_BOOTSTRAP_SOURCE
    assert "signal.SIGINT" in STREAMLIT_BOOTSTRAP_SOURCE
