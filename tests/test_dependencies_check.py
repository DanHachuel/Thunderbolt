"""1.0.47 — diagnóstico de ambiente (Configurações > Dependências).

Contrato: `check_all_dependencies()` devolve as 10 dependências obrigatórias
(regra do AGENTS.md), NUNCA lança excepção — cada checagem é isolada e uma
falha vira «fail» com a mensagem de solução (o CI sem Node/MPT fica vermelho
e informativo, não estoura a página). O Camoufox reusa a checagem central da
1.0.42; o social-auto-upload reusa a mecânica do runtime (provisionamento
`conf` + `_run_sau_cli`).
"""

from __future__ import annotations

import sys as system_sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

from hermes_ui import dependencies_check


ALL_NAMES = (
    "Ambiente Python (venv)",
    "Node.js / NPM",
    "MoneyPrinterTurbo (MPT)",
    "Remotion",
    "Playwright (Chromium e Firefox)",
    "Patchright (Chromium)",
    "Camoufox (GeoIP)",
    "FFmpeg (binário)",
    "social-auto-upload (SAU) + sau_cli",
    "yt-dlp",
)


def _sandbox(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(dependencies_check, "_settings", lambda: {})
    monkeypatch.setattr(dependencies_check, "_thunderbolt_home", lambda: tmp_path / "home")
    monkeypatch.setattr(dependencies_check, "_package_root", lambda: tmp_path / "pkg")


def test_report_lists_all_mandatory_dependencies_in_order():
    report = dependencies_check.check_all_dependencies()
    assert [item["name"] for item in report] == list(ALL_NAMES)
    assert all(item["status"] in {"ok", "fail"} for item in report)
    assert all(isinstance(item.get("message"), str) for item in report)
    assert all(isinstance(item.get("version"), str) for item in report)


def test_everything_broken_returns_fail_with_action_never_raising(tmp_path, monkeypatch):
    _sandbox(tmp_path, monkeypatch)
    monkeypatch.setattr(dependencies_check, "_run", lambda *args, **kwargs: (1, "", "comando indisponível"))
    # venv: fingir Python do sistema (prefix == base_prefix)
    monkeypatch.setattr(dependencies_check.sys, "prefix", "/falso")
    monkeypatch.setattr(dependencies_check.sys, "base_prefix", "/falso")
    # módulos opcionais ausentes (None em sys.modules => ImportError no import)
    for name in ("imageio_ffmpeg", "yt_dlp", "yt_dlp.version", "uploader"):
        monkeypatch.setitem(system_sys.modules, name, None)
    monkeypatch.setattr(
        "hermes_ui.browser_manager.camoufox_environment_ready",
        lambda: {"ready": False, "module": False, "binary": False, "message": "O pacote Camoufox não está instalado."},
    )

    def _broken_conf():
        raise RuntimeError("A dependência pinned do social-auto-upload não está instalada.")

    monkeypatch.setattr("hermes_ui.social_auto_upload_backend._ensure_upstream_runtime_conf", _broken_conf)
    monkeypatch.setattr(
        "hermes_ui.social_auto_upload_backend._run_sau_cli",
        lambda *args, **kwargs: {"status": "not_installed", "returncode": None, "message": "CLI sau não encontrada"},
    )
    report = dependencies_check.check_all_dependencies()
    assert len(report) == len(ALL_NAMES)
    assert all(item["status"] == "fail" for item in report)
    # cada falha traz a acção seguinte — nunca um fail mudo
    assert all(str(item.get("message") or "").strip() for item in report)


def test_everything_ok_reports_versions(tmp_path, monkeypatch):
    _sandbox(tmp_path, monkeypatch)
    mpt = tmp_path / "mpt"
    mpt.mkdir(parents=True)
    (mpt / "cli.py").write_bytes(b"x")
    (mpt / "requirements.txt").write_bytes(b"x")
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"x")
    monkeypatch.setattr(dependencies_check, "_mpt_root", lambda settings: mpt)
    monkeypatch.setattr(dependencies_check, "_settings", lambda: {"moneyprinter_path": str(mpt), "ffmpeg_path": str(ffmpeg)})
    renderer = tmp_path / "home" / "remotion" / "node_modules" / "@remotion" / "renderer"
    renderer.mkdir(parents=True)
    (tmp_path / "pkg" / "packages" / "remotion").mkdir(parents=True)
    chromium = tmp_path / "chrome.exe"
    firefox = tmp_path / "firefox.exe"
    chromium.write_bytes(b"x")
    firefox.write_bytes(b"x")

    def fake_run(command, timeout=60):
        joined = " ".join(str(part) for part in command)
        if command[-1] == "--version" and "node" in command[0]:
            return 0, "v20.11.0", ""
        if "npm" in command[0]:
            return 0, "10.2.4", ""
        if "playwright" in joined:
            return 0, f"{chromium}\n{firefox}", ""
        if "patchright" in joined:
            return 0, str(chromium), ""
        return 0, "", ""

    monkeypatch.setattr(dependencies_check, "_run", fake_run)
    # yt-dlp: o CI não instala o motor (requirements-dev) — simular a versão
    # para o cenário «tudo OK» ser determinístico em qualquer plataforma.
    import types

    fake_yt_dlp = types.ModuleType("yt_dlp")
    fake_yt_dlp_version = types.ModuleType("yt_dlp.version")
    fake_yt_dlp_version.__version__ = "2025.01.15"
    monkeypatch.setitem(system_sys.modules, "yt_dlp", fake_yt_dlp)
    monkeypatch.setitem(system_sys.modules, "yt_dlp.version", fake_yt_dlp_version)
    monkeypatch.setattr(
        "hermes_ui.browser_manager.camoufox_environment_ready",
        lambda: {"ready": True, "module": True, "binary": True, "message": "Camoufox pronto."},
    )
    monkeypatch.setattr("hermes_ui.social_auto_upload_backend._ensure_upstream_runtime_conf", lambda: tmp_path)
    monkeypatch.setattr("hermes_ui.social_auto_upload_backend._run_sau_cli", lambda *a, **k: {"status": "ok", "returncode": 0})
    monkeypatch.setitem(system_sys.modules, "uploader", type(system_sys)("uploader"))
    monkeypatch.setattr(dependencies_check.sys, "prefix", "/falso/venv")
    monkeypatch.setattr(dependencies_check.sys, "base_prefix", "/falso")

    report = dependencies_check.check_all_dependencies()
    by_name = {item["name"]: item for item in report}
    assert all(item["status"] == "ok" for item in report), report
    assert "v20.11.0" in by_name["Node.js / NPM"]["version"]
    assert "npm" in by_name["Node.js / NPM"]["version"]
    assert str(mpt) in by_name["MoneyPrinterTurbo (MPT)"]["version"]
    assert str(ffmpeg) in by_name["FFmpeg (binário)"]["version"]
    assert by_name["Camoufox (GeoIP)"]["version"] == "pronto"
    assert by_name["Playwright (Chromium e Firefox)"]["version"] == str(chromium)
    assert by_name["Patchright (Chromium)"]["version"] == str(chromium)
    assert by_name["yt-dlp"]["version"] == "2025.01.15"


def test_venv_check_detects_system_python(monkeypatch):
    monkeypatch.setattr(dependencies_check.sys, "prefix", "/falso")
    monkeypatch.setattr(dependencies_check.sys, "base_prefix", "/falso")
    assert dependencies_check.check_python_venv()["status"] == "fail"
    monkeypatch.setattr(dependencies_check.sys, "base_prefix", "/outro")
    assert dependencies_check.check_python_venv()["status"] == "ok"


def test_camoufox_check_reuses_the_shared_helper(monkeypatch):
    monkeypatch.setattr(
        "hermes_ui.browser_manager.camoufox_environment_ready",
        lambda: {"ready": False, "module": True, "binary": False, "message": "O binário Firefox do Camoufox não está descarregado. Execute python -m camoufox fetch."},
    )
    result = dependencies_check.check_camoufox()
    assert result["status"] == "fail"
    assert "binário" in result["message"]
    source = (ROOT / "hermes_ui" / "dependencies_check.py").read_text(encoding="utf-8")
    assert "from hermes_ui.browser_manager import camoufox_environment_ready" in source


def test_node_check_probes_node_and_npm(monkeypatch):
    commands: list[list[str]] = []

    def fake_run(command, timeout=60):
        commands.append(list(command))
        return 0, "v20.11.0", ""

    monkeypatch.setattr(dependencies_check, "_run", fake_run)
    result = dependencies_check.check_node()
    assert result["status"] == "ok"
    assert commands[0][0] == "node" and commands[0][-1] == "--version"
    assert commands[1][0] in {"npm", "npm.cmd"} and commands[1][-1] == "--version"


def test_node_check_uses_npm_cmd_on_windows(monkeypatch):
    commands: list[list[str]] = []
    monkeypatch.setattr(
        dependencies_check,
        "_run",
        lambda command, timeout=60: (commands.append(list(command)) or (0, "v20.11.0", "")),
    )
    monkeypatch.setattr(dependencies_check.os, "name", "nt")
    assert dependencies_check.check_node()["status"] == "ok"
    assert commands[1][0] == "npm.cmd"


# ---------------------------------------------------------------------------
# UI: aba «Dependências» no menu de Configurações
# ---------------------------------------------------------------------------


def test_settings_menu_has_dependencies_after_api_config():
    block = MAIN_SOURCE.split("settings_items = [", 1)[1].split("]", 1)[0]
    assert '("Dependências", ":material/extension:", "Dependências")' in block
    assert block.index('("Configuração API"') < block.index('("Dependências"')
    assert '"/configuracoes/dependencias"' in MAIN_SOURCE


def test_dependencies_page_is_routed_and_cached():
    assert '"Dependências": render_dependencies_page,' in MAIN_SOURCE
    before_page = MAIN_SOURCE.split("def render_dependencies_page()", 1)[0]
    assert "@st.cache_data(ttl=60)" in before_page[-600:]
    page = MAIN_SOURCE.split("def render_dependencies_page()", 1)[1].split("def render_mcp()", 1)[0]
    assert "_cached_dependencies_report()" in page  # a página consome o wrapper cacheado
    assert "check_all_dependencies" in before_page
    assert "st.container(border=True)" in page
    assert "st.success" in page and "st.error" in page
    assert "dependências operacionais" in page
    assert "Atualizar Diagnóstico" in page
    assert "_cached_dependencies_report.clear()" in page
