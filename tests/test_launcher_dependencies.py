from __future__ import annotations

import json
import subprocess
import sys
import venv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_psutil_is_declared_in_production_dependency_files():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "psutil>=5.9" in requirements
    assert '"psutil>=5.9.0,<8"' in pyproject


def test_installer_checks_psutil_before_reusing_dependency_state():
    source = (ROOT / "scripts" / "install.mjs").read_text(encoding="utf-8")
    # 1.0.31: a chamada é multi-linha (gained as opções de gating) — o contrato
    # é o MESMO: o requirements do Thunderbolt valida psutil com import real.
    call = source.split("function installThunderboltDependencies(", 1)[1].split("function installRemotionDependencies", 1)[0]
    assert 'join(root, "requirements.txt"),' in call
    assert '["psutil", "streamlit"' in call
    assert 'run(pythonBin, ["-m", "pip", "install", "-r", requirementsPath])' in source


def test_installer_installs_remotion_as_a_mandatory_persistent_dependency():
    # 0.9.55: as dependências do Remotion vivem em THUNDERBOLT_HOME/remotion —
    # persistentes entre versões, como o .venv, os FFmpeg e o Chromium do
    # Playwright. A pasta da versão no npx é recriada a cada actualização e
    # não pode ser o local de instalação (reinstalaria 257 pacotes do zero).
    source = (ROOT / "scripts" / "install.mjs").read_text(encoding="utf-8")
    assert "function installRemotionDependencies()" in source
    assert "if (!skipDeps) installRemotionDependencies();" in source
    assert "--skip-remotion" not in source
    block = source.split("function installRemotionDependencies()", 1)[1].split("\nfunction ", 1)[0]
    assert 'join(thunderboltHome, "remotion")' in block
    # detecção por hash (padrão .sha256 do requirements.txt) — sem reinstalação por versão
    assert ".remotion-dependencies.sha256" in block
    assert "fileHash(packageJson)" in block
    # junction liga a cópia da versão às dependências persistentes
    assert "symlinkSync" in block
    assert '"junction"' in block
    # npm via npm-cli.js (Node >= 18 recusa .cmd directo, CVE-2024-27980)
    assert 'run(process.execPath, [npmCli, "install", "--no-audit", "--no-fund"]' in block
    # validação do binário do esbuild mesmo com postinstall bloqueado pelo npm
    assert "require('esbuild').transform" in block
    # obrigatória e fatal: falha aborta a instalação
    assert "process.exit(1)" in block


def test_launcher_blocks_workers_without_import_retries():
    source = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")
    assert 'const requiredWorkerModules = ["psutil", "serpapi", "playwright", "patchright"]' in source
    assert 'Execute: npx.cmd --yes --prefer-online @danhachuel/thunderbolt install' in source
    assert "workerDependencyFailureReported" in source
    assert "pipelineDependencyFailureReported" in source
    assert "if (!checkWorkerDependencies(\"o worker do pipeline de vídeos\")) process.exit(1);" in source
    assert "pipelineFailureCount >= 5" in source


def test_clean_venv_installs_psutil_from_production_requirement(tmp_path):
    venv_dir = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True, clear=True).create(venv_dir)
    python = venv_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    probe = subprocess.run(
        [str(python), "-c", "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('psutil') else 1)"],
        capture_output=True,
        text=True,
    )
    assert probe.returncode != 0
    install = subprocess.run(
        [str(python), "-m", "pip", "install", "--disable-pip-version-check", "psutil>=5.9.0,<8"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert install.returncode == 0, install.stderr[-2000:]
    verify = subprocess.run([str(python), "-c", "import psutil; print(psutil.__version__)"], capture_output=True, text=True)
    assert verify.returncode == 0, verify.stderr
    assert verify.stdout.strip()


def test_installer_installs_the_camoufox_browser_as_a_mandatory_dependency():
    # 0.9.57: o pacote Python camoufox vinha com os requirements, mas o binário
    # Firefox (sessão de upload directo) exigia fetch manual — agora instala
    # automaticamente como o Chromium do Playwright e do Patchright.
    # 1.0.21: falha deixa de ABORTAR a instalação (fatal → aviso): a rede pode
    # falhar, o resto da instalação termina e o --check denuncia o binário.
    source = (ROOT / "scripts" / "install.mjs").read_text(encoding="utf-8")
    assert "function installCamoufoxBrowser()" in source
    assert "function camoufoxBrowserDownloaded()" in source
    assert "if (!skipDeps && !skipBrowsers) installCamoufoxBrowser();" in source
    block = source.split("function installCamoufoxBrowser()", 1)[1].split("\nfunction ", 1)[0]
    assert '"-m", "camoufox", "fetch"' in block
    assert "camoufoxBrowserDownloaded()" in block
    # sucesso = exit 0 do fetch E detecção pós-fetch a confirmar o binário
    assert "if (result.status === 0 && camoufoxBrowserDownloaded())" in block
    assert '"Camoufox: browser instalado."' in block
    # 1.0.44 — regra "Pré-requisitos e Dependências Obrigatórias": falha = ABORTO com erro claro
    assert '"Falha ao baixar o binário do Camoufox. A instalação foi ABORTADA."' in block
    assert "process.exit(result.status || 1);" in block
    # 1.0.22: integridade REAL — o directório `camoufox path` com bytes;
    # «Installed: yes» do version fica como FALLBACK.
    detection_block = source.split("function camoufoxBrowserDownloaded()", 1)[1].split("\nfunction ", 1)[0]
    assert '"-m", "camoufox", "path"' in source
    assert "directoryHasContent(directory)" in detection_block
    assert "existsSync(directory) && directoryHasContent(directory)" in detection_block
    assert '"-m", "camoufox", "version"' in detection_block
    assert "Installed" in detection_block


def test_installer_skip_browsers_flag_leaves_plain_install_always_downloading():
    # 1.0.22: sem flags, `npx thunderbolt install` baixa SEMPRE os browsers;
    # --skip-browsers é a ÚNICA forma explicita de os saltar.
    source = (ROOT / "scripts" / "install.mjs").read_text(encoding="utf-8")
    main_block = source.split("function main()", 1)[1]
    assert 'const skipBrowsers = args.includes("--skip-browsers");' in main_block
    for guard in (
        "if (!skipDeps && !skipBrowsers) installPlaywrightBrowsers();",
        "if (!skipDeps && !skipBrowsers) installPatchrightBrowser();",
        "if (!skipDeps && !skipBrowsers) installCamoufoxBrowser();",
    ):
        assert guard in main_block, guard
    # os browsers saíram de installThunderboltDependencies (só requirements)
    deps_block = source.split("function installThunderboltDependencies(", 1)[1].split("\nfunction ", 1)[0]
    assert "installPlaywrightBrowsers()" not in deps_block
    assert "installPatchrightBrowser()" not in deps_block
    # o resumo final avisa quando os browsers foram saltos
    assert "SALTOU (--skip-browsers)" in main_block


def test_doctor_check_reports_a_missing_camoufox_binary():
    # 1.0.21: o --check valida o binário do Camoufox (o pip não o traz) e
    # avisa em claro quando falta — sem falhar o check inteiro.
    source = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")
    assert "function camoufoxBinaryDownloaded()" in source
    probe = source.split("function camoufoxBinaryDownloaded()", 1)[1].split("\nfunction ", 1)[0]
    assert '"-m", "camoufox", "version"' in probe
    # 1.0.22: integridade REAL — directório `camoufox path` com bytes,
    # version como fallback.
    assert '"-m", "camoufox", "path"' in source
    assert "existsSync(directory) && directoryHasContent(directory)" in probe
    check_block = source.split("function check()", 1)[1].split('if (args[0] === "doctor"', 1)[0]
    assert "Camoufox: binário do browser ausente. Execute o instalador novamente." in check_block
    assert '"Camoufox: binário do browser OK."' in check_block


def test_browser_manager_camoufox_status_still_reports_fetch_hint():
    # O hint manual mantém-se na UI para diagnósticos, mas o instalador já
    # resolve o passo automaticamente.
    source = (ROOT / "hermes_ui" / "browser_manager.py").read_text(encoding="utf-8")
    assert 'CAMOUFOX_FETCH_HINT = "Execute python -m camoufox fetch para descarregar o browser Camoufox."' in source
    assert "binário Firefox do Camoufox não está descarregado" in source
