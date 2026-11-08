"""1.0.72 — boot dos workers à prova de STATUS_DLL_INIT_FAILED (0xC0000142).

Relato do utilizador: o vídeo principal gerou com sucesso (3 min, via GPU), mas
os workers de `thumbnail` e `image` morreram no boot. Os logs reais mostram
`terminou (código 3221225786)` (= 0xC000013A, STATUS_CONTROL_C_EXIT) e o
utilizador reportou 0xC0000142 (STATUS_DLL_INIT_FAILED) — em ambos os casos o
processo morre **na inicialização**, antes de qualquer import: correr `pip
install` não cura nada, e 4 interpretadores Python a nascer ao mesmo tempo na
mesma sessão de console do Windows é uma das causas.

Estes testes prendem o contrato novo no launcher.
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. env completo em todos os spawns
# ---------------------------------------------------------------------------


def test_every_worker_spawn_receives_the_full_environment():
    """Nenhum spawn cria um dicionário do zero: o `env` é sempre o `runtimeEnv`
    (cópia de `process.env` + as variáveis do Thunderbolt) — sem SYSTEMROOT/
    WINDIR/PATH o Windows não consegue inicializar as DLLs do sistema."""
    spawns = [
        line
        for line in CLI.splitlines()
        if "spawn(" in line and "hermes_ui" in line
    ]
    assert len(spawns) >= 4, f"esperava os 4 workers, encontrados {len(spawns)}"
    for line in spawns:
        assert "spawn(" in line
    # cada bloco de spawn carrega o env completo
    blocks = CLI.split("spawn(")
    worker_blocks = [block for block in blocks if "hermes_ui." in block[:220]]
    assert len(worker_blocks) >= 4
    for block in worker_blocks:
        assert "env: runtimeEnv" in block, "o spawn do worker não leva o env completo"


def test_runtime_env_is_a_copy_of_the_process_environment():
    assert "const runtimeEnv = {" in CLI
    assert "...process.env," in CLI
    assert "THUNDERBOLT_STORAGE_DIR" in CLI.split("const runtimeEnv = {", 1)[1].split("};", 1)[0]


# ---------------------------------------------------------------------------
# 2. respiro entre spawns (Windows)
# ---------------------------------------------------------------------------


def test_workers_spawn_staggered_on_windows():
    assert "WORKER_SPAWN_STAGGER_MS" in CLI
    assert 'process.platform === "win32" ? 500 : 0' in CLI
    # o monitor escala o arranque em vez de lançar os 4 ao mesmo tempo
    monitor = CLI.split("function monitorWorkers()", 1)[1].split("\nfunction ", 1)[0]
    assert "setTimeout(() => { if (!shuttingDown) startAutomationWorker(); }" in monitor
    assert "setTimeout(() => { if (!shuttingDown) startQueueWorkers(); }" in monitor
    # e os dois workers de fila nascem com respiro entre eles
    assert "function spawnImageWorker()" in CLI
    queue = CLI.split("function spawnImageWorker()", 1)[0].rsplit("function startQueueWorkers()", 1)[-1]
    assert "WORKER_SPAWN_STAGGER_MS" in queue


# ---------------------------------------------------------------------------
# 3. morte de inicialização não passa pelo pip
# ---------------------------------------------------------------------------


def test_init_failure_codes_are_classified():
    assert "WORKER_INIT_FAILURE_CODES" in CLI
    assert "3221225786" in CLI  # 0xC000013A STATUS_CONTROL_C_EXIT
    assert "3221225794" in CLI  # 0xC0000142 STATUS_DLL_INIT_FAILED
    assert "function isWorkerInitFailure(code)" in CLI


def test_secondary_workers_recover_without_pip_on_init_failure():
    handler = CLI.split("function handleSecondaryWorkerInitFailure(", 1)[1].split("\nfunction ", 1)[0]
    # não corre pip: não é falta de pacote
    assert "installWorkerDependencies" not in handler
    assert "checkWorkerDependencies" not in handler
    # respiro de 2 s e nova tentativa
    assert "}, 2000)" in handler
    assert "startQueueWorkers();" in handler
    # ao fim de N tentativas, aviso — e o vídeo principal continua
    assert "SECONDARY_WORKER_INIT_LIMIT" in handler
    assert "Falha na inicializacao dos workers secundarios" in handler
    assert "O video principal continuara funcionando" in handler
    assert 'diagnostic("secondary_worker_init_failure"' in handler


def test_queue_workers_exit_handlers_route_init_failures():
    for worker in ("thumbnail worker", "image worker"):
        block = CLI.split(f'handleSecondaryWorkerInitFailure("{worker}"', 1)
        assert len(block) == 2, f"{worker} não encaminha a morte de inicialização"
    # o caminho fica ANTES do caminho de dependências (pip) em cada handler
    for marker in ('thumbnailWorker.on("exit"', 'imageWorker.on("exit"'):
        handler = CLI.split(marker, 1)[1].split("}, 5000)", 1)[0]
        assert "isWorkerInitFailure(code)" in handler
        assert handler.index("isWorkerInitFailure(code)") < handler.index("if (diedFromDependencies)")


def test_secondary_worker_failure_does_not_touch_the_pipeline_worker():
    """Fallback silencioso: o vídeo principal nunca depende dos workers de fila."""
    # o restart dos workers de fila só relança startQueueWorkers
    handler = CLI.split("function handleSecondaryWorkerInitFailure(", 1)[1].split("\nfunction ", 1)[0]
    assert "startPipelineWorker" not in handler
    assert "stopPipelineWorker" not in handler


def test_worker_signal_isolation_is_preserved():
    """A correcção 1.0.71 (grupo próprio contra o Ctrl+C do console) mantém-se."""
    assert "WINDOWS_CREATE_NEW_PROCESS_GROUP" in CLI
    assert "function workerCreationFlags()" in CLI
    assert CLI.count("creationFlags: workerCreationFlags(),") >= 4
