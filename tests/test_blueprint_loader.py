"""Loader de Blueprints (0.9.79) — um blueprint é um blueprint.

MILITAR, FINANCE USA e os 5 Remotion (Quiz, Social Media Reels, Top 10,
Would You Rather, Inspirational Long-Form) são todos blueprints: mesma pasta
(seed/blueprints/), mesma lista, mesmo dropdown. A única diferença funcional:
os Remotion têm composition_id e output_schema.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from hermes_ui import blueprint_loader
from hermes_ui.blueprint_loader import (
    build_system_prompt,
    find_placeholders,
    list_blueprints,
    load_blueprint,
    render_blueprint_prompt,
)
from hermes_ui.schemas import SCHEMAS

REPO = Path(__file__).resolve().parents[1]
SEED_DIR = REPO / "seed" / "blueprints"

REMOTION_FILES = {
    "Blueprint Remotion - Quiz Videos": "Quiz",
    "Blueprint Remotion - Social Media Reels": "SocialReel",
    "Blueprint Remotion - Top 10 Ranking Videos": "Top10",
    "Blueprint Remotion - Would You Rather": "WouldYouRather",
    "Blueprint Remotion - Inspirational Long-Form Videos": "InspirationalVideo",
}
# SCHEMAS é indexada pelo composition_id de cada blueprint Remotion.
COMPOSITION_SCHEMAS = {
    "InspirationalVideo": "InspirationalLongFormOutput",
    "Quiz": "QuizVideosOutput",
    "SocialReel": "SocialMediaReelsOutput",
    "Top10": "Top10VideosOutput",
    "WouldYouRather": "WouldYouRatherOutput",
}


def _load_seed_blueprint(stem: str) -> dict:
    return json.loads((SEED_DIR / f"{stem}.json").read_text(encoding="utf-8"))


def _isolate_storage(tmp_path, monkeypatch) -> Path:
    from hermes_ui import storage

    root = tmp_path / "storage"
    monkeypatch.setattr(storage, "STORAGE", root)
    monkeypatch.setattr(storage, "STATE", root / "state")
    monkeypatch.setattr(storage, "BLUEPRINTS", root / "blueprints")
    monkeypatch.setattr(blueprint_loader, "BLUEPRINTS_DIR", root / "blueprints")
    importados = root / "blueprints" / "importados"
    importados.mkdir(parents=True, exist_ok=True)
    (root / "state").mkdir(parents=True, exist_ok=True)
    return root


class TestSingleBlueprintList:
    def test_list_blueprints_includes_all_five_remotion(self, tmp_path, monkeypatch):
        root = _isolate_storage(tmp_path, monkeypatch)
        importados = root / "blueprints" / "importados"
        # os 5 Remotion chegam ao storage como todos os outros (seed → importados)
        for stem in REMOTION_FILES:
            shutil_copy = (SEED_DIR / f"{stem}.json").read_text(encoding="utf-8")
            (importados / f"{stem}.json").write_text(shutil_copy, encoding="utf-8")
        (importados / "MILITAR.json").write_text(json.dumps({"id": "militar", "name": "Canal Militar"}), encoding="utf-8")

        listed = {item["id"] for item in list_blueprints()}
        assert set(REMOTION_FILES) <= listed
        assert "militar" in listed

    def test_list_blueprints_includes_seed_fallback_before_seeding(self, tmp_path, monkeypatch):
        """Storage vazio: os seeds entram como fallback — lista completa."""
        _isolate_storage(tmp_path, monkeypatch)
        listed = {item["id"] for item in list_blueprints()}
        assert set(REMOTION_FILES) <= listed

    def test_load_blueprint_by_file_stem_and_by_id(self, tmp_path, monkeypatch):
        root = _isolate_storage(tmp_path, monkeypatch)
        importados = root / "blueprints" / "importados"
        (importados / "MILITAR.json").write_text(json.dumps({"id": "militar", "name": "Canal Militar"}), encoding="utf-8")

        assert load_blueprint("militar")["name"] == "Canal Militar"
        quiz = load_blueprint("Blueprint Remotion - Quiz Videos")
        assert quiz["composition_id"] == "Quiz"
        with pytest.raises(FileNotFoundError):
            load_blueprint("inexistente")

    def test_remotion_blueprints_have_composition_id_and_output_schema(self):
        for stem, composition_id in REMOTION_FILES.items():
            data = _load_seed_blueprint(stem)
            assert data["composition_id"] == composition_id
            assert data["output_schema"]
            assert data["reference_example"]
            assert "format_id" not in data


class TestSchemas:
    def test_schemas_are_keyed_by_composition_id(self):
        for composition_id, model_name in COMPOSITION_SCHEMAS.items():
            assert SCHEMAS[composition_id].__name__ == model_name

    def test_reference_examples_validate_against_composition_schemas(self):
        """O reference_example é estrutural (1-3 itens); expande ao mínimo do
        modelo para confirmar que blueprint e schema Pydantic estão alinhados."""
        min_counts = {"Quiz": ("questions", 5), "WouldYouRather": ("questions", 5), "Top10": ("ranking", 10)}

        for stem, composition_id in REMOTION_FILES.items():
            schema = SCHEMAS[composition_id]
            example = copy.deepcopy(_load_seed_blueprint(stem).get("reference_example") or {})
            if composition_id in min_counts:
                list_key, count = min_counts[composition_id]
                items = [copy.deepcopy(item) for item in (example.get(list_key) or [])]
                if items:
                    while len(items) < count:
                        clone = copy.deepcopy(items[len(items) % len(items)])
                        if "rank" in clone:
                            clone["rank"] = len(items) + 1
                        items.append(clone)
                    example[list_key] = items
            if composition_id == "Top10":
                ideas = [str(idea) for idea in (example.get("subjectIdeas") or [])]
                while len(ideas) < 5:
                    ideas.append(f"Subject idea {len(ideas) + 1}")
                example["subjectIdeas"] = ideas
            try:
                schema.model_validate(example)
            except Exception as exc:
                pytest.fail(f"{stem} reference_example (expandido) falha validação: {exc}")


class TestPlaceholdersAndPrompt:
    def test_find_placeholders(self):
        quiz = _load_seed_blueprint("Blueprint Remotion - Quiz Videos")
        placeholders = find_placeholders(quiz)
        assert "language" in placeholders
        assert "difficulty" in placeholders

    def test_render_blueprint_prompt_substitutes_values(self):
        quiz = _load_seed_blueprint("Blueprint Remotion - Quiz Videos")
        resolved = render_blueprint_prompt(quiz, {"topic": "Space", "language": "English", "difficulty": "Hard"})
        text = json.dumps(resolved, ensure_ascii=False)
        assert "{{language}}" not in text
        assert "{{difficulty}}" not in text

    def test_build_system_prompt_uses_only_the_blueprint_fields(self):
        quiz = _load_seed_blueprint("Blueprint Remotion - Quiz Videos")
        prompt = build_system_prompt(quiz)
        assert "Constraints:" in prompt
        assert "Output JSON schema" in prompt
        assert "Reference example" in prompt
        assert "Difficulty calibration" in prompt
        assert "Return ONLY valid JSON" in prompt
        # um blueprint, um prompt: sem secções de "personalidade" ou "formato"
        assert "Channel personality blueprint" not in prompt
        assert "Output format: Remotion composition" not in prompt
