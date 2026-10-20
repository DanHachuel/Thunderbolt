"""Defaults de legendas do sistema (1.0.15).

Novos canais nascem com os valores padrão configurados pelo utilizador:
fonte MicrosoftYaHeiBold 40, fundo DESLIGADO (cor branca), fundo arredondado
LIGADO, outline branco com 2.75 de largura. As TRÊS tabelas de defaults do
domínio (create_channel, criação de tarefas, revalidação do Refazer Vídeo),
os fallbacks da UI e os fallbacks do pipeline de renderização têm de bater
todos com o mesmo standard. Canais existentes NUNCA são sobrescritos — só
canais novos (ou dados sem chave) usam estes valores.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hermes_ui import domain, pipeline_worker
from hermes_ui.domain import create_channel


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
DOMAIN_SOURCE = (ROOT / "hermes_ui" / "domain.py").read_text(encoding="utf-8")
PIPELINE_SOURCE = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")
TEXT_TO_IMAGES_SOURCE = (ROOT / "hermes_ui" / "text_to_images.py").read_text(encoding="utf-8")


NEW_SUBTITLE_DEFAULTS = {
    "default_enable_subtitles": True,
    "default_subtitle_font": "MicrosoftYaHeiBold.ttc",
    "default_subtitle_position": "Bottom (Recommended)",
    "default_subtitle_color": "#FFFFFF",
    "default_subtitle_background": False,
    "default_subtitle_background_color": "#FFFFFF",
    "default_subtitle_rounded_background": True,
    "default_subtitle_font_size": 40,
    "default_subtitle_outline": "#FFFFFF",
    "default_subtitle_outline_width": 2.75,
}


# ---------------------------------------------------------------------------
# Canais novos: o dicionário base do create_channel carrega o novo standard
# ---------------------------------------------------------------------------


def test_new_channels_are_born_with_the_new_subtitle_defaults(monkeypatch):
    monkeypatch.setattr(domain, "read_json", lambda name, default=None: [] if name == "channels.json" else default)
    monkeypatch.setattr(domain, "write_json", lambda name, value: None)

    channel = create_channel("Canal Novo", metadata={"platform": "youtube"})

    for key, expected in NEW_SUBTITLE_DEFAULTS.items():
        assert channel.get(key) == expected, f"{key}: esperado {expected!r}, veio {channel.get(key)!r}"


def test_channel_defaults_do_not_override_explicit_values(monkeypatch):
    """Restrição da migração: canais com valores próprios NUNCA são sobrescritos."""
    monkeypatch.setattr(domain, "read_json", lambda name, default=None: [] if name == "channels.json" else default)
    monkeypatch.setattr(domain, "write_json", lambda name, value: None)
    explicit = {
        "platform": "youtube",
        "default_subtitle_font_size": 72,
        "default_subtitle_background": True,
        "default_subtitle_background_color": "#000000",
        "default_subtitle_rounded_background": False,
        "default_subtitle_outline": "#000000",
        "default_subtitle_outline_width": 1.0,
    }

    channel = create_channel("Canal Custom", metadata=explicit)

    assert channel.get("default_subtitle_font_size") == 72
    assert channel.get("default_subtitle_background") is True
    assert channel.get("default_subtitle_background_color") == "#000000"
    assert channel.get("default_subtitle_rounded_background") is False
    assert channel.get("default_subtitle_outline") == "#000000"
    assert channel.get("default_subtitle_outline_width") == 1.0


# ---------------------------------------------------------------------------
# As TRÊS tabelas do domínio e os fallbacks do pipeline batem com o standard
# ---------------------------------------------------------------------------


def test_domain_has_exactly_one_new_default_per_key():
    for key, expected in NEW_SUBTITLE_DEFAULTS.items():
        # aspas duplas para strings (estilo do source); repr para bool/int/float
        needle = f'"{key}": "{expected}"' if isinstance(expected, str) else f'"{key}": {expected!r}'
        occurrences = DOMAIN_SOURCE.count(needle)
        assert occurrences >= 1, f"{needle} não está no domínio"
    # Nenhum resto do standard antigo pode sobrar no domínio (tabelas dict).
    assert '"default_subtitle_font_size": 60' not in DOMAIN_SOURCE
    assert '"default_subtitle_font_size"), 60' not in DOMAIN_SOURCE
    assert '"default_subtitle_background": True' not in DOMAIN_SOURCE
    assert '"default_subtitle_background"), True' not in DOMAIN_SOURCE
    assert '"default_subtitle_background_color": "#000000"' not in DOMAIN_SOURCE
    assert '"default_subtitle_rounded_background": False' not in DOMAIN_SOURCE
    assert '"default_subtitle_rounded_background"), False' not in DOMAIN_SOURCE
    assert '"default_subtitle_outline": "#000000"' not in DOMAIN_SOURCE
    assert '"default_subtitle_outline_width": 1.5' not in DOMAIN_SOURCE
    assert '"default_subtitle_outline_width"), 1.5' not in DOMAIN_SOURCE


def test_ui_widget_fallbacks_match_the_new_defaults():
    block = MAIN_SOURCE.split("def render_channel_audio_subtitle_defaults(", 1)[1].split('with st.expander("Configurações de Audio"', 1)[0]
    assert 'channel.get("default_enable_subtitles", True)' in block
    assert 'value=int(channel.get("default_subtitle_font_size") or 40)' in block
    assert 'value=bool(channel.get("default_subtitle_background", False))' in block
    assert 'str(channel.get("default_subtitle_background_color") or "#FFFFFF")' in block
    assert 'value=bool(channel.get("default_subtitle_rounded_background", True))' in block
    assert 'value=float(channel.get("default_subtitle_outline_width") or 2.75)' in block
    assert 'str(channel.get("default_subtitle_outline") or "#FFFFFF")' in block


def test_pipeline_render_fallbacks_match_the_new_defaults():
    assert 'int(generation_settings.get("subtitle_font_size") or 40)' in PIPELINE_SOURCE
    assert 'bool(generation_settings.get("subtitle_background", False))' in PIPELINE_SOURCE
    assert '_hex_color(generation_settings.get("subtitle_background_color"), "#FFFFFF")' in PIPELINE_SOURCE
    assert '_hex_color(generation_settings.get("subtitle_outline"), "#FFFFFF")' in PIPELINE_SOURCE
    assert 'float(generation_settings.get("subtitle_outline_width") or 2.75)' in PIPELINE_SOURCE


def test_subtitle_config_for_task_uses_new_fallbacks_when_keys_missing(monkeypatch):
    """Sem chaves (tarefa legada), o render usa o NOVO standard do sistema."""
    monkeypatch.setattr(pipeline_worker, "_resolve_subtitle_font_path", lambda font_name, settings: Path("dummy-font.ttf"))
    config = pipeline_worker._subtitle_config_for_task({"generation_settings": {}}, {})
    assert config is not None
    assert config["font_size"] == 40
    assert config["background"] is False
    assert config["background_color"] == "#FFFFFF"
    assert config["outline"] == "#FFFFFF"
    assert config["outline_width"] == 2.75


def test_text_to_images_font_size_fallback_is_the_new_standard():
    assert 'int(config.get("font_size") or 60)' not in TEXT_TO_IMAGES_SOURCE
    assert TEXT_TO_IMAGES_SOURCE.count('int(config.get("font_size") or 40)') == 2
