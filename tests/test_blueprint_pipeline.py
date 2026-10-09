"""Pipeline dos Blueprints Remotion (0.9.75) — docs/blueprints.md.

Cobre o fluxo especificado: LLM → validação Pydantic (1 retry) → assets →
render Remotion na composição do blueprint, mais deteção de indisponibilidade
e cancelamento. O happy-path corre end-to-end por _run_task com todos os
providers mockados.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_ui import creative_generation, pipeline_worker, storage
from hermes_ui.blueprint_loader import load_blueprint

ROOT = Path(__file__).resolve().parents[1]


def _quiz_output() -> dict:
    """Output válido do quiz: o reference_example do próprio seed."""
    blueprint = load_blueprint("quiz_videos")
    example = (blueprint.get("reference_examples") or [{}])[0]
    return dict(example.get("output") or {})


def _isolate(tmp_path, monkeypatch):
    root = tmp_path / "storage"
    monkeypatch.setattr(storage, "STORAGE", root)
    monkeypatch.setattr(storage, "STATE", root / "state")
    monkeypatch.setattr(storage, "BLUEPRINTS", root / "blueprints")
    monkeypatch.setattr(pipeline_worker, "STORAGE", root)
    storage.ensure_storage()
    return root


def _blueprint_task(tmp_path, **overrides):
    channel = {"id": "channel-bp", "name": "Canal Blueprint", "language": "English"}
    task = {
        "id": "video-bp",
        "state": "to_do",
        "stage": "script",
        "progress": 0,
        "topic": "Everyday science",
        "topic_source": "manual",
        "title": "",
        "style_wide": "remotion",
        "channel_id": channel["id"],
        "language": "en",
        "artifacts": {},
        "generation_settings": {
            "blueprint_id": "quiz_videos",
            "blueprint_values": {"topic": "Everyday science", "language": "English", "difficulty": "Average"},
        },
    }
    task.update(overrides)
    return channel, task


def test_blueprint_pipeline_happy_path(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    channel, task = _blueprint_task(tmp_path)
    storage.write_json("channels.json", [channel])
    storage.write_json("tasks.json", [task])
    video_path = pipeline_worker.STORAGE / "videos" / "video-bp-remotion-blueprint.mp4"
    thumbnail_path = tmp_path / "thumbnail.png"
    thumbnail_path.write_bytes(b"png")
    captured = {}

    monkeypatch.setattr(pipeline_worker, "_settings", lambda: {})
    monkeypatch.setattr(pipeline_worker, "_channel_for_task", lambda value: channel)
    monkeypatch.setattr(pipeline_worker, "_blueprint_for_channel", lambda value: {})
    monkeypatch.setattr(pipeline_worker, "get_remotion_status", lambda: {"available": True, "reasons": []})
    monkeypatch.setattr(creative_generation, "_chat_json", lambda settings, system, user: _quiz_output())
    monkeypatch.setattr(pipeline_worker, "generate_script_document", lambda *args, **kwargs: pytest.fail("o blueprint não gera roteiro Markdown"))
    monkeypatch.setattr(pipeline_worker, "generate_image_from_pool", lambda *args, **kwargs: pytest.fail("quiz não gera imagens"))

    def fake_synthesize(text, settings, voice, output_path):
        Path(output_path).write_bytes(b"mp3")
        return Path(output_path)

    monkeypatch.setattr(pipeline_worker, "synthesize_text_to_images_audio", fake_synthesize)

    def fake_render(task_arg, video, composition_id, input_props, timeout_seconds=None, **kwargs):
        captured["composition_id"] = composition_id
        captured["input_props"] = input_props
        Path(video).write_bytes(b"mp4")
        return {"ok": True}

    monkeypatch.setattr(pipeline_worker, "run_remotion_render", fake_render)
    monkeypatch.setattr(pipeline_worker, "generate_thumbnail_prompt", lambda *args, **kwargs: {"image_prompt": "thumb", "overlay_text": "QUIZ"})
    monkeypatch.setattr(pipeline_worker, "_generate_pipeline_thumbnail", lambda *args, **kwargs: thumbnail_path)
    monkeypatch.setattr(pipeline_worker, "upload_with_default_route", lambda *args, **kwargs: SimpleNamespace(ok=True, data={"uploaded": True}, message="ok"))

    result = pipeline_worker._run_task(task)

    assert result["state"] == "done"
    assert result["artifacts"]["video"] == str(video_path)
    assert result["artifacts"]["blueprint_json"]
    assert captured["composition_id"] == "Quiz"
    # o JSON validado chega como inputProps com os áudios injectados
    assert captured["input_props"]["topic"] == "Everyday science"
    assert len(captured["input_props"]["questions"]) == 5
    assert captured["input_props"]["questions"][0]["audioUrl"]
    assert captured["input_props"]["introAudioUrl"]
    # o título vem do tópico do blueprint, não de creative generation
    assert storage.read_json("tasks.json")[0]["title"] == "Everyday science"


def test_blueprint_pipeline_validation_retry(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    channel, task = _blueprint_task(tmp_path)
    storage.write_json("channels.json", [channel])
    storage.write_json("tasks.json", [task])

    monkeypatch.setattr(pipeline_worker, "_settings", lambda: {})
    monkeypatch.setattr(pipeline_worker, "_channel_for_task", lambda value: channel)
    monkeypatch.setattr(pipeline_worker, "_blueprint_for_channel", lambda value: {})
    monkeypatch.setattr(pipeline_worker, "get_remotion_status", lambda: {"available": True, "reasons": []})
    responses = iter([{**_quiz_output(), "questions": []}, _quiz_output()])
    monkeypatch.setattr(creative_generation, "_chat_json", lambda settings, system, user: next(responses))
    monkeypatch.setattr(pipeline_worker, "synthesize_text_to_images_audio", lambda text, settings, voice, output_path: Path(output_path).write_bytes(b"mp3") or Path(output_path))
    monkeypatch.setattr(pipeline_worker, "run_remotion_render", lambda task_arg, video, composition_id, input_props, timeout_seconds=None, **kwargs: Path(video).write_bytes(b"mp4"))

    video_path, llm_json = pipeline_worker._run_remotion_blueprint(
        task,
        settings={},
        channel=channel,
        topic="Everyday science",
        blueprint_id="quiz_videos",
        blueprint_values={"topic": "Everyday science", "language": "English", "difficulty": "Average"},
    )

    assert video_path.is_file()
    assert len(llm_json["questions"]) == 5


def test_blueprint_pipeline_remotion_unavailable(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    channel, task = _blueprint_task(tmp_path)

    monkeypatch.setattr(pipeline_worker, "_settings", lambda: {})
    monkeypatch.setattr(pipeline_worker, "_channel_for_task", lambda value: channel)
    monkeypatch.setattr(pipeline_worker, "_blueprint_for_channel", lambda value: {})
    monkeypatch.setattr(pipeline_worker, "get_remotion_status", lambda: {"available": False, "reasons": ["node em falta", "chromium em falta"]})

    with pytest.raises(pipeline_worker.PipelineError, match="Remotion indisponível: node em falta"):
        pipeline_worker._run_remotion_blueprint(
            task,
            settings={},
            channel=channel,
            topic="Everyday science",
            blueprint_id="quiz_videos",
            blueprint_values={},
        )


def test_blueprint_pipeline_cancel_during_assets(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    channel, task = _blueprint_task(tmp_path)

    monkeypatch.setattr(pipeline_worker, "_settings", lambda: {})
    monkeypatch.setattr(pipeline_worker, "_channel_for_task", lambda value: channel)
    monkeypatch.setattr(pipeline_worker, "_blueprint_for_channel", lambda value: {})
    monkeypatch.setattr(pipeline_worker, "get_remotion_status", lambda: {"available": True, "reasons": []})
    monkeypatch.setattr(creative_generation, "_chat_json", lambda settings, system, user: _quiz_output())
    monkeypatch.setattr(pipeline_worker, "_task_by_id", lambda task_id: {"state": "blocked", "id": task_id})

    # A tarefa em blocked interrompe o pipeline com PipelineStopped — seja no
    # cancel_check dos assets, seja na transição bloqueada do _update.
    with pytest.raises(pipeline_worker.PipelineStopped):
        pipeline_worker._run_remotion_blueprint(
            task,
            settings={},
            channel=channel,
            topic="Everyday science",
            blueprint_id="quiz_videos",
            blueprint_values={"topic": "Everyday science", "language": "English", "difficulty": "Average"},
        )


def test_blueprint_pipeline_requires_topic(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    channel, task = _blueprint_task(tmp_path, topic="")
    task["generation_settings"]["blueprint_values"] = {}

    monkeypatch.setattr(pipeline_worker, "_settings", lambda: {})
    monkeypatch.setattr(pipeline_worker, "_channel_for_task", lambda value: channel)
    monkeypatch.setattr(pipeline_worker, "_blueprint_for_channel", lambda value: {})
    monkeypatch.setattr(pipeline_worker, "get_remotion_status", lambda: {"available": True, "reasons": []})

    with pytest.raises(pipeline_worker.PipelineError, match="exige um tópico"):
        pipeline_worker._run_remotion_blueprint(
            task,
            settings={},
            channel=channel,
            topic="",
            blueprint_id="quiz_videos",
            blueprint_values={},
        )