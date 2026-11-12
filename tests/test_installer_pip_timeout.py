"""Tempo limite, heartbeat e retry de rede do instalador (1.0.94).

Corre o **codigo real** de `scripts/install.mjs` (o bloco `runQuietTimed` e os
seus ajudantes) dentro de um processo Node, com um `spawn` falso injectado para
os cenarios deterministas e com o `spawn` real para a prova do heartbeat. A
regra 2 do AGENTS.md (saida crua do pip fora do terminal) tambem esta coberta.
"""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install.mjs"
PROBE = ROOT / ".tb-installer-timeout-probe.mjs"

INSTALLER_SOURCE = INSTALLER.read_text(encoding="utf-8")


def _runtime_block():
    """Bloco 1.0.94 do instalador: constantes + isNetworkFailure + runQuietTimed."""
    start = INSTALLER_SOURCE.index("const PIP_INSTALL_TIMEOUT_MS")
    end = INSTALLER_SOURCE.index("function probePython")
    return INSTALLER_SOURCE[start:end]


_PROBE_HEAD = 'import { spawn as realSpawn } from "node:child_process";'

_PROBE_SETUP = """
const execPath = process.execPath;
const spawn = globalThis.__fakeSpawn || realSpawn;
globalThis.installLogPath = "install.log";
globalThis.appendInstallLog = () => {};
globalThis.pythonEnvironment = {};
globalThis.failureTail = () => "";
const lines = [];
globalThis.console = {
  log: (m) => lines.push("LOG:" + String(m)),
  error: (m) => lines.push("ERR:" + String(m)),
};
const realLog = (m) => process.stdout.write("PROBE " + String(m) + "\\n");
const exitCalls = [];
globalThis.process = {
  exit: (code) => {
    exitCalls.push(code);
    throw new Error("EXIT:" + code);
  },
  stdout: process.stdout,
};
"""

_PROBE_TAIL = """
realLog("RESULT:" + JSON.stringify({ lines, exitCalls }));
"""


@pytest.fixture(autouse=True)
def _no_probe_left_behind():
    yield
    PROBE.unlink(missing_ok=True)


def _probe(body, fake=""):
    """Escreve e corre um probe Node com o codigo real do instalador."""
    text = "\n".join(
        [_PROBE_HEAD, fake, _PROBE_SETUP, _runtime_block(), body, _PROBE_TAIL]
    )
    PROBE.write_text(text, encoding="utf-8", newline="\n")
    try:
        proc = subprocess.run(
            ["node", str(PROBE)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
        )
    finally:
        PROBE.unlink(missing_ok=True)
    return proc.stdout + proc.stderr


def _result(output):
    marker = "PROBE RESULT:"
    idx = output.find(marker)
    assert idx >= 0, f"probe nao devolveu resultado: {output[-1500:]}"
    payload = output[idx + len(marker) :].splitlines()[0]
    return json.loads(payload)


def _close_fake(status, payload=""):
    """`spawn` falso que fecha com um codigo e uma saida conhecidos."""
    js_payload = json.dumps(payload)
    return (
        """
globalThis.__fakeSpawn = (command, args, options) => {
  const handlers = {};
  const child = {
    stdout: { on: (evt, cb) => { if (evt === "data") setTimeout(() => cb("""
        + js_payload
        + """), 5); } },
    stderr: { on: (evt, cb) => { if (evt === "data") setTimeout(() => cb("""
        + js_payload
        + """), 5); } },
    on: (evt, cb) => { handlers[evt] = cb; setTimeout(() => handlers.close("""
        + str(status)
        + """, null), 6); },
    kill: () => {},
  };
  return child;
};
"""
    )


def _stubborn_fake():
    """`spawn` falso de um filho teimoso: nao fecha e ignora o kill."""
    return """
globalThis.__fakeSpawn = (command, args, options) => ({
  stdout: { on: () => {} },
  stderr: { on: () => {} },
  on: () => {},
  kill: () => {},
});
"""


def _recover_fake():
    """1.a tentativa: falha de rede. 2.a tentativa: sucesso."""
    return """
globalThis.__attempts = 0;
globalThis.__fakeSpawn = (command, args, options) => {
  globalThis.__attempts += 1;
  const handlers = {};
  const first = globalThis.__attempts === 1;
  const child = {
    stdout: { on: () => {} },
    stderr: {
      on: (evt, cb) => {
        if (evt === "data") {
          setTimeout(() => cb(first ? "HTTPSConnectionPool: Read timed out." : ""), 5);
        }
      },
    },
    on: (evt, cb) => { handlers[evt] = cb; setTimeout(() => handlers.close(first ? 1 : 0, null), 6); },
    kill: () => {},
  };
  return child;
};
"""


def test_timeout_kills_the_step_and_prints_the_clear_message():
    """Passo travado: o filho morre e sai a mensagem pedida (nunca mais silencio)."""
    out = _probe(
        """
const started = Date.now();
try {
  await runQuietTimed(
    "A reparar as dependencias declaradas dos uploaders",
    execPath,
    ["-e", "const t = Date.now() + 60000; while (Date.now() < t) {}"],
    { heartbeatSeconds: 0.05, timeoutMs: 250 },
  );
} catch (error) {
  realLog("CAUGHT:" + error.message);
}
realLog("ELSAPSED:" + (Date.now() - started));
""",
        fake=_stubborn_fake(),
    )
    result = _result(out)
    joined = "\n".join(result["lines"])
    assert "A instalação demorou mais de" in joined
    assert "Verifique sua conexão ou use --force-deps." in joined
    assert "Registo parcial em install.log" in joined
    assert result["exitCalls"] == [1]
    elapsed = [
        int(line.split(":")[1]) for line in out.splitlines() if line.startswith("PROBE ELSAPSED:")
    ]
    assert elapsed and 200 <= elapsed[0] < 5000  # morreu pelo tempo limite, nao pelo passo de 60 s


def test_success_returns_without_exiting():
    """Sucesso: devolve o resultado e nao aborta o instalador."""
    out = _probe(
        """
const outcome = await runQuietTimed("A instalar requirements", execPath, ["-e", "0"], { timeoutMs: 5000 });
realLog("STATUS:" + outcome.status);
""",
        fake=_close_fake(0),
    )
    result = _result(out)
    assert result["exitCalls"] == []
    assert "PROBE STATUS:0" in out
    assert result["lines"][0] == "LOG:A instalar requirements"


def test_network_failure_retries_once_then_warns():
    """Falha de rede: UMA repetição e aviso claro antes do aborto."""
    out = _probe(
        """
try {
  await runQuietTimed("A reparar os uploaders", execPath, ["-e", "1"], { timeoutMs: 5000 });
} catch (error) {
  realLog("CAUGHT:" + error.message);
}
""",
        fake=_close_fake(1, payload="ReadTimeoutError: HTTPSConnectionPool timeout"),
    )
    result = _result(out)
    joined = "\n".join(result["lines"])
    assert "falha de rede detectada; a tentar novamente (tentativa 2 de 2)" in joined
    assert "Falha de rede ao baixar pacotes." in joined
    assert "A geração de vídeos continuará funcionando" in joined
    assert result["exitCalls"] == [1]


def test_network_failure_that_recovers_on_retry_succeeds():
    """Rede que volta: a segunda tentativa tem sucesso e nao aborta."""
    out = _probe(
        """
const outcome = await runQuietTimed("A reparar os uploaders", execPath, ["-e", "1"], { timeoutMs: 5000 });
realLog("STATUS:" + outcome.status + " ATTEMPTS:" + globalThis.__attempts);
""",
        fake=_recover_fake(),
    )
    result = _result(out)
    assert result["exitCalls"] == []
    assert "PROBE STATUS:0 ATTEMPTS:2" in out


def test_non_network_failure_does_not_retry():
    """Falha que nao e de rede: nao repete (nao insiste em erro definitivo)."""
    out = _probe(
        """
try {
  await runQuietTimed("A reparar os uploaders", execPath, ["-e", "1"], { timeoutMs: 5000 });
} catch (error) {
  realLog("CAUGHT:" + error.message);
}
""",
        fake=_close_fake(1, payload="ERROR: No matching distribution found for nope"),
    )
    result = _result(out)
    joined = "\n".join(result["lines"])
    assert "a tentar novamente" not in joined
    assert "Falha de rede ao baixar pacotes." not in joined
    assert result["exitCalls"] == [1]


def test_heartbeat_reports_elapsed_time_while_the_step_runs():
    """Prova real de que o `spawnSync` saiu: o beat sai com o passo a correr."""
    out = _probe(
        """
const started = Date.now();
const outcome = await runQuietTimed(
  "A instalar browsers",
  execPath,
  ["-e", "const t = Date.now() + 700; while (Date.now() < t) {}"],
  { heartbeatSeconds: 0.05, timeoutMs: 30000 },
);
realLog("STATUS:" + outcome.status + " MS:" + (Date.now() - started));
""",
        fake="",
    )
    result = _result(out)
    joined = "\n".join(result["lines"])
    assert "em curso há" in joined, joined
    assert "PROBE STATUS:0 MS:" in out


def test_all_pip_and_browser_steps_have_a_timeout():
    """Todos os pip installs e os 3 browsers passaram a ter tempo limite."""
    assert (
        '["-m", "pip", "install", "--quiet", "--no-input", "--disable-pip-version-check", "-r", requirementsPath]'
        in INSTALLER_SOURCE
    )
    assert '"-m", "pip", "install"' in INSTALLER_SOURCE
    assert INSTALLER_SOURCE.count("await runQuietTimed(") == 6
    assert INSTALLER_SOURCE.count("{ timeoutMs: BROWSER_INSTALL_TIMEOUT_MS }") == 3
    assert "const PIP_INSTALL_TIMEOUT_MS = 5 * 60 * 1000;" in INSTALLER_SOURCE
    assert "const BROWSER_INSTALL_TIMEOUT_MS = 10 * 60 * 1000;" in INSTALLER_SOURCE
    assert "const INSTALL_HEARTBEAT_SECONDS = 30;" in INSTALLER_SOURCE
    # o bloco novo NAO pode chamar o runQuiet sem tempo limite
    assert "runQuiet(" not in _runtime_block()


def test_browser_steps_warn_about_the_heavy_download():
    """Aviso amigavel antes de cada download pesado de browser."""
    assert INSTALLER_SOURCE.count("A instalar browsers (pode demorar alguns minutos)...") == 3
    for label in (
        '"-m", "playwright", "install", "chromium", "firefox"',
        '"install", "chromium"',
        '"-m", "camoufox", "fetch"',
    ):
        assert label in INSTALLER_SOURCE, label


def test_exact_messages_are_in_the_installer():
    """As mensagens pedidas existem, com acentos correctos."""
    assert (
        "A instalação demorou mais de ${Math.round(timeoutMs / 60000)} minutos."
        " Verifique sua conexão ou use --force-deps." in INSTALLER_SOURCE
    )
    assert (
        "Falha de rede ao baixar pacotes. A geração de vídeos continuará funcionando,"
        " mas os uploaders não estarão disponíveis." in INSTALLER_SOURCE
    )
    assert "${label} - em curso há ${seconds}s (detalhes em ${installLogPath})..." in INSTALLER_SOURCE


def test_terminal_silence_rule_is_preserved():
    """Regra 2 do AGENTS.md: nada de saida crua do pip no terminal."""
    block = _runtime_block()
    assert 'stdio: ["ignore", "pipe", "pipe"]' in block
    assert 'stdio: "inherit"' not in block
    # o passo pesado continua silencioso no terminal
    assert '"--quiet", "--no-input"' in INSTALLER_SOURCE


def test_timeout_only_kills_the_heavy_step():
    """O timeout mata o filho do passo pesado - depois aborta com mensagem clara."""
    block = _runtime_block()
    assert 'child.kill("SIGTERM")' in block
    assert "process.exit(1)" in block
    assert "NETWORK_FAILURE_HINTS" in block
    assert '"readtimeout", "connectionerror"' in block
