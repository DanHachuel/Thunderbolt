"""1.0.58 — queima de legendas por FFmpeg puro (substitui o MoviePy).

O relato do utilizador (51 min com codec=h264_nvenc no log) provou que o
gargalo era o MoviePy a compor TextClips frame a frame no Python — não o
encoder. Estes testes prendem o contrato novo:
- .srt gerado com blocos sequenciais proporcionais ao vídeo;
- filtro `subtitles` com force_style mapeado do config do canal;
- caminho Windows escapado como o ffmpeg exige (``C\\\\:/...``);
- GPU primeiro (hwaccel cuda + h264_nvenc), CPU como repetição única;
- web-safe (+faststart + yuv420p) nos dois caminhos;
- medição da geometria do vídeo sem MoviePy (duração/altura).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hermes_ui import text_to_images


ROOT = Path(__file__).resolve().parents[1]


_CONFIG = {
    "font_path": "C:/Windows/Fonts/arial.ttf",
    "font_size": 40,
    "position": "bottom",
    "color": "#FFFFFF",
    "background": True,
    "background_color": "#000000",
    "outline": "#000000",
    "outline_width": 2,
}


# ---------------------------------------------------------------------------
# SRT
# ---------------------------------------------------------------------------


def test_srt_writes_sequential_cues_scaled_to_the_video(tmp_path: Path):
    segments = [
        {"index": 1, "text": "Primeira frase.", "duration": 1.0},
        {"index": 2, "text": "Segunda frase.", "duration": 1.0},
    ]
    srt = tmp_path / "cap.srt"
    cues = text_to_images._write_caption_srt(segments, srt)
    assert cues == 2
    content = srt.read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:01,000" in content
    assert "00:00:01,000 --> 00:00:02,000" in content
    assert "Primeira frase." in content
    assert "Segunda frase." in content


def test_srt_skips_blank_texts(tmp_path: Path):
    srt = tmp_path / "cap.srt"
    cues = text_to_images._write_caption_srt(
        [{"index": 1, "text": "   ", "duration": 1.0}, {"index": 2, "text": "Frase.", "duration": 1.0}],
        srt,
    )
    assert cues == 1


def test_srt_timestamp_formats_hours_and_millis():
    assert text_to_images._srt_timestamp(0) == "00:00:00,000"
    assert text_to_images._srt_timestamp(3661.5) == "01:01:01,500"


# ---------------------------------------------------------------------------
# Escaping do caminho (provado empiricamente no ffmpeg 7.1)
# ---------------------------------------------------------------------------


def test_subtitles_filter_path_escapes_the_windows_drive():
    # O escape do três-pontos aplica-se onde o caminho o tiver (unidade
    # Windows; no Linux o componente embutido fica no meio do caminho).
    escaped = text_to_images._subtitles_filter_path(Path("C:/subs/cap.srt"))
    assert "C" + chr(92) * 2 + ":" in escaped  # duas barras antes dos dois-pontos
    assert "/subs/cap.srt" in escaped
    # Nenhuma barra invertida solta além do par de escape.
    assert escaped.count(chr(92)) == 2


@pytest.mark.skipif(os.name != "nt", reason="prefixo de unidade Windows")
def test_subtitles_filter_path_absolute_windows_prefix():
    escaped = text_to_images._subtitles_filter_path(Path("C:/videos/cap.srt"))
    assert escaped == "C" + chr(92) * 2 + ":/videos/cap.srt"


def test_subtitles_filter_path_never_leaves_backslash_separators():
    escaped = text_to_images._subtitles_filter_path(Path(r"C:\videos\cap.srt"))
    assert "/videos/cap.srt" in escaped
    assert "C" + chr(92) * 2 + ":/videos/" in escaped
    assert escaped.count(chr(92)) == 2


# ---------------------------------------------------------------------------
# Estilo ASS (config do canal -> force_style)
# ---------------------------------------------------------------------------


def test_caption_ass_alignment_numpad():
    assert text_to_images._caption_ass_alignment("bottom") == 2
    assert text_to_images._caption_ass_alignment("Top") == 8
    assert text_to_images._caption_ass_alignment("center") == 5
    assert text_to_images._caption_ass_alignment("estranho") == 2


def test_caption_ass_color_is_bgr():
    assert text_to_images._caption_ass_color("#FFFFFF") == "&H00FFFFFF"
    assert text_to_images._caption_ass_color("#FF0000") == "&H000000FF"  # vermelho -> BGR
    assert text_to_images._caption_ass_color("invalid", "#000000") == "&H00000000"


def test_caption_force_style_maps_the_channel_config():
    style = text_to_images._caption_force_style(_CONFIG, 40)
    assert "FontName=arial" in style
    assert "FontSize=40" in style
    assert "PrimaryColour=&H00FFFFFF" in style
    assert "OutlineColour=&H00000000" in style
    assert "Outline=2" in style
    assert "Alignment=2" in style
    # Background ligado -> caixa opaca hug-text (BorderStyle=3).
    assert "BorderStyle=3" in style
    assert "BackColour=&H00000000" in style


def test_caption_force_style_without_background_uses_outline_box():
    config = {**_CONFIG, "background": False}
    style = text_to_images._caption_force_style(config, 30)
    assert "BorderStyle=1" in style
    assert "BackColour" not in style


def test_caption_font_name_drops_the_extension():
    assert text_to_images._caption_font_name("C:/Windows/Fonts/MicrosoftYaHeiBold.ttc") == "MicrosoftYaHeiBold"


# ---------------------------------------------------------------------------
# Comando FFmpeg
# ---------------------------------------------------------------------------


def test_caption_burn_command_gpu_uses_cuda_and_nvenc(tmp_path: Path, monkeypatch):
    source = tmp_path / "in.mp4"
    source.write_bytes(b"x")
    srt = tmp_path / "cap.srt"
    target = tmp_path / "out.mp4"
    command = text_to_images._caption_burn_command(
        "ffmpeg", source, srt, target, _CONFIG, gpu=True, font_size=40
    )
    assert command[0] == "ffmpeg"
    assert "-hwaccel" in command and command[command.index("-hwaccel") + 1] == "cuda"
    assert "-c:v" in command and command[command.index("-c:v") + 1] == text_to_images.NVENC_VIDEO_CODEC
    assert "-c:a" in command and command[command.index("-c:a") + 1] == "copy"
    assert "-movflags" in command and command[command.index("-movflags") + 1] == "+faststart"
    assert "-pix_fmt" in command and command[command.index("-pix_fmt") + 1] == "yuv420p"
    vf = command[command.index("-vf") + 1]
    assert "subtitles=" in vf and "force_style=" in vf
    assert "FontName=arial" in vf
    assert "BorderStyle=3" in vf


def test_caption_burn_command_cpu_falls_back_to_libx264(tmp_path: Path):
    source = tmp_path / "in.mp4"
    source.write_bytes(b"x")
    srt = tmp_path / "cap.srt"
    target = tmp_path / "out.mp4"
    command = text_to_images._caption_burn_command(
        "ffmpeg", source, srt, target, _CONFIG, gpu=False, font_size=40
    )
    assert "-hwaccel" not in command
    assert command[command.index("-c:v") + 1] == text_to_images.CPU_VIDEO_CODEC
    assert "-pix_fmt" in command and command[command.index("-pix_fmt") + 1] == "yuv420p"


# ---------------------------------------------------------------------------
# Sondagem da geometria (sem MoviePy)
# ---------------------------------------------------------------------------


def test_probe_video_geometry_parses_duration_and_height(tmp_path: Path):
    from hermes_ui.pipeline_worker import _resolve_local_ffmpeg

    ffmpeg = _resolve_local_ffmpeg({})
    # Reaproveita o render existente do teste real desta suíte (CI/Linux ok).
    video = tmp_path / "probe.mp4"
    import subprocess

    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=3:size=640x360:rate=10", "-c:v", "libx264", str(video)],
        capture_output=True, check=False,
    )
    if not video.is_file():
        pytest.skip("ffmpeg não gerou vídeo de teste")
    duration, height = text_to_images._probe_video_geometry(ffmpeg, video)
    assert duration == pytest.approx(3.0, abs=0.6)
    assert height == 360


def test_probe_video_geometry_returns_zero_on_missing_file(tmp_path: Path):
    duration, height = text_to_images._probe_video_geometry("ffmpeg", tmp_path / "nao-existe.mp4")
    assert (duration, height) == (0.0, 0)


# ---------------------------------------------------------------------------
# Contrato da função pública
# ---------------------------------------------------------------------------


def test_burn_captions_without_font_or_text_never_touches_the_video(tmp_path: Path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"conteudo")
    config = {**_CONFIG, "font_path": ""}
    report: dict[str, bool] = {}
    result = text_to_images.burn_captions_on_video(video, "qualquer coisa", config, burn_report=report)
    assert result == video
    assert report["subtitles_burned"] is False
    assert video.read_bytes() == b"conteudo"
    assert not list(tmp_path.glob("*.srt"))


def test_burn_captions_accepts_the_ffmpeg_binary_override():
    """O worker passa o binário resolvido do painel (7.1 com NVENC)."""
    # A chamada do worker usa ffmpeg_binary= com a resolução das settings.
    worker_source = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")
    assert "burn_captions_on_video(" in worker_source
    assert "ffmpeg_binary=_resolve_local_ffmpeg(settings)" in worker_source
    # A assinatura pública aceita o override (opcional — chamadas antigas
    # com 3 posicionais continuam a funcionar).
    import inspect

    parameters = inspect.signature(text_to_images.burn_captions_on_video).parameters
    assert "ffmpeg_binary" in parameters
    assert parameters["ffmpeg_binary"].default == ""


def test_worker_logs_the_codec_total_contract():
    worker_source = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")
    assert "def _log_mpt_captions_total(" in worker_source
    assert "[MPT-TOTAL] MPT levou" in worker_source
    assert "Legendas levaram" in worker_source
