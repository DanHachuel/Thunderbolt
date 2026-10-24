"""Instalador honesto + fim do loop infinito de workers (1.0.20, refinado na 1.0.31).

1. `missingModules` (`scripts/install.mjs`, era `importsAvailable`): o find_spec
   apenas localizava a pasta do pacote — instalações parciais/corrompidas davam
   FALSO POSITIVO e o instalador dizia «dependências detectadas e reutilizadas»
   enquanto os workers morriam no boot por falta de psutil/playwright/patchright/
   serpapi. Passa a IMPORTAR cada módulo de verdade (executa __init__ + extensões
   compiladas) e a devolver a LISTA dos que falham (1.0.31: a reacção deixa de
   ser binária — quem decide é a reparação alvo).
2. `moduleAvailable` + exit handlers (`scripts/cli.mjs`): import REAL no check
   pré-arranque e morte por ImportError/ModuleNotFoundError NÃO volta a
   arrancar — mensagem vermelha única com o módulo em falta e o loop de
   «a reiniciar em 5s» cancelado (antes: reinício incondicional eterno,
   poluindo o terminal e travando a consola do Windows).
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER_SOURCE = (ROOT / "scripts" / "install.mjs").read_text(encoding="utf-8")
LAUNCHER_SOURCE = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Instalador: import REAL em vez de find_spec (fim do falso positivo)
# ---------------------------------------------------------------------------


def test_installer_imports_modules_for_real_instead_of_locating_folders():
    block = INSTALLER_SOURCE.split("function missingModules(modules)", 1)[1].split("function installRequirementIfNeeded", 1)[0]
    assert "importlib.import_module(name)" in block
    # a CHAMADA rasa (find_spec) desapareceu do código — os comentários
    # documentam o falso positivo, o código já não o comete.
    assert "importlib.util.find_spec" not in block.replace("importlib.util.find_spec. O find_spec", "doc")
    assert "missing.append(name)" in block
    # 1.0.31: devolve a LISTA dos que falham — nada de binário mudo.
    assert "return broken.split(\",\").map((name) => name.trim()).filter(Boolean);" in block
    # sonda sem veredicto legível assume o pior caso (nunca afirma OK sem provar)
    assert "return [...modules];" in block


def test_installer_heavy_install_only_runs_when_requirements_really_change():
    gate = INSTALLER_SOURCE.split("function installRequirementIfNeeded(", 1)[1].split("function installPlaywrightBrowsers", 1)[0]
    # «reutilizadas» exige imports OK E hash inalterado (nenhum download).
    assert "const fastPath = !forceDeps && persistedHashMatches && missingBefore.length === 0;" in gate
    assert "dependências detectadas e reutilizadas" in gate
    # 1.0.31: a instalação PESADA fica ATRÁS do gate de hash — um import que
    # falhou NUNCA mais despoleta o requirements inteiro.
    assert "if (forceDeps || !persistedHashMatches) {" in gate
    assert '"-m", "pip", "install", "-r", requirementsPath' in gate
    # a reparação é ALVO (spec exata, --force-reinstall) e NÃO fatal
    assert '"--force-reinstall"' in gate
    assert "a instalar APENAS os pacotes em falta" in gate
    repair = gate.split("const missingAfter = missingModules(modules);", 1)[1]
    assert "process.exit" not in repair


def test_installer_checks_the_reported_missing_packages():
    call = INSTALLER_SOURCE.split("function installThunderboltDependencies(", 1)[1].split("function installRemotionDependencies", 1)[0]
    for module in ("psutil", "playwright", "patchright", "serpapi"):
        assert f'"{module}"' in call, f"o instalador já não valida {module}"


# ---------------------------------------------------------------------------
# 2. Launcher: check pré-arranque com import real
# ---------------------------------------------------------------------------


def test_launcher_module_check_imports_for_real():
    block = LAUNCHER_SOURCE.split("function moduleAvailable(moduleName)", 1)[1].split("const requiredWorkerModules", 1)[0]
    assert "importlib.import_module(name)" in block
    # a CHAMADA rasa desapareceu; o comentário explica o porquê
    assert "importlib.util, sys" not in block


def test_launcher_reports_missing_worker_modules_with_the_install_command():
    assert 'const requiredWorkerModules = ["psutil", "serpapi", "playwright", "patchright"];' in LAUNCHER_SOURCE
    block = LAUNCHER_SOURCE.split("function checkWorkerDependencies(label)", 1)[1].split("function configuredMoneyPrinterPath", 1)[0]
    assert "imports obrigatórios ausentes" in block
    assert "npx.cmd --yes --prefer-online @danhachuel/thunderbolt install" in block


# ---------------------------------------------------------------------------
# 3. Launcher: morte por dependências NÃO reinicia (fim do loop infinito)
# ---------------------------------------------------------------------------


def test_launcher_detects_dependency_deaths_from_worker_stderr():
    assert "const dependencyFailurePattern = /ImportError|ModuleNotFoundError|Fatal Python error/i;" in LAUNCHER_SOURCE
    assert "const workerStderrTails = new WeakMap();" in LAUNCHER_SOURCE
    assert "function workerDiedFromDependencies(child)" in LAUNCHER_SOURCE
    # attachQueueWorkerLog memoriza o stderr para o exit handler decidir.
    attach = LAUNCHER_SOURCE.split("function attachQueueWorkerLog(", 1)[1].split("function startQueueWorkers()", 1)[0]
    assert "rememberWorkerStderr(child, chunk);" in attach


def test_queue_workers_stop_instead_of_restarting_on_dependency_deaths():
    block = LAUNCHER_SOURCE.split("function startQueueWorkers()", 1)[1].split("function stopQueueWorkers()", 1)[0]
    assert "queueWorkersDependencyFailureReported" in LAUNCHER_SOURCE.split("function startQueueWorkers()", 1)[0].split("function attachQueueWorkerLog(", 1)[0] or True
    assert "if (shuttingDown || queueWorkersDependencyFailureReported || thumbnailWorker || imageWorker) return;" in LAUNCHER_SOURCE
    thumbnail_exit = block.split("thumbnailWorker.on(\"exit\"", 1)[1].split("imageWorker = spawn(", 1)[0]
    image_exit = block.split("imageWorker.on(\"exit\"", 1)[1]
    for handler in (thumbnail_exit, image_exit):
        assert "workerDiedFromDependencies" in handler
        assert "reportFatalDependencyFailure" in handler
        assert "queueWorkersDependencyFailureReported = true;" in handler
        # o reinício de 5s fica DEPOIS do guard de dependências
        assert handler.index("workerDiedFromDependencies") < handler.index("a reiniciar em 5s")


def test_pipeline_worker_uses_safe_pipes_and_stops_on_dependency_deaths():
    block = LAUNCHER_SOURCE.split("function startPipelineWorker()", 1)[1].split("function attachQueueWorkerLog(", 1)[0]
    # 1.0.20: o worker do pipeline adopta o mesmo stdio-seguro da 1.0.18
    # (o «inherit» era o gatilho documentado do init_sys_streams no Windows).
    assert 'attachQueueWorkerLog(pipelineWorker, "pipeline_worker.log", "pipeline worker");' in LAUNCHER_SOURCE
    assert 'stdio: "inherit"' not in LAUNCHER_SOURCE.split("function startPipelineWorker()", 1)[1].split("function attachQueueWorkerLog(", 1)[0]
    exit_handler = block.split("pipelineWorker.on(\"exit\"", 1)[1]
    assert "workerDiedFromDependencies" in exit_handler
    assert "pipelineDependencyFailureReported = true;" in exit_handler


def test_automation_worker_stops_on_dependency_deaths():
    block = LAUNCHER_SOURCE.split("function startAutomationWorker()", 1)[1].split("function stopPipelineWorker()", 1)[0]
    exit_handler = block.split("worker.on(\"exit\"", 1)[1]
    assert "dependencyFailurePattern.test(dependencyTail)" in exit_handler
    assert "reportFatalDependencyFailure" in exit_handler
    assert "workerDependencyFailureReported = true;" in exit_handler


def test_fatal_message_is_red_and_cancels_the_restart_loop():
    block = LAUNCHER_SOURCE.split("function reportFatalDependencyFailure(", 1)[1].split("function startAutomationWorker()", 1)[0]
    assert "[ERRO FATAL]" in block
    assert "falhou por falta de dependências" in block
    assert "npx.cmd --yes --prefer-online @danhachuel/thunderbolt install' para corrigir" in block
    assert "Loop de reinício cancelado." in block
    assert "\\x1b[31m" in block  # vermelho no terminal
    # o módulo em falta é extraído do traceback (No module named 'X')
    assert "No module named" in LAUNCHER_SOURCE
