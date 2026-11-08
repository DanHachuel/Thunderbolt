"""1.0.74 — o launcher deixa de encerrar sozinho no PowerShell/MobaXterm.

Relato do utilizador: o Thunderbolt arrancou pelo PowerShell dentro do
MobaXterm (v1.0.70), mostrou os logs do Streamlit e as requisições
[YT-AUTOM] e, logo a seguir, DEVOLVEU o prompt do terminal — a aplicação
continuou a correr (ou morreu) sem ninguém perceber.

INVESTIGAÇÃO (respondida antes de codar)
1. **O `cli.mjs` terminava pelos sinais.** `process.on("SIGHUP", () =>
   stopWorker("console_closed"))` tratava QUALQUER SIGHUP como "janela
   fechada" e derrubava a stack inteira. A telemetria do próprio launcher
   (`storage/state/launcher_diagnostics.jsonl`) regista 82 `launcher_exiting`
   com motivo `console_closed`, vários com `uptime_seconds` = 5 — o sinal
   chegava SEGUNDOS depois do arranque, com o terminal aberto e o utilizador
   noutra aplicação. No Windows o SIGHUP do Node é derivado do console
   (CTRL_CLOSE/LOGOFF), não do fecho real de uma janela.
2. **Havia uma segunda morte silenciosa.** Com a consola desvinculada, a
   primeira escrita num stream sem leitor emite EPIPE NA STREAM; sem ouvinte
   de `"error"` o Node transforma o evento em `uncaughtException` →
   `launcherExiting("crash")` → `exit(1)` → prompt de volta.
3. **O `npx` usa o shim `.cmd` gerado pelo npm, nunca `.ps1`.** O PowerShell
   executa o `.cmd` sem problemas — a ExecutionPolicy nunca foi a causa (a
   nota da 1.0.52 do `install` é outra história).

O QUE ENTRA (`scripts/cli.mjs`)
- keep-alive explícito (intervalo referenciado): o event loop nunca esvazia;
- SIGHUP/SIGINT absorvidos no Windows com `[LAUNCHER] Sinal ignorado.
  Mantendo processo activo.`;
- detecção de orfandade (pai morto) + guarda da consola (EPIPE) com o aviso
  `Thunderbolt: A interface continua ativa em http://localhost:3030/
  (Terminal desvinculado).`;
- nota de terminal a recomendar o CMD clássico (`npx.cmd`) quando o arranque
  vem do PowerShell/MobaXterm — nunca culpa o utilizador.

O que NÃO muda: a lógica do Streamlit e dos workers (isolamento de sinais por
CREATE_NEW_PROCESS_GROUP da 1.0.71 intacto), o Ctrl+Break, o SIGTERM e o
arquivo `.thunderbolt.stop` como paragens deliberadas.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CLI = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")
BOOT_TIMEOUT_SECONDS = 45
ORPHAN_TIMEOUT_SECONDS = 20
STOP_TIMEOUT_SECONDS = 25


def _venv_python() -> Path | None:
    """Venv real do Thunderbolt (só com ele os probes do launcher passam)."""
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


# ---------------------------------------------------------------------------
# 1. keep-alive: o launcher não devolve o prompt sozinho
# ---------------------------------------------------------------------------


def test_keep_alive_interval_holds_the_event_loop():
    """Um intervalo referenciado mantém o launcher vivo enquanto a stack existe."""
    assert "const keepAliveTimer = setInterval(() => {}, 1000);" in CLI
    # não pode ir para unref: um handle referenciado é o que segura o Node
    assert "keepAliveTimer.unref" not in CLI
    assert "unref(keepAliveTimer" not in CLI


def test_keep_alive_never_replaces_the_deliberate_shutdowns():
    """O keep-alive é só vida; encerrar continua a ser deliberado."""
    assert 'process.on("SIGBREAK", () => stopWorker("ctrl+break"));' in CLI
    assert 'process.on("SIGTERM", () => stopWorker("external_kill"));' in CLI
    assert 'stopWorker("stop-file")' in CLI


# ---------------------------------------------------------------------------
# 2. sinais do terminal absorvidos (o sintoma do prompt que volta)
# ---------------------------------------------------------------------------


def test_windows_absorbs_sighup_without_touching_the_stack():
    """No Windows o SIGHUP é absorvido: a stack NÃO é derrubada."""
    win_block = CLI.split('if (platform() === "win32")', 1)[1].split("} else {", 1)[0]
    assert 'process.on("SIGHUP", () => absorbTerminalSignal("SIGHUP"));' in win_block
    assert "stopWorker" not in win_block  # o handler NÃO encerra o launcher


def test_absorbed_signal_logs_the_keep_alive_notice():
    """O aviso pedido: `[LAUNCHER] Sinal ignorado. Mantendo processo activo.`"""
    absorb = CLI.split("function absorbTerminalSignal(", 1)[1].split("\nfunction ", 1)[0]
    assert "stopWorker" not in absorb
    assert "terminal_signal_absorbed" in absorb
    assert "console.log(`[LAUNCHER] Sinal ${signal} ignorado. Mantendo processo activo.`);" in absorb
    # uma linha por rajada (o MobaXterm dispara dezenas de sinais por segundo)
    assert "lastAbsorbedSignalLogAt" in absorb


def test_windows_sigint_absorption_is_preserved():
    """1.0.86: o SIGINT espúrio do Windows continua absorvido (não regride)."""
    win_block = CLI.split('if (platform() === "win32")', 1)[1].split("} else {", 1)[0]
    assert 'process.on("SIGINT"' in win_block
    assert "ctrl_c_absorbed_windows" in win_block


def test_unix_signals_still_stop_the_stack():
    """No Linux/macOS o fecho do terminal é real: encerrar continua correcto."""
    unix_block = CLI.split("} else {", 1)[1].split('process.on("SIGBREAK"', 1)[0]
    assert 'process.on("SIGINT", () => stopWorker("ctrl+c"));' in unix_block
    assert 'process.on("SIGHUP", () => stopWorker("console_closed"));' in unix_block


# ---------------------------------------------------------------------------
# 3. orfandade: o pai (npx) morto não pode derrubar a interface
# ---------------------------------------------------------------------------


def test_orphan_detection_probes_the_parent_and_tolerates_eperm():
    """`process.kill(ppid, 0)` detecta o pai morto; EPERM não é orfandade."""
    assert "function detectDetachedLauncher()" in CLI
    detect = CLI.split("function detectDetachedLauncher()", 1)[1].split("\nif (platform()", 1)[0]
    assert "process.kill(parentPid, 0)" in detect
    assert '"EPERM"' in detect
    assert "Number(process.ppid)" in detect


def test_orphan_detection_runs_on_the_two_second_monitor():
    """O monitor existente detecta a orfandade (nada de timer novo)."""
    monitor = CLI.split("function monitorWorkers()", 1)[1].split("\nfunction ", 1)[0]
    assert "detectDetachedLauncher();" in monitor


def test_detached_console_notice_names_the_url_and_fires_once():
    """A mensagem contratada, uma única vez."""
    assert "function announceDetachedConsole()" in CLI
    announce = CLI.split("function announceDetachedConsole()", 1)[1].split("\nfunction ", 1)[0]
    assert "console.log(`Thunderbolt: A interface continua ativa em http://localhost:${publicPort}/ (Terminal desvinculado).`);" in announce
    assert "detachedConsoleNoticeShown = true;" in announce
    assert "terminal_detached_notice" in announce


# ---------------------------------------------------------------------------
# 4. consola desvinculada: EPIPE não pode matar o launcher
# ---------------------------------------------------------------------------


def test_console_streams_are_guarded_against_epipe():
    """stdout/stderr guardados: o erro passa a evento tratado, não a crash."""
    assert 'guardConsoleStream(process.stdout, "stdout");' in CLI
    assert 'guardConsoleStream(process.stderr, "stderr");' in CLI
    guard = CLI.split("function guardConsoleStream(", 1)[1].split("\nguardConsoleStream(", 1)[0]
    assert 'stream.on("error"' in guard
    assert "noteConsoleDetached(" in guard
    assert "mirrorConsoleOutput(chunk)" in guard


def test_uncaught_exception_no_longer_dies_on_console_writes():
    """Erro de escrita com a consola morta não é crash; o resto continua a ser."""
    uncaught = CLI.split('process.on("uncaughtException"', 1)[1].split('process.on("unhandledRejection"', 1)[0]
    assert "launcherConsoleDetached && isConsoleWriteFailure(error)" in uncaught
    assert "mirrorConsoleOutput(" in uncaught
    assert 'launcherExiting("crash");' in uncaught
    assert "isConsoleWriteFailure(error)" in CLI
    assert "consoleWriteFailurePattern" in CLI


# ---------------------------------------------------------------------------
# 5. aviso de terminal (PowerShell/MobaXterm) sem culpar o utilizador
# ---------------------------------------------------------------------------


def test_terminal_advisory_recommends_the_classic_cmd():
    assert "function launchTerminalAdvisory()" in CLI
    advisory = CLI.split("function launchTerminalAdvisory()", 1)[1].split("\nfunction ", 1)[0]
    assert "npx.cmd --yes @danhachuel/thunderbolt" in advisory
    assert "PowerShell/MobaXterm" in advisory
    assert 'if (platform() !== "win32") return;' in advisory  # a nota é do console Windows
    # uma vez só
    assert "terminalAdvisoryShown = true;" in advisory


def test_terminal_detection_covers_powershell_and_mobaxterm():
    assert "LAUNCH_TERMINAL_NAMES" in CLI
    assert "function launchTerminalAncestry()" in CLI
    assert "function launchingFromSignalHeavyTerminal()" in CLI
    detect = CLI.split("function launchingFromSignalHeavyTerminal()", 1)[1].split("\nlet terminalAdvisoryShown", 1)[0]
    assert "process.env.PSHOME" in detect
    assert "mobaxterm" in detect.lower()
    assert "Get-CimInstance Win32_Process" in CLI  # a caminhada de pais continua real


# ---------------------------------------------------------------------------
# 6. regressões proibidas e sintaxe
# ---------------------------------------------------------------------------


def test_no_reverted_solutions_reintroduced():
    """Nenhuma das soluções revertidas pode voltar (lista do contrato 0.9.86)."""
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
        assert removed not in CLI, removed


def test_launcher_source_is_valid_javascript():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node indisponível neste ambiente")
    result = subprocess.run([node, "--check", str(ROOT / "scripts" / "cli.mjs")], capture_output=True)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# 7. provas reais: o pai morre, a consola morre — o launcher continua
# ---------------------------------------------------------------------------

# A cadeia de arranque do relato: um processo intermediário (o npx/cmd) que morre
# DEPOIS de o launcher arrancar. O launcher nasce escapado ao job object do Node
# (DETACHED_PROCESS só no processo que o cria, não nos filhos — a stack inteira
# continua com a consola do terminal, sem janelas CMD extra).
WRAPPER_NPX = r"""
const net = require("node:net");
const path = require("node:path");
const fs = require("node:fs");
const launcher = path.join(process.cwd(), "scripts", "cli.mjs");
const child = require("node:child_process").spawn(
  process.execPath,
  [launcher],
  { stdio: "inherit", cwd: process.cwd(), windowsHide: false, detached: true },
);
child.on("error", (error) => { console.error(String(error)); process.exit(1); });
fs.writeFileSync(process.env.TB_PID_FILE, String(child.pid));
const port = Number(process.env.THUNDERBOLT_PORT || 3030);
const startedAt = Date.now();
const probe = setInterval(() => {
  const socket = net.connect(port, "127.0.0.1");
  const timer = setTimeout(() => socket.destroy(), 1000);
  socket.on("connect", () => {
    clearTimeout(timer);
    socket.destroy();
    clearInterval(probe);
    // O npx morre depois de a interface estar de pé: é o relato do utilizador.
    setTimeout(() => process.exit(0), 1500);
  });
  socket.on("error", () => { clearTimeout(timer); socket.destroy(); });
  if (Date.now() - startedAt > 90000) { clearInterval(probe); process.exit(1); }
}, 1000);
"""


def _read_console_until_banner(process: subprocess.Popen, marker: str) -> str:
    """Lê a consola do launcher no thread principal até à linha do `marker`.

    NÃO é usada uma thread de leitura: no Windows, fechar um pipe que outra
    thread está a ler (WinError/bloqueio em `CloseHandle`) pendura o processo.
    Lendo no thread principal, o teste é dono do pipe e pode fechá-lo quando
    quiser — que é exactamente a simulação do terminal que morre.
    """
    console = ""
    while True:
        line = process.stdout.readline()
        if not line:
            break  # o launcher morreu
        console += line.decode("utf-8", errors="replace")
        if marker in console:
            break
    return console


def _console_says(sink: list[str], marker: str) -> bool:
    return marker in "".join(sink)


def _wait_for_console(sink: list[str], marker: str, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if _console_says(sink, marker):
            return True
        time.sleep(0.25)
    return _console_says(sink, marker)


def _wait_for_console_file(path: Path, marker: str, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if marker in path.read_text(encoding="utf-8", errors="replace"):
                return True
        except OSError:
            pass
        time.sleep(0.5)
    try:
        return marker in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def _free_tcp_port() -> int:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _alive(pid) -> bool:
    try:
        import psutil

        return bool(pid) and psutil.Process(pid).is_running()
    except Exception:
        return False


def _kill_pid(pid) -> None:
    if not pid:
        return
    try:
        import psutil

        psutil.Process(pid).kill()
    except Exception:
        pass


def _kill_leftover_stack(tmp_path: Path) -> None:
    """Mata o que sobrou da stack do teste (sem `taskkill`, sem bloqueios).

    O launcher morre primeiro, mas os workers e o bootstrap são filhos dele e
    podem sobreviver: a limpeza procura os processos que apontam para o
    THUNDERBOLT_HOME deste teste — nunca o perfil real do utilizador.
    """
    try:
        import psutil
    except ImportError:
        return
    marker = str(tmp_path / "home").lower()
    for process in psutil.process_iter(["cmdline"]):
        cmdline = " ".join(process.info.get("cmdline") or [])
        if marker and marker in cmdline.lower():
            try:
                process.kill()
            except Exception:
                pass


def _launcher_environment(tmp_path: Path, venv: Path, port: int) -> dict[str, str]:
    home = tmp_path / "home"
    environment = {
        **os.environ,
        "THUNDERBOLT_HOME": str(home),
        "THUNDERBOLT_VENV": str(venv),
        "THUNDERBOLT_STORAGE_DIR": str(home / "storage"),
        "THUNDERBOLT_PORT": str(port),
        "TB_PID_FILE": str(tmp_path / "launcher.pid"),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }
    if sys.platform == "win32":
        # userHome do launcher (STOP_FILE/.thunderbolt.stop) segue o USERPROFILE:
        # apontá-lo para o tmp_path mantém o teste longe do perfil real.
        environment["USERPROFILE"] = str(home)
    return environment


def _thunderbolt_stack_running() -> bool:
    """Há uma instância real do Thunderbolt a correr nesta máquina?

    O launcher novo termina a stack anterior antes de arrancar (single-instance
    guard): o teste NÃO pode matar a aplicação do utilizador. Sem psutil a
    resposta é "não sei" — e o teste segue (o guard é só defesa extra).
    """
    try:
        import psutil
    except ImportError:
        return False
    for process in psutil.process_iter(["cmdline"]):
        parts = process.info.get("cmdline") or []
        if any("test_launcher_keep_alive.py" in part for part in parts):
            continue  # o próprio teste (pytest) não é uma instância
        cmdline = " ".join(parts)
        if "cli.mjs" in cmdline and "thunderbolt" in cmdline.lower():
            return True
    return False


@pytest.mark.skipif(not shutil.which("node"), reason="node necessário para arrancar o launcher")
def test_launcher_survives_the_parent_dying(tmp_path: Path):
    """O relato real, reproduzido: o npx morre — o launcher NÃO morre.

    A consola do launcher corre num FICHEIRO (assim é seguro esperar pelas
    linhas) e a provavalida, pela ordem:
    1. o arranque (interface na porta);
    2. a morte do processo de arranque (o pai) — o launcher detecta a orfandade,
       imprime o aviso e continua vivo (keep-alive);
       imprime o aviso e continua vivo (keep-alive);
    3. o encerramento deliberado pelo arquivo `.thunderbolt.stop`, sempre
       imprime o aviso e continua vivo (keep-alive);
    3. o encerramento deliberado pelo arquivo `.thunderbolt.stop`, sempre
       funcional — e `terminal_detached_notice` fica gravado no diagnóstico.
    """
    venv = _venv_python()
    if venv is None:
        pytest.skip("venv do Thunderbolt indisponível neste ambiente")
    if _thunderbolt_stack_running():
        pytest.skip("há uma instância real do Thunderbolt a correr neste ambiente")

    port = _free_tcp_port()
    environment = _launcher_environment(tmp_path, venv, port)
    pid_file = tmp_path / "launcher.pid"
    console_path = tmp_path / "console.log"
    diagnostics = tmp_path / "home" / "storage" / "state" / "launcher_diagnostics.jsonl"

    with console_path.open("wb") as console_file:
        process = subprocess.Popen(
            ["node", "-e", WRAPPER_NPX],
            cwd=str(ROOT),
            env=environment,
            stdout=console_file,
            stderr=subprocess.STDOUT,
            start_new_session=sys.platform != "win32",
        )
        try:
            deadline = time.monotonic() + BOOT_TIMEOUT_SECONDS
            banner = ""
            while time.monotonic() < deadline:
                try:
                    banner = console_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    banner = ""
                if f"interface disponível em http://localhost:{port}" in banner:
                    break
                if process.poll() is not None:
                    break
                time.sleep(0.5)
            assert f"interface disponível em http://localhost:{port}" in banner, (
                f"arranque falhou:\n{banner[-2000:]}"
            )
            launcher_pid = int(pid_file.read_text(encoding="utf-8").strip())
            assert launcher_pid > 0 and launcher_pid != process.pid

            # 1) o npx (pai) morreu: o launcher tem de perceber e avisar.
            process.wait()
            assert _wait_for_console_file(
                console_path,
                "A interface continua ativa em http://localhost:",
                ORPHAN_TIMEOUT_SECONDS,
            ), f"sem aviso de terminal desvinculado:\n{banner[-2000:]}"
            assert _alive(launcher_pid), "o launcher encerrou quando o pai morreu"

            # 2) encerramento deliberado: o arquivo .thunderbolt.stop.
            (tmp_path / "home" / ".thunderbolt.stop").write_text("teste", encoding="utf-8")
            deadline = time.monotonic() + STOP_TIMEOUT_SECONDS
            while time.monotonic() < deadline and _alive(launcher_pid):
                time.sleep(0.5)
            assert not _alive(launcher_pid), "o launcher deixou de responder ao .thunderbolt.stop"
        finally:
            if pid_file.is_file():
                _kill_pid(int(pid_file.read_text(encoding="utf-8").strip()))
            _kill_pid(process.pid)
            _kill_leftover_stack(tmp_path)

    recorded = diagnostics.read_text(encoding="utf-8", errors="replace") if diagnostics.is_file() else ""
    assert "terminal_detached_notice" in recorded


@pytest.mark.skipif(not shutil.which("node"), reason="node necessário para arrancar o launcher")
def test_console_detach_never_kills_the_launcher(tmp_path: Path):
    """EPIPE na consola (leitor do pipe morto) não pode matar o launcher.

    Esta é a segunda morte silenciosa do relato: sem ouvinte de `error` na
    stream, o Node transformava o EPIPE em `uncaughtException` e saía com
    `launcherExiting("crash")` — o prompt do terminal voltava sozinho. Aqui a
    consola é um PIPE e o leitor é destruído a meio do voo: o launcher tem de
    continuar vivo (guarda da consola + keep-alive).
    """
    venv = _venv_python()
    if venv is None:
        pytest.skip("venv do Thunderbolt indisponível neste ambiente")
    if _thunderbolt_stack_running():
        pytest.skip("há uma instância real do Thunderbolt a correr neste ambiente")

    port = _free_tcp_port()
    environment = _launcher_environment(tmp_path, venv, port)
    process = subprocess.Popen(
        ["node", str(ROOT / "scripts" / "cli.mjs")],
        cwd=str(ROOT),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # um único pipe: a consola do terminal
        start_new_session=sys.platform != "win32",
    )
    try:
        console = _read_console_until_banner(process, "interface disponível em http://localhost:")
        assert "interface disponível em http://localhost:" in console, "arranque falhou:\n" + console[-2000:]

        # O terminal fechou: o leitor do pipe morre (EPIPE no launcher). Como a
        # leitura foi feita no thread principal, fechar o pipe não bloqueia.
        os.close(process.stdout.fileno())
        time.sleep(8)
        assert process.poll() is None, "o launcher morreu com a consola desvinculada:\n" + console[-2000:]
    finally:
        _kill_pid(process.pid)
        _kill_leftover_stack(tmp_path)

    diagnostics = tmp_path / "home" / "storage" / "state" / "launcher_diagnostics.jsonl"
    recorded = diagnostics.read_text(encoding="utf-8", errors="replace") if diagnostics.is_file() else ""
    assert "terminal_detached_notice" in recorded or "launcher_console_detached" in recorded, (
        "nem o EPIPE foi registado: a guarda da consola não correu\n" + recorded[-1500:]
    )


