"""Governança dinâmica de Blueprint: o JSON activo é a lei do canal.

O motor de geração deixa de usar um system prompt estático e genérico
("YouTube Viral") e passa a LER o Blueprint do canal em cada chamada:
regras de título, palavras proibidas, extensão obrigatória e tom saem do
próprio JSON, e o output do LLM é VALIDADO em código antes de ser aceite
(o LLM falha em seguir regras negativas; o validador força-as).

Campos explícitos (opcionais — quando o blueprint os tiver, ganham sempre):
- ``SYSTEM_PROMPT_OVERRIDE`` (topo ou metadata): injectado verbatim no prompt.
- ``GLOBAL_BLACKLIST_WORDS`` (topo ou metadata): palavras proibidas no output.
- ``title_analysis.title_mechanics.absolute_rules``: regras de título.
- ``title_analysis.title_mechanics.max_word_count``: limite de palavras do título.
- ``GLOBAL_TONE_DIRECTIVE`` (topo ou metadata): direcção de tom do canal.

Quando os campos explícitos não existem, este módulo DERIVA os equivalentes
das secções que os blueprints reais já têm (forbidden_title_patterns,
validation_check, must_avoid, anti_patterns_to_avoid,
replication_logic, generation_instructions, metadata.strict_character_range,
cta_pattern, channel_persona, ...). As regras derivadas são CALIBRADAS contra
os títulos canónicos do próprio blueprint (correct_forms_use_these,
title_rewrite_examples, corrected_script_example_structure), pelo que a
derivação nunca rejeita um título que o próprio blueprint dá como correcto.
Resultado: qualquer nicho (Oração, FINANCE, Cocomelon, ...) funciona sem
hardcoding.
"""
from __future__ import annotations

import json
import re
from typing import Any


DEFAULT_MAX_TITLE_WORDS = 15
MAX_TITLE_GENERATION_ATTEMPTS = 3
MAX_SCRIPT_GENERATION_ATTEMPTS = 3

# Referências genéricas que são omitidas do bundle quando o blueprint tem as
# suas próprias regras de título (evita prompt bleed de fórmulas virais).
TITLE_REFERENCE_KEYS = {"title_formulas", "viral_titles"}

_AVOID_KEY = re.compile(
    r"(?i)(forbidden|must_avoid|must-not|avoid|never|prohibit|restriction|does_not|do_not)"
)
_DOES_NOT_KEY = re.compile(r"(?i)(does_not|do_not|never_do)")
_FORBIDDEN_MARKER = re.compile(
    r"(?i)\bforbidden\b|\bmust\s+not\b|\bmustn't\b|\bnever\b|\bdo\s+not\b|"
    r"\bdon't\b|\breject\b|\brejeita\w*\b|\bproibid\w*\b|\bnunca\b|\bevita\w*\b"
)
_START_MARKER = re.compile(
    r"(?i)\bstart(?:ing|s)?\s+(?:with|by|com)\b|\bcome[açc]a\w*\s+com\b|"
    r"\bmust\s+not\s+start\b|\bn[aã]o\s+come[açc]a\b"
)
_FORMAT_MARKER = re.compile(r"(?i)\bformat\b|\bin\s+the\s+pattern\b|\bpattern\b|\bpadr[aã]o\b|\bformato\b")
_CONTAIN_MARKER = re.compile(r"(?i)\bcontains?\b|\bcont[eé]m\b")
_TITLE_MARKER = re.compile(r"(?i)\bt[íi]tulo\b|\btitles?\b")
# Aspas simples que toleram contrações/possessivos internos («can't sleep»,
# «God's Peace») e literais de 1 carácter («'A'», «'An'»): um apóstrofo
# seguido de 1–3 letras MINÚSCULAS + não-letra faz parte do literal
# (t, s, re, ll, ve...); os restantes apóstrofos fecham a citação.
_QUOTED = re.compile(
    r"'((?:[^']|'(?=[a-zà-ÿ]{1,3}[^a-zA-ZÀ-ÿ])){1,80})'"
    r'|"((?:[^"]){1,80})"'
)
_PAREN = re.compile(r"\(([^()]{2,80})\)")
_PLACEHOLDER = re.compile(r"\[[^\]]+\]")
# 1.0.17: split COM grupo de captura — sem ele o placeholder não entra na
# lista devolvida por re.split e a paridade índice/texto perdia o sentido:
# «A [type] Prayer for [problem]» virava o padrão partido «^A\s+\S+» (a
# palavra 'Prayer' era tratada como placeholder), que a calibração rejeitava
# contra canónicos como «A House Built on The Rock». Bug latente da 1.0.11.
_TEMPLATE_SPLIT_PLACEHOLDER = re.compile(r"(\[[^\]]+\])")
_ALPHA_WORD = re.compile(r"[A-Za-zÀ-ÿ']+")

# Cabeças de função demasiado amplas para virar padrão contém (ex.: o literal
# "for [problem]" bannaria qualquer título com a preposição "for").
_BROAD_HEADS = {"for", "with", "about", "from", "when", "a", "an", "the", "of", "to", "in", "on", "at", "by", "and", "or"}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_items(value: Any) -> list[str]:
    """Achata listas (aninhadas) de strings; ignora dicts e valores não-texto."""
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple)):
        result: list[str] = []
        for item in value:
            result.extend(_string_items(item))
        return result
    return []


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _quoted_literals(rule: str) -> list[str]:
    literals: list[str] = []
    for match in _QUOTED.finditer(rule):
        literal = (match.group(1) or match.group(2) or "").strip()
        if literal:
            literals.append(literal)
    return literals


def _paren_items(rule: str) -> list[str]:
    """Extrai listas entre parênteses do tipo «(night, evening, bed, alarm)».

    Só aceita tokens alfabéticos de 1–2 palavras (rejeita referências como
    «Psalm 4:8» e abreviaturas como «e.g.»), porque só interessam como
    blacklist de título palavras reais do cenário/sintoma proibido.
    """
    items: list[str] = []
    for match in _PAREN.finditer(rule):
        content = match.group(1)
        if "," not in content:
            continue
        for token in content.split(","):
            cleaned = token.strip().strip(".")
            words = cleaned.split()
            if not (1 <= len(words) <= 2) or not cleaned:
                continue
            if all(_ALPHA_WORD.fullmatch(word) for word in words):
                items.append(cleaned)
    return items


def _contains_pattern(phrase: str) -> re.Pattern[str]:
    """Padrão de contenção com fronteiras de palavra (tolera plurais simples)."""
    core = re.escape(str(phrase).strip())
    return re.compile(rf"\b{core}(?:s|es|ed|ing)?\b", re.IGNORECASE)


def _template_pattern(literal: str) -> re.Pattern[str]:
    """Converte um formato com placeholders («A [type] Prayer for [problem]»)
    num padrão ancorado no início: ^a\\s+\\S+\\s+prayer\\s+for\\s+\\S+."""
    pieces: list[str] = []
    for index, part in enumerate(_TEMPLATE_SPLIT_PLACEHOLDER.split(literal)):
        if index % 2:  # slot do placeholder → uma palavra qualquer
            pieces.append(r"\S+")
        else:
            pieces.extend(re.escape(word) for word in part.strip().split())
    body = r"\s+".join(piece for piece in pieces if piece)
    return re.compile(rf"^{body}", re.IGNORECASE)


def _start_pattern(phrase: str) -> re.Pattern[str]:
    """Padrão de início com fronteira de palavra: ^why\\b apanha «Why ...»
    mas não «WhyNot...»; ^an\\b apanha «An Anchor» mas não «Anointed»."""
    words = [re.escape(word) for word in str(phrase).strip().split() if word]
    body = r"\s+".join(words)
    return re.compile(rf"^\W*{body}\b", re.IGNORECASE)


def has_blueprint_title_rules(blueprint: dict[str, Any] | None) -> bool:
    """True quando o blueprint define as suas próprias mecânicas de título."""
    return bool(_dict(_dict(blueprint).get("title_analysis")).get("title_mechanics"))


# ---------------------------------------------------------------------------
# Recolha e classificação das regras de título
# ---------------------------------------------------------------------------


def _title_rule_sources(blueprint: dict[str, Any]) -> list[tuple[str, bool]]:
    """Regras de título do blueprint como pares (texto, negativa?).

    Items de chaves/secsões proibitivas (forbidden*, must_avoid,
    anti_patterns_to_avoid, must_avoid de generation_instructions filtrado a
    títulos) são negativos por construção; os checklist (validation_check,
    replication_logic) só contam como negativos quando trazem marcador
    explícito (FORBIDDEN, MUST NOT, → REJECT, ...).
    """
    tm = _dict(_dict(blueprint.get("title_analysis")).get("title_mechanics"))
    pairs: list[tuple[str, bool]] = []
    for key, value in tm.items():
        if not _AVOID_KEY.search(str(key)):
            continue
        # Fragments tipo «the_title_does_not: Describe a situation...» perdem a
        # negação fora de contexto: recebem o aviso explícito no prompt.
        prefix = "[O título NÃO deve] " if _DOES_NOT_KEY.search(str(key)) else ""
        for item in _string_items(value):
            pairs.append((f"{prefix}{item}", True))
    # Os anti-padrões de rotação são as regras de título mais concretas.
    for item in _string_items(_dict(blueprint.get("rotation_mandate")).get("anti_patterns_to_avoid")):
        pairs.append((item, True))
    instructions = _dict(blueprint.get("generation_instructions_for_another_model"))
    for item in _string_items(instructions.get("must_avoid")):
        if _TITLE_MARKER.search(item):
            pairs.append((item, True))
    for item in _string_items(tm.get("validation_check_mandatory_before_finalising_any_title")):
        pairs.append((item, bool(_FORBIDDEN_MARKER.search(item))))
    for item in _string_items(_dict(blueprint.get("replication_logic")).get("title_generation_rules_critical")):
        pairs.append((item, bool(_FORBIDDEN_MARKER.search(item))))
    return pairs


def _classify_rules(pairs: list[tuple[str, bool]]) -> tuple[list[str], list[str], list[str]]:
    """Classifica os literais das regras negativas em starts/contains/templates."""
    starts: list[str] = []
    contains: list[str] = []
    templates: list[str] = []
    for rule, negative in pairs:
        if not negative:
            continue  # regras «MAY ...» e checks de aprovação nunca proíbem nada
        is_start = bool(_START_MARKER.search(rule))
        is_format = not is_start and bool(_FORMAT_MARKER.search(rule))
        is_contain = not is_start and not is_format and bool(_CONTAIN_MARKER.search(rule))
        for literal in _quoted_literals(rule):
            literal = literal.strip()
            if not (1 <= len(literal) <= 80):
                continue
            if not re.search(r"[A-Za-zÀ-ÿ0-9]", literal):
                continue  # lixo tipográfico (», «, pontuação solta)
            if _PLACEHOLDER.search(literal):
                if is_contain:
                    head = literal.split("[", 1)[0].strip().casefold()
                    if head in _BROAD_HEADS:
                        continue  # «for [problem]» é demasiado amplo para validar
                    templates.append(literal)
                else:
                    # formatos/modelos de título: sempre ancorados no início
                    templates.append(literal)
                continue
            if literal.endswith("..."):
                prefix = literal.rstrip(".").strip()
                if prefix:
                    starts.append(prefix)
                continue
            if is_start:
                starts.append(literal)
                continue
            words = literal.split()
            if len(words) > 5 or len(literal) > 40:
                continue  # frase longa = regra de estilo, não palavra proibida
            contains.append(literal)
        if _TITLE_MARKER.search(rule):
            for token in _paren_items(rule):
                if 2 <= len(token) <= 40:
                    contains.append(token)
    return _dedupe(starts), _dedupe(contains), _dedupe(templates)


def _positive_title_examples(blueprint: dict[str, Any]) -> list[str]:
    """Títulos que o próprio blueprint apresenta como CORRECTOS.

    Usados para calibrar a derivação: uma regra derivada que rejeitasse um
    destes títulos é artefacto da extracção, não vontade do autor, e é descartada.
    """
    tm = _dict(_dict(blueprint.get("title_analysis")).get("title_mechanics"))
    examples: list[str] = []
    examples.extend(_string_items(tm.get("correct_forms_use_these")))
    examples.extend(_string_items(tm.get("correct_title_forms")))
    for item in tm.get("title_rewrite_examples") or []:
        if not isinstance(item, dict):
            continue
        for key, value in item.items():
            if str(key).casefold().startswith("correct") and isinstance(value, str):
                candidate = value.strip()
                if candidate and "REJECT" not in candidate.upper():
                    examples.append(candidate)
    corrected_title = _dict(blueprint.get("corrected_script_example_structure")).get("title")
    if isinstance(corrected_title, str) and corrected_title.strip():
        examples.append(corrected_title.strip())
    # Os example_themes das categorias de rotação são títulos canónicos do
    # canal: a calibração nunca pode rejeitá-los.
    for category in _dict(blueprint.get("rotation_mandate")).get("categories") or []:
        if isinstance(category, dict):
            examples.extend(_string_items(category.get("example_themes")))
    # Sem cap aqui: a calibração precisa do conjunto completo de canónicos
    # (o cap aplica-se apenas à injecção no prompt, em title_governance).
    return [item for item in _dedupe(examples) if 0 < len(item) <= 80]


def _calibrate(
    starts: list[str],
    contains: list[str],
    templates: list[str],
    positives: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """Remove regras derivadas que rejeitariam um título canónico do blueprint."""
    lowered = [item.lower() for item in positives]
    keep_starts = [
        start for start in starts
        if not any(_start_pattern(start).match(title) for title in lowered)
    ]
    keep_contains = [
        phrase for phrase in contains
        if not any(_contains_pattern(phrase).search(title) for title in positives)
    ]
    keep_templates = [
        template for template in templates
        if not any(_template_pattern(template).search(title) for title in positives)
    ]
    return keep_starts[:16], keep_contains[:40], keep_templates[:12]


# ---------------------------------------------------------------------------
# Governança de títulos
# ---------------------------------------------------------------------------


def _explicit_override(blueprint: dict[str, Any]) -> str:
    metadata = _dict(blueprint.get("metadata"))
    for source in (blueprint, metadata):
        for key in ("SYSTEM_PROMPT_OVERRIDE", "system_prompt_override"):
            value = str(source.get(key) or "").strip()
            if value:
                return value
    return ""


def _explicit_blacklist(blueprint: dict[str, Any]) -> list[str]:
    metadata = _dict(blueprint.get("metadata"))
    for source in (metadata, blueprint):
        for key in ("GLOBAL_BLACKLIST_WORDS", "global_blacklist_words"):
            items = _string_items(source.get(key))
            if items:
                return items
    return []


# 1.0.17: tags de produção que NUNCA podem chegar ao TTS nem às legendas.
_PRODUCTION_TAG = re.compile(
    r"\[\s*(?:visual|audio|sfx|narrator|narration|voice\s*over|voiceover|"
    r"on[\s-]*screen(?:\s*text)?|scene|cena|narra[çc][ãa]o|voz|som|[áa]udio)\b[^\]]*\]",
    re.IGNORECASE,
)
_SCENE_LABEL = re.compile(r"(?i)^\s*(?:scene|cena)\s*\d+\s*[:.\-–—]?")


def _parse_character_range(text: str) -> tuple[int, int] | None:
    """Extrai o intervalo de caracteres de uma frase tipo «STRICTLY 7,000–9,000 characters».

    1.0.17: o Blueprint Oração corrigido expressa a extensão obrigatória na
    string ``character_length_requirement`` (sem a lista
    ``strict_character_range``); o motor passa a ACEITAR AS DUAS FORMAS para
    que a validação dura de extensão nunca se desligue por detalhe de schema.
    """
    matches = re.findall(r"\d{1,3}(?:[.,]\d{3})+|\d+", str(text or ""))
    if len(matches) < 2:
        return None
    try:
        numbers = [int(re.sub(r"[.,]", "", match)) for match in matches[:2]]
    except ValueError:
        return None
    low, high = numbers[0], numbers[1]
    if 0 < low < high:
        return (low, high)
    return None


def _structural_title_guidance(tm: dict[str, Any]) -> list[str]:
    """Fallback: quando não há regras proibitivas, injecta a mecânica estrutural."""
    guidance: list[str] = []
    for key in ("structure", "the_title_is", "common_forms", "correct_forms_use_these", "title_psychology", "tone_signature", "number_usage"):
        value = tm.get(key)
        if isinstance(value, str) and value.strip():
            guidance.append(f"{key}: {value.strip()}")
        elif isinstance(value, list) and value:
            joined = "; ".join(str(item) for item in _string_items(value)[:6])
            if joined:
                guidance.append(f"{key}: {joined}")
    return guidance[:8]


def title_governance(blueprint: dict[str, Any] | None) -> dict[str, Any]:
    """Extrai (ou deriva) as regras de título do blueprint num objecto normalizado."""
    blueprint = _dict(blueprint)
    tm = _dict(_dict(blueprint.get("title_analysis")).get("title_mechanics"))
    active = bool(tm)

    explicit_rules = _string_items(tm.get("absolute_rules"))
    pairs = _title_rule_sources(blueprint)
    derived_rules = _dedupe([rule for rule, negative in pairs if negative and len(rule) <= 240])[:30]
    rules = explicit_rules or derived_rules or (_structural_title_guidance(tm) if active else [])

    starts, contains, templates = _classify_rules(pairs)
    positives = _positive_title_examples(blueprint)
    starts, contains, templates = _calibrate(starts, contains, templates, positives)

    explicit_max = tm.get("max_word_count") or tm.get("max_title_words") or _dict(blueprint.get("metadata")).get("max_title_word_count")
    try:
        max_words = max(1, int(explicit_max))
    except (TypeError, ValueError):
        max_words = DEFAULT_MAX_TITLE_WORDS

    return {
        "active": active,
        "system_prompt_override": _explicit_override(blueprint),
        "absolute_rules": rules,
        "blacklist_words": _dedupe(_explicit_blacklist(blueprint) + contains),
        "forbidden_starts": starts,
        "forbidden_templates": [
            {"literal": literal, "pattern": _template_pattern(literal)} for literal in templates
        ],
        "max_word_count": max_words,
        "validation_check": _string_items(tm.get("validation_check_mandatory_before_finalising_any_title"))[:10],
        "correct_examples": positives[:20],
    }


def validate_title_with_governance(title: str, governance: dict[str, Any]) -> tuple[bool, str]:
    """Valida um título contra a governança já extraída (sem reprocessar o JSON)."""
    title = str(title or "").strip()
    if not title:
        return False, "O título está vazio."
    word_count = len(title.split())
    max_words = int(governance.get("max_word_count") or DEFAULT_MAX_TITLE_WORDS)
    if word_count > max_words:
        return False, f"O título tem {word_count} palavras. O limite máximo é {max_words}."
    for word in governance.get("blacklist_words") or []:
        if _contains_pattern(str(word)).search(title):
            return False, f"O título contém a palavra ou expressão proibida: '{word}'."
    for start in governance.get("forbidden_starts") or []:
        if _start_pattern(str(start)).match(title):
            return False, f"O título começa com um padrão proibido pelo blueprint ('{start}')."
    for template in governance.get("forbidden_templates") or []:
        if template["pattern"].match(title):
            return False, f"O título segue o formato proibido pelo blueprint ('{template['literal']}')."
    return True, "Válido"


def validate_generated_title(title: str, blueprint: dict[str, Any] | None) -> tuple[bool, str]:
    """Hard validation de um título contra o blueprint (API pública).

    Devolve (válido?, motivo). O motivo é devolvido ao LLM como feedback
    quando o título é rejeitado, fechando o loop de auto-correcção.
    """
    return validate_title_with_governance(title, title_governance(blueprint))


def title_rules_prompt_section(governance: dict[str, Any]) -> str:
    """Bloco de system prompt com as regras de título extraídas do blueprint."""
    sections: list[str] = []
    if governance.get("system_prompt_override"):
        sections.append(
            "REGRAS CRÍTICAS DO CANAL (VIOLAÇÃO = FALHA DO SISTEMA):\n"
            + str(governance["system_prompt_override"])
        )
    rules = governance.get("absolute_rules") or []
    if rules:
        sections.append(
            "REGRAS DE TÍTULO DO BLUEPRINT (cumpre TODAS — nenhuma excepção):\n"
            + json.dumps(rules, indent=2, ensure_ascii=False)
        )
    if governance.get("validation_check"):
        sections.append(
            "VALIDAÇÃO OBRIGATÓRIA DE CADA TÍTULO ANTES DE O DEVOLVER:\n"
            + json.dumps(governance["validation_check"], indent=2, ensure_ascii=False)
        )
    sections.append(
        f"O título deve ter NO MÁXIMO {governance['max_word_count']} palavras."
    )
    if governance.get("blacklist_words"):
        sections.append(
            "PALAVRAS/EXPRESSÕES TERMINANTEMENTE PROIBIDAS NO TÍTULO:\n"
            + ", ".join(governance["blacklist_words"])
        )
    if governance.get("forbidden_starts"):
        sections.append(
            "O título NUNCA pode começar por: " + ", ".join(governance["forbidden_starts"])
        )
    templates = governance.get("forbidden_templates") or []
    if templates:
        sections.append(
            "FORMATOS DE TÍTULO PROIBIDOS (qualquer título neste molde é rejeitado): "
            + "; ".join(template["literal"] for template in templates)
        )
    if governance.get("correct_examples"):
        sections.append(
            "EXEMPLOS DE TÍTULOS CORRECTOS DESTE CANAL (segue exactamente este padrão):\n"
            + json.dumps(governance["correct_examples"], indent=2, ensure_ascii=False)
        )
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Governança de roteiros
# ---------------------------------------------------------------------------


def _explicit_visual_requirements(blueprint: dict[str, Any]) -> dict[str, Any]:
    """Normaliza ``metadata.visual_requirements`` do blueprint (1.0.17).

    O motor NÃO faz hardcoding de regras visuais: lê a chave do blueprint e
    passa-a aos geradores de imagem (prompts de thumbnail e de cenas).
    """
    raw = _dict(_dict(blueprint.get("metadata")).get("visual_requirements"))
    if not raw:
        return {}
    return {
        "prompt_keywords": _string_items(raw.get("image_prompt_keywords"))[:24],
        "blacklist_keywords": _string_items(raw.get("image_blacklist_keywords"))[:24],
        "instruction": str(raw.get("instruction") or "").strip(),
    }


def script_governance(blueprint: dict[str, Any] | None) -> dict[str, Any]:
    """Extrai (ou deriva) as regras de roteiro do blueprint."""
    blueprint = _dict(blueprint)
    metadata = _dict(blueprint.get("metadata"))
    instructions = _dict(blueprint.get("generation_instructions_for_another_model"))
    persona = _dict(metadata.get("channel_persona"))

    character_range: tuple[int, int] | None = None
    raw_range = metadata.get("strict_character_range")
    if isinstance(raw_range, (list, tuple)) and len(raw_range) == 2:
        try:
            low, high = int(raw_range[0]), int(raw_range[1])
            if 0 < low < high:
                character_range = (low, high)
        except (TypeError, ValueError):
            character_range = None
    length_rule_text = str(
        metadata.get("character_length_requirement") or metadata.get("character_length_rule") or ""
    ).strip()
    if character_range is None and metadata.get("length_compliance_mandatory") is True:
        # 1.0.17: blueprint corrigido só traz a frase («STRICTLY 7,000–9,000
        # characters») — o intervalo é derivado dela; a validação dura
        # continua a funcionar com qualquer uma das formas.
        character_range = _parse_character_range(length_rule_text)

    tone_directive = ""
    for source in (blueprint, metadata):
        for key in ("GLOBAL_TONE_DIRECTIVE", "global_tone_directive"):
            value = str(source.get(key) or "").strip()
            if value:
                tone_directive = value
                break
        if tone_directive:
            break
    if not tone_directive:
        parts: list[str] = []
        role = str(persona.get("role") or "").strip()
        voice = str(persona.get("voice") or "").strip()
        if role:
            parts.append(f"Persona do canal: {role}")
        if voice:
            parts.append(f"Voz: {voice}")
        parts.extend(_string_items(instructions.get("role_enforcement"))[:3])
        tone_directive = "\n".join(parts)

    # 1.0.17: o CTA vive em ``cta_pattern.mandatory_closing_pattern`` (formato
    # antigo) OU em ``generation_instructions.cta_pattern`` (blueprint
    # corrigido) — aceita os dois.
    mandatory_cta = str(_dict(blueprint.get("cta_pattern")).get("mandatory_closing_pattern") or "").strip()
    if not mandatory_cta:
        mandatory_cta = str(instructions.get("cta_pattern") or "").strip()

    format_rules = _string_items(metadata.get("script_format_rules"))

    return {
        "active": bool(character_range or tone_directive or mandatory_cta or instructions or format_rules),
        "system_prompt_override": _explicit_override(blueprint),
        "tone_directive": tone_directive,
        "character_length_rule": length_rule_text,
        "strict_character_range": character_range,
        "length_compliance_mandatory": metadata.get("length_compliance_mandatory") is True,
        "blacklist_words": _explicit_blacklist(blueprint),
        "format_rules": format_rules,
        "visual_requirements": _explicit_visual_requirements(blueprint),
        "must_include": _string_items(instructions.get("must_include"))[:12],
        "must_avoid": _string_items(instructions.get("must_avoid"))[:14],
        "mandatory_cta": mandatory_cta,
    }


def validate_script_content(content: str, governance: dict[str, Any]) -> tuple[bool, str]:
    """Hard guardrail do roteiro contra o blueprint (1.0.17: tom + blacklist + tags + extensão).

    1. O LLM falha em seguir regras negativas — cada verificação devolve um
    motivo accionável que o loop de geração (script_generation) reenvia ao
    LLM como ``system_feedback`` até cumprir (máx. 3 tentativas).
    2. ``GLOBAL_BLACKLIST_WORDS`` (ex.: meditation/yoga/sleep) nunca pode
    chegar ao texto falado — o mesmo validador protege títulos e roteiros.
    3. Tags de produção (``[Visual: ...]``, ``[Audio: ...]``, ``[SFX]`` …)
    poluem o TTS e as legendas — rejeitadas na origem.
    4. A extensão continua a ser regra DURA quando o blueprint declara
    ``length_compliance_mandatory`` (aceita lista OU frase «7,000–9,000»).
    """
    text = str(content or "")
    for word in governance.get("blacklist_words") or []:
        if _contains_pattern(str(word)).search(text):
            return False, f"O roteiro contém a palavra ou expressão proibida pelo blueprint: '{word}'."
    if _PRODUCTION_TAG.search(text):
        return False, (
            "O roteiro contém tags de produção entre colchetes (ex.: '[Visual: ...]', '[Audio: ...]', "
            "'[SFX]') que seriam lidas em voz alta pelo TTS e apareceriam nas legendas. "
            "Escreve apenas o texto falado."
        )
    if _SCENE_LABEL.match(text.splitlines()[0] if text else "") and all(
        _SCENE_LABEL.match(line) for line in text.splitlines() if line.strip()
    ):
        return False, "O roteiro só contém rótulos de cena ('SCENE 1', ...), sem narração falada."
    if not governance.get("length_compliance_mandatory"):
        return True, "Válido"
    character_range = governance.get("strict_character_range")
    if not character_range:
        return True, "Válido"
    count = len(text)
    low, high = character_range
    if count < low:
        return False, (
            f"O roteiro tem {count} caracteres; o blueprint exige um MÍNIMO de {low} caracteres"
            + (f" ({governance.get('character_length_rule')})" if governance.get("character_length_rule") else "")
            + "."
        )
    if count > high:
        return False, (
            f"O roteiro tem {count} caracteres; o blueprint exige um MÁXIMO de {high} caracteres"
            + (f" ({governance.get('character_length_rule')})" if governance.get("character_length_rule") else "")
            + "."
        )
    return True, "Válido"


def script_rules_prompt_section(governance: dict[str, Any]) -> str:
    """Bloco de system prompt com as regras de roteiro extraídas do blueprint."""
    sections: list[str] = []
    if governance.get("system_prompt_override"):
        sections.append(
            "REGRAS CRÍTICAS DO CANAL (VIOLAÇÃO = FALHA DO SISTEMA):\n"
            + str(governance["system_prompt_override"])
        )
    if governance.get("tone_directive"):
        sections.append(
            "DIRECÇÃO DE TOM E PERSONA (obrigatória em todo o texto):\n"
            + str(governance["tone_directive"])
        )
    if governance.get("format_rules"):
        sections.append(
            "REGRAS CRÍTICAS DE FORMATO DO TEXTO (o texto será lido directamente por um TTS):\n"
            + "\n".join(f"- {rule}" for rule in governance["format_rules"])
        )
    if governance.get("strict_character_range"):
        low, high = governance["strict_character_range"]
        rule = governance.get("character_length_rule") or ""
        sections.append(
            "EXTENSÃO OBRIGATÓRIA DO ROTEIRO"
            + (f" ({rule})" if rule else "")
            + f": o conteúdo final deve ter ESTRITAMENTE entre {low} e {high} caracteres — "
            "cumpre este intervalo à letra; qualquer valor abaixo ou acima é falha do sistema."
        )
    if governance.get("blacklist_words"):
        sections.append(
            "PALAVRAS/EXPRESSÕES PROIBIDAS NO CORPO DO TEXTO (VIOLAÇÃO = FALHA DO SISTEMA):\n"
            + ", ".join(governance["blacklist_words"])
        )
    if governance.get("must_avoid"):
        sections.append(
            "O BLUEPRINT PROÍBE (nunca faças):\n"
            + json.dumps(governance["must_avoid"], indent=2, ensure_ascii=False)
        )
    if governance.get("must_include"):
        sections.append(
            "O BLUEPRINT EXIGE (inclui obrigatoriamente):\n"
            + json.dumps(governance["must_include"], indent=2, ensure_ascii=False)
        )
    if governance.get("mandatory_cta"):
        sections.append(
            "CTA FINAL OBRIGATÓRIO (usa exactamente este padrão no fecho):\n"
            + governance["mandatory_cta"]
        )
    return "\n\n".join(sections)


def visual_requirements_prompt_section(blueprint: dict[str, Any] | None) -> str:
    """Bloco de requisitos visuais do blueprint para os geradores de imagem (1.0.17).

    O motor lê ``metadata.visual_requirements`` (instrução + keywords a
    incluir + keywords proibidas) e passa-a adiante — ZERO hardcoding: cada
    nicho dita as suas próprias regras de imagem pelo seu blueprint.
    """
    requirements = script_governance(blueprint).get("visual_requirements") or {}
    if not requirements:
        return ""
    sections: list[str] = []
    if requirements.get("instruction"):
        sections.append(str(requirements["instruction"]))
    if requirements.get("prompt_keywords"):
        sections.append(
            "Visual keyword themes to favour: " + ", ".join(requirements["prompt_keywords"]) + "."
        )
    if requirements.get("blacklist_keywords"):
        sections.append(
            "NEVER depict or evoke: " + ", ".join(requirements["blacklist_keywords"]) + "."
        )
    if not sections:
        return ""
    return "CHANNEL VISUAL REQUIREMENTS (mandatory in EVERY image):\n" + "\n".join(sections)
