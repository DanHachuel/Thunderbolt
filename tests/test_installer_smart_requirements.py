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


def test_repair_failure_warns_and_continues_without_blocking_startup():
    repair = _gate_block().split("const missingAfter = missingModules(modules);", 1)[1]
    assert "a instalação CONTINUA (nada bloqueado)" in repair
    assert "Verifique com: npx.cmd --yes --prefer-online @danhachuel/thunderbolt --check" in repair
    # nenhum process.exit na reparação — o arranque nunca é bloqueado
    assert "process.exit" not in repair


def test_moneyprinter_requirements_keep_the_plain_contract():
    # o requirements do MPT (clonado) continua a valer o gate de hash sem gating
    assert (
        'installRequirementIfNeeded(join(moneyprinterPath, "requirements.txt"), "moneyprinter_requirements_sha256", '
        '["fastapi", "moviepy", "PIL", "numpy", "requests"], "MoneyPrinterTurbo");' in INSTALLER_SOURCE
    )


# ---------------------------------------------------------------------------
# 3. Uploaders GitHub OPT-IN (--with-uploaders)
# ---------------------------------------------------------------------------


def test_uploaders_flag_is_parsed_and_wired_to_the_thunderbolt_requirements():
    assert 'const withUploaders = args.includes("--with-uploaders");' in INSTALLER_SOURCE
    call = INSTALLER_SOURCE.split("function installThunderboltDependencies(", 1)[1].split("function installRemotionDependencies", 1)[0]
    assert '{ gatedModules: ["uploader", "sau_cli"], gatedFlag: withUploaders }' in call
    # TODOS os módulos continuam validados (garantia 1.0.20) — uploader/sau_cli
    # seguem na lista, só a REACÇÃO é que mudou.
    for module in ("psutil", "streamlit", "playwright", "patchright", "camoufox", "uploader", "sau_cli", "serpapi"):
        assert f'"{module}"' in call


def test_default_install_filters_the_heavy_github_uploaders_line():
    gate = _gate_block()
    filtered = gate.split("if (gatedModules.length && !gatedFlag) {", 1)[1].split("} else {", 1)[0]
    # a cópia filtrada vive no home persistente (a pasta do npx pode ser read-only)
    assert 'join(thunderboltHome, "storage", "state", `requirements.${stateKey}.filtered.txt`)' in filtered
    assert "writeFileSync(filteredPath, filteredLines.join(\"\\n\") + \"\\n\", \"utf8\");" in filtered
    # o requirements.txt REAL tem exactamente UMA linha social-auto-upload a filtrar
    assert sum(1 for line in REQUIREMENTS_LINES if line.startswith("social-auto-upload")) == 1
    assert any(line.startswith("justokenmax") for line in REQUIREMENTS_LINES)


def test_missing_uploaders_warn_with_the_opt_in_command_and_skip_download():
    repair = _gate_block().split("const missingAfter = missingModules(modules);", 1)[1]
    warn = repair.split("if (gatedModules.includes(moduleName) && !gatedFlag) {", 1)[1].split("continue;", 1)[0]
    assert "uploader GitHub opt-in" in warn
    assert "install --with-uploaders" in warn


def test_installer_summary_reports_the_uploaders_opt_in():
    main_block = INSTALLER_SOURCE.split("function main() {", 1)[1]
    assert "--with-uploaders" in main_block


# ---------------------------------------------------------------------------
# 4. --check informa (não falha) + backend aciona com o comando exacto
# ---------------------------------------------------------------------------


def test_check_reports_uploader_status_informationally():
    check_block = LAUNCHER_SOURCE.split("function check() {", 1)[1].split('if (args[0] === "install"', 1)[0]
    assert "Uploaders (social-auto-upload)" in check_block
    assert "install --with-uploaders" in check_block
    # informativo: o gate de falha do check continua a depender SÓ dos módulos
    # críticos e do ffmpeg — nunca dos uploaders
    assert "if (missing.length || !ffmpeg) {" in check_block
    assert 'moduleAvailable("uploader") && moduleAvailable("sau_cli")' in check_block


def test_upload_backend_error_names_the_opt_in_flag():
    # o import do uploader é lazy: sem o pacote, o upload falha com a mensagem
    # ACCIONÁVEL (regra 4: validação no momento da acção) — nunca no arranque.
    assert "--with-uploaders" in BACKEND_SOURCE
    assert "uploaders opt-in" in BACKEND_SOURCE
