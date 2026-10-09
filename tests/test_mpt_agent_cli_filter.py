"""Filtragem das opções encaminhadas conforme a versão instalada do cli.py.

O Thunderbolt encaminha opções novas (estilo completo de legendas, transições,
…) ao MoneyPrinterTurbo; instalações mais antigas não as conhecem e o argparse
abortava toda a geração com "unrecognized arguments". O helper detecta as
opções suportadas pelo cli.py instalado e ignora as restantes.
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "seed" / "skills" / "mpt_agent.py"
SPEC = importlib.util.spec_from_file_location("test_mpt_agent_filter", MODULE_PATH)
mpt_agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mpt_agent)


def test_filter_drops_unsupported_option_and_value():
    supported = {
        "--video-source": True,
        "--subtitle-enabled": False,
        "--font-name": True,
    }
    forwarded = [
        "--video-source", "pixabay",
        "--subtitle-enabled",
        "--font-name", "Arial.ttf",
        "--text-fore-color", "#FFFFFF",
        "--no-subtitle-background-enabled",
    ]

    filtered = mpt_agent.filter_forwarded_args(forwarded, supported)

    assert filtered == ["--video-source", "pixabay", "--subtitle-enabled", "--font-name", "Arial.ttf"]


def test_filter_without_detection_forwards_everything():
    forwarded = ["--text-fore-color", "#FFFFFF", "--no-subtitle-enabled"]

    assert mpt_agent.filter_forwarded_args(forwarded, None) == forwarded


def test_supported_cli_options_parses_help(monkeypatch):
    class Result:
        returncode = 0
        stdout = (
            "usage: cli.py [-h] [--video-source VIDEO_SOURCE]\n"
            "\n"
            "options:\n"
            "  --video-source VIDEO_SOURCE\n"
            "                        video material provider\n"
            "  --subtitle-enabled, --no-subtitle-enabled\n"
            "                        enable subtitles\n"
            "  --bgm-type {none,random,custom}\n"
            "                        background music mode\n"
            "  --font-name FONT_NAME\n"
            "                        subtitle font filename\n"
            "  --match-materials-to-script\n"
            "                        preserve script keyword order\n"
        )
        stderr = ""

    def fake_run(command, **kwargs):
        return Result()

    monkeypatch.setattr(mpt_agent.subprocess, "run", fake_run)

    supported = mpt_agent.supported_cli_options(Path("."), "uv")

    assert supported["--video-source"] is True
    assert supported["--subtitle-enabled"] is False
    assert supported["--no-subtitle-enabled"] is False
    assert supported["--bgm-type"] is True
    assert supported["--font-name"] is True
    assert supported["--match-materials-to-script"] is False


def test_supported_cli_options_ignores_epilog_example_lines(monkeypatch):
    class Result:
        returncode = 0
        stdout = (
            "options:\n"
            "  --voice-name VOICE_NAME\n"
            "                        TTS voice identifier\n"
            "  --stop-at {script,terms,audio,subtitle,materials,video}\n"
            "                        stop after this pipeline stage\n"
            "Examples:\n"
            "  uv run python cli.py --video-subject \"topic\"\n"
            "    --voice-name no-voice --stop-at video\n"
        )
        stderr = ""

    def fake_run(command, **kwargs):
        return Result()

    monkeypatch.setattr(mpt_agent.subprocess, "run", fake_run)

    supported = mpt_agent.supported_cli_options(Path("."), "uv")

    # As definições verdadeiras (maiúsculas/metavAR) vêm antes do epilog e o
    # merge nunca rebaixa uma opção com valor a flag.
    assert supported["--voice-name"] is True
    assert supported["--stop-at"] is True


def test_supported_cli_options_returns_none_on_failure(monkeypatch):
    def fake_run(*args, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr(mpt_agent.subprocess, "run", fake_run)

    assert mpt_agent.supported_cli_options(Path("."), "uv") is None
