"""Botão «Legendar» com trava de estado (1.0.33).

Flag ``has_subtitles`` nas tarefas: gravada no fim da geração normal (True
quando as legendas foram queimadas — MPT nativo/`_apply_mpt_captions` ou
montagens locais com config resolvível; False quando desligadas/sem narração/
sem config). O botão «Legendar» fica DESABILITADO quando ``has_subtitles=True``
(trava: nunca re-legenda um vídeo já legendado). O worker intercepta
``action="burn_subtitles_only"`` e queima as legendas com MoviePy sem
re-renderizar (1-2 min vs 10+ de um «Refazer Vídeo»).
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
# 1. Flag has_subtitles: computada correctamente pelas condições da tarefa
# ---------------------------------------------------------------------------


def _task(**extra):
    base = {
        "id": "t1",
        "topic": "Tema",
        "channel_id": "",
        "generation_settings": {"voiceover_mode": "tts", "enable_subtitles": True},
    }
    base.update(extra)
    return base


def test_has_subtitles_true_when_subtitles_enabled_and_config_resolves(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    # config resolvível: font_path presente → config não é None
    settings = {"resource": {"font_dir": str(tmp_path)}}
    monkeypatch.setattr(pipeline_worker, "_resolve_subtitle_font_path", lambda name, s: str(tmp_path / "arial.ttf"))
    task = _task()
    (tmp_path / "arial.ttf").write_bytes(b"font")
    assert pipeline_worker._task_has_subtitles(task, settings) is True


def test_has_subtitles_false_when_voiceover_mode_is_none():
    task = _task(generation_settings={"voiceover_mode": "none", "enable_subtitles": True})
    assert pipeline_worker._task_has_subtitles(task, {}) is False


def test_has_subtitles_false_when_subtitles_disabled():
    task = _task(generation_settings={"voiceover_mode": "tts", "enable_subtitles": False})
    assert pipeline_worker._task_has_subtitles(task, {}) is False


def test_has_subtitles_false_when_config_unresolvable(monkeypatch):
    # sem fonte resolvível → _subtitle_config_for_task devolve None → False
    monkeypatch.setattr(pipeline_worker, "_resolve_subtitle_font_path", lambda name, settings: None)
    task = _task(generation_settings={"voiceover_mode": "tts", "enable_subtitles": True})
    assert pipeline_worker._task_has_subtitles(task, {}) is False


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

    def fake_burn(video_path, text, config, **kwargs):
        captured["text"] = text
        captured["config"] = config
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
    _storage(tmp_path, monkeypatch)
    storage.write_json("tasks.json", [{
        "id": "t_sem_video",
        "state": "to_do",
        "action": "burn_subtitles_only",
        "artifacts": {},
        "generation_settings": {},
    }])
    task = storage.read_json("tasks.json", [])[0]
    with pytest.raises(pipeline_worker.PipelineError, match="não tem um vídeo"):
        pipeline_worker._run_task(task)


# ---------------------------------------------------------------------------
# 2. Worker: a flag é gravada no fim normal da geração de vídeo
# ---------------------------------------------------------------------------


def test_normal_pipeline_persists_has_subtitles_flag():
    """Source-structure: o _update com video_ready=True também grava
    has_subtitles (computado pela mesma função que decide queimar)."""
    assert "has_subtitles=_task_has_subtitles(task, settings)" in PIPELINE_SOURCE
    assert "def _task_has_subtitles(" in PIPELINE_SOURCE


def test_burn_subtitles_only_intercepted_before_normal_cascade():
    """Source-structure: a intercepção acontece no TOPO do _run_task."""
    block = PIPELINE_SOURCE.split("def _run_task(", 1)[1].split("def ", 1)[0][:1200]
    assert 'task.get("action")' in block
    assert '"burn_subtitles_only"' in block
    assert "_run_burn_subtitles_only(task, settings)" in block


# ---------------------------------------------------------------------------
# 3. UI: o botão «Legendar» com trava de estado
# ---------------------------------------------------------------------------


def test_youtube_card_has_legendar_button_with_state_lock():
    """O card tem o botão com as TRÊS estados: sem vídeo (disabled), já
    legendado (✓ Legendado disabled), pronto (ativo)."""
    block = APP_SOURCE.split("def _youtube_task_card_body(", 1)[1].split("return _catalog_task_state(task)", 1)[0]
    assert 'has_subtitles = bool(task.get("has_subtitles"))' in block
    assert '"✓ Legendado"' in block
    assert "disabled=True" in block
    assert '"Legendar"' in block
    # o Upload está em coluna (mesmo tamanho dos downloads)
    assert "upload_legend_col, legend_col = st.columns(2, gap=\"small\")" in block
    assert '"type": "primary"' not in block  # Legendar NÃO é azul


def test_backlog_card_has_legendar_button_with_state_lock():
    block = APP_SOURCE.split("def _video_backlog_card_body(", 1)[1].split("return task_state", 1)[0]
    assert 'has_subtitles = bool(task.get("has_subtitles"))' in block
    assert '"✓ Legendado"' in block
    assert '"Legendar"' in block
    # a acção marca a tarefa com o campo correcto
    assert '"action": "burn_subtitles_only"' in APP_SOURCE
