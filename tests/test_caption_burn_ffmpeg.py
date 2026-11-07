"""1.0.58/1.0.61 — queima de legendas por FFmpeg puro, com .ass dinâmico.

O relato do utilizador (51 min com codec=h264_nvenc no log) provou que o
gargalo era o MoviePy a compor TextClips frame a frame no Python — não o
encoder. Estes testes prendem o contrato novo:
- .ass gerado com ``PlayResX/PlayResY`` da resolução REAL do vídeo, margens
  de 60px e ``WrapStyle: 0`` (o .srt + ``force_style`` deixava o libass
  escalar a fonte a partir de 384x288: FontSize 40 virava ~200px e a
  legenda estourava o ecrã, cortada nas laterais — 1.0.61);
- caminho Windows escapado como o ffmpeg exige (``C\\:/...``);
- GPU primeiro (hwaccel cuda + h264_nvenc), CPU como repetição única;
- web-safe (+faststart +yuv420p) nos dois caminhos;
- medição da geometria do vídeo sem MoviePy (duração/largura/altura).
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
    "outline_width": 2.75,
}


# ---------------------------------------------------------------------------
# .ass — cabeçalho dinâmico (a correcção do relato)
# ---------------------------------------------------------------------------


def test_ass_header_declares_the_real_video_resolution(tmp_path: Path):
    captions = tmp_path / "cap.ass"
    cues = text_to_images._write_caption_ass(
        [{"index": 1, "text": "Olá mundo.", "duration": 2.0}],
        captions,
        width=1920,
        height=1080,
        subtitle_config=_CONFIG,
        font_size=40,
    )
    assert cues == 1
    content = captions.read_text(encoding="utf-8")
    assert "[Script Info]" in content
    assert "PlayResX: 1920" in content
    assert "PlayResY: 1080" in content
    # Quebra de linha automática (o libass decide, não o texto com \N).
    assert "WrapStyle: 0" in content
    assert "ScaledBorderAndShadow: yes" in content
    assert "[V4+ Styles]" in content and "[Events]" in content


def test_ass_header_uses_the_shorts_resolution(tmp_path: Path):
    captions = tmp_path / "cap.ass"
    text_to_images._write_caption_ass(
        [{"index": 1, "text": "Vertical.", "duration": 1.0}],
        captions,
        width=1080,
        height=1920,
        subtitle_config=_CONFIG,
        font_size=40,
    )
    content = captions.read_text(encoding="utf-8")
    assert "PlayResX: 1080" in content
    assert "PlayResY: 1920" in content


def test_ass_header_falls_back_to_1080p_when_geometry_is_unknown(tmp_path: Path):
    captions = tmp_path / "cap.ass"
    text_to_images._write_caption_ass(
        [{"index": 1, "text": "Sem sonda.", "duration": 1.0}],
        captions,
        width=0,
        height=0,
        subtitle_config=_CONFIG,
        font_size=40,
    )
    content = captions.read_text(encoding="utf-8")
    assert f"PlayResX: {text_to_images.CAPTION_ASS_FALLBACK_WIDTH}" in content
    assert f"PlayResY: {text_to_images.CAPTION_ASS_FALLBACK_HEIGHT}" in content


# ---------------------------------------------------------------------------
# .ass — Style (UI -> ASS) e eventos
# ---------------------------------------------------------------------------


def test_ass_style_maps_the_channel_config_with_exact_font_size():
    style = text_to_images._caption_ass_style_line(_CONFIG, 40, with_background=True)
    fields = style.split(",", 1)[1].split(",")  # [0]=Fontname .. [21]=Encoding
    assert style.startswith("Style: Default,")
    assert fields[0] == "arial"  # Fontname (stem)
    assert fields[1] == "40"  # FontSize EXACTO da UI (PlayRes real)
    assert fields[2] == "&H00FFFFFF"  # PrimaryColour (branco)
    assert fields[4] == "&H00000000"  # OutlineColour (preto)
    assert fields[5] == "&H00000000"  # BackColour (fundo pedido)
    assert fields[14] == "3"  # BorderStyle = 3 (caixa hug-text)
    assert fields[15] == "2.75"  # Outline (float da UI)
    assert fields[16] == "0"  # Shadow
    assert fields[17] == "2"  # Alignment (bottom = numpad 2)
    assert fields[18] == "60" and fields[19] == "60"  # MarginL/MarginR
    assert fields[20] == "40"  # MarginV
    assert fields[21] == "1"  # Encoding


def test_ass_style_without_background_uses_outline_box():
    config = {**_CONFIG, "background": False}
    style = text_to_images._caption_ass_style_line(config, 30, with_background=False)
    fields = style.split(",", 1)[1].split(",")
    assert fields[1] == "30"
    assert fields[14] == "1"  # BorderStyle = 1 (contorno simples)
    assert fields[15] == "2.75"


def test_ass_style_colors_follow_the_channel():
    config = {**_CONFIG, "color": "#FF0000", "outline": "#00FF00", "background_color": "#0000FF"}
    style = text_to_images._caption_ass_style_line(config, 40, with_background=True)
    fields = style.split(",", 1)[1].split(",")
    assert fields[2] == "&H000000FF"  # vermelho -> BGR
    assert fields[4] == "&H0000FF00"  # verde -> BGR
    assert fields[5] == "&H00FF0000"  # azul -> BGR


def test_ass_events_have_no_manual_line_breaks(tmp_path: Path):
    captions = tmp_path / "cap.ass"
    cues = text_to_images._write_caption_ass(
        [
            {"index": 1, "text": "Primeira frase.", "duration": 1.5},
            {"index": 2, "text": "Segunda  com    espaços.", "duration": 2.5},
        ],
        captions,
        width=1920,
        height=1080,
        subtitle_config=_CONFIG,
        font_size=40,
    )
    assert cues == 2
    events = captions.read_text(encoding="utf-8").split("[Events]", 1)[1]
    assert "\\N" not in events  # a quebra é do libass, nunca manual
    assert events.count("Dialogue: 0,") == 2
    flat = events.replace(" ", "")
    assert "0:00:00.00,0:00:01.50,Default,,0,0,0,,Primeirafrase." in flat
    assert "0:00:01.50,0:00:04.00,Default,,0,0,0,,Segundacomespaços." in flat
    # Os eventos declaram Margem 0 (herdam as 60px do Default).
    assert ",Default,,0,0,0,," in events


def test_ass_skips_blank_texts(tmp_path: Path):
    captions = tmp_path / "cap.ass"
    cues = text_to_images._write_caption_ass(
        [
            {"index": 1, "text": "   ", "duration": 1.0},
            {"index": 2, "text": "Frase.", "duration": 1.0},
        ],
        captions,
        width=1920,
        height=1080,
        subtitle_config=_CONFIG,
        font_size=40,
    )
    assert cues == 1


def test_ass_timestamp_formats_centiseconds():
    assert text_to_images._ass_timestamp(0) == "0:00:00.00"
    assert text_to_images._ass_timestamp(3661.5) == "1:01:01.50"


# ---------------------------------------------------------------------------
# Escaping do caminho (provado empiricamente no ffmpeg 7.1)
# ---------------------------------------------------------------------------


def test_subtitles_filter_path_escapes_the_windows_drive():
    escaped = text_to_images._subtitles_filter_path(Path("C:/subs/cap.ass"))
    assert "C" + chr(92) * 2 + ":" in escaped  # duas barras antes dos dois-pontos
    assert "/subs/cap.ass" in escaped
    assert escaped.count(chr(92)) == 2


@pytest.mark.skipif(os.name != "nt", reason="prefixo de unidade Windows")
def test_subtitles_filter_path_absolute_windows_prefix():
    escaped = text_to_images._subtitles_filter_path(Path("C:/videos/cap.ass"))
    assert escaped == "C" + chr(92) * 2 + ":/videos/cap.ass"


def test_subtitles_filter_path_never_leaves_backslash_separators():
    escaped = text_to_images._subtitles_filter_path(Path(r"C:\videos\cap.ass"))
    assert "/videos/cap.ass" in escaped
    assert "C" + chr(92) * 2 + ":/videos/" in escaped
    assert escaped.count(chr(92)) == 2


# ---------------------------------------------------------------------------
# Comando FFmpeg — .ass sem force_style
# ---------------------------------------------------------------------------


def test_caption_burn_command_gpu_uses_cuda_and_nvenc(tmp_path: Path):
    source = tmp_path / "in.mp4"
    source.write_bytes(b"x")
    captions = tmp_path / "cap.ass"
    target = tmp_path / "out.mp4"
    command = text_to_images._caption_burn_command(
        "ffmpeg", source, captions, target, _CONFIG, gpu=True
    )
    assert command[0] == "ffmpeg"
    assert "-hwaccel" in command and command[command.index("-hwaccel") + 1] == "cuda"
    assert "-c:v" in command and command[command.index("-c:v") + 1] == text_to_images.NVENC_VIDEO_CODEC
    assert "-c:a" in command and command[command.index("-c:a") + 1] == "copy"
    assert "-movflags" in command and command[command.index("-movflags") + 1] == "+faststart"
    assert "-pix_fmt" in command and command[command.index("-pix_fmt") + 1] == "yuv420p"
    vf = command[command.index("-vf") + 1]
    assert "subtitles=" in vf and "cap.ass" in vf
    # 1.0.61: force_style MORREU (não controla resolução nem quebra de linha).
    assert "force_style" not in vf
    assert "FontName=" not in vf


def test_caption_burn_command_cpu_falls_back_to_libx264(tmp_path: Path):
    source = tmp_path / "in.mp4"
    source.write_bytes(b"x")
    captions = tmp_path / "cap.ass"
    target = tmp_path / "out.mp4"
    command = text_to_images._caption_burn_command(
        "ffmpeg", source, captions, target, _CONFIG, gpu=False
    )
    assert "-hwaccel" not in command
    assert command[command.index("-c:v") + 1] == text_to_images.CPU_VIDEO_CODEC
    assert "-pix_fmt" in command


def test_force_style_is_gone_from_the_module():
    """Contrato anti-regressão: ninguém volta ao force_style/.srt.

    A MENÇÃO em comentários/docstrings é legítima (explica a decisão); o que
    não pode existir é o USO — nenhum ``:force_style=`` no comando.
    """
    assert not hasattr(text_to_images, "_caption_force_style")
    assert not hasattr(text_to_images, "_write_caption_srt")
    source = (ROOT / "hermes_ui" / "text_to_images.py").read_text(encoding="utf-8")
    assert ":force_style=" not in source
    assert "_caption_force_style(" not in source
    assert "_write_caption_srt(" not in source
    assert "_write_caption_ass" in source


# ---------------------------------------------------------------------------
# Sondagem da geometria (sem MoviePy)
# ---------------------------------------------------------------------------


def test_probe_video_geometry_parses_duration_and_size(tmp_path: Path):
    from hermes_ui.pipeline_worker import _resolve_local_ffmpeg

    ffmpeg = _resolve_local_ffmpeg({})
    video = tmp_path / "probe.mp4"
    import subprocess

    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=3:size=640x360:rate=10", "-c:v", "libx264", str(video)],
        capture_output=True, check=False,
    )
    if not video.is_file():
        pytest.skip("ffmpeg não gerou vídeo de teste")
    duration, width, height = text_to_images._probe_video_geometry(ffmpeg, video)
    assert duration == pytest.approx(3.0, abs=0.6)
    assert (width, height) == (640, 360)


def test_probe_video_geometry_returns_zero_on_missing_file(tmp_path: Path):
    duration, width, height = text_to_images._probe_video_geometry("ffmpeg", tmp_path / "nao-existe.mp4")
    assert (duration, width, height) == (0.0, 0, 0)


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
    assert not list(tmp_path.glob("*.ass"))


def test_burn_captions_accepts_the_ffmpeg_binary_override():
    """O worker passa o binário resolvido do painel (7.1 com NVENC)."""
    worker_source = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")
    assert "burn_captions_on_video(" in worker_source
    assert "ffmpeg_binary=_resolve_local_ffmpeg(settings)" in worker_source
    import inspect

    parameters = inspect.signature(text_to_images.burn_captions_on_video).parameters
    assert "ffmpeg_binary" in parameters
    assert parameters["ffmpeg_binary"].default == ""


def test_worker_logs_the_codec_total_contract():
    worker_source = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")
    assert "def _log_mpt_captions_total(" in worker_source
    assert "[MPT-TOTAL] MPT levou" in worker_source
    assert "Legendas levaram" in worker_source


# ---------------------------------------------------------------------------
# 1.0.67 - blindagem final: resolucao certa SEMPRE + dump auditectavel
# ---------------------------------------------------------------------------


def test_ass_header_for_a_1080p_video_declares_1920x1080(tmp_path: Path):
    """O teste de regressao pedido: video 1920x1080 -> PlayResX/Y reais.

    Falha se o codigo tentar usar o fallback (384x288 era a resolucao virtual
    do .srt que fazia a legenda estourar o ecra).
    """
    captions = tmp_path / "cap.ass"
    text_to_images._write_caption_ass(
        [{"index": 1, "text": "Frase de teste.", "duration": 2.0}],
        captions,
        width=1920,
        height=1080,
        subtitle_config=_CONFIG,
        font_size=40,
    )
    content = captions.read_text(encoding="utf-8")
    assert "PlayResX: 1920" in content
    assert "PlayResY: 1080" in content
    # A resolucao proibida NUNCA aparece (era o fallback do .srt).
    assert "PlayResX: 384" not in content
    assert "PlayResY: 288" not in content


def test_ass_never_falls_back_to_384x288():
    """Contrato anti-regressao: o fallback do .ass e 1920x1080, nunca 384x288."""
    assert text_to_images.CAPTION_ASS_FALLBACK_WIDTH == 1920
    assert text_to_images.CAPTION_ASS_FALLBACK_HEIGHT == 1080


def test_ass_fallback_declares_1920x1080_when_the_probe_fails(tmp_path: Path):
    """Quando o ffmpeg nao consegue sondar (0x0), o cabecalho usa 1920x1080 -
    e a legenda continua no tamanho certo (nunca gigante)."""
    captions = tmp_path / "cap.ass"
    text_to_images._write_caption_ass(
        [{"index": 1, "text": "Frase de teste.", "duration": 2.0}],
        captions,
        width=0,
        height=0,
        subtitle_config=_CONFIG,
        font_size=40,
    )
    content = captions.read_text(encoding="utf-8")
    assert "PlayResX: 1920" in content
    assert "PlayResY: 1080" in content
    assert "PlayResX: 384" not in content


def test_font_size_is_the_real_pixel_size_on_a_1080p_video(tmp_path: Path):
    """FontSize=40 da UI = 40px REAIS no .ass (o .srt escalava ~5x)."""
    captions = tmp_path / "cap.ass"
    text_to_images._write_caption_ass(
        [{"index": 1, "text": "Frase.", "duration": 2.0}],
        captions,
        width=1920,
        height=1080,
        subtitle_config=_CONFIG,
        font_size=40,
    )
    style = [
        line
        for line in captions.read_text(encoding="utf-8").splitlines()
        if line.startswith("Style:")
    ][0]
    assert ",40," in style, f"FontSize 40 no Style: {style[:120]}"


def test_burn_dumps_captions_debug_ass_next_to_the_video(tmp_path, monkeypatch):
    """1.0.67 - a queima deixa captions_debug.ass na pasta da tarefa: o
    cabecalho pode ser auditado sem reender nada (foi assim que a regressao do
    tamanho gigante passou despercebida)."""
    import subprocess

    video = tmp_path / "final-1.mp4"
    video.write_bytes(b"mp4")

    def fake_probe(ffmpeg, path):
        return 12.0, 1920, 1080

    def fake_run(command, **kwargs):
        class Completed:
            returncode = 0

        return Completed()

    monkeypatch.setattr(text_to_images, "_probe_video_geometry", fake_probe)
    monkeypatch.setattr(text_to_images, "_nvenc_encoder_available", lambda _ffmpeg: False)
    monkeypatch.setattr(text_to_images.subprocess, "run", fake_run)
    # Simula a saida do ffmpeg: o temporario "criado" pela queima.
    original_with_name = Path.with_name

    def _with_name(self, name):
        candidate = original_with_name(self, name)
        if name.endswith("-tmp.mp4"):
            candidate.write_bytes(b"mp4-queimado")
        return candidate

    monkeypatch.setattr(Path, "with_name", _with_name)

    report: dict = {}
    result = text_to_images.burn_captions_on_video(
        video,
        "Uma frase de teste com palavras suficientes.",
        _CONFIG,
        burn_report=report,
        ffmpeg_binary="ffmpeg",
    )

    assert result == video
    assert report.get("subtitles_burned") is True
    debug_ass = tmp_path / "captions_debug.ass"
    assert debug_ass.is_file(), "o dump auditectavel tem de existir"
    assert "PlayResX: 1920" in debug_ass.read_text(encoding="utf-8")
    assert "PlayResY: 1080" in debug_ass.read_text(encoding="utf-8")
    assert str(debug_ass) == report.get("captions_debug_ass")


def test_burn_audit_dump_reports_the_path_for_the_worker_log():
    """O worker carimba o caminho do dump no burn_report (auditoria no log)."""
    assert "captions_debug_ass" in (ROOT / "hermes_ui" / "text_to_images.py").read_text(encoding="utf-8")


def test_caption_burn_command_has_no_force_style():
    """Contrato 1.0.61 mantido: o comando usa o .ass completo, sem force_style
    (o force_style do .srt era o que escalava a fonte a partir de 384x288)."""
    captions = tmp_path / "cap.ass" if False else Path("cap.ass")
    source = (ROOT / "hermes_ui" / "text_to_images.py").read_text(encoding="utf-8")
    burn_source = source.split("def burn_captions_on_video(", 1)[1].split(
        "def synthesize_text_to_images_audio", 1
    )[0]
    assert "force_style" not in burn_source.split('"""', 2)[-1]
    assert "_write_caption_ass(" in burn_source
    assert "_write_caption_srt" not in burn_source
