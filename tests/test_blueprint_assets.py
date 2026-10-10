"""Asset generation for Remotion blueprints (0.9.79: keyed by composition_id)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from hermes_ui.blueprint_assets import (
    extract_image_prompts,
    extract_tts_segments,
    generate_assets,
    inject_assets,
)

COMPOSITION_IDS = ("InspirationalVideo", "Quiz", "SocialReel", "Top10", "WouldYouRather")
SEED_DIR = Path(__file__).resolve().parents[1] / "seed" / "blueprints"
BLUEPRINT_FILES = {
    "InspirationalVideo": "Blueprint Remotion - Inspirational Long-Form Videos",
    "Quiz": "Blueprint Remotion - Quiz Videos",
    "SocialReel": "Blueprint Remotion - Social Media Reels",
    "Top10": "Blueprint Remotion - Top 10 Ranking Videos",
    "WouldYouRather": "Blueprint Remotion - Would You Rather",
}


def _reference_output(composition_id: str) -> dict:
    stem = BLUEPRINT_FILES[composition_id]
    data = json.loads((SEED_DIR / f"{stem}.json").read_text(encoding="utf-8"))
    return dict(data.get("reference_example") or {})


class TestExtractImagePrompts:
    def test_inspirational(self):
        out = _reference_output("InspirationalVideo")
        prompts = extract_image_prompts(out, "InspirationalVideo")
        assert len(prompts) >= 3
        assert all(p["prompt"] for p in prompts)

    def test_quiz_has_no_image_prompts(self):
        out = _reference_output("Quiz")
        assert extract_image_prompts(out, "Quiz") == []

    def test_social_reel(self):
        out = _reference_output("SocialReel")
        prompts = extract_image_prompts(out, "SocialReel")
        assert len(prompts) >= 4

    def test_top_10_includes_intro_and_outro(self):
        out = _reference_output("Top10")
        prompts = extract_image_prompts(out, "Top10")
        keys = [p["key"] for p in prompts]
        assert "intro" in keys
        assert "outro" in keys

    def test_would_you_rather_two_options_per_question(self):
        out = _reference_output("WouldYouRather")
        prompts = extract_image_prompts(out, "WouldYouRather")
        assert len(prompts) == 2  # 1 pergunta × 2 opções


class TestExtractTtsSegments:
    def test_inspirational(self):
        out = _reference_output("InspirationalVideo")
        segments = extract_tts_segments(out, "InspirationalVideo")
        assert len(segments) >= 3

    def test_quiz_includes_intro_and_outro(self):
        out = _reference_output("Quiz")
        segments = extract_tts_segments(out, "Quiz")
        keys = [s["key"] for s in segments]
        assert "intro" in keys
        assert "outro" in keys
        assert len(segments) == 3  # intro + 1 pergunta + outro

    def test_top_10(self):
        out = _reference_output("Top10")
        segments = extract_tts_segments(out, "Top10")
        keys = [s["key"] for s in segments]
        assert "intro" in keys and "outro" in keys

    def test_would_you_rather(self):
        out = _reference_output("WouldYouRather")
        segments = extract_tts_segments(out, "WouldYouRather")
        assert len(segments) >= 2  # pergunta + outro


class TestInjectAssets:
    def test_inspirational_injects_scene_assets(self):
        out = _reference_output("InspirationalVideo")
        first_key = out["scenes"][0]["id"]
        assets = {"images": {first_key: "/tmp/img.png"}, "audio": {first_key: "/tmp/audio.mp3"}}
        enriched = inject_assets(out, assets, "InspirationalVideo")
        assert enriched["scenes"][0]["imageUrl"] == "/tmp/img.png"
        assert enriched["scenes"][0]["audioUrl"] == "/tmp/audio.mp3"
        assert enriched["scenes"][0]["id"] == first_key  # structure intact

    def test_would_you_rather_injects_both_options(self):
        out = _reference_output("WouldYouRather")
        qid = out["questions"][0]["id"]
        assets = {
            "images": {f"{qid}_option1": "/tmp/o1.png", f"{qid}_option2": "/tmp/o2.png"},
            "audio": {qid: "/tmp/audio.mp3"},
        }
        enriched = inject_assets(out, assets, "WouldYouRather")
        assert enriched["questions"][0]["option1_imageUrl"] == "/tmp/o1.png"
        assert enriched["questions"][0]["option2_imageUrl"] == "/tmp/o2.png"
        assert enriched["questions"][0]["audioUrl"] == "/tmp/audio.mp3"

    def test_injection_does_not_remove_original_keys(self):
        out = _reference_output("Quiz")
        enriched = inject_assets(out, {"images": {}, "audio": {}}, "Quiz")
        assert enriched["topic"] == out["topic"]
        assert len(enriched["questions"]) == len(out["questions"])


class TestGenerateAssets:
    def test_generate_assets_with_mocked_providers(self, tmp_path, monkeypatch):
        from hermes_ui import blueprint_assets

        monkeypatch.setattr(blueprint_assets, "STORAGE", tmp_path / "storage")
        out = _reference_output("SocialReel")

        image_provider = MagicMock(side_effect=lambda prompt: b"fake-png")
        tts_provider = MagicMock(side_effect=lambda text: b"fake-mp3")

        task = {"id": "test-blueprint"}
        enriched = generate_assets(task, out, "SocialReel", image_provider, tts_provider)

        assert image_provider.call_count >= 4
        assert tts_provider.call_count >= 4
        for scene in enriched["scenes"]:
            assert "imageUrl" in scene
            assert "audioUrl" in scene
