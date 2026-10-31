"""Escudo de comprimento de roteiro — REGRA INVIOLÁVEL (AGENTS.md).

O ``average_video_time`` (Tempo Médio de Vídeo) do canal é a ÚNICA fonte de
verdade para o tamanho do roteiro. Blueprints JSON trazem regras engessadas
de contagem de caracteres («STRICTLY 7,000–9,000 characters»,
``hard_fail_condition`` …) que durante três releases ignoraram a vontade do
utilizador. Este módulo:

1. ``sanitize_blueprint_for_prompt`` — remove IMPIEDOSAMENTE as chaves de
   comprimento de um blueprint, a QUALQUER profundidade (dicts dentro de
   listas, dentro de dicts …), antes de o JSON ser serializado para a LLM;
2. ``strip_length_governance`` — neutraliza as mesmas regras na governança
   derivada (sem secção «EXTENSÃO OBRIGATÓRIA» no prompt, sem validação
   dura de caracteres);
3. ``channel_length_instruction`` — calcula o alvo a partir do tempo do
   canal (150 palavras/minuto) e devolve a instrução obrigatória que vai
   no TOPO do system prompt.

Qualquer chave nova que apareça nos blueprints e cheire a contagem de
caracteres/palavras pode ser acrescentada a ``LENGTH_INSTRUCTION_KEYS`` —
mas a lista existente já cobre as famílias reais (FINANCE, MILITAR,
Cocomelon, História, Universo, …).
"""

from __future__ import annotations

import copy
from typing import Any

from .video_length import WORDS_PER_MINUTE, channel_video_length, minutes_from_hhmm


# Chaves terminantemente proibidas no prompt (a qualquer profundidade).
# A lista da regra + as variantes reais encontradas nos blueprints.
LENGTH_INSTRUCTION_KEYS: frozenset[str] = frozenset(
    {
        "character_length_requirement",
        "strict_character_range",
        "character_length_rule",
        "character_length_verification",
        "character_length",
        "char_length",
        "char_count",
        "character_count",
        "output_length_requirement",
        "output_length_verification",
        "hard_fail_condition",
        "length_compliance_mandatory",
        "length_compliance",
        "length_requirement",
        "length_rule",
        "length_mandate",
        "mandatory_length",
        "script_length_requirement",
        "script_length_rule",
        "script_length_mandatory",
        "min_characters",
        "max_characters",
        "minimum_characters",
        "maximum_characters",
        "min_character_count",
        "max_character_count",
        "min_length_chars",
    }
)

# Sub-strings que denunciam uma chave de comprimento mesmo fora da lista
# (reforço: `character_length_*`, `*_character_range`, …).
_FORBIDDEN_FRAGMENTS = (
    "character_length",
    "character_count",
    "char_count",
    "char_length",
    "character_range",
    "length_compliance",
    "length_requirement",
    "length_mandate",
    "hard_fail",
    "characters_mandatory",
    "min_characters",
    "max_characters",
    "minimum_characters",
    "maximum_characters",
)


def _key_is_forbidden(key: str) -> bool:
    normalized = str(key).strip().casefold().replace("-", "_")
    if normalized in LENGTH_INSTRUCTION_KEYS:
        return True
    return any(fragment in normalized for fragment in _FORBIDDEN_FRAGMENTS)


def sanitize_blueprint_for_prompt(blueprint: Any) -> dict[str, Any]:
    """Cópia profunda do blueprint SEM nenhuma chave de comprimento.

    Remove as chaves proibidas a qualquer profundidade (incluindo dicts
    dentro de listas). O blueprint devolvido é uma cópia — o original nunca
    é mutado (outros consumidores, como a validação de títulos ou os
    requisitos visuais, continuam intactos).
    """
    if not isinstance(blueprint, dict):
        return {}

    def _clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: _clean(item)
                for key, item in value.items()
                if not _key_is_forbidden(key)
            }
        if isinstance(value, list):
            return [_clean(item) for item in value]
        return copy.deepcopy(value)

    return {key: _clean(item) for key, item in blueprint.items() if not _key_is_forbidden(key)}


def strip_length_governance(governance: dict[str, Any] | None) -> dict[str, Any]:
    """Neutraliza as regras de comprimento numa governança derivada.

    A governança mantém tudo o que é lei do canal (tom, blacklist, CTA,
    must_include/must_avoid, formato) — mas ``strict_character_range``,
    ``character_length_rule`` e ``length_compliance_mandatory`` saem, para
    que o prompt não tenha secção «EXTENSÃO OBRIGATÓRIA» e o validador não
    rejeite roteiros pelo tamanho.
    """
    cleaned = dict(governance or {})
    cleaned["strict_character_range"] = None
    cleaned["character_length_rule"] = ""
    cleaned["length_compliance_mandatory"] = False
    return cleaned


def length_instruction_for_words(words: int, duration: str = "") -> tuple[str, int, str]:
    """Instrução obrigatória para um alvo EXPLÍCITO de palavras.

    Usada pelo canal (via ``channel_length_instruction``) e quando o
    chamador já traz o ``target_word_count`` resolvido do cartão do canal —
    em ambos os casos a instrução vai no TOPO do system prompt e manda
    ignorar restrições de tamanho residuais do Blueprint.
    """
    words = int(words or 0)
    if words <= 0:
        return "", 0, duration
    minutes = minutes_from_hhmm(duration) if duration else words / WORDS_PER_MINUTE
    characters = words * 6
    instruction = (
        "[INSTRUÇÃO DE TAMANHO OBRIGATÓRIA]\n"
        f"O roteiro DEVE ter exatamente {minutes:g} minutos de narração.\n"
        f"Escreva aproximadamente {words:,} palavras (cerca de {characters:,} caracteres).\n"
        "Ignore qualquer restrição de tamanho que possa ter sobrado do contexto do Blueprint."
    )
    return instruction, words, duration


def channel_length_instruction(channel: dict[str, Any] | None) -> tuple[str, int, str]:
    """Instrução de tamanho obrigatória a partir do tempo do canal.

    Devolve ``(instrucao, palavras, duracao_hhmm)``. O cálculo é
    ``minutos × 150 palavras`` (WORDS_PER_MINUTE) e a instrução vai no TOPO
    do system prompt — antes de qualquer regra do blueprint — com a ordem
    explícita de ignorar restrições de tamanho residuais.
    """
    channel = channel or {}
    words, duration, _source = channel_video_length(channel)
    return length_instruction_for_words(words, duration)


__all__ = [
    "LENGTH_INSTRUCTION_KEYS",
    "channel_length_instruction",
    "length_instruction_for_words",
    "sanitize_blueprint_for_prompt",
    "strip_length_governance",
    "WORDS_PER_MINUTE",
]
