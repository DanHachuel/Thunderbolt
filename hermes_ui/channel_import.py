"""Helpers for importing YouTube channel registrations from spreadsheets.

The spreadsheet is intentionally treated as a human-authored document rather
than a database export: headers and values are normalised semantically, common
Portuguese/English variants are accepted, and catalog-backed values are
resolved to the application's canonical identifiers before persistence.
"""

from __future__ import annotations

from datetime import date, datetime, time
from difflib import SequenceMatcher
from io import BytesIO
import math
import re
import unicodedata
from copy import copy
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd

from .languages import language_code


CHANNEL_TEMPLATE_COLUMNS: tuple[str, ...] = (
    "URL canal",
    "Nome canal",
    "Handle canal",
    "Narrador/ voz padrão",
    "Idioma",
    "Nicho",
    "Blueprint Padrão",
    "Estilo Wide",
    "Activo ",
    "Descrição",
    "Conta Google do Documento deste Canal",
    "Automação Ligada ",
    "Horário diário (HH:MM)",
    "DELEGATED_SESSION_ID",
    "Duração Padrão Vídeos (Min)",
)


_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "url": ("url canal", "url", "link canal", "link", "youtube url", "youtube link", "channel url"),
    "name": ("nome canal", "nome", "nome do canal", "channel name", "name"),
    "handle": ("handle canal", "handle", "identificador canal", "youtube handle", "channel handle"),
    "voice": ("narrador voz padrão", "narrador voz padrao", "narrador", "voz padrão", "voz padrao", "voz", "voice"),
    "language": ("idioma", "lingua", "language", "lang"),
    "niche": ("nicho", "niche", "tema", "categoria", "category"),
    "blueprint": ("blueprint padrão", "blueprint padrao", "blueprint", "modelo blueprint", "blueprint name"),
    "style_wide": ("estilo wide", "estilo", "wide style", "video style", "style"),
    "active": ("activo", "ativo", "activa", "ativa", "active", "enabled"),
    "description": ("descrição", "descricao", "description", "sobre o canal", "channel description"),
    "google_account": (
        "conta google do documento deste canal",
        "conta google",
        "google account",
        "gmail",
        "email google",
        "e mail google",
    ),
    "automation_on": ("automação ligada", "automacao ligada", "automação", "automacao", "automation", "automation on"),
    "automation_time": ("horário diário hh mm", "horario diario hh mm", "horário diário", "horario diario", "automation time", "schedule"),
    "delegated_session_id": ("delegated session id", "delegated_session_id", "delegated session", "session id"),
    "duration_minutes": (
        "duração padrão vídeos min",
        "duracao padrao videos min",
        "duração padrão vídeos",
        "duracao padrao videos",
        "duração vídeos min",
        "video duration minutes",
        "duration minutes",
    ),
}


def _strip_accents(value: Any) -> str:
    text = str(value or "")
    return "".join(char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char))


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _strip_accents(value).casefold())


def _semantic_key(value: Any) -> str:
    """Return a comparison key that ignores catalog naming conventions.

    For example, ``finanças``, ``blueprint_finanças`` and
    ``Blueprint Canal Finanças`` all become ``financas``.
    """
    compact = _key(value)
    for generic in ("blueprints", "blueprint", "canal", "channel", "padrao", "default", "modelo"):
        compact = compact.replace(generic, "")
    return compact


def _header_match(header: Any) -> str | None:
    normalized = _key(header)
    if not normalized:
        return None
    aliases: dict[str, str] = {}
    for field, values in _FIELD_ALIASES.items():
        for alias in values:
            aliases[_key(alias)] = field
    if normalized in aliases:
        return aliases[normalized]
    # Spreadsheet authors often add a unit or a harmless prefix/suffix.
    ranked: list[tuple[float, str]] = []
    for alias, field in aliases.items():
        if alias and (alias in normalized or normalized in alias):
            ranked.append((min(len(alias), len(normalized)) / max(len(alias), len(normalized)), field))
    if ranked:
        return max(ranked)[1]
    return None


def parse_channel_workbook(file_content: bytes, filename: str = "channels.xlsx") -> tuple[list[dict[str, Any]], list[str]]:
    """Read the first worksheet and return normalised source rows.

    Blank rows are discarded. Unknown columns are ignored and reported so a
    user can still import a workbook containing extra operational columns.
    """
    suffix = str(filename or "").lower().rsplit(".", 1)[-1] if "." in str(filename) else "xlsx"
    engine = "xlrd" if suffix == "xls" else "openpyxl"
    try:
        frame = pd.read_excel(BytesIO(file_content), sheet_name=0, dtype=object, engine=engine)
    except ImportError as exc:
        raise ValueError("Para ficheiros .xls, instale o suporte xlrd; para .xlsx, use o formato Excel moderno (.xlsx).") from exc
    except Exception as exc:
        raise ValueError(f"Não foi possível ler a planilha Excel: {exc}") from exc

    warnings: list[str] = []
    field_by_column: dict[Any, str] = {}
    for column in frame.columns:
        field = _header_match(column)
        if field is None:
            warnings.append(f"Coluna ignorada: {str(column).strip() or '(sem nome)'}")
            continue
        if field in field_by_column.values():
            warnings.append(f"Coluna duplicada ignorada para {field}: {str(column).strip()}")
            continue
        field_by_column[column] = field

    if not any(field in field_by_column.values() for field in ("url", "name", "handle")):
        expected = ", ".join(("URL canal", "Nome canal", "Handle canal"))
        raise ValueError(f"A planilha precisa de pelo menos uma coluna de identificação: {expected}.")

    rows: list[dict[str, Any]] = []
    for source_index, (_, record) in enumerate(frame.iterrows(), start=2):
        if all(not _text(value) for value in record.tolist()):
            continue
        row: dict[str, Any] = {field: record[column] for column, field in field_by_column.items()}
        row["_source_row"] = source_index
        normalized = normalize_channel_row(row)
        # The public template contains pre-filled defaults such as False and
        # 10 minutes. They do not make a row a channel registration.
        if not any(normalized.get(field) for field in ("url", "name", "handle")):
            continue
        rows.append(normalized)
    return rows, warnings


def normalize_handle(value: Any) -> str:
    raw = _text(value)
    if not raw:
        return ""
    match = re.search(r"(?:youtube\.com/)?@([A-Za-z0-9_.-]+)", raw, flags=re.IGNORECASE)
    if match:
        return f"@{match.group(1)}"
    return raw if raw.startswith("@") else f"@{raw}"


def _normalise_boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    raw = _strip_accents(_text(value)).casefold()
    if not raw:
        return None
    if raw in {"1", "true", "t", "yes", "y", "sim", "s", "ativo", "activa", "ativa", "ligado", "ligada", "on", "x"}:
        return True
    if raw in {"0", "false", "f", "no", "n", "nao", "inativo", "inactiva", "inativa", "desligado", "desligada", "off"}:
        return False
    if raw.endswith(".0") and raw[:-2] in {"0", "1"}:
        return raw[:-2] == "1"
    return None


def _normalise_time(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%H:%M")
    if isinstance(value, time):
        return value.strftime("%H:%M")
    raw = _text(value)
    if not raw:
        return ""
    match = re.search(r"\b([01]?\d|2[0-3])\s*[:hH]\s*([0-5]\d)\b", raw)
    if match:
        return f"{int(match.group(1)):02d}:{int(match.group(2)):02d}"
    return raw


def _normalise_duration(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return float(value.hour * 60 + value.minute) or None
    if isinstance(value, time):
        return float(value.hour * 60 + value.minute) or None
    raw = _text(value)
    if not raw:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:min|m|minutes?)?", raw, flags=re.IGNORECASE)
    if match:
        try:
            parsed = float(match.group(1).replace(",", "."))
            return parsed if parsed > 0 else None
        except ValueError:
            return None
    return None


def _normalise_style(value: Any) -> str:
    raw = _strip_accents(_text(value)).casefold()
    if not raw:
        return ""
    if raw in {"only_music", "only music", "apenas musica", "audio only", "so audio"}:
        return "only_music"
    if raw in {"text_to_images", "text-to-images", "montage: text-to-images"}:
        return "text_to_images"
    if raw in {"google_images", "google imagem api", "montage: google imagem api"}:
        return "google_images"
    if raw == "remotion":
        return "remotion"
    if raw in {"music_clips", "music clips", "clipes de musica"}:
        return "music_clips"
    if any(token in raw for token in ("musica", "music", "audio only", "so audio")):
        return "music"
    if any(token in raw for token in ("full", "ia", "ai", "gerado", "artificial")):
        return "full_ia"
    if any(token in raw for token in ("pexels", "pixabay", "stock", "banco", "material")):
        return "pexels"
    return _text(value)


def normalize_channel_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Convert raw spreadsheet values into the application's field vocabulary."""
    normalized: dict[str, Any] = {
        "url": _text(row.get("url")),
        "name": _text(row.get("name")),
        "handle": normalize_handle(row.get("handle")),
        "voice": _text(row.get("voice")),
        "language": _text(row.get("language")),
        "niche": _text(row.get("niche")),
        "blueprint": _text(row.get("blueprint")),
        "style_wide": _normalise_style(row.get("style_wide")),
        "active": _normalise_boolean(row.get("active")),
        "description": _text(row.get("description")),
        "google_account": _text(row.get("google_account")),
        "automation_on": _normalise_boolean(row.get("automation_on")),
        "automation_time": _normalise_time(row.get("automation_time")),
        "delegated_session_id": _text(row.get("delegated_session_id")),
        "duration_minutes": _normalise_duration(row.get("duration_minutes")),
    }
    if "_source_row" in row:
        normalized["_source_row"] = row["_source_row"]
    return normalized


def resolve_blueprint(value: Any, catalog: Sequence[tuple[str, str]]) -> str:
    """Resolve a human label or filename-like value to a Blueprint id."""
    raw = _text(value)
    if not raw:
        return ""
    raw_key = _key(raw)
    raw_semantic = _semantic_key(raw)
    candidates = [(str(identifier), str(label)) for identifier, label in catalog if str(identifier).strip()]
    for identifier, label in candidates:
        if raw_key in {_key(identifier), _key(label)}:
            return identifier
    if raw_semantic:
        semantic_matches = [(identifier, label) for identifier, label in candidates if raw_semantic in {_semantic_key(identifier), _semantic_key(label)}]
        if len(semantic_matches) == 1:
            return semantic_matches[0][0]
        if semantic_matches:
            return max(semantic_matches, key=lambda item: SequenceMatcher(None, raw_semantic, _semantic_key(item[1])).ratio())[0]
    scored: list[tuple[float, str]] = []
    for identifier, label in candidates:
        score = max(SequenceMatcher(None, raw_key, _key(identifier)).ratio(), SequenceMatcher(None, raw_key, _key(label)).ratio())
        if score >= 0.72:
            scored.append((score, identifier))
    if scored:
        return max(scored)[1]
    return raw


def resolve_voice(value: Any, catalog: Iterable[str]) -> str:
    raw = _text(value)
    if not raw:
        return ""
    options = [str(item) for item in catalog if str(item).strip()]
    raw_key = _key(raw)
    for option in options:
        option_key = _key(option)
        if raw_key == option_key or raw_key in option_key or option_key in raw_key:
            return option
    scored = [(SequenceMatcher(None, raw_key, _key(option)).ratio(), option) for option in options]
    best = max(scored, default=(0.0, ""))
    return best[1] if best[0] >= 0.72 else raw


def resolve_google_account(value: Any, accounts: Iterable[Mapping[str, Any]]) -> tuple[str, str]:
    """Resolve an email, id or display label to ``(id, email)``."""
    raw = _text(value)
    if not raw:
        return "", ""
    raw_key = _key(raw)
    candidates: list[tuple[str, str, str]] = []
    for account in accounts:
        identifier = _text(account.get("id"))
        if not identifier:
            continue
        email = _text(account.get("email"))
        label = _text(account.get("label"))
        candidates.append((identifier, email, label))
        if raw_key in {_key(identifier), _key(email), _key(label)}:
            return identifier, email
    scored = []
    for identifier, email, label in candidates:
        score = max(SequenceMatcher(None, raw_key, _key(email)).ratio(), SequenceMatcher(None, raw_key, _key(label)).ratio())
        scored.append((score, identifier, email))
    best = max(scored, default=(0.0, "", ""))
    return (best[1], best[2]) if best[0] >= 0.78 else ("", raw)


def _canonical_url(value: Any) -> str:
    raw = _text(value)
    if not raw:
        return ""
    if not re.match(r"^https?://", raw, flags=re.IGNORECASE):
        raw = f"https://{raw}"
    try:
        parsed = urlsplit(raw)
        query = [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True) if key.casefold() not in {"utm_source", "utm_medium", "utm_campaign", "si"}]
        return urlunsplit((parsed.scheme.casefold(), parsed.netloc.casefold(), parsed.path.rstrip("/").casefold(), urlencode(query), ""))
    except ValueError:
        return _key(raw)


def _identity_text(value: Any) -> str:
    return _key(value)


def channel_is_duplicate(candidate: Mapping[str, Any], existing: Mapping[str, Any]) -> bool:
    """Return true when two records identify the same channel.

    Handle, canonical URL and YouTube id are strong identifiers. A name is a
    fallback only when one side has no handle, avoiding false positives for
    two channels that happen to share a common name.
    """
    candidate_id = _key(candidate.get("youtube_channel_id") or candidate.get("youtube_id"))
    existing_id = _key(existing.get("youtube_channel_id") or existing.get("youtube_id"))
    if candidate_id and existing_id and candidate_id == existing_id:
        return True
    candidate_handle = _identity_text(candidate.get("handle"))
    existing_handle = _identity_text(existing.get("handle"))
    if candidate_handle and existing_handle and candidate_handle == existing_handle:
        return True
    candidate_url = _canonical_url(candidate.get("url"))
    existing_url = _canonical_url(existing.get("url"))
    if candidate_url and existing_url and candidate_url == existing_url:
        return True
    candidate_name = _identity_text(candidate.get("name"))
    existing_name = _identity_text(existing.get("name"))
    return bool(candidate_name and existing_name and candidate_name == existing_name and not (candidate_handle and existing_handle and candidate_handle != existing_handle))


def find_duplicate_channel(candidate: Mapping[str, Any], channels: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    return next((channel for channel in channels if isinstance(channel, Mapping) and channel_is_duplicate(candidate, channel)), None)


def build_channel_template_xlsx() -> bytes:
    """Build a fresh, formatted workbook using the public template columns."""
    frame = pd.DataFrame([{column: "" for column in CHANNEL_TEMPLATE_COLUMNS} for _ in range(20)])
    frame["Automação Ligada "] = False
    frame["Activo "] = True
    frame["Horário diário (HH:MM)"] = "00:00"
    frame["Duração Padrão Vídeos (Min)"] = 10
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="Canais YouTube")
        worksheet = writer.book["Canais YouTube"]
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions
        for cell in worksheet[1]:
            font = copy(cell.font)
            font.bold = True
            font.color = "FFFFFF"
            cell.font = font
            fill = copy(cell.fill)
            fill.fill_type = "solid"
            fill.fgColor = "1F4E78"
            cell.fill = fill
        widths = {column: max(18, min(42, len(column) + 4)) for column in CHANNEL_TEMPLATE_COLUMNS}
        widths["Descrição"] = 48
        widths["URL canal"] = 38
        for index, column in enumerate(CHANNEL_TEMPLATE_COLUMNS, start=1):
            worksheet.column_dimensions[chr(64 + index) if index <= 26 else worksheet.cell(1, index).column_letter].width = widths[column]
    return output.getvalue()


__all__ = [
    "CHANNEL_TEMPLATE_COLUMNS",
    "build_channel_template_xlsx",
    "channel_is_duplicate",
    "find_duplicate_channel",
    "normalize_channel_row",
    "parse_channel_workbook",
    "resolve_blueprint",
    "resolve_google_account",
    "resolve_voice",
]
