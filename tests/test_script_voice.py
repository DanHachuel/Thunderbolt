from hermes_ui.script_voice import narration_text_from_script
from hermes_ui.pipeline_worker import _moneyprinter_cli_args

import pytest


def test_narration_filters_title_summary_headings_and_visual_block():
    script = """> Russia's Submarines Are Hiding Inside Civilian Cargo Ships — Here's How
> An operational breakdown of disguised patrols.
# Russia's Submarines Are Hiding Inside Civilian Cargo Ships — Here's How
---
## HOOK (0:00 – 0:35)
**[VISUAL]**
Cold-open aerial drone shot: a rust-streaked bulk carrier cuts through grey North Atlantic swells.
**[NARRAÇÃO]**
Russia is using a deceptive maritime pattern to conceal its patrols.
"""

    result = narration_text_from_script(script)

    assert result == "Russia is using a deceptive maritime pattern to conceal its patrols."
    assert "Hashatag" not in result
    assert "VISUAL" not in result
    assert "Cold-open" not in result
    assert "0:00" not in result


def test_narration_without_explicit_voice_keeps_prose_but_not_editorial_labels():
    script = """# The Arctic Route
## INTRO (0:00 - 0:20)
The convoy moves through freezing water.
**[VISUAL]**
Satellite imagery shows the coastline.
The narrator explains the strategic risk.
"""

    result = narration_text_from_script(script)

    assert result == "The convoy moves through freezing water."
    assert "Satellite" not in result
    assert "narrator explains" not in result


def test_narration_strips_inline_markdown():
    assert narration_text_from_script("**This** is a [spoken](https://example.com) line.") == "This is a spoken line."


def test_moneyprinter_cli_receives_clean_narration_text():
    script = """# Title
**[VISUAL]**
Ships move through the fog.
**[NARRAÇÃO]**
The patrol follows a concealed route.
"""
    args = _moneyprinter_cli_args({"video_script": script, "generation_settings": {}}, "pexels", {})
    assert args[args.index("--video-script") + 1] == "The patrol follows a concealed route."


# ── 1.0.03: roteiros em inglês (NARRATION + corpos em blockquote) ────────────


def test_english_narration_marker_with_blockquote_bodies():
    """Regressão do vídeo video_fecb50306d: o roteiro real usa `**[NARRATION]**`
    (inglês) com corpos em blockquote `>` — a extração devolvia 28 palavras do
    frontmatter (áudio de 16,85 s para um vídeo de 10 minutos)."""
    script = """---
id: acc9dc30128b
type: video_script
title: Russia's Submarines Are Hiding Inside Civilian Cargo Ships
---
# Russia's Submarines Are Hiding Inside Civilian Cargo Ships
## HOOK (0:00 – 0:35)
**[VISUAL]**
Cold-open aerial drone shot of a bulk carrier.
**[SFX]**
Low-frequency hydrophone rumble under ocean ambience.
**[NARRATION]**
> On the surface, she's the *MV Meridian Star*, a 22,000-tonne bulk carrier.
> Below the waterline, she's carrying a Russian attack submarine.
**[ON-SCREEN TEXT]**
> *How a civilian hull is becoming a mobile pier.*
"""
    result = narration_text_from_script(script)

    assert "On the surface, she's the MV Meridian Star, a 22,000-tonne bulk carrier." in result
    assert "Below the waterline, she's carrying a Russian attack submarine." in result
    assert "Cold-open" not in result, "director visual não se narra"
    assert "hydrophone" not in result, "SFX não se narra"
    assert "mobile pier" not in result, "ON-SCREEN TEXT é família visual, não narração"
    assert "id: acc9dc30128b" not in result, "frontmatter YAML nunca chega ao TTS"
    assert "NARRATION" not in result
    assert "Russia's Submarines Are Hiding" not in result, "título não se narra"


def test_frontmatter_without_narration_returns_empty_not_metadata():
    script = """---
id: abc
type: video_script
title: Sem narração
---
# Só o título
"""
    assert narration_text_from_script(script) == ""


def test_voice_over_marker_is_recognised():
    script = """**[VOICE OVER]**
> The convoy moves at dusk.
"""
    assert narration_text_from_script(script) == "The convoy moves at dusk."


# ── 1.0.03: durações das cenas escaladas à duração real do áudio ─────────────


def test_scene_durations_scale_to_real_audio(monkeypatch, tmp_path):
    from hermes_ui import pipeline_worker

    monkeypatch.setattr(pipeline_worker, "audio_duration_seconds", lambda path: 10.0)
    scenes = [
        {"index": 1, "text": "primeira", "start": 0.0, "end": 6.0, "duration": 6.0},
        {"index": 2, "text": "segunda", "start": 6.0, "end": 12.0, "duration": 6.0},
    ]
    pipeline_worker._scale_scene_durations_to_audio(scenes, tmp_path / "narração.mp3")

    assert scenes[0]["duration"] == pytest.approx(5.0)
    assert scenes[1]["start"] == pytest.approx(5.0)
    assert scenes[-1]["end"] == pytest.approx(10.0), "o vídeo termina com o áudio"


def test_scene_durations_untouched_when_scale_is_negligible(monkeypatch, tmp_path):
    from hermes_ui import pipeline_worker

    monkeypatch.setattr(pipeline_worker, "audio_duration_seconds", lambda path: 12.0)
    scenes = [{"index": 1, "text": "única", "start": 0.0, "end": 12.0, "duration": 12.0}]
    pipeline_worker._scale_scene_durations_to_audio(scenes, tmp_path / "a.mp3")
    assert scenes[0]["duration"] == 12.0


def test_scene_durations_survive_audio_probe_failure(monkeypatch, tmp_path):
    from hermes_ui import pipeline_worker

    def boom(path):
        raise RuntimeError("sem ffprobe")

    monkeypatch.setattr(pipeline_worker, "audio_duration_seconds", boom)
    scenes = [{"index": 1, "text": "única", "start": 0.0, "end": 8.0, "duration": 8.0}]
    pipeline_worker._scale_scene_durations_to_audio(scenes, tmp_path / "a.mp3")
    assert scenes[0]["duration"] == 8.0


def test_local_routes_split_scenes_from_narration_not_raw_markdown():
    """Source-structure: as rotas text_to_images e web_images constroem as cenas
    (imagens + subtítulos) a partir da narração extraída e escalam as durações
    ao áudio real — o markdown cru produzia subtítulos com frontmatter YAML."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")
    assert source.count('narration_content = narration_text_from_script(str(script.get("content") or ""))') >= 2
    assert source.count("_scale_scene_durations_to_audio(scenes, audio_path)") >= 2
    # o split já não recebe o markdown cru
    assert 'split_script_into_scenes(\n                    str(script.get("content") or "")' not in source
    assert 'split_script_into_scenes(str(script.get("content") or "")' not in source
