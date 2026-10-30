"""1.0.42 — Camoufox OBRIGATÓRIO: uma checagem central, zero avisos falsos.

O utilizador reportou a discórdia: a UI «Testar instalação do browser» atesta
que o Camoufox funciona, enquanto o terminal do launcher imprime
«dependências opcionais ausentes (camoufox)». Camoufox é OBRIGATÓRIO (o
stealth do upload directo YouTube depende dele) e passa a haver UMA fonte de
verdade: `hermes_ui.browser_manager.camoufox_environment_ready` (import REAL
do módulo + integridade do binário) — usada pelo botão da UI E pelo boot do
launcher (`python -c`). Sem flag no ambiente => erro REAL com o comando do
instalador; nunca mais um aviso de «opcional».
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_SOURCE = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")
INSTALLER_SOURCE = (ROOT / "scripts" / "install.mjs").read_text(encoding="utf-8")
REQUIREMENTS = (ROOT / "requirements.txt").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Checagem CENTRAL partilhada (Python)
# ---------------------------------------------------------------------------


def test_environment_ready_requires_real_import_and_binary(monkeypatch):
    from hermes_ui import browser_manager

    monkeypatch.setattr(browser_manager, "_camoufox_module_importable", lambda: True)
    monkeypatch.setattr(browser_manager, "_camoufox_browser_downloaded", lambda: True)
    state = browser_manager.camoufox_environment_ready()
    assert state["ready"] is True
    assert state["module"] is True
    assert state["binary"] is True
    assert state["message"] == "Camoufox pronto."


def test_environment_ready_reports_missing_module_with_action(monkeypatch):
    from hermes_ui import browser_manager

    monkeypatch.setattr(browser_manager, "_camoufox_module_importable", lambda: False)
    monkeypatch.setattr(browser_manager, "_camoufox_browser_downloaded", lambda: True)
    state = browser_manager.camoufox_environment_ready()
    assert state["ready"] is False
    assert state["module"] is False
    assert "pacote" in state["message"]


def test_environment_ready_reports_missing_binary_with_action(monkeypatch):
    from hermes_ui import browser_manager

    monkeypatch.setattr(browser_manager, "_camoufox_module_importable", lambda: True)
    monkeypatch.setattr(browser_manager, "_camoufox_browser_downloaded", lambda: False)
    state = browser_manager.camoufox_environment_ready()
    assert state["ready"] is False
    assert state["module"] is True
    assert "binário" in state["message"]


def test_module_probe_is_a_subprocess_that_cannot_pollute_the_host():
    """Regressão da poluição (comportamental): o import REAL do camoufox
    arrasta o `playwright` para o `sys.modules` do hospedeiro — quebrou o
    isolamento de testes que dependem do playwright NÃO estar em memória.
    A checagem central corre as sondas em SUBPROCESSO: o hospedeiro sai
    limpo. Cross-plataforma: onde o módulo existe (dev/estações do
    utilizador) a poluição é verificada; no CI (requirements-dev exclui os
    motores pesados) apenas a consistência e o contrato do subprocesso."""
    import sys

    from hermes_ui import browser_manager

    before = "playwright.sync_api" in sys.modules
    module_present = browser_manager._camoufox_module_importable()
    state = browser_manager.camoufox_environment_ready()
    assert state["module"] is module_present  # consistência em qualquer ambiente
    if module_present:
        assert ("playwright.sync_api" in sys.modules) == before, "a sonda poluiu o hospedeiro"
        assert state["ready"] is state["binary"]
    # e o contrato do subprocesso fica pinado no fonte
    source = (ROOT / "hermes_ui" / "browser_manager.py").read_text(encoding="utf-8")
    assert "def _camoufox_module_importable() -> bool:" in source
    probe_block = source.split("def _camoufox_module_importable", 1)[1].split("def camoufox_environment_ready", 1)[0]
    assert "[sys.executable, \"-c\", \"import importlib; importlib.import_module('camoufox')\"]" in probe_block
    assert "subprocess.run(" in probe_block


def test_browser_status_uses_the_shared_helper(monkeypatch):
    """O botão «Testar instalação» e o boot do launcher partilham a função."""
    from hermes_ui import browser_manager

    monkeypatch.setattr(
        browser_manager,
        "camoufox_environment_ready",
        lambda: {"ready": False, "module": False, "binary": False, "message": "O pacote Camoufox não está instalado."},
    )
    assert browser_manager.get_browser_status("camoufox")["status"] == "not_installed"
    source = (ROOT / "hermes_ui" / "browser_manager.py").read_text(encoding="utf-8")
    assert "def camoufox_environment_ready() -> dict[str, Any]:" in source
    assert "camoufox_environment_ready()" in source


# ---------------------------------------------------------------------------
# 2. Launcher: obrigatório, sem aviso falso, pela checagem central
# ---------------------------------------------------------------------------


def test_false_optional_warning_is_gone_from_the_launcher():
    # a frase só pode sobreviver em COMENTÁRIOS (a lápide do aviso morto) —
    # nenhuma linha de execução a pode emitir
    runtime = "\n".join(
        line for line in LAUNCHER_SOURCE.splitlines() if not line.strip().startswith("//")
    )
    assert "dependências opcionais ausentes" not in runtime
    assert "funcionalidades opcionais ficarão indisponíveis" not in runtime
    # o maquinário de opcionais desapareceu do código por completo
    assert "optionalWorkerModules" not in LAUNCHER_SOURCE
    assert "optionalMissing" not in LAUNCHER_SOURCE


def test_boot_probes_camoufox_through_the_shared_helper():
    assert "camoufoxWorkerReady()" in LAUNCHER_SOURCE
    assert "from hermes_ui.browser_manager import camoufox_environment_ready" in LAUNCHER_SOURCE
    assert "PYTHONPATH: root" in LAUNCHER_SOURCE
    # fallback honesto quando o probe Python não corre: import REAL (1.0.20)
    boot_block = LAUNCHER_SOURCE.split("function camoufoxWorkerReady()", 1)[1].split("function checkWorkerDependencies", 1)[0]
    assert "moduleAvailable(\"camoufox\")" in boot_block


def test_missing_camoufox_is_a_real_error_not_a_warning():
    handler = LAUNCHER_SOURCE.split("function checkWorkerDependencies", 1)[1].split("function configuredMoneyPrinterPath", 1)[0]
    assert 'missing.push("camoufox")' in handler
    assert "imports obrigatórios ausentes" in handler
    assert "install --with-uploaders" in handler or "thunderbolt install" in handler
    # quando tudo está presente, o boot não imprime NADA sobre o Camoufox
    assert "if (!missing.length) return true;" in handler


# ---------------------------------------------------------------------------
# 3. Instalador: obrigatório desde sempre (contrato verificado)
# ---------------------------------------------------------------------------


def test_installer_treats_camoufox_as_required():
    call = INSTALLER_SOURCE.split("function installThunderboltDependencies(", 1)[1].split("function installRemotionDependencies", 1)[0]
    assert '"camoufox"' in call  # validado com import REAL na lista obrigatória
    main_block = INSTALLER_SOURCE.split("function main() {", 1)[1]
    assert "installCamoufoxBrowser();" in main_block
    # o binário é descarregado por omissão (sem --skip-browsers)
    assert "if (!skipDeps && !skipBrowsers) installCamoufoxBrowser();" in main_block


def test_requirements_pin_camoufox_as_a_hard_dependency():
    camoufox_lines = [line for line in REQUIREMENTS.splitlines() if "camoufox" in line.lower()]
    assert camoufox_lines, "requirements.txt deixou de declarar o camoufox"
    for line in camoufox_lines:
        assert not line.strip().startswith("#"), "camoufox não pode ser opcional/comentário"
    assert any("camoufox[geoip]>=0.4,<1" in line for line in camoufox_lines)
