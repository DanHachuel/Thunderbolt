"""Testes das legendas queimadas nas montagens locais (0.9.63).

As Configurações de legendas existiam na UI e nos defaults por canal, mas a
montagem por cenas (text_to_images/web_images) nunca as aplicava — nenhum
vídeo gerado nas automações saía com legendas. Estes testes fixam a cadeia:
config da tarefa → resolução de fonte → clips TextClip → render real.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hermes_ui.pipeline_worker import _resolve_subtitle_font_path, _subtitle_config_for_task
from hermes_ui.text_to_images import _subtitle_clips_for_scenes, assemble_text_to_images_video

ROOT = Path(__file__).resolve().parents[1]
PIPELINE_SOURCE = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")
ASSEMBLY_SOURCE = (ROOT / "hermes_ui" / "text_to_images.py").read_text(encoding="utf-8")


def test_subtitle_config_enabled_resolves_font_from_mpt(monkeypatch, tmp_path):
    fonts_dir = tmp_path / "resource" / "fonts"
    fonts_dir.mkdir(parents=True)
    (fonts_dir / "MicrosoftYaHeiBold.ttc").write_bytes(b"font")
    monkeypatch.setattr(
        "hermes_ui.pipeline_worker._configured_moneyprinter_root",
        lambda settings: str(tmp_path),
    )
    task = {
        "generation_settings": {
            "enable_subtitles": True,
            "subtitle_font": "MicrosoftYaHeiBold.ttc",
            "subtitle_position": "Bottom (Recommended)",
            "subtitle_color": "#FFEEDD",
            "subtitle_font_size": 70,
            "subtitle_outline_width": 2.0,
        }
    }
    config = _subtitle_config_for_task(task, {})
    assert config is not None
    assert config["font_path"].endswith("MicrosoftYaHeiBold.ttc")
    assert config["position"] == "bottom"
    assert config["color"] == "#FFEEDD"
    assert config["font_size"] == 70
    assert config["outline_width"] == 2.0


def test_subtitle_config_disabled_returns_none():
    task = {"generation_settings": {"enable_subtitles": False}}
    assert _subtitle_config_for_task(task, {}) is None


def test_subtitle_config_defaults_when_keys_absent(monkeypatch, tmp_path):
    fonts_dir = tmp_path / "resource" / "fonts"
    fonts_dir.mkdir(parents=True)
    (fonts_dir / "arial.ttf").write_bytes(b"font")
    monkeypatch.setattr(
        "hermes_ui.pipeline_worker._configured_moneyprinter_root",
        lambda settings: str(tmp_path),
    )
    config = _subtitle_config_for_task({"generation_settings": {}}, {})
    assert config is not None
    assert config["font_size"] == 60
    assert config["color"] == "#FFFFFF"
    assert config["background"] is True
    assert config["position"] == "bottom"


def test_subtitle_config_position_mapping(monkeypatch, tmp_path):
    fonts_dir = tmp_path / "resource" / "fonts"
    fonts_dir.mkdir(parents=True)
    (fonts_dir / "arial.ttf").write_bytes(b"font")
    monkeypatch.setattr(
        "hermes_ui.pipeline_worker._configured_moneyprinter_root",
        lambda settings: str(tmp_path),
    )
    for raw, expected in (("Top", "top"), ("Centered captions", "center"), ("Custom", "bottom")):
        config = _subtitle_config_for_task({"generation_settings": {"subtitle_position": raw}}, {})
        assert config is not None and config["position"] == expected


def test_font_resolution_falls_back_without_mpt(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "hermes_ui.pipeline_worker._configured_moneyprinter_root",
        lambda settings: None,
    )
    # sem MPT e sem fonte conhecida no sistema, devolve None (video segue sem legendas)
    def fake_is_file(self):
        return False

    monkeypatch.setattr(Path, "is_file", fake_is_file)
    assert _resolve_subtitle_font_path("QualquerCoisa.ttc", {}) is None


def test_pipelines_pass_subtitle_config_to_assembly():
    # os dois ramos de montagem local recebem o config de legendas
    text_block = PIPELINE_SOURCE.split('elif route == "text_to_images":', 1)[1].split('elif route ==', 1)[0]
    assert "subtitle_config=_subtitle_config_for_task(task, settings)" in text_block
    web_block = PIPELINE_SOURCE.split('elif route == "web_images":', 1)[1].split('elif route ==', 1)[0]
    assert "subtitle_config=_subtitle_config_for_task(task, settings)" in web_block


def test_assembly_burns_captions_with_pil_hug_text_boxes():
    assert "def _subtitle_clips_for_scenes" in ASSEMBLY_SOURCE
    assert "ImageClip" in ASSEMBLY_SOURCE
    assert "CompositeVideoClip" in ASSEMBLY_SOURCE
    # render determinístico: métricas reais da fonte + wrap medido em pixels
    assert "getmetrics" in ASSEMBLY_SOURCE
    assert "def _wrap_text_pixels" in ASSEMBLY_SOURCE
    assert "stroke_fill" in ASSEMBLY_SOURCE
    # a barra full-width do modo caption com fundo no TextClip não volta
    assert '"caption"' not in ASSEMBLY_SOURCE
    assert "bg_color" not in ASSEMBLY_SOURCE


@pytest.mark.skipif(
    not Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf").is_file()
    and not Path("C:/Windows/Fonts/arial.ttf").is_file(),
    reason="sem fonte do sistema disponivel para o render real",
)
def test_assemble_renders_real_video_with_burned_captions(tmp_path):
    import numpy as np
    from moviepy import AudioArrayClip
    from PIL import Image

    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    if not Path(font).is_file():
        font = "C:/Windows/Fonts/arial.ttf"
    for name, color in (("a.png", (30, 40, 60)), ("b.png", (200, 120, 40))):
        Image.new("RGB", (320, 180), color).save(tmp_path / name)
    silence = AudioArrayClip(np.zeros((24 * 24000, 1), dtype=np.int16), fps=24000)
    audio_path = tmp_path / "narration.wav"
    silence.write_audiofile(str(audio_path), logger=None)
    scenes = [
        {"image_path": str(tmp_path / "a.png"), "duration": 1.2, "text": "Primeira cena com legenda queimada"},
        {"image_path": str(tmp_path / "b.png"), "duration": 1.2, "text": "Segunda cena com contorno e fundo"},
    ]
    subtitle_config = {
        "font_path": font,
        "font_size": 40,
        "position": "bottom",
        "color": "#FFFFFF",
        "background": True,
        "background_color": "#000000",
        "outline": "#000000",
        "outline_width": 1.5,
    }
    with_subs = assemble_text_to_images_video(
        scenes, audio_path, tmp_path / "com-legendas.mp4", "wide", fps=10, subtitle_config=subtitle_config
    )
    without_subs = assemble_text_to_images_video(
        scenes, audio_path, tmp_path / "sem-legendas.mp4", "wide", fps=10
    )
    assert with_subs.is_file() and with_subs.stat().st_size > 2000
    assert without_subs.is_file()
    # as legendas queimadas adicionam bytes ao ficheiro final
    assert with_subs.stat().st_size > without_subs.stat().st_size


def test_subtitle_clip_failure_never_breaks_the_video(tmp_path, monkeypatch):
    """Falha de fonte/PIL cai para a montagem simples com aviso no stderr."""
    import numpy as np
    from moviepy import AudioArrayClip
    from PIL import Image

    if not Path("C:/Windows/Fonts/arial.ttf").is_file() and not Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf").is_file():
        pytest.skip("sem fonte para preparar o video base")
    Image.new("RGB", (320, 180), (20, 20, 20)).save(tmp_path / "a.png")
    silence = AudioArrayClip(np.zeros((12 * 24000, 1), dtype=np.int16), fps=24000)
    audio_path = tmp_path / "narration.wav"
    silence.write_audiofile(str(audio_path), logger=None)
    scenes = [{"image_path": str(tmp_path / "a.png"), "duration": 1.2, "text": "texto"}]

    def broken_clips(scenes, width, height, config):
        raise RuntimeError("fonte em falta")

    monkeypatch.setattr(
        "hermes_ui.text_to_images._subtitle_clips_for_scenes",
        broken_clips,
    )
    subtitle_config = {"font_path": "caminho/quebrado.ttf", "font_size": 40, "position": "bottom"}
    result = assemble_text_to_images_video(
        scenes, audio_path, tmp_path / "video.mp4", "wide", fps=10, subtitle_config=subtitle_config
    )
    assert result.is_file() and result.stat().st_size > 0


def _isolated_storage(monkeypatch, tmp_path):
    from hermes_ui import storage

    monkeypatch.setattr(storage, "STATE", tmp_path)
    return tmp_path


def test_manual_batch_carries_subtitle_settings_into_tasks(monkeypatch, tmp_path):
    """Modo manual: o form submete generation_settings com as legendas e a
    tarefa criada chega ao worker com elas (0.9.63)."""
    from hermes_ui import domain, storage

    monkeypatch.setattr(storage, "STATE", tmp_path)
    storage.write_json("channels.json", [{
        "id": "channel-manual", "name": "Canal Manual", "platform": "youtube",
        "style_wide": "text_to_images", "language": "Português",
        "default_enable_subtitles": True, "default_subtitle_font": "MicrosoftYaHeiBold.ttc",
        "default_subtitle_position": "Bottom (Recommended)", "default_subtitle_font_size": 60,
    }])
    form_settings = {
        "video_source": "text_to_images",
        "enable_subtitles": True,
        "subtitle_font": "MicrosoftYaHeiBold.ttc",
        "subtitle_position": "Bottom (Recommended)",
        "subtitle_font_size": 55,
        "subtitle_color": "#FFFFFF",
    }
    batch = domain.create_batch(
        channel_ids=["channel-manual"],
        quantity=1,
        mode="single",
        topic="Tópico manual",
        options={"generation_settings": form_settings, "style_wide": "text_to_images", "format": "wide", "topic_source": "manual"},
    )
    tasks = domain.create_tasks_for_batch(batch)
    assert len(tasks) == 1
    gs = tasks[0].get("generation_settings") or {}
    assert gs.get("enable_subtitles") is True
    assert gs.get("subtitle_font_size") == 55
    assert gs.get("subtitle_position") == "Bottom (Recommended)"
    assert gs.get("subtitle_outline_width") == 1.5


def test_automation_batch_keeps_channel_subtitles_as_source_of_truth(monkeypatch, tmp_path):
    """Modo automação: os defaults do canal vencem payloads obsoletos (o
    comentário do domain.py exige que legendas antigas não sejam desligadas)."""
    from hermes_ui import domain, storage

    monkeypatch.setattr(storage, "STATE", tmp_path)
    storage.write_json("channels.json", [{
        "id": "channel-auto", "name": "Canal Auto", "platform": "youtube",
        "style_wide": "text_to_images", "language": "Português",
        "default_enable_subtitles": True, "default_subtitle_font": "MicrosoftYaHeiBold.ttc",
    }])
    batch = domain.create_batch(
        channel_ids=["channel-auto"],
        quantity=1,
        mode="single",
        topic="Tópico automação",
        options={
            "generation_settings": {"enable_subtitles": False},
            "style_wide": "text_to_images",
            "format": "wide",
            "topic_source": "manual",
            "automation_worker": True,
        },
    )
    tasks = domain.create_tasks_for_batch(batch)
    gs = tasks[0].get("generation_settings") or {}
    assert gs.get("enable_subtitles") is True, "a automação tem de manter as legendas do canal"


# ── 0.9.64: rota Pexels (MPT) — legendas queimadas quando o MPT as salta ─────


def _mpt_task(voiceover_mode="tts", voiceover_service="Azure TTS V1", **extra):
    generation_settings = {
        "video_source": "pexels",
        "enable_subtitles": True,
        "voiceover_mode": voiceover_mode,
        "voiceover_service": voiceover_service,
        **extra,
    }
    return {"generation_settings": generation_settings}


def test_mpt_custom_audio_detection():
    from hermes_ui.pipeline_worker import _mpt_uses_custom_audio

    assert _mpt_uses_custom_audio(_mpt_task(voiceover_mode="upload")) is True
    assert _mpt_uses_custom_audio(_mpt_task(voiceover_mode="none")) is True
    assert _mpt_uses_custom_audio(_mpt_task(voiceover_service="elevenlabs")) is True
    assert _mpt_uses_custom_audio(_mpt_task(voiceover_service="Azure Speech SDK V2")) is True
    # TTS nativo do MPT: o sub_maker existe e as legendas ficam a cargo do MPT
    assert _mpt_uses_custom_audio(_mpt_task()) is False


def test_mpt_cli_disables_subtitles_for_custom_audio():
    from hermes_ui.pipeline_worker import _moneyprinter_cli_args

    args = _moneyprinter_cli_args(_mpt_task(voiceover_service="elevenlabs"), "pexels")
    assert "--no-subtitle-enabled" in args
    assert "--subtitle-enabled" not in args
    native_args = _moneyprinter_cli_args(_mpt_task(), "pexels")
    assert "--subtitle-enabled" in native_args
    assert "--no-subtitle-enabled" not in native_args


def test_apply_mpt_captions_skips_native_and_disabled_and_none(monkeypatch, tmp_path):
    from hermes_ui import pipeline_worker

    video = tmp_path / "video.mp4"
    video.write_bytes(b"mp4")
    script = {"content": "Narração do vídeo de teste."}
    # TTS nativo: o MPT já queimou as legendas — não mexer
    assert pipeline_worker._apply_mpt_captions(_mpt_task(), video, script, {}) == video
    # modo sem voz: sem áudio não há legendas para queimar
    assert pipeline_worker._apply_mpt_captions(_mpt_task(voiceover_mode="none"), video, script, {}) == video
    # legendas desactivadas nas configurações
    assert pipeline_worker._apply_mpt_captions(_mpt_task(voiceover_service="elevenlabs", enable_subtitles=False), video, script, {}) == video


def test_apply_mpt_captions_burns_when_custom_audio(monkeypatch, tmp_path):
    from hermes_ui import pipeline_worker

    fonts_dir = tmp_path / "resource" / "fonts"
    fonts_dir.mkdir(parents=True)
    (fonts_dir / "arial.ttf").write_bytes(b"font")
    monkeypatch.setattr(
        "hermes_ui.pipeline_worker._configured_moneyprinter_root",
        lambda settings: str(tmp_path),
    )
    video = tmp_path / "video.mp4"
    video.write_bytes(b"mp4")
    script = {"content": "Narração do vídeo com ElevenLabs."}
    captured = {}

    def fake_burn(video_path, narration, config):
        captured["narration"] = narration
        captured["config"] = config
        return video

    monkeypatch.setattr("hermes_ui.text_to_images.burn_captions_on_video", fake_burn)
    result = pipeline_worker._apply_mpt_captions(
        _mpt_task(voiceover_service="elevenlabs"), video, script, {}
    )
    assert result == video
    assert captured["narration"].startswith("Narração")
    assert captured["config"].get("font_path")


def test_burn_captions_failure_leaves_original_video(monkeypatch, tmp_path):
    from hermes_ui import pipeline_worker

    fonts_dir = tmp_path / "resource" / "fonts"
    fonts_dir.mkdir(parents=True)
    (fonts_dir / "arial.ttf").write_bytes(b"font")
    monkeypatch.setattr(
        "hermes_ui.pipeline_worker._configured_moneyprinter_root",
        lambda settings: str(tmp_path),
    )
    video = tmp_path / "video.mp4"
    video.write_bytes(b"mp4-original")
    script = {"content": "Narração."}

    def fake_burn(video_path, narration, config):
        raise RuntimeError("fonte em falta")

    monkeypatch.setattr("hermes_ui.text_to_images.burn_captions_on_video", fake_burn)
    result = pipeline_worker._apply_mpt_captions(
        _mpt_task(voiceover_service="elevenlabs"), video, script, {}
    )
    assert result == video
    assert video.read_bytes() == b"mp4-original"


def test_pipeline_wires_mpt_captions_after_helper():
    source = PIPELINE_SOURCE
    mpt_block = source.split("video_path = _run_video_helper({", 1)[1].split("})", 1)[0]
    assert "_apply_mpt_captions" in source
    wiring = source.split('video_path = _run_video_helper({', 1)[1]
    assert "video_path = _apply_mpt_captions(task, video_path, script, settings)" in wiring.split("except MediaGenerationError", 1)[0]


@pytest.mark.skipif(
    not Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf").is_file()
    and not Path("C:/Windows/Fonts/arial.ttf").is_file(),
    reason="sem fonte do sistema disponivel para o render real",
)
def test_burn_captions_on_real_video_replaces_in_place(tmp_path):
    import numpy as np
    from moviepy import AudioArrayClip, ColorClip

    from hermes_ui.text_to_images import burn_captions_on_video

    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    if not Path(font).is_file():
        font = "C:/Windows/Fonts/arial.ttf"
    base = ColorClip(size=(320, 180), color=(40, 40, 40), duration=2.4)
    silence = AudioArrayClip(np.zeros((int(2.4 * 24000), 1), dtype=np.int16), fps=24000)
    base = base.with_audio(silence)
    video_path = tmp_path / "pexels.mp4"
    base.write_videofile(str(video_path), fps=10, codec="libx264", audio_codec="aac", logger=None)
    size_before = video_path.stat().st_size
    subtitle_config = {
        "font_path": font,
        "font_size": 40,
        "position": "bottom",
        "color": "#FFFFFF",
        "background": True,
        "background_color": "#000000",
        "outline": "#000000",
        "outline_width": 1.5,
    }
    result = burn_captions_on_video(
        video_path,
        "Primeira frase da narração. Segunda frase para dividir em segmentos.",
        subtitle_config,
    )
    assert result == video_path
    assert video_path.stat().st_size > size_before, "a queima tem de acrescentar conteudo"
    assert not list(tmp_path.glob("*.legendas-tmp.mp4")), "o temporario foi substituido, nao deixado para tras"


# ── 0.10.00: fundo hug-text, sem clip e wrap medido em pixels ────────────────


_SUBTITLE_RENDER_CONFIG = {
    "position": "bottom",
    "color": "#FFFFFF",
    "background": True,
    "background_color": "#000000",
    "outline": "#000000",
    "outline_width": 1.5,
}


def _subtitle_test_font():
    for candidate in ("C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(candidate).is_file():
            return candidate
    return None


def _yahei_font():
    import os

    candidates = [
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "MicrosoftYaHeiBold.ttc",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "THUNDERBOLT"
        / "MoneyPrinterTurbo"
        / "resource"
        / "fonts"
        / "MicrosoftYaHeiBold.ttc",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _render_subtitle_frame(text, font_size, video_size=(960, 540), config_extra=None):
    import numpy as np

    from hermes_ui.text_to_images import _subtitle_clips_for_scenes

    config = {**_SUBTITLE_RENDER_CONFIG, "font_path": _subtitle_test_font(), "font_size": font_size}
    config.update(config_extra or {})
    clips = _subtitle_clips_for_scenes(
        [{"index": 1, "text": text, "duration": 1.0}],
        video_size[0],
        video_size[1],
        config,
    )
    assert len(clips) == 1
    return np.asarray(clips[0].get_frame(0)).astype(int)


def _ink_gaps(frame):
    """Distância (px) entre a tinta visível e cada borda da caixa."""
    import numpy as np

    luminance = frame.mean(axis=2)
    ys, xs = np.where(luminance > 100)
    height, width = frame.shape[:2]
    return {
        "left": int(xs.min()),
        "right": int(width - 1 - xs.max()),
        "top": int(ys.min()),
        "bottom": int(height - 1 - ys.max()),
    }


@pytest.mark.skipif(_subtitle_test_font() is None, reason="sem fonte do sistema")
def test_subtitle_box_hugs_short_text_with_uniform_padding():
    from PIL import Image, ImageDraw, ImageFont

    text = "Legenda curta"
    frame = _render_subtitle_frame(text, 40, config_extra={"outline_width": 0})
    # a barra full-width (86% do vídeo) deixou de existir para texto curto
    assert frame.shape[1] < int(960 * 0.86)
    # a caixa é hug-text: largura da tinta + padding nas duas pontas
    # (o tamanho da fonte escala com a altura do vídeo: 40 * 540 // 1080 = 20)
    scaled = max(12, 40 * 540 // 1080)
    font = ImageFont.truetype(_subtitle_test_font(), scaled)
    ink = ImageDraw.Draw(Image.new("RGBA", (8, 8))).textbbox((0, 0), text, font=font)
    expected_width = (ink[2] - ink[0]) + 2 * 10
    assert abs(frame.shape[1] - expected_width) <= 3
    gaps = _ink_gaps(frame)
    for side in ("left", "right", "top", "bottom"):
        assert gaps[side] == pytest.approx(10, abs=3), f"padding {side} = {gaps[side]}"


@pytest.mark.skipif(_subtitle_test_font() is None, reason="sem fonte do sistema")
def test_subtitle_ascenders_and_descenders_fully_visible():
    # g/p/q/y (descendentes) e Ã/ç/Q (altos) têm de ficar dentro da caixa —
    # no renderer antigo a base das letras era cortada pela altura do TextClip
    frame = _render_subtitle_frame("gaguejar pelo quilo? pique já çã Qy", 40, config_extra={"outline_width": 0})
    gaps = _ink_gaps(frame)
    assert min(gaps.values()) >= 6, f"tinta encostada à borda: {gaps}"


@pytest.mark.skipif(_subtitle_test_font() is None, reason="sem fonte do sistema")
def test_subtitle_wraps_long_text_into_lines_within_max_width():
    long_text = (
        "Your mind has gone quiet but your heart is still racing and you have turned "
        "the page on a long and heavy day full of worries"
    )
    frame = _render_subtitle_frame(long_text, 40, config_extra={"outline_width": 0})
    assert frame.shape[1] <= int(960 * 0.86) + 2, "a caixa ultrapassa a largura máxima"
    row_has_ink = (frame.mean(axis=2) > 100).any(axis=1)
    bands = 0
    previous = False
    for has_ink in row_has_ink:
        if has_ink and not previous:
            bands += 1
        previous = has_ink
    assert bands >= 2, "a frase longa devia partir em 2+ linhas"


@pytest.mark.skipif(_subtitle_test_font() is None, reason="sem fonte do sistema")
def test_subtitle_background_is_opaque_box_behind_text():
    import numpy as np

    from hermes_ui.text_to_images import _subtitle_clips_for_scenes

    text = "Legenda curta"
    with_bg = _render_subtitle_frame(text, 40, config_extra={"outline_width": 0})
    # o fundo opaco preenche a caixa inteira (canto incluído)
    assert tuple(with_bg[0, 0]) == (0, 0, 0)
    clips = _subtitle_clips_for_scenes(
        [{"index": 1, "text": text, "duration": 1.0}],
        960,
        540,
        {**_SUBTITLE_RENDER_CONFIG, "font_path": _subtitle_test_font(), "font_size": 40, "background": False, "outline_width": 0},
    )
    mask = np.asarray(clips[0].mask.get_frame(0))
    # sem fundo, só a tinta é opaca — os cantos da caixa são transparentes
    assert mask[0, 0] == 0.0 and mask.max() > 0.9


@pytest.mark.skipif(_subtitle_test_font() is None, reason="sem fonte do sistema")
def test_wrap_text_pixels_respects_width_and_splits_huge_words():
    from PIL import ImageFont

    from hermes_ui.text_to_images import _wrap_text_pixels

    font = ImageFont.truetype(_subtitle_test_font(), 40)
    lines = _wrap_text_pixels("uma frase relativamente longa para testar o wrap", font, 200)
    assert len(lines) >= 2
    assert all(font.getlength(line) <= 200 for line in lines)
    huge = "Palavramuitoexecessivamentelongademesmo"
    lines = _wrap_text_pixels(huge, font, 150)
    assert lines, "palavra gigante tem de gerar linhas"
    assert all(font.getlength(line) <= 150 for line in lines)
    assert "".join(lines) == huge


@pytest.mark.skipif(_yahei_font() is None, reason="MicrosoftYaHeiBold.ttc indisponivel")
def test_subtitle_yahei_regression_no_full_width_bar_and_no_clipped_descenders():
    """Regressão do frame 150 (0.9.99): barra preta de 1651px (86% de 1920) com
    a base das letras cortada no segmento real do canal."""
    import numpy as np

    from hermes_ui.text_to_images import _subtitle_clips_for_scenes

    text = "has gone quiet, but your mind is still racing. You have turned"
    config = {**_SUBTITLE_RENDER_CONFIG, "font_path": _yahei_font(), "font_size": 35}
    clips = _subtitle_clips_for_scenes([{"index": 1, "text": text, "duration": 1.0}], 1920, 1080, config)
    frame = np.asarray(clips[0].get_frame(0)).astype(int)
    assert frame.shape[1] < int(1920 * 0.86), "a barra full-width de 86% voltou"
    gaps = _ink_gaps(frame)
    assert min(gaps.values()) >= 6, f"descendentes cortados (g/q/y): {gaps}"
