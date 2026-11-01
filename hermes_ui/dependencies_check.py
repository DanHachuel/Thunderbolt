"""1.0.47 — diagnóstico de ambiente para a aba Configurações > Dependências.

A fonte de verdade do que é OBRIGATÓRIO é a regra «Pré-requisitos e
Dependências Obrigatórias» do AGENTS.md: venv, Node/NPM, MoneyPrinterTurbo,
Remotion, Playwright, Patchright, Camoufox (GeoIP), FFmpeg, social-auto-upload
+ sau_cli (mais yt-dlp, usado pelo Download Média).

Regras de desenho (restrições da tarefa):
  · NUNCA lança excepção — cada checagem é isolada e uma falha devolve um
    resultado «fail» com a mensagem de solução (o CI sem Node/MPT fica vermelho
    e informativo, não estoura a página);
  · subprocessos com TIMEOPO e captura — a página nunca trava;
  · o Camoufox reusa a checagem CENTRAL da 1.0.42 (`camoufox_environment_ready`),
    a mesma do botão «Testar instalação» e do boot do launcher.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


DEPENDENCY_TIMEOUT_SECONDS = 60


def _result(name: str, ok: bool, *, version: str = "", message: str = "") -> dict[str, Any]:
    return {"name": name, "status": "ok" if ok else "fail", "version": version, "message": message}


def _run(command: list[str], timeout: int = DEPENDENCY_TIMEOUT_SECONDS) -> tuple[int, str, str]:
    """Subprocesso seguro: devolve (returncode, stdout, stderr) sem lançar."""
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            shell=os.name == "nt" and command[0].lower().endswith(".cmd"),
        )
        return completed.returncode, (completed.stdout or "").strip(), (completed.stderr or "").strip()
    except Exception as exc:  # ausente, timeout, permissão — tudo vira «fail»
        return 1, "", f"{type(exc).__name__}: {exc}"


def _settings() -> dict[str, Any]:
    try:
        from hermes_ui.storage import read_json

        payload = read_json("settings.json", {})
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _thunderbolt_home() -> Path:
    env_home = (os.environ.get("THUNDERBOLT_HOME") or "").strip()
    if env_home:
        return Path(env_home)
    storage_dir = (os.environ.get("THUNDERBOLT_STORAGE_DIR") or "").strip()
    if storage_dir:
        return Path(storage_dir).parent
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "THUNDERBOLT"
    return Path.home() / ".thunderbolt"


def _package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _mpt_root(settings: dict[str, Any]) -> Path:
    configured = str(settings.get("moneyprinter_path") or os.environ.get("MONEYPRINTER_PATH") or "").strip()
    return Path(configured).expanduser() if configured else _thunderbolt_home() / "MoneyPrinterTurbo"


_INSTALL_HINT = "Execute o instalador: npx.cmd --yes --prefer-online @danhachuel/thunderbolt install"


# ---------------------------------------------------------------------------
# Checagens individuais — cada uma nunca lança
# ---------------------------------------------------------------------------


def check_python_venv() -> dict[str, Any]:
    """`sys.prefix != sys.base_prefix` = dentro de uma venv."""
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    return _result(
        "Ambiente Python (venv)",
        in_venv,
        version=version,
        message="A aplicação está a correr no Python do sistema, sem venv própria. "
        f"{_INSTALL_HINT} cria o ambiente em {_thunderbolt_home() / '.venv'}.",
    )


def check_node() -> dict[str, Any]:
    # no Windows o npm vive como npm.cmd — o comando nu não resolve pelo spawn
    npm_command = "npm.cmd" if os.name == "nt" else "npm"
    code_node, out_node, err_node = _run(["node", "--version"], timeout=30)
    code_npm, out_npm, err_npm = _run([npm_command, "--version"], timeout=30)
    if code_node != 0:
        return _result("Node.js / NPM", False, message=f"Node.js não encontrado ({err_node or 'comando indisponível'}). Instale o Node.js 18+ e rode o instalador.")
    if code_npm != 0:
        return _result("Node.js / NPM", False, message=f"npm não encontrado ({err_npm or 'comando indisponível'}). Instale o npm e rode o instalador.")
    return _result("Node.js / NPM", True, version=f"node {out_node} · npm {out_npm}")


def check_moneyprinter(settings: dict[str, Any]) -> dict[str, Any]:
    root = _mpt_root(settings)
    required = [root / "cli.py", root / "requirements.txt"]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        return _result(
            "MoneyPrinterTurbo (MPT)",
            False,
            message=f"Motor de vídeo incompleto em {root} (faltam: {', '.join(Path(path).name for path in missing)}). {_INSTALL_HINT}",
        )
    return _result("MoneyPrinterTurbo (MPT)", True, version=str(root))


def check_remotion() -> dict[str, Any]:
    package = _package_root() / "packages" / "remotion"
    persistent_modules = _thunderbolt_home() / "remotion" / "node_modules"
    renderer = persistent_modules / "@remotion" / "renderer"
    if not package.is_dir():
        return _result("Remotion", False, message="Pacote packages/remotion ausente nesta cópia do Thunderbolt. Reinstale a versão actual.")
    if not renderer.is_dir():
        return _result("Remotion", False, message=f"Dependências de renderização não instaladas ({renderer}). {_INSTALL_HINT}")
    return _result("Remotion", True, version=str(persistent_modules))


def check_playwright() -> dict[str, Any]:
    """Executáveis do Chromium e do Firefox resolvidos pelo driver (subprocesso)."""
    code = (
        "from playwright.sync_api import sync_playwright\n"
        "driver = sync_playwright().start()\n"
        "try:\n"
        "    print(driver.chromium.executable_path)\n"
        "    print(driver.firefox.executable_path)\n"
        "finally:\n"
        "    driver.stop()\n"
    )
    returncode, out, err = _run([sys.executable, "-c", code])
    if returncode != 0:
        return _result("Playwright (Chromium e Firefox)", False, message=f"Playwright não respondeu ({err or 'sem detalhe'}). {_INSTALL_HINT}")
    paths = [line.strip() for line in out.splitlines() if line.strip()]
    if len(paths) < 2 or not all(Path(path).is_file() for path in paths[:2]):
        return _result(
            "Playwright (Chromium e Firefox)",
            False,
            message="Browsers do Playwright não descarregados. " + _INSTALL_HINT,
        )
    return _result("Playwright (Chromium e Firefox)", True, version=paths[0])


def check_patchright() -> dict[str, Any]:
    code = (
        "from patchright.sync_api import sync_playwright\n"
        "driver = sync_playwright().start()\n"
        "try:\n"
        "    print(driver.chromium.executable_path)\n"
        "finally:\n"
        "    driver.stop()\n"
    )
    returncode, out, err = _run([sys.executable, "-c", code])
    if returncode != 0:
        return _result("Patchright (Chromium)", False, message=f"Patchright não respondeu ({err or 'sem detalhe'}). {_INSTALL_HINT}")
    paths = [line.strip() for line in out.splitlines() if line.strip()]
    if not paths or not Path(paths[0]).is_file():
        return _result("Patchright (Chromium)", False, message="Chromium do Patchright não descarregado. " + _INSTALL_HINT)
    return _result("Patchright (Chromium)", True, version=paths[0])


def check_camoufox() -> dict[str, Any]:
    """Reusa a checagem CENTRAL da 1.0.42 — a mesma do botão «Testar instalação»."""
    try:
        from hermes_ui.browser_manager import camoufox_environment_ready

        state = camoufox_environment_ready()
    except Exception as exc:  # nunca lança
        return _result("Camoufox (GeoIP)", False, message=f"Checagem indisponível ({type(exc).__name__}: {exc}).")
    ready = bool(state.get("ready"))
    version = "pronto" if ready else ""
    return _result("Camoufox (GeoIP)", ready, version=version, message=str(state.get("message") or _INSTALL_HINT))


def check_ffmpeg(settings: dict[str, Any]) -> dict[str, Any]:
    configured = str(settings.get("ffmpeg_path") or "").strip()
    if configured and Path(configured).is_file():
        return _result("FFmpeg (binário)", True, version=configured)
    try:
        import imageio_ffmpeg

        bundled = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        return _result("FFmpeg (binário)", False, message=f"Binário do imageio-ffmpeg indisponível ({type(exc).__name__}). {_INSTALL_HINT}")
    if not bundled or not Path(bundled).is_file():
        return _result("FFmpeg (binário)", False, message="Binário do FFmpeg não encontrado. " + _INSTALL_HINT)
    return _result("FFmpeg (binário)", True, version=str(bundled))


def check_social_auto_upload() -> dict[str, Any]:
    """Pacote `uploader` importável + CLI `sau_cli` respondendo — pela MESMA
    mecânica do runtime (provisionamento `conf` de 1.0.06 e `_run_sau_cli`),
    para o diagnóstico nunca divergir do que o upload realmente usa."""
    problems: list[str] = []
    try:
        from hermes_ui.social_auto_upload_backend import _ensure_upstream_runtime_conf, _run_sau_cli

        _ensure_upstream_runtime_conf()
        importlib.import_module("uploader")
    except Exception as exc:
        problems.append(f"módulo «uploader» ({exc})")
    try:
        from hermes_ui.social_auto_upload_backend import _run_sau_cli

        cli = _run_sau_cli(["--help"], timeout_seconds=30)
        if cli.get("returncode") != 0:
            problems.append(f"CLI «sau_cli» ({cli.get('message') or cli.get('stderr') or 'não responde'})")
    except Exception as exc:
        problems.append(f"CLI «sau_cli» ({type(exc).__name__}: {exc})")
    if problems:
        return _result(
            "social-auto-upload (SAU) + sau_cli",
            False,
            message=f"Uploader incompleto: {'; '.join(str(problem) for problem in problems)}. {_INSTALL_HINT}",
        )
    return _result("social-auto-upload (SAU) + sau_cli", True, version="pacote + CLI operacionais")


def check_yt_dlp() -> dict[str, Any]:
    try:
        import yt_dlp.version as yt_dlp_version

        version = str(getattr(yt_dlp_version, "__version__", "") or "").strip()
    except Exception:
        version = ""
    if not version:
        try:
            import yt_dlp  # ainda importa? então está instalado, só sem versão legível

            _ = yt_dlp
        except Exception as exc:
            return _result("yt-dlp", False, message=f"Módulo «yt_dlp» não importa ({type(exc).__name__}). {_INSTALL_HINT}")
    return _result("yt-dlp", True, version=version)


def check_all_dependencies() -> list[dict[str, Any]]:
    """Diagnóstico completo — NUNCA lança (cada checagem é isolada)."""
    settings = _settings()
    checks = (
        lambda: check_python_venv(),
        lambda: check_node(),
        lambda: check_moneyprinter(settings),
        lambda: check_remotion(),
        lambda: check_playwright(),
        lambda: check_patchright(),
        lambda: check_camoufox(),
        lambda: check_ffmpeg(settings),
        lambda: check_social_auto_upload(),
        lambda: check_yt_dlp(),
    )
    report: list[dict[str, Any]] = []
    for check in checks:
        try:
            report.append(check())
        except Exception as exc:  # cinto de segurança: nada estoura a página
            report.append(_result("Checagem", False, message=f"Falha inesperada ({type(exc).__name__}: {exc})."))
    return report
