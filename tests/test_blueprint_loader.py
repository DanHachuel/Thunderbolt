"""Tests for the Remotion format loader, personality blueprints and prompts (0.9.76)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_ui import blueprint_loader
from hermes_ui.blueprint_loader import (
    build_remotion_system_prompt,
    find_placeholders,
    list_personality_blueprints,
    list_remotion_formats,
    load_personality_blueprint,
    load_remotion_format,
    render_blueprint_prompt,
    validate_remotion_format,
)
from hermes_ui.schemas import SCHEMAS

FORMAT_IDS = ("inspirational", "quiz", "social_reel", "top_10", "would_you_rather")
REPO = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO / "packages" / "remotion" / "schemas"


def _load_format(format_id: str) -> dict:
    return load_remotion_format(format_id)


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


class TestRemotionFormats:
    def test_list_remotion_formats_returns_5(self):
        formats = list_remotion_formats()
        assert sorted(item["format_id"] for item in formats) == sorted(FORMAT_IDS)

    def test_all_five_formats_pass_validation(self):
        for format_id in FORMAT_IDS:
            errors = validate_remotion_format(_load_format(format_id))
            assert errors == [], f"{format_id}: {errors}"

    def test_all_five_formats_have_pydantic_schemas(self):
        for format_id in FORMAT_IDS:
            assert format_id in SCHEMAS, f"Schema em falta: {format_id}"

    def test_reference_examples_validate_against_schemas(self):
        """O reference_example é estrutural (1-3 itens); expande ao mínimo do
        modelo para confirmar que o formato e o schema Pydantic estão alinhados."""
        import copy

        min_counts = {"quiz": ("questions", 5), "would_you_rather": ("questions", 5), "top_10": ("ranking", 10)}

        def _expand(example: dict, list_key: str, count: int) -> None:
            items = [copy.deepcopy(item) for item in (example.get(list_key) or [])]
            if not items:
                return
            while len(items) < count:
                clone = copy.deepcopy(items[len(items) % len(items)])
                if "rank" in clone:
                    clone["rank"] = len(items) + 1
                items.append(clone)
            example[list_key] = items

        for format_id in FORMAT_IDS:
            schema = SCHEMAS[format_id]
            example = copy.deepcopy(_load_format(format_id).get("reference_example") or {})
            if format_id in min_counts:
                _expand(example, *min_counts[format_id])
            if format_id == "top_10":
                ideas = [str(idea) for idea in (example.get("subjectIdeas") or [])]
                while len(ideas) < 5:
                    ideas.append(f"Subject idea {len(ideas) + 1}")
                example["subjectIdeas"] = ideas
            try:
                schema.model_validate(example)
            except Exception as exc:
                pytest.fail(f"{format_id} reference_example (expandido) falha validação: {exc}")

    def test_find_placeholders(self):
        """0.9.76: os formatos corrigidos usam {{language}}; o {{difficulty}}
        foi removido das novas versões dos schemas."""
        for format_id in FORMAT_IDS:
            placeholders = find_placeholders(_load_format(format_id))
            assert "language" in placeholders, format_id
        quiz_placeholders = find_placeholders(_load_format("quiz"))
        assert "difficulty" not in quiz_placeholders

    def test_render_blueprint_prompt_substitutes_values(self):
        resolved = render_blueprint_prompt(_load_format("quiz"), {"topic": "Space", "language": "English", "difficulty": "Easy"})
        text = json.dumps(resolved, ensure_ascii=False)
        assert "{{language}}" not in text
        assert "{{difficulty}}" not in text

    def test_validate_remotion_format_reports_missing_fields(self):
        errors = validate_remotion_format({"format_id": "x"})
        assert any("format_id" not in error for error in errors) or errors  # tem erros
        assert errors  # campo em falta é reportado

    def test_load_remotion_format_missing_raises(self):
        with pytest.raises(FileNotFoundError):
            load_remotion_format("nao_existe")


class TestPersonalityBlueprints:
    def test_list_personality_blueprints_excludes_formats(self, tmp_path, monkeypatch):
        root = _isolate_storage(tmp_path, monkeypatch)
        importados = root / "blueprints" / "importados"
        (importados / "MILITAR.json").write_text(json.dumps({"id": "militar", "name": "Canal Militar"}), encoding="utf-8")
        (importados / "FINANCE USA.json").write_text(json.dumps({"id": "finance-usa", "name": "FINANCE USA"}), encoding="utf-8")
        # formatos (novo e antigo estilo) na biblioteca de personalidades
        (importados / "quiz-fmt.json").write_text(json.dumps({"format_id": "quiz", "composition_id": "Quiz"}), encoding="utf-8")
        (importados / "old-bp.json").write_text(json.dumps({"blueprint_id": "quiz_videos", "composition_id": "Quiz"}), encoding="utf-8")

        listed = list_personality_blueprints()
        ids = {item["id"] for item in listed}
        assert "militar" in ids
        assert "finance-usa" in ids
        assert "quiz" not in ids
        assert "quiz_videos" not in ids

    def test_migration_removes_format_files_from_storage(self, tmp_path, monkeypatch):
        root = _isolate_storage(tmp_path, monkeypatch)
        importados = root / "blueprints" / "importados"
        (importados / "MILITAR.json").write_text(json.dumps({"id": "militar", "name": "Canal Militar"}), encoding="utf-8")
        (importados / "quiz-fmt.json").write_text(json.dumps({"format_id": "quiz", "composition_id": "Quiz"}), encoding="utf-8")
        (importados / "old-bp.json").write_text(json.dumps({"blueprint_id": "quiz_videos", "composition_id": "Quiz"}), encoding="utf-8")

        removed = blueprint_loader.migrate_remotion_formats_out_of_storage()

        assert len(removed) == 2
        assert (importados / "quiz-fmt.json").exists() is False
        assert (importados / "old-bp.json").exists() is False
        assert (importados / "MILITAR.json").exists()  # personalidade intacta

    def test_load_personality_blueprint(self, tmp_path, monkeypatch):
        root = _isolate_storage(tmp_path, monkeypatch)
        (root / "blueprints" / "importados" / "MILITAR.json").write_text(
            json.dumps({"id": "militar", "name": "Canal Militar", "niche": "militar"}), encoding="utf-8"
        )
        assert load_personality_blueprint("militar")["name"] == "Canal Militar"
        with pytest.raises(FileNotFoundError):
            load_personality_blueprint("inexistente")


class TestRemotionSystemPrompt:
    def test_combines_personality_and_format_sections(self):
        personality = {"id": "militar", "name": "Canal Militar", "niche": "militar"}
        format_def = _load_format("quiz")
        prompt = build_remotion_system_prompt(personality, format_def)
        # secção da personalidade
        assert "Canal Militar" in prompt
        assert "Channel personality blueprint" in prompt
        # secção do formato
        assert "Remotion composition Quiz" in prompt
        assert "Output JSON schema" in prompt
        assert "Return ONLY valid JSON" in prompt

    def test_without_personality_uses_neutral_tone(self):
        prompt = build_remotion_system_prompt({}, _load_format("quiz"))
        assert "No channel personality blueprint configured" in prompt
        assert "Remotion composition Quiz" in prompt
