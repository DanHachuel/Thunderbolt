"""Loader and validator for Remotion video blueprints.

Reads self-contained blueprint JSON files from storage/blueprints/ (seeded
from seed/blueprints/ on install). Each blueprint describes an LLM prompt,
output schema, style guide and Remotion composition mapping for a specific
video format (quiz, top-10, would-you-rather, etc.).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .storage import STORAGE

logger = logging.getLogger(__name__)

BLUEPRINTS_DIR = STORAGE / "blueprints"
SEED_BLUEPRINTS_DIR = Path(__file__).resolve().parents[1] / "seed" / "blueprints"

REQUIRED_FIELDS = (
    "blueprint_id",
    "composition_id",
    "fps",
    "width",
    "height",
    "system_instructions",
    "output_schema",
    "style_guide",
    "reference_examples",
    "generation_instructions",
    "remotion_mapping",
)


def _blueprint_files() -> list[Path]:
    """Return sorted blueprint JSON paths from the remotion seed naming convention."""
    if not BLUEPRINTS_DIR.is_dir():
        return []
    return sorted(
        path
        for path in BLUEPRINTS_DIR.glob("*.json")
        if path.name != "thumbnail_blueprint_pairs.json"
    )


def validate_blueprint(blueprint: dict[str, Any]) -> list[str]:
    """Return a list of validation errors; empty means valid."""
    if not isinstance(blueprint, dict):
        return ["Blueprint is not a JSON object"]
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in blueprint or blueprint[field] in (None, "", [], {}):
            errors.append(f"Missing required field: {field}")
    instructions = blueprint.get("system_instructions")
    if isinstance(instructions, dict):
        for key in ("role", "task_description"):
            if not str(instructions.get(key) or "").strip():
                errors.append(f"system_instructions.{key} is empty")
    remotion = blueprint.get("remotion_mapping")
    if isinstance(remotion, dict):
        if not str(remotion.get("composition_id") or "").strip():
            errors.append("remotion_mapping.composition_id is empty")
    for numeric in ("fps", "width", "height"):
        value = blueprint.get(numeric)
        if value is not None:
            try:
                int(value)
            except (TypeError, ValueError):
                errors.append(f"{numeric} must be an integer, got {value!r}")
    return errors


def list_blueprints() -> list[dict[str, Any]]:
    """Read all blueprint JSONs and return lightweight metadata for the UI."""
    metadata: list[dict[str, Any]] = []
    for path in _blueprint_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Blueprint %s is unreadable: %s", path.name, exc)
            continue
        errors = validate_blueprint(data)
        if errors:
            logger.warning("Blueprint %s failed validation: %s", path.name, "; ".join(errors))
            continue
        metadata.append({
            "blueprint_id": data["blueprint_id"],
            "version": data.get("version", ""),
            "domain": data.get("domain", ""),
            "composition_id": data["composition_id"],
            "fps": data["fps"],
            "width": data["width"],
            "height": data["height"],
            "file": path.name,
        })
    return metadata


def load_blueprint(blueprint_id: str) -> dict[str, Any]:
    """Load the full blueprint by blueprint_id. Raises FileNotFoundError."""
    for path in _blueprint_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("blueprint_id") == blueprint_id:
            return data
    raise FileNotFoundError(f"Blueprint not found: {blueprint_id}")


def find_placeholders(blueprint: dict[str, Any]) -> list[str]:
    """Extract {{placeholder}} tokens from all string fields of the blueprint."""
    import re

    text = json.dumps(blueprint, ensure_ascii=False)
    return sorted(set(re.findall(r"\{\{(\w+)\}\}", text)))


def render_blueprint_prompt(blueprint: dict[str, Any], values: dict[str, str]) -> dict[str, Any]:
    """Deep-copy the blueprint and substitute {{placeholders}} with values."""
    import copy
    import re

    resolved = copy.deepcopy(blueprint)

    def substitute(obj: Any) -> Any:
        if isinstance(obj, str):
            def repl(match: re.Match[str]) -> str:
                key = match.group(1)
                return str(values.get(key, match.group(0)))
            return re.sub(r"\{\{(\w+)\}\}", repl, obj)
        if isinstance(obj, dict):
            return {key: substitute(value) for key, value in obj.items()}
        if isinstance(obj, list):
            return [substitute(item) for item in obj]
        return obj

    return substitute(resolved)


def build_system_prompt(blueprint: dict[str, Any]) -> str:
    """Concatenate the blueprint's instruction blocks into the final system prompt."""
    instructions = blueprint.get("system_instructions") or {}
    parts: list[str] = []
    role = str(instructions.get("role") or "").strip()
    if role:
        parts.append(f"Role: {role}")
    task = str(instructions.get("task_description") or "").strip()
    if task:
        parts.append(f"Task: {task}")
    constraints = instructions.get("constraints") or []
    if constraints:
        parts.append("Constraints:\n" + "\n".join(f"- {c}" for c in constraints))
    critical = str(instructions.get("critical_instruction") or "").strip()
    if critical:
        parts.append(f"CRITICAL: {critical}")
    style = blueprint.get("style_guide") or {}
    if style:
        parts.append("Style guide:\n" + json.dumps(style, indent=2, ensure_ascii=False))
    examples = blueprint.get("reference_examples") or []
    if examples:
        parts.append("Reference examples:\n" + json.dumps(examples[:1], indent=2, ensure_ascii=False))
    gen = blueprint.get("generation_instructions") or {}
    if gen:
        parts.append("Generation instructions:\n" + json.dumps(gen, indent=2, ensure_ascii=False))
    schema = blueprint.get("output_schema") or {}
    if schema:
        parts.append("Output JSON schema (produce ONLY this JSON structure, no markdown fences):\n" + json.dumps(schema, indent=2, ensure_ascii=False))
    return "\n\n".join(parts)
