"""Loader de Blueprints de personalidade e Formatos Remotion (0.9.76).

Separa dois conceitos que a 0.9.75 confundia:

- **Blueprint de personalidade** — define *quem o canal é* (tom, estilo,
  vocabulário, referências). Vive em `storage/blueprints/` (semeado de
  `seed/blueprints/`): MILITAR, FINANCE USA, Cocomelon, etc.
- **Formato Remotion** — schema técnico que define *o formato do JSON que o
  LLM deve produzir* para cada composição Remotion. Vive em
  `packages/remotion/schemas/*.schema.json`: quiz, social_reel, top_10,
  would_you_rather, inspirational.

O modo Remotion combina os dois; os restantes modos continuam a usar apenas
os blueprints de personalidade, exactamente como antes.
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
REMOTION_SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "packages" / "remotion" / "schemas"

REMOTION_FORMAT_REQUIRED_FIELDS = (
    "format_id",
    "composition_id",
    "fps",
    "width",
    "height",
    "constraints",
    "output_schema",
    "reference_example",
    "remotion_mapping",
)


def _is_remotion_format_document(data: Any) -> bool:
    """True para documentos de formato Remotion.

    Reconhece o formato novo (`format_id`) e o formato antigo da 0.9.75
    (`blueprint_id` + `composition_id`) — ambos têm de sair da biblioteca de
    blueprints de personalidade.
    """
    if not isinstance(data, dict):
        return False
    return "format_id" in data or ("blueprint_id" in data and "composition_id" in data)


def migrate_remotion_formats_out_of_storage() -> list[str]:
    """0.9.76: remove formatos Remotion que tenham ficado em storage/blueprints.

    Os formatos pertencem a `packages/remotion/schemas/`; cópias antigas na
    biblioteca de personalidades (raiz ou importados/) são apagadas com log.
    """
    removed: list[str] = []
    if not BLUEPRINTS_DIR.is_dir():
        return removed
    for path in sorted(BLUEPRINTS_DIR.rglob("*.json")):
        if path.name == "thumbnail_blueprint_pairs.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if _is_remotion_format_document(data):
            try:
                path.unlink()
                removed.append(str(path))
                logger.info("Formato Remotion removido de %s (vive em packages/remotion/schemas).", path)
            except OSError as exc:
                logger.warning("Não foi possível remover o formato de %s: %s", path, exc)
    return removed


# ---------------------------------------------------------------------------
# Blueprints de personalidade
# ---------------------------------------------------------------------------


def list_personality_blueprints() -> list[dict[str, Any]]:
    """Blueprints de personalidade (MILITAR, FINANCE USA, …) para os selectores.

    Ignora silenciosamente qualquer ficheiro de formato Remotion e apaga as
    cópias antigas que por ventura existam (migração 0.9.76).
    """
    migrate_remotion_formats_out_of_storage()
    result: list[dict[str, Any]] = []
    for path in list_blueprint_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if _is_remotion_format_document(data):
            continue
        result.append({
            "id": str(data.get("id") or path.stem),
            "name": str(data.get("name") or data.get("title") or path.stem),
            "file": path.name,
        })
    return result


def load_personality_blueprint(blueprint_id: str) -> dict[str, Any]:
    """Carrega um blueprint de personalidade por id. Raises FileNotFoundError."""
    wanted = str(blueprint_id or "").strip()
    for path in list_blueprint_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if _is_remotion_format_document(data):
            continue
        if str(data.get("id") or path.stem) == wanted:
            return data
    raise FileNotFoundError(f"Blueprint de personalidade não encontrado: {blueprint_id}")


# ---------------------------------------------------------------------------
# Formatos Remotion
# ---------------------------------------------------------------------------


def validate_remotion_format(format_def: dict[str, Any]) -> list[str]:
    """Devolve os erros de validação do formato (vazio = válido)."""
    if not isinstance(format_def, dict):
        return ["Formato não é um objecto JSON"]
    errors: list[str] = []
    for field in REMOTION_FORMAT_REQUIRED_FIELDS:
        if field not in format_def or format_def[field] in (None, "", [], {}):
            errors.append(f"Campo obrigatório em falta: {field}")
    for numeric in ("fps", "width", "height"):
        value = format_def.get(numeric)
        if value is not None:
            try:
                int(value)
            except (TypeError, ValueError):
                errors.append(f"{numeric} deve ser inteiro, obtido {value!r}")
    remotion = format_def.get("remotion_mapping")
    if isinstance(remotion, dict) and not str(remotion.get("composition_id") or "").strip():
        errors.append("remotion_mapping.composition_id vazio")
    return errors


def list_remotion_formats() -> list[dict[str, Any]]:
    """Metadados dos formatos em packages/remotion/schemas/*.schema.json."""
    if not REMOTION_SCHEMAS_DIR.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for path in sorted(REMOTION_SCHEMAS_DIR.glob("*.schema.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Formato Remotion %s ilegível: %s", path.name, exc)
            continue
        errors = validate_remotion_format(data)
        if errors:
            logger.warning("Formato Remotion %s inválido: %s", path.name, "; ".join(errors))
            continue
        result.append({
            "format_id": data["format_id"],
            "composition_id": data["composition_id"],
            "fps": data["fps"],
            "width": data["width"],
            "height": data["height"],
            "file": path.name,
        })
    return result


def load_remotion_format(format_id: str) -> dict[str, Any]:
    """Carrega o formato Remotion completo por format_id. Raises FileNotFoundError."""
    wanted = str(format_id or "").strip()
    if wanted and REMOTION_SCHEMAS_DIR.is_dir():
        for path in sorted(REMOTION_SCHEMAS_DIR.glob("*.schema.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and str(data.get("format_id") or "") == wanted:
                return data
    raise FileNotFoundError(f"Formato Remotion não encontrado: {format_id}")


# ---------------------------------------------------------------------------
# Placeholders e prompts (modo Remotion)
# ---------------------------------------------------------------------------


def find_placeholders(document: dict[str, Any]) -> list[str]:
    """Extrai os tokens {{placeholder}} de todos os campos de texto."""
    import re

    text = json.dumps(document, ensure_ascii=False)
    return sorted(set(re.findall(r"\{\{(\w+)\}\}", text)))


def render_blueprint_prompt(document: dict[str, Any], values: dict[str, str]) -> dict[str, Any]:
    """Deep-copy do documento com {{placeholders}} substituídos por values."""
    import copy
    import re

    resolved = copy.deepcopy(document)

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


def build_remotion_system_prompt(personality: dict[str, Any], format_def: dict[str, Any]) -> str:
    """System prompt do modo Remotion: personalidade do canal + formato técnico.

    Concatena o conteúdo do blueprint de personalidade (tom, estilo,
    vocabulário, regras) com os constraints e o output_schema do formato —
    nada mais. O LLM devolve apenas o JSON do formato.
    """
    parts: list[str] = []
    if personality:
        parts.append(
            "Channel personality blueprint — the channel's tone, style, vocabulary and rules below "
            "must be respected in every text you write (topic, voiceovers, questions, answers, labels):"
        )
        parts.append(json.dumps(personality, ensure_ascii=False, indent=2))
    else:
        parts.append(
            "No channel personality blueprint configured; write with a clear, engaging narrator tone "
            "appropriate to the topic."
        )
    parts.append(
        f"Output format: Remotion composition {format_def.get('composition_id', '?')} "
        f"({format_def.get('width', '?')}×{format_def.get('height', '?')} @ {format_def.get('fps', 30)}fps)."
    )
    constraints = format_def.get("constraints") or []
    if constraints:
        parts.append("Structural constraints:\n" + "\n".join(f"- {constraint}" for constraint in constraints))
    schema = format_def.get("output_schema") or {}
    if schema:
        parts.append("Output JSON schema (produce ONLY this JSON structure, no markdown fences):\n" + json.dumps(schema, indent=2, ensure_ascii=False))
    example = format_def.get("reference_example")
    if example:
        parts.append("Reference example (structure only, not content):\n" + json.dumps(example, indent=2, ensure_ascii=False))
    parts.append("CRITICAL: Return ONLY valid JSON matching output_schema. No markdown, no explanations, no text outside the JSON.")
    return "\n\n".join(parts)
