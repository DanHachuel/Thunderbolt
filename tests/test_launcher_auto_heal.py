"""1.0.65 — auto-cura de dependências, auto-start por demanda e force-restart.

Regra de ouro do utilizador: "eu NÃO devo correr `install`". O relato: depois de
um `npx` que deixou o `.venv` incompleto, os workers morreram por falta de
dependências e o launcher — mesmo com o circuit breaker da 1.0.53 a parar o loop
infinito — deixou o sistema "na mão" com uma mensagem a pedir `npx install`.

Estes testes prendem o comportamento novo:
1. ``installWorkerDependencies`` corre o pip SILENCIOSO sobre o requirements;
2. ``checkWorkerDependencies`` repara e só depois arranca (nunca ordena install
   no arranque normal);
3. morte por dependência dispara a auto-cura em vez de matar o worker;
4. os workers arrancam por DEMANDA (tarefas na fila ou canais automatizados);
5. o botão "Forçar Reinício do Sistema" da UI escreve ``force_restart.json`` e o
   launcher consome-o no tick de 2 s.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _cli_source() -> str:
    return (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")


def _cli_block(anchor: str, end: str = "\nfunction ") -> str:
    source = _cli_source()
    return source.split(anchor, 1)[1].split(end, 1)[0]


# ---------------------------------------------------------------------------
# 1. Auto-cura: pip silencioso + reparação antes do arranque
# ---------------------------------------------------------------------------


def test_launcher_installs_missing_dependencies_silently():
    block = _cli_block("function installWorkerDependencies()")
    assert '["-m", "pip", "install", "-r", requirements' in block
    assert '"--quiet"' in block
    assert '"--no-input"' in block
    assert '"--disable-pip-version-check"' in block
    # Silêncio absoluto (regra do repositório): a saída do pip nunca aparece.
    assert 'stdio: "ignore"' in block
    assert "windowsHide: true" in block
    # O requirements.txt do Thunderbolt é a fonte da reparação.
    assert 'join(root, "requirements.txt")' in block


def test_launcher_heals_before_starting_workers():
    block = _cli_block("function checkWorkerDependencies(label)")
    assert "[SISTEMA] A actualizar dependencias internas. Por favor, aguarde..." in block
    assert "[SISTEMA] Dependencias actualizadas. A iniciar os trabalhadores..." in block
    assert "installWorkerDependencies()" in block
    # Reparou => limpa os bloqueios permanentes e devolve True (arranca).
    assert "clearDependencyBlocks();" in block
    assert "return true;" in block
    # Backoff: não insiste a cada tick de 2 s depois de falhar.
    assert "dependencyHealResult.at < 60000" in block


def test_launcher_boot_never_asks_the_user_to_run_install():
    """A mensagem "corra npx install" só pode existir no diagnóstico (--check),
    nunca no arranque: a auto-cura é a regra, o instalador manual é o último
    recurso quando a rede falha."""
    source = _cli_source()
    heal_block = _cli_block("function checkWorkerDependencies(label)")
    assert "Execute: npx" not in heal_block
    assert "run install" not in heal_block.casefold()
    # O caminho de diagnóstico mantém a instrução (é ferramenta do utilizador).
    check_block = _cli_block("function check()", '\nif (args[0] === "install"')
    assert "Execute: npx.cmd --yes --prefer-online @danhachuel/thunderbolt install" in check_block
    # ...e antes de acusar falta, o check também repara.
    assert "installWorkerDependencies()" in check_block


def test_worker_death_from_dependencies_triggers_the_heal():
    """Morrer por Import deixa de ser definitivo: o launcher repara e volta a
    arrancar no tick seguinte (o bloqueio permanente era o "na mão")."""
    source = _cli_source()
    automation_block = _cli_block("function startAutomationWorker()")
    pipeline_block = _cli_block("function startPipelineWorker()")
    for label, block in (("automação", automation_block), ("pipeline", pipeline_block)):
        assert "dependencyHealResult = null;" in block, f"{label} rearma a cura"
        assert "workerDependencyFailureReported = false;" in block or (
            "pipelineDependencyFailureReported = false;" in block
        ), f"{label} limpa o bloqueio"


def test_dependency_block_is_only_permanent_after_the_heal_fails():
    """Enquanto a auto-cura corre (ou vai tentar de novo), o arranque não fica
    travado — o bloqueio permanente só acontece depois de a cura falhar."""
    source = _cli_source()
    for label in ("o worker de automacao", "o worker do pipeline de videos"):
        guard = source.split(f'if (!checkWorkerDependencies("{label}"))', 1)[1].split("return;", 1)[0]
        assert "dependencyHealInFlight" in guard, label
        assert "dependencyHealResult && !dependencyHealResult.ok" in guard, label


# ---------------------------------------------------------------------------
# 2. Auto-start baseado em demanda
# ---------------------------------------------------------------------------


def test_workers_start_from_demand_without_manual_clicks():
    source = _cli_source()
    automation_block = _cli_block("function startAutomationWorker()")
    # Canal automatizado OU tarefas na fila (to_do/doing) forçam o arranque.
    assert "if (!hasScheduledAutomation() && !hasPendingPipelineWork()) return;" in automation_block
    # A função de demanda passou a ser USADA (antes estava morta no fonte).
    assert source.count("hasPendingPipelineWork()") >= 4


def test_channel_automation_flag_is_read_for_the_demand():
    block = _cli_block("function hasScheduledAutomation()")
    assert "automation_on === true" in block
    assert "automation_worker === true" in block


def test_pipeline_worker_rearms_for_pending_work():
    block = _cli_block("function startPipelineWorker()")
    assert "if (hasPendingPipelineWork())" in block
    assert "clearDependencyBlocks();" in block
    assert "pipelineFastFailDisabled = false;" in block


# ---------------------------------------------------------------------------
# 3. Forçar Reinício do Sistema (UI -> launcher)
# ---------------------------------------------------------------------------


def test_launcher_consumes_the_force_restart_flag():
    source = _cli_source()
    assert 'const forceRestartPath = join(diagnosticsDir, "force_restart.json");' in source
    block = _cli_block("function consumeForceRestartRequest()")
    assert "existsSync(forceRestartPath)" in block
    assert "rmSync(forceRestartPath" in block
    assert "[SISTEMA] Reinicio forcado pedido" in block
    # Rearme completo antes de relançar.
    assert "clearDependencyBlocks();" in block
    assert "pipelineFastFailDisabled = false;" in block
    assert "startPipelineWorker();" in block
    assert "startAutomationWorker();" in block
    assert "startQueueWorkers();" in block
    # Consumido no tick de 2 s.
    monitor = _cli_block("function monitorWorkers()")
    assert "consumeForceRestartRequest();" in monitor


def test_force_restart_path_matches_between_ui_and_launcher():
    """A UI escreve state/force_restart.json; o launcher lê diagnosticsDir/force_restart.json
    (diagnosticsDir = storageDir/state) — o mesmo ficheiro."""
    source = _cli_source()
    assert 'const diagnosticsDir = join(storageDir, "state");' in source
    assert 'const forceRestartPath = join(diagnosticsDir, "force_restart.json");' in source
    ui = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert '"force_restart.json"' in ui


def test_ui_shows_the_force_restart_button_on_the_yellow_banner():
    ui = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    banner = ui.split("def _render_pipeline_worker_banner(", 1)[1].split("\ndef ", 1)[0]
    assert 'st.button(\n            "For\u00e7ar Rein\u00edcio do Sistema"' in banner
    assert 'key="force_worker_restart"' in banner
    assert 'write_json(\n                    "force_restart.json"' in banner
    # O pedido guarda a razão e o timestamp.
    assert "requested_at" in banner
    assert "botao Forcar Reinicio do Sistema" in banner


def test_force_restart_flag_is_valid_json_for_the_launcher():
    """O payload que a UI escreve é JSON válido e tem os campos que o launcher lê."""
    import json

    payload = json.dumps({"requested_at": "2026-11-05T00:00:00+00:00", "reason": "botao Forcar Reinicio do Sistema"})
    parsed = json.loads(payload)
    assert parsed["reason"]
    launcher = _cli_block("function consumeForceRestartRequest()")
    assert "request?.reason" in launcher
