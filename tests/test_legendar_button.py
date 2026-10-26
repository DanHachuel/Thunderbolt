"""Botão «Legendar» — REGISTRO DETERMINÍSTICO + trava estrita (1.0.38).

1.0.38 (fim da adivinhação): a flag ``has_subtitles`` é carimbada no exacto
momento da criação a partir do QUE ACONTECEU — o report das funções de queima
(``burn_report`` nas montagens locais e no ``burn_captions_on_video``) e o
tuplo ``(video, burned)`` do ``_apply_mpt_captions``; NUNCA a partir de
configurações. Regra de ouro para os vídeos antigos: sem flag => botão
«Legendar» ACTIVO (é melhor duplicar do que impedir) — o utilizador congela
manualmente («Marcar como Legendado»). A LIMPEZA ÚNICA do arranque remove as
flags adivinhadas da era pré-1.0.38 (marcador impede repetições).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hermes_ui import pipeline_worker
from hermes_ui import storage


ROOT = Path(__file__).resolve().parents[1]
PIPELINE_SOURCE = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")
APP_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def _storage(tmp_path, monkeypatch):
    root = tmp_path / "storage"
    monkeypatch.setattr(storage, "STORAGE", root)
    monkeypatch.setattr(storage, "STATE", root / "state")
    monkeypatch.setattr(storage, "BLUEPRINTS", root / "blueprints")
    storage.ensure_storage()
    return root


# ---------------------------------------------------------------------------
# 1. 1.0.38 — REGISTRO DETERMINÍSTICO: a flag sai do QUE ACONTECEU na queima
# ---------------------------------------------------------------------------


def test_fresh_generation_stamps_the_actual_burn_outcome():
    """Source-structure: o carimbo final vem de `subtitles_burned` (report das
    funções de queima), nunca de `_task_has_subtitles` ou configurações."""
    assert "has_subtitles=subtitles_burned" in PIPELINE_SOURCE
    # a função de adivinhação da 1.0.33 desapareceu por inteiro
    assert "def _task_has_subtitles(" not in PIPELINE_SOURCE
    assert "_task_has_subtitles(" not in PIPELINE_SOURCE
    # as montagens locais reportam o que aconteceu (burn_report wired)
    assert "burn_report=burn_report" in PIPELINE_SOURCE
    assert "subtitles_burned = bool(burn_report.get(\"subtitles_burned\"))" in PIPELINE_SOURCE
    # a rota MPT devolve o desfecho no tuplo
    assert "video_path, subtitles_burned = _apply_mpt_captions(task, video_path, script, settings)" in PIPELINE_SOURCE


def test_apply_mpt_captions_returns_what_actually_happened(monkeypatch, tmp_path):
    """Tuplo determinístico (video, burned) nos desfechos da rota MPT."""
    video = tmp_path / "final-1.mp4"
    video.write_bytes(b"mp4")
    script = {"content": "Narração do vídeo de teste."}

    def _task(**extra):
        base = {"generation_settings": {"voiceover_mode": "tts", "voiceover_service": "", "enable_subtitles": True}}
        base["generation_settings"].update(extra.pop("generation_settings", {}))
        base.update(extra)
        return base

    # TTS nativo: o motor queima quando levou --subtitle-enabled com config válida
    monkeypatch.setattr(pipeline_worker, "_resolve_subtitle_font_path", lambda name, settings: str(tmp_path / "arial.ttf"))
    assert pipeline_worker._apply_mpt_captions(_task(), video, script, {}) == (video, True)
    # sem fonte resolvível o motor não tinha config para queimar
    monkeypatch.setattr(pipeline_worker, "_resolve_subtitle_font_path", lambda name, settings: None)
    assert pipeline_worker._apply_mpt_captions(_task(), video, script, {}) == (video, False)
    # sem narração não há legendas por definição
    assert pipeline_worker._apply_mpt_captions(_task(generation_settings={"voiceover_mode": "none"}), video, script, {}) == (video, False)


def test_burn_captions_reports_failure_when_clips_are_empty(tmp_path, monkeypatch):
    """O report determinístico distingue queima real de saída antecipada:
    sem clips para queimar => subtitles_burned False (nunca True às cegas)."""
    from PIL import Image
    from moviepy import ImageClip

    from hermes_ui.text_to_images import burn_captions_on_video

    if not Path("C:/Windows/Fonts/arial.ttf").is_file() and not Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf").is_file():
        pytest.skip("sem fonte para preparar o video base")
    Image.new("RGB", (320, 180), (20, 20, 20)).save(tmp_path / "a.png")
    video = tmp_path / "final-1.mp4"
    base = ImageClip(str(tmp_path / "a.png")).with_duration(1)
    base.write_videofile(str(video), fps=10, codec="libx264", logger=None)
    base.close()
    monkeypatch.setattr(
        "hermes_ui.text_to_images._subtitle_clips_for_scenes",
        lambda *args, **kwargs: [],
    )
    report: dict = {}
    result = burn_captions_on_video(video, "texto", {"font_path": "arial.ttf"}, burn_report=report)
    assert result == video
    assert report.get("subtitles_burned") is False


def test_worker_intercepts_burn_subtitles_only_action(tmp_path, monkeypatch):
    """O worker intercepta a acção ANTES da cascata normal: queima e devolve done."""
    _storage(tmp_path, monkeypatch)
    video = tmp_path / "final-1.mp4"
    video.write_bytes(b"mp4")
    script_md = tmp_path / "roteiro.md"
    script_md.write_text("# Título\n**[NARRAÇÃO]**\nUma narração de teste para legendas.\n", encoding="utf-8")
    storage.write_json("tasks.json", [{
        "id": "t_legendar",
        "state": "to_do",
        "stage": "video",
        "topic": "Tema",
        "action": "burn_subtitles_only",
        "artifacts": {"video": str(video), "script": str(script_md)},
        "generation_settings": {"voiceover_mode": "tts", "enable_subtitles": True},
    }])
    captured = {}

    def fake_burn(video_path, text, config, burn_report=None, **kwargs):
        captured["text"] = text
        captured["config"] = config
        # 1.0.38 — a queima real preenche o report determinístico
        if burn_report is not None:
            burn_report["subtitles_burned"] = True
        return Path(video_path)

    import hermes_ui.text_to_images
    monkeypatch.setattr(hermes_ui.text_to_images, "burn_captions_on_video", fake_burn)
    monkeypatch.setattr(
        pipeline_worker, "_resolve_subtitle_font_path",
        lambda name, settings: str(tmp_path / "arial.ttf"),
    )
    (tmp_path / "arial.ttf").write_bytes(b"font")
    task = storage.read_json("tasks.json", [])[0]
    result = pipeline_worker._run_task(task)
    # queimou as legendas com a narração do roteiro salvo
    assert "Uma narração de teste" in captured["text"]
    # devolveu a tarefa a done com a flag e sem a acção
    assert result["state"] == "done"
    assert result["has_subtitles"] is True
    assert result.get("action") is None
    assert result.get("progress") == 100


def test_worker_burn_subtitles_fails_without_video(tmp_path, monkeypatch):
    """1.0.37: falha LIMPA — a tarefa fica failed com a acção limpa (nunca
    doing eterno) e a mensagem exacta, em vez de excepção genérica."""
    _storage(tmp_path, monkeypatch)
    storage.write_json("tasks.json", [{
        "id": "t_sem_video",
        "state": "to_do",
        "action": "burn_subtitles_only",
        "artifacts": {},
        "generation_settings": {},
    }])
    task = storage.read_json("tasks.json", [])[0]
    result = pipeline_worker._run_task(task)
    assert result["state"] == "failed"
    assert result.get("action") is None
    assert "não tem um vídeo" in str(result.get("error") or "")


# ---------------------------------------------------------------------------
# 2. Worker: o carimbo vem da geração real
# ---------------------------------------------------------------------------


def test_normal_pipeline_stamps_the_deterministic_outcome():
    """Source-structure: o _update com video_ready=True carimba has_subtitles
    a partir do desfecho real (subtitles_burned), nunca de configurações."""
    assert "has_subtitles=subtitles_burned" in PIPELINE_SOURCE
    assert "has_subtitles=_task_has_subtitles" not in PIPELINE_SOURCE


def test_burn_subtitles_only_intercepted_before_normal_cascade():
    """Source-structure: a intercepção acontece no TOPO do _run_task."""
    block = PIPELINE_SOURCE.split("def _run_task(", 1)[1].split("def ", 1)[0][:1200]
    assert 'task.get("action")' in block
    assert '"burn_subtitles_only"' in block
    assert "_run_burn_subtitles_only(task, settings)" in block


# ---------------------------------------------------------------------------
# 3. UI: trava estrita + override manual (regra de ouro: sem flag => ACTIVO)
# ---------------------------------------------------------------------------


def test_youtube_card_has_legendar_button_with_state_lock():
    """O card tem o botão com as TRÊS estados: sem vídeo (disabled), já
    legendado (✓ Legendado disabled), pronto (ativo). 1.0.38: trava ESTRITA
    (só a flag gravada) + override manual para vídeos antigos."""
    block = APP_SOURCE.split("def _youtube_task_card_body(", 1)[1].split("return _catalog_task_state(task)", 1)[0]
    # 1.0.38 — FIM DA ADIVINHAÇÃO: apenas a flag determinística
    assert 'has_subtitles = bool(task.get("has_subtitles"))' in block
    assert "_ensure_task_subtitles_flag" not in APP_SOURCE
    assert "_task_subtitles_flag" not in APP_SOURCE
    assert '"✓ Legendado"' in block
    assert "disabled=True" in block
    assert '"Legendar"' in block
    # 1.0.38 — override manual: congela vídeos antigos já legendados
    assert '"Marcar como Legendado"' in block
    assert 'update_task(task_id, {"has_subtitles": True})' in block
    # o Upload está em coluna (mesmo tamanho dos downloads)
    assert "upload_legend_col, legend_col = st.columns(2, gap=\"small\")" in block
    assert '"type": "primary"' not in block  # Legendar NÃO é azul


def test_backlog_card_has_legendar_button_with_state_lock():
    block = APP_SOURCE.split("def _video_backlog_card_body(", 1)[1].split("return task_state", 1)[0]
    # trava estrita + override manual também no Backlog
    assert 'has_subtitles = bool(task.get("has_subtitles"))' in block
    assert '"Marcar como Legendado"' in block
    assert 'update_task(str(task["id"]), {"has_subtitles": True})' in block
    assert '"✓ Legendado"' in block
    assert '"Legendar"' in block
    # a acção marca a tarefa com o campo correcto
    assert '"action": "burn_subtitles_only"' in APP_SOURCE


# ---------------------------------------------------------------------------
# 4. 1.0.38 — limpeza única das flags adivinhadas + restantes correcções E2E
# ---------------------------------------------------------------------------


def test_cleanup_removes_guessed_flags_exactly_once(tmp_path, monkeypatch):
    """A limpeza 1.0.38 remove as flags ADIVINHADAS (todas as pré-1.0.38) e o
    marcador impede repetições — os carimbos DETERMINÍSTICOS de depois (uma
    queima real, um override) ficam intactos para sempre."""
    _storage(tmp_path, monkeypatch)
    from hermes_ui import domain

    storage.write_json("tasks.json", [
        {"id": "t_antiga_com_flag", "state": "done", "has_subtitles": True},
        {"id": "t_antiga_sem_flag", "state": "done"},
        {"id": "t_recente", "state": "done", "has_subtitles": False},
    ])
    removed = domain.cleanup_legacy_subtitle_flags()
    assert removed == 2  # as duas flags existentes saíram (sejam elas quais forem)
    tasks = {task["id"]: task for task in storage.read_json("tasks.json", [])}
    assert "has_subtitles" not in tasks["t_antiga_com_flag"]
    assert "has_subtitles" not in tasks["t_recente"]
    # a limpeza corre UMA vez: o marcador bloqueia novas passagens
    storage.write_json("tasks.json", [
        {"id": "t_queimada_depois", "state": "done", "has_subtitles": True},
    ])
    assert domain.cleanup_legacy_subtitle_flags() == 0
    tasks = {task["id"]: task for task in storage.read_json("tasks.json", [])}
    assert tasks["t_queimada_depois"].get("has_subtitles") is True


def test_cleanup_wired_at_both_boots():
    """A limpeza corre no arranque da UI E do worker (o primeiro a chegar
    executa; o marcador desarma o segundo)."""
    assert "cleanup_legacy_subtitle_flags()" in APP_SOURCE
    worker_boot = PIPELINE_SOURCE.split("def run_worker(", 1)[1].split("while True:", 1)[0]
    assert "cleanup_legacy_subtitle_flags()" in worker_boot


def test_legendar_payload_forces_worker_pickup():
    """1.0.37: o click limpa manual_start_required — a tarefa em to_do é
    apanhada pelo worker de imediato (o legado do Start retinha a fila)."""
    assert APP_SOURCE.count('"action": "burn_subtitles_only", "manual_start_required": False, "error": None') == 2


def test_interception_logs_immediately_before_the_normal_cascade():
    """A validação pede ver no terminal: a intercepção é logada antes de tudo."""
    block = PIPELINE_SOURCE.split("def _run_task(", 1)[1][:1400]
    assert "intercepção imediata" in block
    assert block.index("_mpt_runtime_log") < block.index("_run_burn_subtitles_only(task, settings)")


def test_burn_reports_visible_progress_in_the_card():
    """1.0.37: progresso visível — status em cada passo + progresso sintético
    60→90 durante o encode (o polling de 3s mostra-o a mover)."""
    burn_block = PIPELINE_SOURCE.split("def _run_burn_subtitles_only(", 1)[1].split("def _run_task(", 1)[0]
    assert 'video_helper_status="A preparar queima de legendas..."' in burn_block
    assert '"Queimando legendas com MoviePy' in burn_block
    assert "min(90, 60 + elapsed // 4)" in burn_block
    assert 'video_helper_status=f"Queimando legendas... {elapsed}s"' in burn_block


def test_burn_timeout_marks_failed_and_clears_action(tmp_path, monkeypatch):
    """O cenário dos 40 minutos: encode que não termina → failed com a acção
    limpa depois do timeout RÍGIDO, nunca doing eterno."""
    import time as _time

    _storage(tmp_path, monkeypatch)
    video = tmp_path / "final-1.mp4"
    video.write_bytes(b"mp4")
    script_md = tmp_path / "roteiro.md"
    script_md.write_text("# Título\nUma narração de teste para legendas.\n", encoding="utf-8")
    storage.write_json("tasks.json", [{
        "id": "t_lento",
        "state": "to_do",
        "stage": "video",
        "topic": "Tema",
        "action": "burn_subtitles_only",
        "artifacts": {"video": str(video), "script": str(script_md)},
        "generation_settings": {"voiceover_mode": "tts", "enable_subtitles": True},
    }])

    def slow_burn(video_path, text, config, burn_report=None, **kwargs):
        _time.sleep(5)  # mais lento que o timeout de 1s injectado
        return Path(video_path)

    import hermes_ui.text_to_images

    monkeypatch.setattr(hermes_ui.text_to_images, "burn_captions_on_video", slow_burn)
    monkeypatch.setattr(pipeline_worker, "_resolve_subtitle_font_path", lambda name, settings: str(tmp_path / "arial.ttf"))
    (tmp_path / "arial.ttf").write_bytes(b"font")
    monkeypatch.setattr(pipeline_worker, "BURN_SUBTITLES_TIMEOUT_SECONDS", 1)
    task = storage.read_json("tasks.json", [])[0]
    result = pipeline_worker._run_task(task)
    assert result["state"] == "failed"
    assert result.get("action") is None
    assert "excedeu" in str(result.get("error") or "")


def test_burn_success_returns_the_path_within_the_timeout(tmp_path, monkeypatch):
    """A via feliz do helper: queima rápida devolve o caminho dentro do tempo."""
    video = tmp_path / "v.mp4"
    video.write_bytes(b"mp4")
    monkeypatch.setattr(
        "hermes_ui.text_to_images.burn_captions_on_video",
        lambda video_path, text, config, burn_report=None, **kwargs: Path(video_path),
    )
    burned = pipeline_worker._run_burn_with_timeout(video, "texto", {"font_path": "f"}, timeout_seconds=10)
    assert burned == video
