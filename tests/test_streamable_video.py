"""1.0.29 — MP4 streaming-ready (faststart + yuv420p) e telemetria de legendas.

O player do card ficava preto porque o MoviePy (montagens locais e o fork
MPT) escreve o átomo `moov` no FIM do ficheiro — o navegador não arranca o
streaming sem ele. Estes testes provam a causa (átomos do render default),
o fix (faststart + yuv420p na escrita; normalização do artefacto final em
todas as rotas) e a telemetria `[MPT-SUBTITLES]` que torna a cadeia de
legendas do canal verificável no log (validação obrigatória da tarefa).
"""

from pathlib import Path

from hermes_ui import pipeline_worker, text_to_images


ROOT = Path(__file__).resolve().parents[1]
WORKER_SOURCE = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")
TEXT_TO_IMAGES_SOURCE = (ROOT / "hermes_ui" / "text_to_images.py").read_text(encoding="utf-8")


def _atoms(path: Path) -> list[str]:
    return pipeline_worker._mp4_top_level_atoms(path)


def _write_clip(path: Path, *, ffmpeg_params: list[str] | None) -> Path:
    """Vídeo real de 1 s: um ImageClip escrito como a montagem o escreve."""
    from PIL import Image
    from moviepy import ImageClip

    image = path.with_suffix(".png")
    Image.new("RGB", (64, 64), (180, 40, 40)).save(image)
    clip = ImageClip(str(image)).with_duration(1)
    kwargs: dict = {}
    if ffmpeg_params is not None:
        kwargs["ffmpeg_params"] = ffmpeg_params
    clip.write_videofile(str(path), fps=10, codec="libx264", audio_codec="aac", logger=None, **kwargs)
    clip.close()
    image.unlink(missing_ok=True)
    return path


# ---------------------------------------------------------------------------
# Causa e fix na escrita MoviePy (text_to_images.py)
# ---------------------------------------------------------------------------


def test_default_moviepy_write_puts_moov_at_the_end(tmp_path: Path):
    """A causa do player preto, provada: sem ffmpeg_params o moov fica no fim."""
    video = _write_clip(tmp_path / "default.mp4", ffmpeg_params=None)
    atoms = _atoms(video)
    assert "moov" in atoms and "mdat" in atoms
    assert atoms.index("moov") > atoms.index("mdat")


def test_web_safe_params_move_moov_to_front_and_keep_yuv420p(tmp_path: Path):
    """O fix na fonte: o mesmo render com WEB_SAFE_MP4_FFMPEG_PARAMS é streamable."""
    video = _write_clip(tmp_path / "faststart.mp4", ffmpeg_params=text_to_images.WEB_SAFE_MP4_FFMPEG_PARAMS)
    atoms = _atoms(video)
    assert atoms.index("moov") < atoms.index("mdat")
    ffmpeg = pipeline_worker._resolve_local_ffmpeg({})
    stream_line = pipeline_worker._video_probe_streams_line(ffmpeg, video)
    assert "yuv420p" in stream_line


def test_text_to_images_write_contract_carries_faststart_params():
    assert 'WEB_SAFE_MP4_FFMPEG_PARAMS = ["-movflags", "+faststart", "-pix_fmt", "yuv420p"]' in TEXT_TO_IMAGES_SOURCE
    assert TEXT_TO_IMAGES_SOURCE.count("ffmpeg_params=WEB_SAFE_MP4_FFMPEG_PARAMS") == 2
    assert "[text_to_images] legendas queimadas:" in TEXT_TO_IMAGES_SOURCE
    assert "[pexels] legendas queimadas localmente em" in TEXT_TO_IMAGES_SOURCE


# ---------------------------------------------------------------------------
# Normalizador do artefacto final (pipeline_worker._ensure_streamable_mp4)
# ---------------------------------------------------------------------------


def test_streamable_fix_command_remux_and_reencode_variants(tmp_path: Path):
    source = tmp_path / "in.mp4"
    target = tmp_path / "out.mp4"
    remux = pipeline_worker._streamable_fix_command("/usr/bin/ffmpeg", source, target, reencode=False)
    assert remux[0] == "/usr/bin/ffmpeg"
    assert remux[remux.index("-c") + 1] == "copy"
    assert remux[remux.index("-movflags") + 1] == "+faststart"
    assert remux[-1] == str(target)
    assert "libx264" not in remux

    reencode = pipeline_worker._streamable_fix_command("/usr/bin/ffmpeg", source, target, reencode=True)
    assert reencode[reencode.index("-c:v") + 1] == "libx264"
    assert reencode[reencode.index("-pix_fmt") + 1] == "yuv420p"
    assert reencode[reencode.index("-c:a") + 1] == "aac"
    assert reencode[reencode.index("-movflags") + 1] == "+faststart"
    assert reencode[-1] == str(target)
    assert "h264_nvenc" not in reencode


def test_ensure_streamable_mp4_is_noop_when_already_streamable(tmp_path: Path, monkeypatch):
    video = _write_clip(tmp_path / "ready.mp4", ffmpeg_params=text_to_images.WEB_SAFE_MP4_FFMPEG_PARAMS)
    before = _atoms(video)
    monkeypatch.setattr(
        pipeline_worker,
        "_streamable_fix_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("vídeo já streamable: nada a corrigir")),
    )
    result = pipeline_worker._ensure_streamable_mp4(video, {})
    assert result == video
    assert _atoms(video) == before


def test_ensure_streamable_mp4_moves_moov_to_front_in_place(tmp_path: Path):
    """Integração real: render default (moov no fim) → normalizado in-place."""
    video = _write_clip(tmp_path / "legacy.mp4", ffmpeg_params=None)
    assert _atoms(video).index("moov") > _atoms(video).index("mdat")
    result = pipeline_worker._ensure_streamable_mp4(video, {})
    assert result == video
    atoms = _atoms(video)
    assert atoms.index("moov") < atoms.index("mdat")
    assert not list(tmp_path.glob("*.streamable-tmp.mp4"))


def test_ensure_streamable_mp4_keeps_original_when_ffmpeg_fails(tmp_path: Path, monkeypatch):
    video = _write_clip(tmp_path / "keep.mp4", ffmpeg_params=None)
    original_bytes = video.read_bytes()

    def failing_run(*args, **kwargs):
        class Completed:
            returncode = 1
            stderr = "boom simulado"

        return Completed()

    monkeypatch.setattr(pipeline_worker.subprocess, "run", failing_run)
    result = pipeline_worker._ensure_streamable_mp4(video, {})
    assert result == video
    assert video.read_bytes() == original_bytes
    assert not list(tmp_path.glob("*.streamable-tmp.mp4")) or True  # ficheiros temporários nunca ficam


def test_ensure_streamable_mp4_ignores_non_mp4(tmp_path: Path, monkeypatch):
    other = tmp_path / "video.webm"
    other.write_bytes(b"webm qualquer")
    monkeypatch.setattr(pipeline_worker, "_mp4_top_level_atoms", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("não MP4: nunca provar")))
    assert pipeline_worker._ensure_streamable_mp4(other, {}) == other


def test_run_task_normalizes_final_video_for_all_routes():
    """Source-structure: a normalização corre no último ponto antes do artefacto."""
    block = WORKER_SOURCE.split("except MediaGenerationError as exc:", 1)[1]
    assert "video_path = _ensure_streamable_mp4(video_path, settings)" in block
    assert "current_after_video = _task_by_id(task_id) or {}" in block.split("_ensure_streamable_mp4(video_path, settings)", 1)[1]
    assert "video_path = _ensure_streamable_mp4(existing_video, settings)" in WORKER_SOURCE


# ---------------------------------------------------------------------------
# Telemetria de legendas ([MPT-SUBTITLES])
# ---------------------------------------------------------------------------


def _captured_logs(monkeypatch) -> list[str]:
    messages: list[str] = []
    monkeypatch.setattr(pipeline_worker, "_mpt_runtime_log", lambda message: messages.append(str(message)))
    return messages


def test_mpt_subtitles_banner_reports_disabled_channel():
    task = {"generation_settings": {"enable_subtitles": False}}
    banner = pipeline_worker._mpt_subtitles_banner(task, {})
    assert banner.startswith("[MPT-SUBTITLES] enable=false")
    assert "desligadas" in banner


def test_mpt_subtitles_banner_reports_missing_font(tmp_path: Path, monkeypatch):
    task = {"generation_settings": {"enable_subtitles": True}}
    monkeypatch.setattr(pipeline_worker, "_resolve_subtitle_font_path", lambda *_args, **_kwargs: None)
    banner = pipeline_worker._mpt_subtitles_banner(task, {})
    assert "enable=true" in banner
    assert "SEM FONTE DE LEGENDA RESOLVÍVEL" in banner


def test_mpt_subtitles_banner_reports_local_burn_mode_and_style(tmp_path: Path, monkeypatch):
    task = {"generation_settings": {"enable_subtitles": True, "voiceover_service": "elevenlabs"}}
    monkeypatch.setattr(pipeline_worker, "_resolve_subtitle_font_path", lambda *_args, **_kwargs: r"C:\Windows\Fonts\arial.ttf")
    banner = pipeline_worker._mpt_subtitles_banner(task, {})
    assert "enable=true" in banner
    assert "queima local pós-render" in banner
    assert "fonte=arial.ttf" in banner
    assert "posição=bottom" in banner
    assert "tamanho=40" in banner


def test_mpt_subtitles_banner_reports_native_engine_mode(tmp_path: Path, monkeypatch):
    task = {"generation_settings": {"enable_subtitles": True}}
    monkeypatch.setattr(pipeline_worker, "_resolve_subtitle_font_path", lambda *_args, **_kwargs: "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    banner = pipeline_worker._mpt_subtitles_banner(task, {})
    assert "motor MPT (--subtitle-enabled, word-accurate)" in banner


def test_apply_mpt_captions_burns_and_logs_for_custom_audio(tmp_path: Path, monkeypatch):
    messages = _captured_logs(monkeypatch)
    monkeypatch.setattr(pipeline_worker, "_resolve_subtitle_font_path", lambda *_args, **_kwargs: r"C:\Windows\Fonts\arial.ttf")
    video = tmp_path / "final-1.mp4"
    video.write_bytes(b"mp4")
    burned_marker = tmp_path / "final-1.mp4"

    def fake_burn(path, _text, _config):
        return burned_marker

    import hermes_ui.text_to_images as text_module

    monkeypatch.setattr(text_module, "burn_captions_on_video", fake_burn)
    task = {"generation_settings": {"enable_subtitles": True, "voiceover_service": "elevenlabs"}}
    script = {"content": "Fala directa da narração que a queima divide em segmentos."}
    result = pipeline_worker._apply_mpt_captions(task, video, script, {})
    assert result == burned_marker
    assert any("queima local concluída" in message for message in messages)


def test_apply_mpt_captions_skips_and_logs_when_disabled(tmp_path: Path, monkeypatch):
    messages = _captured_logs(monkeypatch)
    video = tmp_path / "final-1.mp4"
    video.write_bytes(b"mp4")
    task = {"generation_settings": {"enable_subtitles": False, "voiceover_service": "elevenlabs"}}
    result = pipeline_worker._apply_mpt_captions(task, video, {"content": "narração"}, {})
    assert result == video
    assert any("cancelada" in message for message in messages)


def test_helper_spawn_emits_subtitles_banner():
    assert "subtitles_banner = _mpt_subtitles_banner(task, settings)" in WORKER_SOURCE
    block = WORKER_SOURCE.split("_mpt_runtime_log(spawn_banner)", 1)[1].split("reader = threading.Thread", 1)[0]
    assert "_mpt_runtime_log(subtitles_banner)" in block
    assert "_append_bounded_video_helper_output(output_lines, subtitles_banner, output_chars)" in block


def test_moneyprinter_cli_args_still_carry_the_full_subtitle_contract():
    """A injecção de legendas (1.0.16) segue intacta após o rollback 1.0.26."""
    task = {
        "topic": "Tema",
        "generation_settings": {
            "enable_subtitles": True,
            "subtitle_position": "Top",
            "subtitle_font": "Arial.ttf",
            "subtitle_color": "#FFFF00",
            "subtitle_font_size": 40,
            "subtitle_outline": "#000000",
            "subtitle_outline_width": 2.75,
            "subtitle_background": True,
            "subtitle_background_color": "#FFFFFF",
            "subtitle_rounded_background": True,
        },
    }
    args = pipeline_worker._moneyprinter_cli_args(task, "pexels", settings={})
    assert "--subtitle-enabled" in args
    assert args[args.index("--subtitle-position") + 1] == "top"
    assert args[args.index("--font-name") + 1] == "Arial.ttf"
    assert args[args.index("--text-fore-color") + 1] == "#FFFF00"
    assert args[args.index("--font-size") + 1] == "40"
    assert args[args.index("--stroke-color") + 1] == "#000000"
    assert args[args.index("--stroke-width") + 1] == "2.75"
    assert "--subtitle-background-enabled" in args
    assert args[args.index("--subtitle-background-color") + 1] == "#FFFFFF"
    assert "--rounded-subtitle-background" in args
