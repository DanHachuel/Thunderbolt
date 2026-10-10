"""Reintrodução do {{difficulty}} no formato quiz (0.9.78).

- o placeholder existe apenas no quiz (os outros 4 formatos ficam como na 0.9.77);
- o default vem de default_values.difficulty ("Average");
- o pipeline resolve-o só quando o formato o declara;
- a UI mostra o dropdown de dificuldade apenas para o quiz.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
SCHEMAS_DIR = ROOT / "packages" / "remotion" / "schemas"
QUIZ = json.loads((SCHEMAS_DIR / "quiz.schema.json").read_text(encoding="utf-8"))


def test_quiz_schema_contains_difficulty_placeholder():
    assert any("{{difficulty}}" in constraint for constraint in QUIZ["constraints"])


def test_quiz_schema_has_default_average():
    assert (QUIZ.get("default_values") or {}).get("difficulty") == "Average"
    calibration = QUIZ.get("difficulty_calibration") or {}
    assert sorted(calibration) == ["Average", "Easy", "Hard"]


def test_other_formats_do_not_gain_difficulty():
    for name in ("inspirational", "social_reel", "top_10", "would_you_rather"):
        raw = (SCHEMAS_DIR / f"{name}.schema.json").read_text(encoding="utf-8")
        assert "{{difficulty}}" not in raw, name


def _quiz_output() -> dict:
    """Output válido do quiz: reference_example expandido a 5 perguntas."""
    import copy

    example = copy.deepcopy(QUIZ.get("reference_example") or {})
    questions = [copy.deepcopy(item) for item in (example.get("questions") or [])]
    while len(questions) < 5:
        clone = copy.deepcopy(questions[len(questions) % len(questions)])
        clone["question"] = f"Question {len(questions) + 1}?"
        questions.append(clone)
    example["questions"] = questions
    return example


def test_pipeline_resolves_difficulty_for_quiz_only(tmp_path, monkeypatch):
    """O {{difficulty}} é injectado só quando o formato o declara (quiz);
    o default vem do default_values do formato."""
    from hermes_ui import creative_generation, pipeline_worker, storage
    from hermes_ui.blueprint_loader import find_placeholders, load_remotion_format

    root = tmp_path / "storage"
    monkeypatch.setattr(storage, "STORAGE", root)
    monkeypatch.setattr(storage, "STATE", root / "state")
    monkeypatch.setattr(storage, "BLUEPRINTS", root / "blueprints")
    monkeypatch.setattr(pipeline_worker, "STORAGE", root)
    storage.ensure_storage()

    channel = {"id": "c1", "name": "Canal", "language": "English"}
    monkeypatch.setattr(pipeline_worker, "_settings", lambda: {})
    monkeypatch.setattr(pipeline_worker, "_channel_for_task", lambda value: channel)
    monkeypatch.setattr(pipeline_worker, "_blueprint_for_channel", lambda value: {})
    monkeypatch.setattr(pipeline_worker, "get_remotion_status", lambda: {"available": True, "reasons": []})

    captured = {}

    def fake_chat_json(settings, system, user):
        captured["system"] = system
        captured["user"] = user
        return _quiz_output()

    monkeypatch.setattr(creative_generation, "_chat_json", fake_chat_json)
    monkeypatch.setattr(pipeline_worker, "_update", lambda task_id, **updates: {"id": task_id, **updates})
    monkeypatch.setattr(pipeline_worker, "synthesize_text_to_images_audio", lambda text, settings, voice, output_path: Path(output_path).write_bytes(b"mp3") or Path(output_path))
    monkeypatch.setattr(pipeline_worker, "run_remotion_render", lambda task_arg, video, composition_id, input_props, timeout_seconds=None, **kwargs: Path(video).write_bytes(b"mp4"))

    # quiz: difficulty resolvido com o valor escolhido pelo utilizador
    task = {
        "id": "video-quiz-diff",
        "topic": "Everyday science",
        "language": "en",
        "channel_id": channel["id"],
        "generation_settings": {"remotion_format_id": "quiz", "blueprint_values": {"topic": "Everyday science", "language": "English", "difficulty": "Hard"}},
        "artifacts": {},
    }
    pipeline_worker._run_remotion_blueprint(
        task, settings={}, channel=channel, topic="Everyday science", format_id="quiz",
        blueprint_values=task["generation_settings"]["blueprint_values"],
    )
    assert 'difficulty: "Hard"' in captured["user"]
    assert "specified in Hard" in captured["system"].replace("{{difficulty}}", "Hard")

    # quiz sem escolha: default "Average" do default_values do formato
    task2 = {**task, "id": "video-quiz-default", "generation_settings": {"remotion_format_id": "quiz", "blueprint_values": {"topic": "Everyday science", "language": "English"}}}
    pipeline_worker._run_remotion_blueprint(
        task2, settings={}, channel=channel, topic="Everyday science", format_id="quiz",
        blueprint_values=task2["generation_settings"]["blueprint_values"],
    )
    assert 'difficulty: "Average"' in captured["user"]

    # formato sem {{difficulty}} (social_reel): nada é injectado
    social_format = load_remotion_format("social_reel")
    assert "difficulty" not in find_placeholders(social_format)
    task3 = {
        "id": "video-social",
        "topic": "City life",
        "language": "en",
        "channel_id": channel["id"],
        "generation_settings": {"remotion_format_id": "social_reel", "blueprint_values": {"topic": "City life", "language": "English"}},
        "artifacts": {},
    }
    social_output = json.loads((SCHEMAS_DIR / "social_reel.schema.json").read_text(encoding="utf-8"))["reference_example"]

    def fake_social_chat(settings, system, user):
        captured["system"] = system
        captured["user"] = user
        return dict(social_output)

    monkeypatch.setattr(creative_generation, "_chat_json", fake_social_chat)
    pipeline_worker._run_remotion_blueprint(
        task3, settings={}, channel=channel, topic="City life", format_id="social_reel",
        blueprint_values=task3["generation_settings"]["blueprint_values"],
    )
    assert "difficulty:" not in captured["user"]


def test_ui_shows_difficulty_only_for_quiz():
    """O dropdown de dificuldade só existe no ramo do placeholder — aparece
    apenas quando o formato declara {{difficulty}} (quiz)."""
    form_block = APP_SOURCE.split("def render_video_generation_settings(", 1)[1]
    assert 'placeholder == "difficulty"' in form_block
    assert "difficulty_calibration" in form_block
    assert '"Average"' in form_block
    # os placeholders são dinâmicos: quem dita a visibilidade é o próprio formato
    assert "find_placeholders(format_document)" in form_block
