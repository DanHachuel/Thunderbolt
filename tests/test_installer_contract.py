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
    assert '"-m", "pip", "install", "-r", requirementsPath' in heavy
    assert "filtered" not in heavy.lower()
    assert "run(pythonBin, [\"-m\", \"pip\", \"install\", \"-r\", requirementsPath])" in heavy


def test_failed_install_or_repair_aborts_with_clear_error():
    """Regra 3: falhar ABORTA com erro claro — nunca pula silenciosamente."""
    gate = INSTALLER_SOURCE.split("function installRequirementIfNeeded(", 1)[1].split("function installPlaywrightBrowsers", 1)[0]
    repair = gate.split("const missingAfter = missingModules(modules);", 1)[1]
    for failure in (
        "pacotes obrigatórios sem spec no requirements.txt",
        "A instalação foi ABORTADA",
    ):
        assert failure in repair
    assert repair.count("process.exit(") >= 3  # sem spec / reparação falhou / ainda em falta
    # e o caminho pesado já aborta pelo run() (exit on failure)
    assert "if (result.status !== 0) process.exit(result.status || 1);" in INSTALLER_SOURCE


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
