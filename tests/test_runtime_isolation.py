"""1.0.81 — RUNTIME PERMANENTE: a execução nunca sai do cache do npx.

O Thunderbolt corria de ``.npm/_npx/<hash>/...``; com o processo vivo, o npm
não consegue actualizar a pasta (**EBUSY**) e o utilizador fica preso à versão
antiga. A arquitectura validada no ProdMaker separa as responsabilidades:

- ``install`` **apenas prepara**: mata o que está atrelado ao runtime anterior,
  corre o instalador (venv/dependências), copia o CÓDIGO do pacote para
  ``THUNDERBOLT_HOME/.runtime`` e encerra **sem servidor**;
- ``run`` **executa de ``.runtime``** (``cwd: executionRoot``) — nunca do
  cache do npx;
- ``storage/`` (dados, chaves, logs) e ``.env`` ficam na **raiz** do
  ``THUNDERBOLT_HOME`` — a whitelist de cópia só contém código.

Estes testes leem o ``scripts/cli.mjs`` e falham se qualquer peça da
arquitectura desaparecer.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI_SOURCE = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")

SUPERVISED_MODULES = ("automation_worker", "pipeline_worker", "thumbnail_worker", "image_worker")


def _spawn_block(module: str) -> str:
    marker = f'spawn(python, ["-m", "hermes_ui.{module}"]'
    return CLI_SOURCE.split(marker, 1)[1].split("});", 1)[0]


def _install_block() -> str:
    return CLI_SOURCE.split('if (args[0] === "install" || args[0] === "--install") {', 1)[1].split("\nif (args[0] ===", 1)[0]


# ---------------------------------------------------------------------------
# 1. O diretório de runtime existe e vive no THUNDERBOLT_HOME (não no npx)
# ---------------------------------------------------------------------------


def test_runtime_dir_is_inside_thunderbolt_home():
    assert ".runtime" in CLI_SOURCE
    assert 'const runtimeDir = process.env.THUNDERBOLT_RUNTIME_DIR || join(thunderboltHome, ".runtime");' in CLI_SOURCE
    # o runtime NUNCA é resolvido a partir da raiz do pacote (cache do npx).
    assert "join(runtimeDir" not in CLI_SOURCE.split("const runtimeDir")[0]


def test_execution_root_switches_to_the_runtime_when_ready():
    assert "let executionRoot = root;" in CLI_SOURCE
    assert "executionRoot = runtimeDir;" in CLI_SOURCE
    # app/, bootstrap e kill_tree passam a ser resolvidos pela raiz de execução.
    assert 'main = resolve(executionRoot, "app", "main.py");' in CLI_SOURCE
    assert 'streamlitBootstrap = resolve(executionRoot, "scripts", "streamlit_bootstrap.py");' in CLI_SOURCE
    assert 'killTreeHelper = resolve(executionRoot, "scripts", "kill_tree.py");' in CLI_SOURCE


def test_missing_runtime_is_prepared_silently_before_starting():
    assert "ensureRuntimeSources();" in CLI_SOURCE
    assert "refreshRuntimeSources(true);" in CLI_SOURCE
    # 1.0.94 - o guard passou a negado (preparar quando FALTA) para deixar
    # espaço à sincronização por versão do teste seguinte.
    assert 'if (!existsSync(join(runtimeDir, "app", "main.py"))) {' in CLI_SOURCE


def test_runtime_is_resynced_when_the_package_version_changes():
    """1.0.94 - auditoria A7: o `.runtime` não pode ficar com código velho.

    Quem corria `npx thunderbolt` sem `install` depois de uma actualização
    tinha o pacote novo e o `.runtime` velho, enquanto a sidebar mostrava a
    versão nova (THUNDERBOLT_VERSION vem do pacote). A diferença de versão
    dispara a recopia silenciosa — o que corre é o que a interface diz.
    """
    assert "function runtimePackageVersion()" in CLI_SOURCE
    assert "runtime_desatualizado" in CLI_SOURCE
    ensure = CLI_SOURCE.split("function ensureRuntimeSources()", 1)[1].split("\n}\n", 1)[0]
    assert 'runtimePackageVersion() !== packageVersion' in ensure
    # a recopia é POR CIMA no caminho da sincronização (nunca apagar o runtime
    # antes de copiar o novo): um rmSync antes da cópia deixaria a stack sem
    # código se a cópia falhasse. A limpeza total continua dona do arranque a
    # frio (runtime em falta) e do `install`.
    sync_block = ensure.split('runtimePackageVersion() !== packageVersion', 1)[1]
    assert "refreshRuntimeSources(false);" in sync_block
    assert "refreshRuntimeSources(true);" not in sync_block
    assert ensure.count("refreshRuntimeSources(true);") == 1


# ---------------------------------------------------------------------------
# 2. O comando install é SÓ cópia — nunca arranca o servidor
# ---------------------------------------------------------------------------


def test_install_only_prepares_and_never_starts_the_server():
    block = _install_block()
    assert "startStackComponents" not in block
    assert "startStreamlit" not in block
    assert "process.exit(installStatus);" in block
    # copia efetiva dos alivos essenciais (código) e encerramento com log claro.
    assert "refreshRuntimeSources(true);" in block
    assert "runtime permanente preparado" in block
    assert "runInstaller(" in block  # instalador síncrono e visível


def test_install_kills_previous_runtime_processes_before_copying():
    block = _install_block()
    assert "stopRuntimeProcesses();" in block
    assert '"--cleanup", String(process.pid)' in CLI_SOURCE  # kill_tree.py
    # em EBUSY residual a cópia é por cima (fallback) com aviso, não aborta.
    assert "refreshRuntimeSources(false);" in block


def test_runtime_copy_whitelist_is_code_only():
    """storage/, .env e .venv NUNCA entram no .runtime (dados do utilizador)."""
    targets = CLI_SOURCE.split("const RUNTIME_COPY_TARGETS = [", 1)[1].split("];", 1)[0]
    for essential in ('"app"', '"hermes_ui"', '"scripts"', '"seed"', '"integrations"', '"packages"', '"requirements.txt"'):
        assert essential in targets, f"alvo essencial em falta: {essential}"
    for forbidden in ("storage", ".env", ".venv", "channels.json", "tasks.json"):
        assert f'"{forbidden}"' not in targets, f"{forbidden} nunca pode ser copiado para o .runtime"


# ---------------------------------------------------------------------------
# 3. O run corre do .runtime (spawn + cwd) — nunca do cache do npx
# ---------------------------------------------------------------------------


def test_streamlit_spawn_runs_from_the_runtime():
    block = CLI_SOURCE.split('child = spawn(python, [streamlitBootstrap', 1)[1].split("});", 1)[0]
    assert "cwd: executionRoot," in block
    # o isolamento do Windows sobreviveu à mudança de raiz.
    assert "stdio: [\"ignore\", \"pipe\", \"pipe\"]" in block
    assert "windowsHide: true" in block
    assert "creationFlags: workerCreationFlags()," in block


def test_every_worker_spawn_runs_from_the_runtime():
    for module in SUPERVISED_MODULES:
        block = _spawn_block(module)
        assert "cwd: executionRoot," in block, f"{module} não corre do runtime"
        # isolamento intacto (1.0.80): sem inherit, grupo próprio, NO_WINDOW, hide.
        stdio = next(line.strip() for line in block.splitlines() if line.strip().startswith("stdio:"))
        assert "inherit" not in stdio
        assert stdio.startswith('stdio: ["ignore"')
        assert "windowsHide: true" in block
        assert "creationFlags: workerCreationFlags()," in block


def test_worker_isolation_flags_survive_the_runtime_move():
    assert "const WINDOWS_CREATE_NEW_PROCESS_GROUP = 0x00000200;" in CLI_SOURCE
    assert "const WINDOWS_CREATE_NO_WINDOW = 0x08000000;" in CLI_SOURCE
    helper = CLI_SOURCE.split("function workerCreationFlags()", 1)[1].split("\n}", 1)[0]
    assert "WINDOWS_CREATE_NEW_PROCESS_GROUP | WINDOWS_CREATE_NO_WINDOW" in helper
    assert "0x00000008" not in helper  # DETACHED_PROCESS continua proibido


# ---------------------------------------------------------------------------
# 4. storage/ e .env ficam na raiz do THUNDERBOLT_HOME
# ---------------------------------------------------------------------------


def test_storage_dir_stays_out_of_the_runtime():
    assert 'const storageDir = process.env.THUNDERBOLT_STORAGE_DIR || join(thunderboltHome, "storage");' in CLI_SOURCE
    assert 'join(runtimeDir, "storage")' not in CLI_SOURCE
    # o runtimeEnv continua a apontar os filhos para o storage da raiz.
    assert "THUNDERBOLT_STORAGE_DIR: storageDir," in CLI_SOURCE


def test_keep_alive_and_signal_absorption_are_preserved():
    """A arquitectura do terminal desvinculado (1.0.77) não pode regredir."""
    assert "setInterval" in CLI_SOURCE  # keep-alive timer
    assert "absorbTerminalSignal" in CLI_SOURCE
    assert "guardConsoleStream" in CLI_SOURCE
    assert "ignorado. Mantendo processo activo." in CLI_SOURCE


# ---------------------------------------------------------------------------
# 1.0.84 — worker de automação: diagnóstico e watchdog (runtime permanente)
# ---------------------------------------------------------------------------


def test_automation_worker_spawn_has_runtime_flags_and_own_log():
    """O worker de automação corre do runtime, isolado, e escreve log próprio.

    Sem log próprio (1.0.80/1.0.81) o erro que matava o worker na
    inicialização era invisível: a UI mostrava «Worker de automação não está
    activo» sem ninguém saber porquê. Agora segue o contrato stdio-seguro dos
    outrosworkers — pipes + storage/logs/automation_worker.log.
    """
    block = _spawn_block("automation_worker")
    assert "cwd: executionRoot," in block
    assert "windowsHide: true" in block
    assert "creationFlags: workerCreationFlags()," in block
    # pipes (nada de inherit) e log próprio do worker.
    assert 'stdio: ["ignore", "pipe", "pipe"]' in block
    assert 'attachQueueWorkerLog(worker, "automation_worker.log"' in CLI_SOURCE
    # a mensagem de crash loop passa a apontar o ficheiro do log.
    assert 'reportFastFailLoop("worker de automacao", "automation", code, signal, automationLog);' in CLI_SOURCE


def test_automation_worker_watchdog_tolerates_slow_ticks(tmp_path, monkeypatch):
    """Um worker VIVO com tick lento não pode ser reportado morto (e vice-versa)."""
    from datetime import datetime, timedelta, timezone

    monkeypatch.setenv("THUNDERBOLT_STORAGE_DIR", str(tmp_path / "storage"))
    from hermes_ui import storage

    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.ensure_storage()
    from hermes_ui import automation_worker

    now = datetime.now(timezone.utc)

    def status_with_heartbeat_age(seconds: float):
        stamp = (now - timedelta(seconds=seconds)).astimezone().isoformat(timespec="seconds")
        storage.write_json("automation_worker.json", {**automation_worker.DEFAULT_STATE, "last_heartbeat_local": stamp})
        return automation_worker.load_worker_status()

    assert status_with_heartbeat_age(0)["alive"] is True
    assert status_with_heartbeat_age(29)["alive"] is True
    # 40 s é mais que o tick (30 s) mas menos que a folga: continua VIVO.
    assert status_with_heartbeat_age(40)["alive"] is True
    # morte real continua detectada.
    assert status_with_heartbeat_age(automation_worker.WORKER_HEARTBEAT_TTL_SECONDS + 60)["alive"] is False

    storage.write_json("automation_worker.json", {**automation_worker.DEFAULT_STATE, "last_heartbeat_local": None})
    assert automation_worker.load_worker_status()["alive"] is False
