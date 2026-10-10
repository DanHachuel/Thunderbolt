"""Loader de Blueprints do Thunderbolt (0.9.79).

Um blueprint é um blueprint. Não existem "tipos": MILITAR, FINANCE USA,
Cocomelon e os 5 Remotion (Quiz, Social Media Reels, Top 10, Would You
Rather, Inspirational Long-Form) são todos blueprints, vivem todos em
`seed/blueprints/` (copiados para `storage/blueprints/importados/` no arranque)
e aparecem todos nas mesmas listas. Se um blueprint tem `composition_id`,
o pipeline Remotion renderiza com essa composição e valida com o
`output_schema`; se não tem, o comportamento é o normal dos outros modos.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .storage import STORAGE, list_blueprint_files

logger = logging.getLogger(__name__)

BLUEPRINTS_DIR = STORAGE / "blueprints"
SEED_BLUEPRINTS_DIR = Path(__file__).resolve().parents[1] / "seed" / "blueprints"


def _blueprint_files() -> list[Path]:
    """Todos os blueprints: storage (raiz, importados, canais, nichos) + seed.

    Sem filtro, sem distinção, sem tipos — os seeds entram como fallback para
    que a lista esteja completa mesmo antes do arranque copiar para o storage.
    """
    paths: list[Path] = []
    seen_names: set[str] = set()
    for path in list_blueprint_files():
        seen_names.add(path.name)
        paths.append(path)
    if SEED_BLUEPRINTS_DIR.is_dir():
        for path in sorted(SEED_BLUEPRINTS_DIR.glob("*.json")):
            if path.name not in seen_names and path.name != "thumbnail_blueprint_pairs.json":
                paths.append(path)
    return paths


def list_blueprints() -> list[dict[str, Any]]:
    """Metadados de TODOS os blueprints, sem distinção de tipo."""
    result: list[dict[str, Any]] = []
    for path in _blueprint_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        result.append({
            "id": str(data.get("id") or path.stem),
            "name": str(data.get("name") or data.get("title") or path.stem),
            "composition_id": str(data.get("composition_id") or ""),
            "file": path.name,
        })
    return result


def load_blueprint(blueprint_id: str) -> dict[str, Any]:
    """Carrega o blueprint completo por id (campo id ou nome do ficheiro)."""
    wanted = str(blueprint_id or "").strip()
    for path in _blueprint_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and str(data.get("id") or path.stem) == wanted:
            return data
    raise FileNotFoundError(f"Blueprint não encontrado: {blueprint_id}")


# ---------------------------------------------------------------------------
# Placeholders e prompt — um blueprint, um prompt
# ---------------------------------------------------------------------------


def find_placeholders(blueprint: dict[str, Any]) -> list[str]:
    """Extrai os tokens {{placeholder}} de todos os campos de texto."""
    import re

    text = json.dumps(blueprint, ensure_ascii=False)
    return sorted(set(re.findall(r"\{\{(\w+)\}\}", text)))


def render_blueprint_prompt(blueprint: dict[str, Any], values: dict[str, str]) -> dict[str, Any]:
    """Deep-copy do blueprint com {{placeholders}} substituídos por values."""
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
    """System prompt de UM blueprint — os campos do próprio ficheiro, nada mais.

    Para blueprints com `output_schema` (Remotion): constraints estruturais,
    schema, exemplo de referência e calibração de dificuldade quando existem.
    """
    parts: list[str] = []
    constraints = blueprint.get("constraints") or []
    if constraints:
        parts.append("Constraints:\n" + "\n".join(f"- {constraint}" for constraint in constraints))
    calibration = blueprint.get("difficulty_calibration")
    if isinstance(calibration, dict) and calibration:
        parts.append("Difficulty calibration:\n" + json.dumps(calibration, indent=2, ensure_ascii=False))
    schema = blueprint.get("output_schema") or {}
    if schema:
        parts.append("Output JSON schema (produce ONLY this JSON structure, no markdown fences):\n" + json.dumps(schema, indent=2, ensure_ascii=False))
    example = blueprint.get("reference_example")
    if example:
        parts.append("Reference example (structure only, not content):\n" + json.dumps(example, indent=2, ensure_ascii=False))
    parts.append("CRITICAL: Return ONLY valid JSON matching output_schema. No markdown, no explanations, no text outside the JSON.")
    return "\n\n".join(parts)
