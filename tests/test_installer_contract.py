"""1.0.44 — CONTRATO DO INSTALADOR: pré-requisitos obrigatórios, zero opt-in.

Regra «Pré-requisitos e Dependências Obrigatórias (IMUTÁVEL)» do AGENTS.md:
o `npx @danhachuel/thunderbolt install` instala TODAS as dependências
obrigatórias incondicionalmente — nenhuma pode ficar atrás de flag opt-in
(a era `--with-uploaders` da 1.0.31 foi revertida na 1.0.44). Este ficheiro é
o porteiro: nenhuma sessão futura volta a colocar o social-auto-upload (ou
qualquer outra dependência essencial) atrás de uma flag.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER_SOURCE = (ROOT / "scripts" / "install.mjs").read_text(encoding="utf-8")
AGENTS_SOURCE = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
REQUIREMENTS = (ROOT / "requirements.txt").read_text(encoding="utf-8")

# as dependências obrigatórias validadas pelo instalador (import real 1.0.20)
MANDATORY_MODULES = (
    "psutil",
    "streamlit",
    "requests",
    "pandas",
    "imageio_ffmpeg",
    "playwright",
    "patchright",
    "camoufox",
    "filelock",
    "uploader",  # social-auto-upload — NUNCA opt-in
    "sau_cli",   # CLI multi-plataforma — NUNCA opt-in
    "serpapi",
)

# strings que denunciam dependência essencial atrás de flag (a lição 1.0.31)
FORBIDDEN_STRINGS = (
    "--with-uploaders",
    "withUploaders",
    "gatedModules",
    "gatedFlag",
    "skipUploaders",
    "skipUploders",
    "requirements.*.filtered.txt",
    "filteredPath",
)


def _runtime_lines() -> str:
    """Linhas de execução do instalador (comentários documentam a história)."""
    return "\n".join(
        line for line in INSTALLER_SOURCE.splitlines() if not line.strip().startswith("//")
    )


def test_no_opt_in_flag_for_mandatory_dependencies():
    runtime = _runtime_lines()
    for forbidden in FORBIDDEN_STRINGS:
        assert forbidden not in runtime, f"o instalador voltou a usar «{forbidden}» — dependência obrigatória atrás de flag"
    assert "opt-in" not in runtime


def test_all_mandatory_modules_are_validated_unconditionally():
    call = INSTALLER_SOURCE.split("function installThunderboltDependencies(", 1)[1].split("function installRemotionDependencies", 1)[0]
    for module in MANDATORY_MODULES:
        assert f'"{module}"' in call, f"o instalador deixou de validar «{module}»"
    # a chamada não passa opções de gating (4 args, sem quinto parâmetro)
    assert "installRequirementIfNeeded(\n    join(root, \"requirements.txt\"),\n    \"thunderbolt_requirements_sha256\",\n    [\"psutil\", \"streamlit\"" in INSTALLER_SOURCE
    assert "gatedModules" not in call


def test_heavy_install_always_uses_the_complete_requirements():
    """A instalação pesada (quando o hash muda) é SEMPRE o ficheiro inteiro —
    nenhuma cópia filtrada a esconder pacotes obrigatórios."""
    heavy = INSTALLER_SOURCE.split("if (forceDeps || !persistedHashMatches) {", 1)[1].split("writeFileSync(markerPath", 1)[0]
    assert '"--quiet", "--no-input", "--disable-pip-version-check", "-r", requirementsPath' in heavy
    assert "filtered" not in heavy.lower()
    # 1.0.48 — execução silenciosa (rótulo amigável + install.log), ficheiro
    # INTEIRO. 1.0.94: o passo pesado passou a ter tempo limite + heartbeat
    # (runQuietTimed ~ runQuiet, mas com timeout, retry de rede e beat).
    assert "runQuietTimed(" in heavy
    assert "runQuiet(" not in heavy  # o passo pesado não volta a ser sem tempo limite


def test_failed_install_or_repair_aborts_with_clear_error():
    """Regra 3: falhar ABORTA com erro claro — nunca pula silenciosamente."""
    gate = INSTALLER_SOURCE.split("function installRequirementIfNeeded(", 1)[1].split("function installPlaywrightBrowsers", 1)[0]
    repair = gate.split("const missingAfter = missingModules(modules);", 1)[1]
    for failure in (
        "A instalação foi ABORTADA",
        "reportMissingModules(",  # 1.0.91: diagnóstico real + aborto (sem spec/ainda em falta)
    ):
        assert failure in repair
    assert repair.count("process.exit(") >= 3  # sem spec / reparação falhou / ainda em falta
    # e o caminho pesado já aborta pelo run() (exit on failure)
    assert "if (result.status !== 0) process.exit(result.status || 1);" in INSTALLER_SOURCE
    # 1.0.91: a causa de cada pacote é impressa antes do aborto
    assert "reportMissingModules(label, stillMissing);" in repair
    assert "reportMissingModules(label, unmatched," in repair


def test_browsers_and_mpt_abort_on_failure():
    """Browsers obrigatórios (Playwright/Patchright/Camoufox) e o MPT:
    falha = aborto com erro claro (nenhum aviso silencioso)."""
    for function in ("installPlaywrightBrowsers", "installPatchrightBrowser", "installCamoufoxBrowser", "cloneMoneyPrinter"):
        assert f"function {function}(" in INSTALLER_SOURCE
        block = INSTALLER_SOURCE.split(f"function {function}(", 1)[1].split("\nfunction ", 1)[0]
        assert "process.exit(" in block, f"{function} deixou de abortar em falha"


def test_requirements_declare_every_mandatory_module():
    """O requirements.txt declara as distribuições dos módulos obrigatórios —
    a reparação alvo precisa da spec exacta de cada uma."""
    for distribution in (
        "social-auto-upload @ https://github.com/dreammis/social-auto-upload",  # uploader + sau_cli
        "camoufox[geoip]>=0.4,<1",
        "playwright>=1.45,<2",
        "patchright==1.58.2",
        "psutil>=5.9,<8",
        "serpapi>=1.1,<2",
    ):
        assert distribution in REQUIREMENTS, f"requirements.txt deixou de declarar {distribution}"


def test_agents_md_records_the_immutable_rule():
    assert "## Pré-requisitos e Dependências Obrigatórias (IMUTÁVEL)" in AGENTS_SOURCE
    assert "--with-uploaders" in AGENTS_SOURCE  # a regra cita o exemplo proibido
    assert "social-auto-upload (SAU) + `sau_cli` (CLI multi-plataforma)" in AGENTS_SOURCE


# ---------------------------------------------------------------------------
# 1.0.48 — REGRAS INVIOLÁVEIS DE ESCOPO, TERMINAL E PROJETO (AGENTS.md)
# ---------------------------------------------------------------------------


def test_agents_md_records_the_terminal_and_scope_rules():
    assert "## 🚨 REGRAS INVIOLÁVEIS DE ESCOPO, TERMINAL E PROJETO" in AGENTS_SOURCE
    assert "Silêncio Absoluto no Terminal" in AGENTS_SOURCE
    assert "Fim do Mojibake" in AGENTS_SOURCE
    assert "PYTHONIOENCODING=utf-8" in AGENTS_SOURCE
    assert "Verificação de Importação Correta" in AGENTS_SOURCE


def test_agents_md_records_the_menu_insertion_rule():
    """1.0.49 — crava a regra de UI: novos itens NUNCA reordenam o menu."""
    assert "## Regra de UI: Inserção de Itens" in AGENTS_SOURCE
    assert "NUNCA mova, reordene ou toque na posição dos itens que já estavam lá" in AGENTS_SOURCE
    assert "Insira o novo item EXATAMENTE na posição solicitada" in AGENTS_SOURCE


def test_pip_installs_are_quiet_and_never_touch_the_terminal():
    """Regra 2: pip em --quiet/--no-input e NENHUM stdio "inherit" — o
    terminal mostra só mensagens amigáveis; a saída completa vai a install.log."""
    runtime = "\n".join(
        line for line in INSTALLER_SOURCE.splitlines() if not line.strip().startswith("//")
    )
    assert '"-m", "pip", "install", "--quiet", "--no-input", "--disable-pip-version-check", "-r", requirementsPath' in runtime
    # 1.0.91 - --no-cache-dir: um ZIP do GitHub corrompido no cache do pip era
    # reaproveitado em cada tentativa de reparação dos uploaders.
    assert '"-m", "pip", "install", "--quiet", "--no-input", "--force-reinstall", "--no-cache-dir", "--disable-pip-version-check"' in runtime
    assert 'stdio: "inherit"' not in runtime  # nada de pip/npm/browser no console


def test_installer_output_is_redirected_to_install_log():
    runtime = "\n".join(
        line for line in INSTALLER_SOURCE.splitlines() if not line.strip().startswith("//")
    )
    assert "install.log" in runtime
    assert "appendInstallLog(" in runtime
    assert "function runQuiet(" in INSTALLER_SOURCE  # execução silenciosa com aborto claro
    # o caminho feliz imprime SÓ a etiqueta; no falhanço aponta o registo
    assert 'stdout: []' not in runtime
    assert 'stdio: ["ignore", "pipe", "pipe"]' in runtime


def test_git_and_npm_are_quiet_too():
    assert '"clone", "--quiet", "--depth", "1"' in INSTALLER_SOURCE
    assert INSTALLER_SOURCE.count('"--silent"') >= 3  # as 3 vias do npm install (npmCli/cmd/npm)


def test_post_install_import_check_uses_the_venv_python():
    """Regra 4: a verificação pós-instalação (imports que validam uploader,
    sau_cli, camoufox...) usa o pythonBin — o interpretador do .venv."""
    probe = INSTALLER_SOURCE.split("function missingModules(", 1)[1].split("\nfunction ", 1)[0]
    assert "spawnSync(pythonBin," in probe
    assert "pythonBin = " in INSTALLER_SOURCE  # definido a partir do venvPath
    assert 'join(venvPath, "Scripts", "python.exe")' in INSTALLER_SOURCE
    # e nunca um python genérico do sistema na verificação
    runtime = "\n".join(
        line for line in INSTALLER_SOURCE.splitlines() if not line.strip().startswith("//")
    )
    assert '"python3", "-c"' not in runtime
    assert '"python", "-c"' not in runtime


def test_python_environment_forces_utf8_for_every_subprocess():
    """Regra 3 (fim do mojibake): todas as execuções levam o ambiente UTF-8."""
    assert 'PYTHONIOENCODING: "utf-8"' in INSTALLER_SOURCE
    assert 'PYTHONUTF8: "1"' in INSTALLER_SOURCE
    assert 'PYTHONLEGACYWINDOWSSTDIO: "1"' in INSTALLER_SOURCE
    # e o runQuiet propaga esse ambiente em TODAS as chamadas
    quiet = INSTALLER_SOURCE.split("function runQuiet(", 1)[1].split("\nfunction ", 1)[0]
    assert "env: { ...pythonEnvironment" in quiet
