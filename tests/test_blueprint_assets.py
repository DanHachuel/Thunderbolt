"""Tests for blueprint asset extraction, generation and injection."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hermes_ui.blueprint_assets import (
    extract_image_prompts,
    extract_tts_segments,
    generate_assets,
    inject_assets,
)


REMISSION_IDS = ("inspirational_long_form", "quiz_videos", "social_media_reels", "top_10_videos", "would_you_rather")
SEED = Path(__file__).resolve().parents[1] / "seed" / "blueprints"


def _reference_output(blueprint_id: str) -> dict:
    for path in sorted(SEED.glob("*.json")):
        if path.name == "thumbnail_blueprint_pairs.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("blueprint_id") == blueprint_id:
            examples = data.get("reference_examples") or [{}]
            return (examples[0].get("output") or {})
    return {}


class TestExtractImagePrompts:
    def test_inspirational(self):
        out = _reference_output("inspirational_long_form")
        prompts = extract_image_prompts(out, "inspirational_long_form")
        assert len(prompts) >= 3
        assert all(p["prompt"] for p in prompts)

    def test_quiz_has_no_image_prompts(self):
        out = _reference_output("quiz_videos")
        prompts = extract_image_prompts(out, "quiz_videos")
        assert prompts == []

    def test_social_reels(self):
        out = _reference_output("social_media_reels")
        prompts = extract_image_prompts(out, "social_media_reels")
        assert len(prompts) >= 3

    def test_top10_includes_intro_and_outro(self):
        out = _reference_output("top_10_videos")
        prompts = extract_image_prompts(out, "top_10_videos")
        keys = [p["key"] for p in prompts]
        assert "intro" in keys
        assert "outro" in keys
        assert len(prompts) >= 12  # intro + 10 items + outro

    def test_would_you_rather_two_options_per_question(self):
        out = _reference_output("would_you_rather")
        prompts = extract_image_prompts(out, "would_you_rather")
        assert len(prompts) == 10  # 5 questions × 2 options


class TestExtractTtsSegments:
    def test_inspirational(self):
        out = _reference_output("inspirational_long_form")
        segments = extract_tts_segments(out, "inspirational_long_form")
        assert len(segments) >= 3

    def test_quiz_includes_intro_and_outro(self):
        out = _reference_output("quiz_videos")
        segments = extract_tts_segments(out, "quiz_videos")
        keys = [s["key"] for s in segments]
        assert "intro" in keys
        assert "outro" in keys

    def test_top10(self):
        out = _reference_output("top_10_videos")
        segments = extract_tts_segments(out, "top_10_videos")
        assert len(segments) >= 12  # intro + 10 items + outro

    def test_would_you_rather(self):
        out = _reference_output("would_you_rather")
        segments = extract_tts_segments(out, "would_you_rather")
        assert len(segments) >= 5


class TestInjectAssets:
    def test_inspirational_injects_scene_assets(self):
        out = _reference_output("inspirational_long_form")
        first_key = out["scenes"][0]["id"]
        assets = {
            "images": {first_key: "/tmp/img.png"},
            "audio": {first_key: "/tmp/audio.mp3"},
        }
        enriched = inject_assets(out, assets, "inspirational_long_form")
        assert enriched["scenes"][0]["imageUrl"] == "/tmp/img.png"
        assert enriched["scenes"][0]["audioUrl"] == "/tmp/audio.mp3"
        assert enriched["scenes"][0]["id"] == first_key  # structure intact

    def test_would_you_rather_injects_both_options(self):
        out = _reference_output("would_you_rather")
        qid = out["questions"][0]["id"]
        assets = {
            "images": {f"{qid}_option1": "/tmp/o1.png", f"{qid}_option2": "/tmp/o2.png"},
            "audio": {qid: "/tmp/audio.mp3"},
        }
        enriched = inject_assets(out, assets, "would_you_rather")
        assert enriched["questions"][0]["option1_imageUrl"] == "/tmp/o1.png"
        assert enriched["questions"][0]["option2_imageUrl"] == "/tmp/o2.png"
        assert enriched["questions"][0]["audioUrl"] == "/tmp/audio.mp3"

    def test_injection_does_not_remove_original_keys(self):
        out = _reference_output("quiz_videos")
        enriched = inject_assets(out, {"images": {}, "audio": {}}, "quiz_videos")
        assert enriched["topic"] == out["topic"]
        assert len(enriched["questions"]) == len(out["questions"])


class TestGenerateAssets:
    def test_generate_assets_with_mocked_providers(self, tmp_path, monkeypatch):
        from hermes_ui import blueprint_assets
        monkeypatch.setattr(blueprint_assets, "STORAGE", tmp_path / "storage")
        out = _reference_output("social_media_reels")

        image_provider = MagicMock(side_effect=lambda prompt: b"fake-png")
        tts_provider = MagicMock(side_effect=lambda text: b"fake-mp3")

        task = {"id": "test-blueprint"}
        enriched = generate_assets(task, out, "social_media_reels", image_provider, tts_provider)

        assert image_provider.call_count >= 3
        assert tts_provider.call_count >= 3
        for scene in enriched["scenes"]:
            assert "imageUrl" in scene
            assert "audioUrl" in scene
