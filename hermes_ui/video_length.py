"""Shared video-length estimation and channel override helpers."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

WORDS_PER_MINUTE = 150
DEFAULT_AVERAGE_VIDEO_TIME = "20:00"
DEFAULT_TIKTOK_AVERAGE_VIDEO_TIME = "01:20"
AVERAGE_VIDEO_TIME_KEY = "average_video_time"
AVERAGE_VIDEO_WORD_COUNT_KEY = "average_video_word_count"


def default_average_video_time(channel: dict[str, Any] | None = None) -> str:
    """Return the platform-specific default duration for a channel."""
    platform = str((channel or {}).get("platform") or "").strip().casefold()
    return DEFAULT_TIKTOK_AVERAGE_VIDEO_TIME if platform == "tiktok" else DEFAULT_AVERAGE_VIDEO_TIME


def channel_video_time_value(channel: dict[str, Any]) -> str:
    """Return the card value, migrating only the historical twelve-minute default."""
    default_time = default_average_video_time(channel)
    value = str(channel.get(AVERAGE_VIDEO_TIME_KEY) or "").strip()
    configured_words = str(channel.get(AVERAGE_VIDEO_WORD_COUNT_KEY) or "").strip()
    if value == "00:12" and configured_words in {"", "0", "1800"}:
        return default_time
    return value or default_time


def valid_hhmm(value: Any) -> bool:
    """Keep the historical helper name while validating a MM:SS duration."""
    match = re.fullmatch(r"\s*(\d{1,3}):(\d{2})\s*", str(value or ""))
    if not match:
        return False
    minutes, seconds = int(match.group(1)), int(match.group(2))
    return minutes >= 0 and 0 <= seconds <= 59


def minutes_from_hhmm(value: Any) -> float:
    """Convert a stored MM:SS duration to fractional minutes."""
    if not valid_hhmm(value):
        return 0
    minutes, seconds = (int(part) for part in str(value).strip().split(":"))
    return minutes + seconds / 60


def hhmm_from_minutes(value: Any) -> str:
    try:
        total_seconds = max(0, round(float(value) * 60))
    except (TypeError, ValueError):
        total_seconds = 0
    return f"{total_seconds // 60:02d}:{total_seconds % 60:02d}"


def _numbers(value: Any) -> list[int]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [int(value)] if value > 0 else []
    return [int(item.replace(",", "")) for item in re.findall(r"(?<![\w])\d[\d,.]*(?![\w])", str(value or "")) if int(item.replace(",", "").replace(".", "")) > 0]


def _configured_word_count(value: Any, key: str = "") -> int:
    """Find an explicit word target, or convert an explicit character target."""
    if isinstance(value, dict):
        for child_key, child in value.items():
            normalized = str(child_key).casefold().replace("_", " ").replace("-", " ")
            if any(token in normalized for token in ("word", "words", "palavra", "palavras")):
                numbers = _numbers(child)
                if numbers:
                    return max(numbers) if len(numbers) > 1 else numbers[0]
            result = _configured_word_count(child, str(child_key))
            if result:
                return result
        return 0
    if isinstance(value, list):
        normalized_key = key.casefold().replace("_", " ").replace("-", " ")
        if any(token in normalized_key for token in ("character", "caracter", "char length", "length requirement")):
            numbers = [number for child in value for number in _numbers(child)]
            if numbers:
                return max(1, round((sum(numbers) / len(numbers)) / 6))
        for child in value:
            result = _configured_word_count(child, key)
            if result:
                return result
        return 0
    text = str(value or "")
    normalized_key = key.casefold().replace("_", " ").replace("-", " ")
    if any(token in normalized_key for token in ("word", "words", "palavra", "palavras")):
        numbers = _numbers(text)
        if numbers:
            return max(numbers) if len(numbers) > 1 else numbers[0]
    if any(token in normalized_key for token in ("character", "caracter", "char length", "length requirement")):
        numbers = _numbers(text)
        if numbers:
            return max(1, round((sum(numbers) / len(numbers)) / 6))
    return 0


def explicit_word_count(blueprint: Any = None, prompt_master: str = "") -> int:
    """Return only an explicit target; never count the instructions themselves."""
    result = _configured_word_count(blueprint)
    if result:
        return result
    matches = re.findall(r"(?:at least|minimum of|around|approximately|exactly|entre|mínimo de|cerca de|aproximadamente)\s+(\d[\d,.]*)\s+(?:words|word|palavras|palavra)", prompt_master, flags=re.IGNORECASE)
    if matches:
        return max(1, int(matches[-1].replace(",", "").replace(".", "")))
    return 0


def channel_video_length(channel: dict[str, Any], blueprint: Any = None, prompt_master: str = "") -> tuple[int, str, str]:
    """Return (word_count, mm:ss, source), preferring channel override over defaults.

    1.0.61 - REGRA INVIOLAVEL (AGENTS.md) aplicada A LETRA. Ate aqui um canal
    com o tempo vazio/``00:00`` caía nas regras de contagem do BLUEPRINT
    (``strict_character_range``/``character_length`` convertidos em palavras)
    ou do Prompt Master - era essa a origem real do relato do utilizador
    ("os videos saem com o tamanho errado, a LLM obedece ao Blueprint"): o
    alvo efectivo nao era o do canal. A resolucao passa a ser, por ordem:

    1. tempo do canal (MM:SS > 0);
    2. contagem explicita de palavras do canal;
    3. padrao da PLATAFORMA (20:00 YouTube / 01:20 TikTok) - o canal nasce
       ou assume 20:00 quando o campo esta vazio ou ``00:00``.

    O Blueprint e o Prompt Master NUNCA definem o tamanho (continuam a mandar
    em tom, estrutura, must_include/must_avoid e CTA). ``blueprint`` e
    ``prompt_master`` ficam na assinatura por compatibilidade - o alvo ignora-os
    de proposito; ``explicit_word_count`` permanece apenas como referencia de
    diagnostico para a UI mostrar.
    """
    raw_configured_time = str(channel.get(AVERAGE_VIDEO_TIME_KEY) or "").strip()
    configured_words = int(channel.get(AVERAGE_VIDEO_WORD_COUNT_KEY) or 0) if str(channel.get(AVERAGE_VIDEO_WORD_COUNT_KEY) or "0").isdigit() else 0
    if raw_configured_time == "00:12" and configured_words in {0, 1800}:
        raw_configured_time = DEFAULT_AVERAGE_VIDEO_TIME
    configured_time = minutes_from_hhmm(raw_configured_time)
    if configured_time:
        return round(configured_time * WORDS_PER_MINUTE), hhmm_from_minutes(configured_time), "canal"
    if configured_words:
        return configured_words, hhmm_from_minutes(round(configured_words / WORDS_PER_MINUTE)), "canal"
    default_time = default_average_video_time(channel)
    default_minutes = minutes_from_hhmm(default_time)
    return round(default_minutes * WORDS_PER_MINUTE), default_time, "padrão do canal"


def words_from_channel_time(value: Any) -> int:
    minutes = minutes_from_hhmm(value)
    return round(minutes * WORDS_PER_MINUTE) if minutes else 0


def length_generation_settings(channel: dict[str, Any], blueprint: Any = None, prompt_master: str = "") -> dict[str, Any]:
    words, duration, source = channel_video_length(channel, blueprint, prompt_master)
    if not words:
        return {}
    return {
        "target_word_count": words,
        "target_video_duration": duration,
        "target_word_count_source": source,
    }

__all__ = [
    "AVERAGE_VIDEO_TIME_KEY",
    "AVERAGE_VIDEO_WORD_COUNT_KEY",
    "DEFAULT_AVERAGE_VIDEO_TIME",
    "DEFAULT_TIKTOK_AVERAGE_VIDEO_TIME",
    "default_average_video_time",
    "channel_video_time_value",
    "WORDS_PER_MINUTE",
    "channel_video_length",
    "explicit_word_count",
    "hhmm_from_minutes",
    "length_generation_settings",
    "minutes_from_hhmm",
    "valid_hhmm",
    "words_from_channel_time",
]
