"""Tests for Remotion format asset extraction, generation and injection (0.9.76)."""
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

FORMAT_IDS = ("inspirational", "quiz", "social_reel", "top_10", "would_you_rather")
SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "packages" / "remotion" / "schemas"


def _reference_output(format_id: str) -> dict:
    """O reference_example (estrutural) do formato em packages/remotion/schemas."""
    for path in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("format_id") == format_id:
            return dict(data.get("reference_example") or {})
    return {}


class TestExtractImagePrompts:
    def test_inspirational(self):
        out = _reference_output("inspirational")
        prompts = extract_image_prompts(out, "inspirational")
        assert len(prompts) >= 3
        assert all(p["prompt"] for p in prompts)

    def test_quiz_has_no_image_prompts(self):
        out = _reference_output("quiz")
        assert extract_image_prompts(out, "quiz") == []

    def test_social_reel(self):
        out = _reference_output("social_reel")
        prompts = extract_image_prompts(out, "social_reel")
        assert len(prompts) >= 4

    def test_top_10_includes_intro_and_outro(self):
        out = _reference_output("top_10")
        prompts = extract_image_prompts(out, "top_10")
        keys = [p["key"] for p in prompts]
        assert "intro" in keys
        assert "outro" in keys

    def test_would_you_rather_two_options_per_question(self):
        out = _reference_output("would_you_rather")
        prompts = extract_image_prompts(out, "would_you_rather")
        assert len(prompts) == 2  # 1 pergunta × 2 opções


class TestExtractTtsSegments:
    def test_inspirational(self):
        out = _reference_output("inspirational")
        segments = extract_tts_segments(out, "inspirational")
        assert len(segments) >= 3

    def test_quiz_includes_intro_and_outro(self):
        out = _reference_output("quiz")
        segments = extract_tts_segments(out, "quiz")
        keys = [s["key"] for s in segments]
        assert "intro" in keys
        assert "outro" in keys
        assert len(segments) == 3  # intro + 1 pergunta + outro

    def test_top_10(self):
        out = _reference_output("top_10")
        segments = extract_tts_segments(out, "top_10")
        keys = [s["key"] for s in segments]
        assert "intro" in keys and "outro" in keys

    def test_would_you_rather(self):
        out = _reference_output("would_you_rather")
        segments = extract_tts_segments(out, "would_you_rather")
        assert len(segments) >= 2  # pergunta + outro


class TestInjectAssets:
    def test_inspirational_injects_scene_assets(self):
        out = _reference_output("inspirational")
        first_key = out["scenes"][0]["id"]
        assets = {"images": {first_key: "/tmp/img.png"}, "audio": {first_key: "/tmp/audio.mp3"}}
        enriched = inject_assets(out, assets, "inspirational")
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
        out = _reference_output("quiz")
        enriched = inject_assets(out, {"images": {}, "audio": {}}, "quiz")
        assert enriched["topic"] == out["topic"]
        assert len(enriched["questions"]) == len(out["questions"])


class TestGenerateAssets:
    def test_generate_assets_with_mocked_providers(self, tmp_path, monkeypatch):
        from hermes_ui import blueprint_assets

        monkeypatch.setattr(blueprint_assets, "STORAGE", tmp_path / "storage")
        out = _reference_output("social_reel")

        image_provider = MagicMock(side_effect=lambda prompt: b"fake-png")
        tts_provider = MagicMock(side_effect=lambda text: b"fake-mp3")

        task = {"id": "test-format"}
        enriched = generate_assets(task, out, "social_reel", image_provider, tts_provider)

        assert image_provider.call_count >= 4
        assert tts_provider.call_count >= 4
        for scene in enriched["scenes"]:
            assert "imageUrl" in scene
            assert "audioUrl" in scene
