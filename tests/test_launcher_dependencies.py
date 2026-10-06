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
    assert 'installRequirementIfNeeded(join(root, "requirements.txt")' in source
    assert '["psutil", "streamlit"' in source
    assert 'run(pythonBin, ["-m", "pip", "install", "-r", requirementsPath])' in source


def test_installer_installs_remotion_as_a_mandatory_dependency():
    # 0.9.53: o Remotion é obrigatório — as dependências Node instalam-se
    # automaticamente como o Python, os FFmpeg e o Chromium do Playwright;
    # falha do npm install aborta a instalação (não existe --skip-remotion).
    source = (ROOT / "scripts" / "install.mjs").read_text(encoding="utf-8")
    assert "function installRemotionDependencies()" in source
    assert "if (!skipDeps) installRemotionDependencies();" in source
    assert "--skip-remotion" not in source
    block = source.split("function installRemotionDependencies()", 1)[1].split("\nfunction ", 1)[0]
    # npm invocado via npm-cli.js ao lado do node (Node >= 18 recusa .cmd directo)
    assert 'run(process.execPath, [npmCli, "install", "--no-audit", "--no-fund"]' in block
    assert "process.exit(1)" in block
    assert 'join(remotionPackage, "node_modules", "@remotion", "renderer")' in block


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
