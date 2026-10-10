"""O {{difficulty}} do blueprint Quiz (0.9.78, mantido na 0.9.79).

- o placeholder existe apenas no blueprint Quiz (os outros 4 Remotion não o têm);
- o default vem de default_values.difficulty ("Average");
- o pipeline resolve-o quando o blueprint o declara;
- a UI mostra o dropdown de dificuldade apenas quando o blueprint tem {{difficulty}}.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
SEED_DIR = ROOT / "seed" / "blueprints"
QUIZ_BLUEPRINT_ID = "Blueprint Remotion - Quiz Videos"
QUIZ = json.loads((SEED_DIR / f"{QUIZ_BLUEPRINT_ID}.json").read_text(encoding="utf-8"))
OTHER_REMOTION = (
    "Blueprint Remotion - Inspirational Long-Form Videos",
    "Blueprint Remotion - Social Media Reels",
    "Blueprint Remotion - Top 10 Ranking Videos",
    "Blueprint Remotion - Would You Rather",
)


def _quiz_output() -> dict:
    """Output válido do quiz: reference_example expandido a 5 perguntas."""
    example = copy.deepcopy(QUIZ.get("reference_example") or {})
    questions = [copy.deepcopy(item) for item in (example.get("questions") or [])]
    while len(questions) < 5:
        clone = copy.deepcopy(questions[len(questions) % len(questions)])
        clone["question"] = f"Question {len(questions) + 1}?"
        questions.append(clone)
    example["questions"] = questions
    return example


def test_quiz_schema_contains_difficulty_placeholder():
    assert any("{{difficulty}}" in constraint for constraint in QUIZ["constraints"])


def test_quiz_schema_has_default_average():
    assert (QUIZ.get("default_values") or {}).get("difficulty") == "Average"
    calibration = QUIZ.get("difficulty_calibration") or {}
    assert sorted(calibration) == ["Average", "Easy", "Hard"]


def test_other_blueprints_do_not_gain_difficulty():
    for name in OTHER_REMOTION:
        raw = (SEED_DIR / f"{name}.json").read_text(encoding="utf-8")
        assert "{{difficulty}}" not in raw, name


def test_pipeline_resolves_difficulty_for_quiz_only(tmp_path, monkeypatch):
    """O {{difficulty}} é injectado só quando o blueprint o declara (quiz);
    o default vem do default_values do blueprint."""
    from hermes_ui import creative_generation, pipeline_worker, storage
    from hermes_ui.blueprint_loader import find_placeholders, load_blueprint

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
        "generation_settings": {"blueprint_id": QUIZ_BLUEPRINT_ID, "blueprint_values": {"topic": "Everyday science", "language": "English", "difficulty": "Hard"}},
        "artifacts": {},
    }
    pipeline_worker._run_remotion_blueprint(
        task, settings={}, channel=channel, topic="Everyday science", blueprint_id=QUIZ_BLUEPRINT_ID,
        blueprint_values=task["generation_settings"]["blueprint_values"],
    )
    assert 'difficulty: "Hard"' in captured["user"]
    assert "difficulty" in find_placeholders(load_blueprint(QUIZ_BLUEPRINT_ID))

    # quiz sem escolha: default "Average" do default_values do blueprint
    task2 = {**task, "id": "video-quiz-default", "generation_settings": {"blueprint_id": QUIZ_BLUEPRINT_ID, "blueprint_values": {"topic": "Everyday science", "language": "English"}}}
    pipeline_worker._run_remotion_blueprint(
        task2, settings={}, channel=channel, topic="Everyday science", blueprint_id=QUIZ_BLUEPRINT_ID,
        blueprint_values=task2["generation_settings"]["blueprint_values"],
    )
    assert 'difficulty: "Average"' in captured["user"]

    # blueprint sem {{difficulty}} (Social Media Reels): nada é injectado
    social_id = "Blueprint Remotion - Social Media Reels"
    social_document = load_blueprint(social_id)
    assert "difficulty" not in find_placeholders(social_document)
    social_output = dict(social_document.get("reference_example") or {})

    def fake_social_chat(settings, system, user):
        captured["system"] = system
        captured["user"] = user
        return social_output

    monkeypatch.setattr(creative_generation, "_chat_json", fake_social_chat)
    task3 = {
        "id": "video-social",
        "topic": "City life",
        "language": "en",
        "channel_id": channel["id"],
        "generation_settings": {"blueprint_id": social_id, "blueprint_values": {"topic": "City life", "language": "English"}},
        "artifacts": {},
    }
    pipeline_worker._run_remotion_blueprint(
        task3, settings={}, channel=channel, topic="City life", blueprint_id=social_id,
        blueprint_values=task3["generation_settings"]["blueprint_values"],
    )
    assert "difficulty:" not in captured["user"]


def test_ui_shows_difficulty_only_for_quiz():
    """O dropdown de dificuldade só existe no ramo do placeholder — aparece
    apenas quando o blueprint escolhido declara {{difficulty}} (quiz)."""
    form_block = APP_SOURCE.split("def render_video_generation_settings(", 1)[1]
    assert 'placeholder == "difficulty"' in form_block
    assert "difficulty_calibration" in form_block
    assert '"Average"' in form_block
    # os placeholders são dinâmicos: quem dita a visibilidade é o próprio blueprint
    assert "find_placeholders(blueprint_document)" in form_block
