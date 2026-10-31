"""1.0.31 — requirements inteligentes no instalador.

Critério de sucesso da tarefa: correr `npx @danhachuel/thunderbolt install` com
o ambiente já configurado NÃO volta a descarregar nada, a menos que o
requirements.txt tenha mudado mesmo (hash persistido); pacotes partidos são
reparados ALVO (apenas os que falham, com a spec exacta) e nunca bloqueiam o
arranque; os uploaders GitHub (social-auto-upload) ficam OPT-IN
(--with-uploaders) — um zip pesado que não pode obrigar a um download massivo
só porque o seu import falhou.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER_SOURCE = (ROOT / "scripts" / "install.mjs").read_text(encoding="utf-8")
LAUNCHER_SOURCE = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")
BACKEND_SOURCE = (ROOT / "hermes_ui" / "social_auto_upload_backend.py").read_text(encoding="utf-8")
REQUIREMENTS_LINES = [
    line.strip()
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.strip().startswith("#")
]


def _gate_block() -> str:
    return INSTALLER_SOURCE.split("function installRequirementIfNeeded(", 1)[1].split("function installPlaywrightBrowsers", 1)[0]


# ---------------------------------------------------------------------------
# 1. Hash decide a instalação pesada (nada de downloads em vão)
# ---------------------------------------------------------------------------


def test_requirements_hash_is_the_only_trigger_for_the_heavy_install():
    gate = _gate_block()
    # o hash vem do install-state.json (storage/state) + marcador .sha256 junto
    # ao venv — ambos PERSISTENTES no THUNDERBOLT_HOME, sobrevivem às pastas do
    # npx que mudam a cada versão.
    assert "const dependencyStatePath = join(thunderboltHome, \"storage\", \"state\", \"install-state.json\");" in INSTALLER_SOURCE
    assert "const hashMatches = state[stateKey] === currentHash;" in gate
    assert "persistedHashMatches = hashMatches || markerHash === currentHash" in gate
    # a mensagem antiga que reinstalava por causa de imports partidos desapareceu
    assert "A reinstalar o requirements.txt por causa deles" not in INSTALLER_SOURCE


def test_broken_optional_import_no_longer_forces_the_full_requirements():
    gate = _gate_block()
    # caminho rápido: hash OK + todos os imports OK => reutiliza, zero pip
    assert "dependências detectadas e reutilizadas; nenhuma reinstalação necessária." in gate
    # a sonda de imports (missingBefore) NÃO é condição da instalação pesada —
    # apenas do caminho rápido e da reparação alvo
    heavy = gate.split("if (forceDeps || !persistedHashMatches) {", 1)[1].split("const missingAfter", 1)[0]
    assert "missingBefore" not in heavy


# ---------------------------------------------------------------------------
# 2. Reparação ALVO: só os pacotes em falta, com a spec exacta, nunca fatal
# ---------------------------------------------------------------------------


def test_repair_uses_the_exact_requirements_spec_per_module():
    # resolver nome de import → LINHA do requirements (versão/URL preservados;
    # nunca nome nu, que deixaria o pip re-resolver versões)
    assert "function requirementSpecForModule(lines, moduleName)" in INSTALLER_SOURCE
    assert "function requirementAliasForModule(moduleName)" in INSTALLER_SOURCE
    aliases = INSTALLER_SOURCE.split("const moduleRequirementAliases = {", 1)[1].split("};", 1)[0]
    assert 'pil: "pillow"' in aliases
    assert 'uploader: "social-auto-upload"' in aliases
    assert 'sau_cli: "social-auto-upload"' in aliases
    assert 'googleapiclient: "google-api-python-client"' in aliases
    # os dois imports do social-auto-upload não podem duplicar a mesma spec
    assert "if (!repairSpecs.includes(spec)) repairSpecs.push(spec);" in INSTALLER_SOURCE


def test_repair_failure_aborts_the_installation():
    """1.0.44 — regra 3 do AGENTS.md: falhar a reparação de um pacote
    obrigatório ABORTA a instalação com erro claro (a cultura do
    "aviso e continua" da 1.0.31 morreu — nada de skip silencioso)."""
    repair = _gate_block().split("const missingAfter = missingModules(modules);", 1)[1]
    assert "A instalação foi ABORTADA" in repair
    assert "a instalação CONTINUA" not in repair
    assert repair.count("process.exit(") >= 3  # sem spec / reparação falhou / ainda em falta
    # e a mensagem aponta sempre para a acção seguinte
    assert "npx.cmd --yes --prefer-online @danhachuel/thunderbolt install --force-deps" in repair


def test_moneyprinter_requirements_keep_the_plain_contract():
    # o requirements do MPT (clonado) continua a valer o gate de hash sem gating
    assert (
        'installRequirementIfNeeded(join(moneyprinterPath, "requirements.txt"), "moneyprinter_requirements_sha256", '
        '["fastapi", "moviepy", "PIL", "numpy", "requests"], "MoneyPrinterTurbo");' in INSTALLER_SOURCE
    )


# ---------------------------------------------------------------------------
# 3. Uploaders GitHub OPT-IN (--with-uploaders)
# ---------------------------------------------------------------------------


def _installer_runtime() -> str:
    """Linhas de execução do instalador (comentários documentam a história)."""
    return "\n".join(
        line for line in INSTALLER_SOURCE.splitlines() if not line.strip().startswith("//")
    )


def test_uploaders_are_unconditional_mandatory_dependencies():
    """1.0.44 — a era opt-in (--with-uploaders) foi REVERTIDA: os uploaders
    GitHub são OBRIGATÓRIOS e validados/reparados como todos os módulos."""
    assert "--with-uploaders" not in _installer_runtime()
    assert "withUploaders" not in INSTALLER_SOURCE
    call = INSTALLER_SOURCE.split("function installThunderboltDependencies(", 1)[1].split("function installRemotionDependencies", 1)[0]
    for module in ("psutil", "streamlit", "playwright", "patchright", "camoufox", "uploader", "sau_cli", "serpapi"):
        assert f'"{module}"' in call
    # a chamada não carrega opções de gating
    assert "gatedModules" not in call


def test_default_install_never_filters_the_requirements_file():
    """A instalação pesada é sempre o ficheiro INTEIRO — nenhuma cópia filtrada
    a esconder pacotes obrigatórios (social-auto-upload incluído)."""
    runtime = _installer_runtime()
    assert "filtered" not in runtime.lower()
    heavy = INSTALLER_SOURCE.split("if (forceDeps || !persistedHashMatches) {", 1)[1].split("writeFileSync(markerPath", 1)[0]
    assert '"-m", "pip", "install", "-r", requirementsPath' in heavy
    assert "run(pythonBin, [\"-m\", \"pip\", \"install\", \"-r\", requirementsPath])" in heavy
    # o requirements.txt REAL tem exactamente UMA linha social-auto-upload — e ela é instalada
    assert sum(1 for line in REQUIREMENTS_LINES if line.startswith("social-auto-upload")) == 1
    assert any(line.startswith("justokenmax") for line in REQUIREMENTS_LINES)


def test_missing_uploaders_are_repaired_like_any_mandatory_module():
    """Uploader em falta entra na reparação ALVO como os restantes; falhar a
    reparação ABORTA a instalação (regra 3 do AGENTS.md) — nunca um skip."""
    repair = _gate_block().split("const missingAfter = missingModules(modules);", 1)[1]
    assert "gatedModules" not in repair
    assert "opt-in" not in repair
    assert "A instalação foi ABORTADA" in repair
    assert repair.count("process.exit(") >= 3


def test_installer_summary_has_no_opt_in_state():
    main_block = INSTALLER_SOURCE.split("function main() {", 1)[1]
    assert "--with-uploaders" not in _installer_runtime()
    assert "Uploaders (social-auto-upload): fora desta instalação" not in main_block

# ---------------------------------------------------------------------------


def test_check_reports_uploaders_as_mandatory():
    """1.0.44 — o --check informa o estado dos uploaders e FALHA se estiverem
    em falta: são obrigatórios, não há mais sugestão de flag opt-in."""
    check_block = LAUNCHER_SOURCE.split("function check() {", 1)[1].split('if (args[0] === "install"', 1)[0]
    assert "Uploaders (social-auto-upload/sau_cli): OK." in check_block
    assert "dependências obrigatórias do upload automático" in check_block
    assert "--with-uploaders" not in check_block
    # a falha do check passa a incluir os uploaders
    assert "if (missing.length || !ffmpeg || !uploadersReady) {" in check_block


def test_upload_backend_error_names_the_opt_in_flag():
    # o import do uploader é lazy: sem o pacote, o upload falha com a mensagem
    # ACCIONÁVEL (regra 4: validação no momento da acção) — nunca no arranque.
    assert "--with-uploaders" in BACKEND_SOURCE
    assert "uploaders opt-in" in BACKEND_SOURCE
