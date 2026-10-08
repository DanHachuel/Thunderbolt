"""Tests for the Remotion blueprint loader and Pydantic schemas."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_ui.blueprint_loader import (
    build_system_prompt,
    find_placeholders,
    load_blueprint,
    render_blueprint_prompt,
    validate_blueprint,
)
from hermes_ui.schemas import SCHEMAS


REMISSION_BLUEPRINT_IDS = (
    "inspirational_long_form",
    "quiz_videos",
    "social_media_reels",
    "top_10_videos",
    "would_you_rather",
)


def _load_seed_blueprint(blueprint_id: str) -> dict:
    seed_dir = Path(__file__).resolve().parents[1] / "seed" / "blueprints"
    for path in sorted(seed_dir.glob("*.json")):
        if path.name == "thumbnail_blueprint_pairs.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("blueprint_id") == blueprint_id:
            return data
    raise FileNotFoundError(f"Seed blueprint not found: {blueprint_id}")


class TestBlueprintLoader:
    def test_all_five_remotion_blueprints_exist_in_seed(self):
        found = set()
        for blueprint_id in REMISSION_BLUEPRINT_IDS:
            try:
                _load_seed_blueprint(blueprint_id)
                found.add(blueprint_id)
            except FileNotFoundError:
                pass
        assert found == set(REMISSION_BLUEPRINT_IDS), f"Faltam: {set(REMISSION_BLUEPRINT_IDS) - found}"

    def test_all_five_blueprints_pass_validation(self):
        for blueprint_id in REMISSION_BLUEPRINT_IDS:
            data = _load_seed_blueprint(blueprint_id)
            errors = validate_blueprint(data)
            assert errors == [], f"{blueprint_id}: {errors}"

    def test_all_five_blueprints_have_pydantic_schemas(self):
        for blueprint_id in REMISSION_BLUEPRINT_IDS:
            assert blueprint_id in SCHEMAS, f"Schema em falta: {blueprint_id}"

    def test_reference_examples_validate_against_schemas(self):
        for blueprint_id in REMISSION_BLUEPRINT_IDS:
            data = _load_seed_blueprint(blueprint_id)
            schema = SCHEMAS[blueprint_id]
            examples = data.get("reference_examples") or []
            for index, example in enumerate(examples[:1]):
                # O reference_example embrulha o output do LLM numa chave "output".
                output = example.get("output") or example
                try:
                    schema.model_validate(output)
                except Exception as exc:
                    pytest.fail(f"{blueprint_id} example {index} falha validação: {exc}")

    def test_find_placeholders(self):
        data = _load_seed_blueprint("quiz_videos")
        placeholders = find_placeholders(data)
        assert "language" in placeholders
        assert "difficulty" in placeholders

    def test_render_blueprint_prompt_substitutes_values(self):
        data = _load_seed_blueprint("quiz_videos")
        resolved = render_blueprint_prompt(data, {"topic": "Space", "language": "English", "difficulty": "Easy"})
        text = json.dumps(resolved, ensure_ascii=False)
        assert "{{topic}}" not in text
        assert "{{language}}" not in text
        assert "{{difficulty}}" not in text

    def test_build_system_prompt_contains_core_blocks(self):
        data = _load_seed_blueprint("quiz_videos")
        prompt = build_system_prompt(data)
        assert "Role:" in prompt
        assert "Task:" in prompt
        assert "Output JSON schema" in prompt


class TestSchemaValidation:
    def test_quiz_rejects_wrong_answer_range(self):
        from hermes_ui.schemas.quiz_videos import QuizQuestion

        with pytest.raises(Exception):
            QuizQuestion(
                question="What is 2+2?",
                answer1="4",
                answer2="3",
                answer3="5",
                answer4="6",
                correct_answer=99,
                durationInSeconds=5,
                revealDelaySeconds=3,
            )

    def test_would_you_rather_rejects_invalid_percentage(self):
        from hermes_ui.schemas.would_you_rather import WouldYouRatherQuestion

        with pytest.raises(Exception):
            WouldYouRatherQuestion(
                id="q1",
                option1_text="Fly",
                option1_image_prompt="A person flying",
                option2_text="Invisible",
                option2_image_prompt="A person invisible",
                option1_result=150,
                voiceover_text="Would you rather fly or be invisible?",
                durationInSeconds=8,
                thinkingDelaySeconds=3,
                revealDurationSeconds=3,
            )

    def test_top10_requires_exactly_10_items(self):
        from hermes_ui.schemas.top_10_videos import Top10VideosOutput

        with pytest.raises(Exception):
            Top10VideosOutput.model_validate({
                "subjectIdeas": ["a", "b", "c", "d", "e"],
                "title": "Test",
                "intro": {"voiceoverText": "Hello", "imagePrompt": "img", "durationInSeconds": 5},
                "ranking": [],
                "outro": {"voiceoverText": "Bye", "imagePrompt": "img", "durationInSeconds": 3},
            })
