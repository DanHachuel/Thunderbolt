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
    legendado (✓ Legendado disabled), pronto (ativo). 1.0.37: a trava usa a
    flag COM inferência retroactiva (tarefas antigas sem a chave)."""
    block = APP_SOURCE.split("def _youtube_task_card_body(", 1)[1].split("return _catalog_task_state(task)", 1)[0]
    assert "has_subtitles = _ensure_task_subtitles_flag(task, state)" in block
    assert '"✓ Legendado"' in block
    assert "disabled=True" in block
    assert '"Legendar"' in block
    # o Upload está em coluna (mesmo tamanho dos downloads)
    assert "upload_legend_col, legend_col = st.columns(2, gap=\"small\")" in block
    assert '"type": "primary"' not in block  # Legendar NÃO é azul


def test_backlog_card_has_legendar_button_with_state_lock():
    block = APP_SOURCE.split("def _video_backlog_card_body(", 1)[1].split("return task_state", 1)[0]
    assert "has_subtitles = _ensure_task_subtitles_flag(task, task_state)" in block
    assert '"✓ Legendado"' in block
    assert '"Legendar"' in block
    # a acção marca a tarefa com o campo correcto
    assert '"action": "burn_subtitles_only"' in APP_SOURCE


# ---------------------------------------------------------------------------
# 4. 1.0.37 — correção E2E: inferência para tarefas antigas, timeout rígido,
#    progresso visível e pickup garantido
# ---------------------------------------------------------------------------


def test_old_task_without_flag_infers_from_generation_settings():
    """Cenário reportado: tarefa ANTIGA sem a flag — o vídeo saiu com legendas
    quando as legendas estavam activas nas definições da tarefa."""
    from app import main as app_main

    # sem a chave + legendas activas + narração → vídeo tem legendas
    assert app_main._task_subtitles_flag({"generation_settings": {"voiceover_mode": "tts", "enable_subtitles": True}}) is True
    # sem a chave + legendas desligadas → sem legendas
    assert app_main._task_subtitles_flag({"generation_settings": {"voiceover_mode": "tts", "enable_subtitles": False}}) is False
    # sem a chave + sem narração → sem legendas por definição
    assert app_main._task_subtitles_flag({"generation_settings": {"voiceover_mode": "none", "enable_subtitles": True}}) is False
    # a chave EXPLÍCITA vence a inferência
    assert app_main._task_subtitles_flag({"has_subtitles": False, "generation_settings": {"enable_subtitles": True}}) is False
    assert app_main._task_subtitles_flag({"has_subtitles": True, "generation_settings": {"enable_subtitles": False}}) is True


def test_ensure_task_subtitles_flag_persists_retroactively_for_done_tasks(tmp_path, monkeypatch):
    """Retro-migração: a inferência é GRAVADA no tasks.json (write-once) para
    tarefas done — o estado do botão deixa de depender do cálculo."""
    _storage(tmp_path, monkeypatch)
    storage.write_json("tasks.json", [{
        "id": "t_antiga",
        "state": "done",
        "artifacts": {"video": str(tmp_path / "v.mp4")},
        "generation_settings": {"voiceover_mode": "tts", "enable_subtitles": True},
    }])
    task = storage.read_json("tasks.json", [])[0]
    from app import main as app_main

    flag = app_main._ensure_task_subtitles_flag(task, "done")
    assert flag is True
    persisted = storage.read_json("tasks.json", [])[0]
    assert persisted.get("has_subtitles") is True
    # tarefa em curso não é retro-migrada (a flag só faz sentido no done)
    storage.write_json("tasks.json", [{
        "id": "t_curso",
        "state": "doing",
        "generation_settings": {"voiceover_mode": "tts", "enable_subtitles": True},
    }])
    task_doing = storage.read_json("tasks.json", [])[0]
    assert app_main._ensure_task_subtitles_flag(task_doing, "doing") is True
    assert "has_subtitles" not in storage.read_json("tasks.json", [])[0]


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

    def slow_burn(video_path, text, config, **kwargs):
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
        lambda video_path, text, config, **kwargs: Path(video_path),
    )
    burned = pipeline_worker._run_burn_with_timeout(video, "texto", {"font_path": "f"}, timeout_seconds=10)
    assert burned == video
