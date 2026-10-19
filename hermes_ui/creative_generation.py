from __future__ import annotations

import json
import re
from functools import lru_cache

import requests
from pathlib import Path
from typing import Any

from .languages import LANGUAGE_BY_CODE, language_code
from .llm_providers import active_llm_card, provider_definition
from .blueprint_governance import (
    MAX_TITLE_GENERATION_ATTEMPTS,
    TITLE_REFERENCE_KEYS,
    has_blueprint_title_rules,
    title_governance,
    title_rules_prompt_section,
    validate_title_with_governance,
)
from .provider_routing import ProviderRoutingError, route_llm_json


ROOT = Path(__file__).resolve().parents[1]
REFERENCES_DIR = ROOT / "seed" / "references"

REFERENCE_FILES = {
    "title_formulas": "title-formulas.md",
    "viral_titles": "viral-titles.md",
    "thumbnail_checklist": "thumbnail-checklist.md",
    "viral_thumbnails": "viral-thumbnails.md",
    "trend_intelligence": "trend-intelligence.md",
    "humanize": "humanize-integration.md",
    "ai_tells": "ai-tells.md",
}


class CreativeGenerationError(RuntimeError):
    """Raised when a configured LLM cannot produce a valid creative package."""


_TARGET_LANGUAGE_NAMES = {
    code: str(item.get("ui_name") or item.get("name") or code)
    for code, item in LANGUAGE_BY_CODE.items()
}


def target_language(value: Any, default: str = "pt") -> tuple[str, str]:
    """Return a canonical video-language code and an unambiguous prompt label."""
    code = language_code(value, default=default)
    return code, _TARGET_LANGUAGE_NAMES.get(code, code)


def _language_instruction(value: Any, default: str = "pt") -> str:
    code, label = target_language(value, default=default)
    return f"{label} ({code})"


def _provider_config(settings: dict[str, Any]) -> tuple[str, str, str, str]:
    card = active_llm_card(settings)
    provider = str(card.get("provider") or "openai").strip().lower()
    definition = provider_definition(provider)
    key = str(card.get("api_key") or "").strip()
    base_url = str(card.get("base_url") or "").strip() or definition.default_base_url
    model = str(card.get("model") or "").strip()
    if not base_url:
        raise CreativeGenerationError(
            f"O provider LLM '{provider}' não tem Base URL configurada em Configuração API > API Keys > Serviços e modelos."
        )
    if not model:
        raise CreativeGenerationError(
            f"O provider LLM '{provider}' não tem modelo configurado em Configuração API > API Keys > Serviços e modelos."
        )
    if definition.requires_api_key and not key:
        raise CreativeGenerationError(
            f"Configure a API key do provider LLM '{provider}' em Configuração API > API Keys > Serviços e modelos."
        )
    return provider, key, base_url.rstrip("/"), model


@lru_cache(maxsize=2)
def _reference_bundle_cached(skip_title_references: bool) -> str:
    sections: list[str] = []
    for label, filename in REFERENCE_FILES.items():
        # 1.1.x — prompt bleed: um blueprint com mecânicas de título próprias
        # substitui as fórmulas virais genéricas (title-formulas/viral-titles);
        # as referências de thumbnail/humanização continuam a aplicar-se.
        if skip_title_references and label in TITLE_REFERENCE_KEYS:
            continue
        path = REFERENCES_DIR / filename
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        # Keep prompts bounded while preserving the concrete rules from the attachments.
        sections.append(f"[{label}]\n{content[:4200]}")
    return "\n\n".join(sections)


def reference_bundle(blueprint: dict[str, Any] | None = None) -> str:
    """Bundle de referências genéricas, EXCEPTO fórmulas de título quando o
    blueprint activo define as suas próprias regras de título."""
    return _reference_bundle_cached(has_blueprint_title_rules(blueprint))


def _json_content(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices") or []
    if not choices:
        raise CreativeGenerationError("O endpoint LLM devolveu uma resposta sem choices.")
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        content = "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    text = str(content or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CreativeGenerationError("O endpoint LLM não devolveu JSON válido.") from exc
    if not isinstance(parsed, dict):
        raise CreativeGenerationError("A resposta do endpoint LLM não é um objecto JSON.")
    return parsed


def _chat_json(settings: dict[str, Any], system_prompt: str, user_prompt: str) -> dict[str, Any]:
    # Keep the actionable legacy validation for an entirely unconfigured setup;
    # the router still skips incomplete cards when a configured fallback exists.
    cards = settings.get("llm_provider_cards") if isinstance(settings, dict) else None
    if not isinstance(cards, list) or not any(
        isinstance(card, dict)
        and bool(card.get("enabled", True))
        and str(card.get("api_key") or "").strip()
        and str(card.get("model") or card.get("model_name") or "").strip()
        for card in cards
    ):
        _provider_config(settings)
    try:
        routed = route_llm_json(settings, system_prompt, user_prompt)
    except ProviderRoutingError as exc:
        raise CreativeGenerationError(str(exc)) from exc
    return _json_content(routed.payload)


def channel_context(channel: dict[str, Any], blueprint: dict[str, Any] | None = None) -> dict[str, Any]:
    blueprint = blueprint or {}
    metadata = blueprint.get("metadata") if isinstance(blueprint.get("metadata"), dict) else {}
    return {
        "channel_name": str(channel.get("name") or "Canal sem nome"),
        "handle": str(channel.get("handle") or ""),
        "description": str(channel.get("description") or ""),
        "language": language_code(channel.get("language") or "pt"),
        "language_name": _TARGET_LANGUAGE_NAMES.get(language_code(channel.get("language") or "pt"), "Portuguese"),
        "style_wide": str(channel.get("style_wide") or "pexels"),
        "blueprint_id": str(blueprint.get("id") or channel.get("default_blueprint_id") or channel.get("blueprint_id") or ""),
        "blueprint_name": str(blueprint.get("name") or "SEM BLUEPRINT CONFIGURADO"),
        "blueprint_niche": str(blueprint.get("target_niche") or blueprint.get("niche") or metadata.get("target_niche") or metadata.get("niche") or ""),
        "thumbnail_blueprint_rules": str(blueprint.get("thumbnail_blueprint_rules") or "").strip(),
        "default_voice": str(channel.get("default_voice") or channel.get("voice") or ""),
    }


def generate_video_description(
    settings: dict[str, Any],
    channel: dict[str, Any],
    topic: str,
    *,
    title: str = "",
    tags: list[str] | None = None,
    language: str = "",
) -> str:
    """Generate a concise YouTube description through the configured text LLM pool."""
    topic = str(topic or "").strip()
    title = str(title or "").strip()
    if not topic and not title:
        raise CreativeGenerationError("É necessário um tópico ou título antes de gerar a descrição do vídeo.")
    context = channel_context(channel)
    requested_language = language or channel.get("language") or context["language"]
    language_instruction = _language_instruction(requested_language)
    normalized_tags = [str(item).strip() for item in (tags or []) if str(item).strip()][:15]
    system = (
        "És um editor de metadados de YouTube. Cria uma descrição útil, clara e envolvente para o vídeo, "
        f"e escreve todos os campos textuais de saída em {language_instruction}. "
        "sem alegações não verificadas, sem clickbait falso e sem mencionar que foi gerada por IA. "
        "Usa dois parágrafos curtos, inclui um convite natural para subscrever quando apropriado e devolve "
        "apenas JSON válido com a chave description."
    )
    user = json.dumps(
        {
            "channel": context,
            "language": target_language(requested_language)[0],
            "language_name": target_language(requested_language)[1],
            "topic": topic,
            "title": title or topic,
            "tags": normalized_tags,
            "requirements": {"paragraphs": 2, "max_characters": 1800, "no_unverified_claims": True},
        },
        ensure_ascii=False,
    )
    result = _chat_json(settings, system, user)
    description = str(result.get("description") or "").strip()
    if not description:
        raise CreativeGenerationError("O provider LLM não devolveu uma descrição válida para o vídeo.")
    return description[:1800]


def generate_topic_for_channel(
    settings: dict[str, Any],
    channel: dict[str, Any],
    blueprint: dict[str, Any] | None = None,
    user_context: str = "",
) -> dict[str, Any]:
    context = channel_context(channel, blueprint)
    language_instruction = _language_instruction(channel.get("language") or context["language"])
    system = (
        "És o estratega editorial de um canal faceless. Gera um briefing específico para este canal. "
        f"Todos os campos textuais devolvidos devem estar em {language_instruction}. "
        "Não inventes factos sobre o canal. Se o contexto já tiver um tópico, desenvolve-o sem trocar o nicho. "
        "Escreve de forma natural, sem introduções artificiais, frases de IA, clickbait enganoso ou CTA genérico. "
        "Responde apenas com JSON válido com as chaves topic, angle, hook, niche e rationale."
    )
    user = json.dumps(
        {
            "channel": context,
            "output_language": language_instruction,
            "user_context": user_context.strip(),
            "reference_rules": reference_bundle(blueprint),
            "requirements": [
                "topic em uma frase clara",
                "angle contrarian ou inesperado quando fizer sentido",
                "hook para os primeiros segundos",
                "niche coerente com o Blueprint e descrição",
                "rationale curta e prática",
            ],
        },
        ensure_ascii=False,
    )
    result = _chat_json(settings, system, user)
    required = ("topic", "angle", "hook", "niche", "rationale")
    if any(not str(result.get(key) or "").strip() for key in required):
        raise CreativeGenerationError("O briefing gerado veio incompleto; tente novamente.")
    result["topic_source"] = "llm"
    result["channel_id"] = str(channel.get("id") or "")
    return result


def generate_video_keywords(
    settings: dict[str, Any],
    channel: dict[str, Any],
    topic: str,
    script: str,
    blueprint: dict[str, Any] | None = None,
    language: str = "",
) -> list[str]:
    """Generate SEO keywords for a video subject and script using the configured LLM.

    This mirrors MoneyPrinterTurbo's ``llm.generate_terms`` step while keeping the
    Thunderbolt provider configuration and blueprint context in one place.
    """
    topic = str(topic or "").strip()
    script = str(script or "").strip()
    if not topic:
        raise CreativeGenerationError("É necessário um Video Subject antes de gerar palavras-chave.")
    if not script:
        raise CreativeGenerationError("É necessário um roteiro antes de gerar palavras-chave.")

    context = channel_context(channel, blueprint)
    system = (
        "És um especialista de SEO para vídeos faceless e pesquisa de materiais. "
        "Extrai entre 8 e 15 palavras-chave curtas, concretas e úteis para o vídeo. "
        "Devolve as palavras-chave em inglês, sem hashtags, sem frases longas, sem duplicados "
        "e sem comentários adicionais. Responde apenas com JSON válido na chave keywords."
    )
    user = json.dumps(
        {
            "channel": context,
            "language": language or context["language"],
            "video_subject": topic,
            "video_script": script,
            "reference_rules": reference_bundle(blueprint),
            "requirements": {
                "count": "8 to 15",
                "language": "English",
                "format": "short keyword phrases without hashtags",
            },
        },
        ensure_ascii=False,
    )
    result = _chat_json(settings, system, user)
    raw_keywords = result.get("keywords")
    if isinstance(raw_keywords, str):
        raw_keywords = re.split(r"[,\n;|]+", raw_keywords)
    keywords = []
    seen = set()
    if isinstance(raw_keywords, list):
        for item in raw_keywords:
            value = re.sub(r"^#+", "", str(item or "").strip())
            normalized = value.casefold()
            if value and normalized not in seen:
                keywords.append(value)
                seen.add(normalized)
    if not keywords:
        keywords = _keywords_from_text(topic, script)
    return keywords[:15]


def _score(value: Any) -> int:
    try:
        return max(0, min(3, int(value)))
    except (TypeError, ValueError):
        return 0


def _short_overlay(value: Any) -> str:
    words = re.findall(r"\S+", str(value or "").strip())
    return " ".join(words[:4])


def _keywords_from_text(*values: str) -> list[str]:
    """Build a small deterministic keyword fallback when the LLM omits keywords."""
    blocked = {"para", "como", "sobre", "mais", "esse", "esta", "that", "this", "with", "from", "video"}
    result: list[str] = []
    for value in values:
        for word in re.findall(r"[\wÀ-ÿ]{4,}", str(value or "").casefold(), flags=re.UNICODE):
            if word not in blocked and word not in result:
                result.append(word)
    return result[:15]


def _validated_title_candidates(
    result: dict[str, Any], governance: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """Valida cada candidato contra a governança do blueprint.

    Devolve (válidos, rejeitados com o motivo exacto). Os rejeitados nunca
    chegam ao utilizador: alimentam o feedback do loop de auto-correcção.
    """
    raw_titles = result.get("title_candidates")
    valid: list[dict[str, Any]] = []
    rejected: list[tuple[str, str]] = []
    for item in (raw_titles if isinstance(raw_titles, list) else [])[:40]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        is_valid, reason = validate_title_with_governance(title, governance)
        if not is_valid:
            rejected.append((title, reason))
            continue
        valid.append(
            {
                "title": title,
                "formula": str(item.get("formula") or "custom").strip(),
                "curiosity_score": _score(item.get("curiosity_score")),
                "specificity_score": _score(item.get("specificity_score")),
                "emotional_score": _score(item.get("emotional_score")),
            }
        )
    return valid, rejected


def _title_generation_loop(
    settings: dict[str, Any],
    system_prompt: str,
    user_payload: dict[str, Any],
    governance: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Loop de auto-correcção: LLM → validação em código → feedback → LLM.

    O LLM falha em seguir regras negativas por prompt sozinho; este loop
    valida cada título contra o blueprint e devolve ao modelo os rejeitados
    com o motivo exacto, até obter >= 20 títulos válidos (máx. 3 tentativas).
    """
    feedback = ""
    candidates: list[dict[str, Any]] = []
    rejected: list[tuple[str, str]] = []
    attempts = max(1, MAX_TITLE_GENERATION_ATTEMPTS)
    for attempt in range(1, attempts + 1):
        payload = dict(user_payload)
        if feedback:
            payload["system_feedback"] = feedback
        result = _chat_json(settings, system_prompt, json.dumps(payload, ensure_ascii=False))
        candidates, rejected = _validated_title_candidates(result, governance)
        if len(candidates) >= 20:
            return result, candidates
        if attempt < attempts:
            if rejected:
                sample = "; ".join(f"«{title}» ({reason})" for title, reason in rejected[:4])
                feedback = (
                    f"AVISO DO SISTEMA: {len(rejected)} dos títulos devolvidos foram REJEITADOS pelo validador do blueprint. "
                    f"Exemplos rejeitados: {sample}. "
                    "Gera uma NOVA lista com pelo menos 20 títulos que cumpram TODAS as regras; não repitas nenhum rejeitado."
                )
            else:
                feedback = (
                    "AVISO DO SISTEMA: A resposta veio com menos de 20 títulos candidatos válidos. "
                    "Devolve pelo menos 20 títulos que cumpram TODAS as regras do blueprint."
                )
    raise CreativeGenerationError(
        f"Após {attempts} tentativas, o provider não devolveu 20 títulos candidatos válidos "
        f"(última tentativa: {len(candidates)} válidos, {len(rejected)} rejeitados pelo blueprint)."
    )


def generate_thumbnail_prompt(
    settings: dict[str, Any],
    channel: dict[str, Any],
    topic: str,
    current_prompt: str = "",
    blueprint: dict[str, Any] | None = None,
    language: str = "",
) -> dict[str, Any]:
    """Create one image prompt while keeping visual direction and lettering separate."""
    topic = str(topic or "").strip()
    if not topic:
        raise CreativeGenerationError("É necessário um tópico para refazer o prompt da thumbnail.")
    context = channel_context(channel, blueprint)
    requested_language = language or channel.get("language") or context["language"]
    language_instruction = _language_instruction(requested_language)
    system = (
        "És um director de arte de thumbnails para YouTube. Refaz um prompt de imagem forte e específico "
        f"O overlay_text e todo o texto editorial devem estar em {language_instruction}; o image_prompt pode permanecer em inglês. "
        "para o tópico fornecido, mantendo a intenção visual quando já existir um prompt. "
        "Separa rigorosamente a imagem sem texto do lettering: image_prompt nunca deve pedir texto renderizado, "
        "enquanto overlay_text é obrigatório, deve ser curto, legível e ter entre três e quatro palavras. "
        "Responde apenas com JSON válido nas chaves concept, overlay_text, composition, color_palette, subject, "
        "image_prompt, title_synergy e lettering_prompt."
    )
    user = json.dumps(
        {
            "channel": context,
            "language": target_language(requested_language)[0],
            "language_name": target_language(requested_language)[1],
            "topic": topic,
            "current_prompt": str(current_prompt or "").strip(),
            "reference_rules": reference_bundle(blueprint),
            "requirements": {
                "image_prompt": "cinematic visual direction, no words, letters, logos or watermarks rendered in the image",
                "overlay_text": "required, 3 to 4 words, emotionally strong, not the full title",
                "lettering_prompt": "required instructions for rendering the exact overlay_text after the base image exists",
            },
        },
        ensure_ascii=False,
    )
    result = _chat_json(settings, system, user)
    image_prompt = str(result.get("image_prompt") or "").strip()
    if not image_prompt:
        raise CreativeGenerationError("O provider não devolveu um prompt de imagem válido.")
    overlay_text = _short_overlay(result.get("overlay_text")) or _short_overlay(topic) or "WATCH NOW"
    lettering_prompt = str(result.get("lettering_prompt") or "").strip() or (
        "Render the exact overlay_text as bold, readable, high-contrast sans-serif lettering with an outline or shadow, "
        "inside a safe zone and away from the main face or subject."
    )
    return {
        "concept": str(result.get("concept") or "Thumbnail renovada").strip(),
        "overlay_text": overlay_text,
        "composition": str(result.get("composition") or "").strip(),
        "color_palette": str(result.get("color_palette") or "").strip(),
        "subject": str(result.get("subject") or topic).strip(),
        "image_prompt": image_prompt,
        "title_synergy": str(result.get("title_synergy") or "").strip(),
        "lettering_prompt": lettering_prompt,
        "status": "prompt_ready",
    }


def generate_title_and_keywords(
    settings: dict[str, Any],
    channel: dict[str, Any],
    topic: str,
    blueprint: dict[str, Any] | None = None,
    language: str = "",
) -> dict[str, Any]:
    """Generate the editorial title and SEO keywords without generating thumbnail prompts."""
    if not topic.strip():
        raise CreativeGenerationError("É necessário um tópico ou briefing antes de gerar título e keywords.")
    context = channel_context(channel, blueprint)
    requested_language = language or channel.get("language") or context["language"]
    language_instruction = _language_instruction(requested_language)
    # System prompt DINÂMICO: as regras críticas do canal saem do Blueprint
    # activo (override, regras de título, blacklist, exemplos correctos),
    # nunca de um prompt genérico "YouTube Viral".
    governance = title_governance(blueprint)
    system = (
        "És um director editorial para YouTube. Cria apenas o pacote editorial do vídeo: títulos candidatos e keywords SEO. "
        f"Todos os títulos, fórmulas e campos editoriais textuais devem estar em {language_instruction}; as keywords podem permanecer em inglês para SEO. "
        "Não cries prompts, conceitos ou variantes de thumbnail. Gera exactamente pelo menos 20 títulos candidatos, "
        "um título seleccionado e entre 8 e 15 keywords curtas. O título deve carregar keywords no início, ter curiosidade, "
        "especificidade e emoção, sem clickbait falso."
    )
    governance_section = title_rules_prompt_section(governance)
    if governance_section:
        system += (
            "\n\n" + governance_section
            + "\n\nGera exactamente pelo menos 20 títulos candidatos que sigam ESTRITAMENTE estas regras — "
            "qualquer título que viole uma única regra é eliminado pelo validador."
        )
    system += " Responde apenas com JSON válido nas chaves selected_title, title_candidates e keywords."
    user_payload = {
        "channel": context,
        "language": target_language(requested_language)[0],
        "language_name": target_language(requested_language)[1],
        "topic": topic.strip(),
        "reference_rules": reference_bundle(blueprint),
        "keywords_schema": ["lista de 8 a 15 keywords SEO curtas, sem hashtags"],
        "title_candidates_schema": {
            "title": "string",
            "formula": "string",
            "curiosity_score": "integer 0-3",
            "specificity_score": "integer 0-3",
            "emotional_score": "integer 0-3",
        },
    }
    result, titles = _title_generation_loop(settings, system, user_payload, governance)
    selected_title = str(result.get("selected_title") or "").strip()
    if selected_title not in {item["title"] for item in titles}:
        selected_title = titles[0]["title"]
    raw_keywords = result.get("keywords")
    keywords = [str(item).strip() for item in raw_keywords if str(item).strip()] if isinstance(raw_keywords, list) else []
    if not keywords:
        keywords = _keywords_from_text(topic, selected_title)
    return {
        "title": selected_title,
        "title_candidates": titles,
        "keywords": keywords[:15],
        "topic_source": "llm",
        "generated_by": "configured_llm",
    }


def generate_creative_package(
    settings: dict[str, Any],
    channel: dict[str, Any],
    topic: str,
    blueprint: dict[str, Any] | None = None,
    language: str = "",
) -> dict[str, Any]:
    if not topic.strip():
        raise CreativeGenerationError("É necessário um tópico ou briefing antes de gerar título e thumbnail.")
    context = channel_context(channel, blueprint)
    requested_language = language or channel.get("language") or context["language"]
    language_instruction = _language_instruction(requested_language)
    # System prompt DINÂMICO: as regras críticas do canal saem do Blueprint
    # activo (override, regras de título, blacklist, exemplos correctos).
    governance = title_governance(blueprint)
    system = (
        "És director editorial e de thumbnails para YouTube. Cria um pacote coerente de título e thumbnail "
        f"Todos os títulos e textos visíveis da thumbnail devem estar em {language_instruction}; o image_prompt pode permanecer em inglês. "
        "para o tópico fornecido. Gera exactamente pelo menos 20 títulos candidatos e entre 3 e 5 variantes de thumbnail. "
        "O título deve carregar keywords no início, ter curiosidade, especificidade e emoção, sem clickbait falso. "
        "A thumbnail deve ter no máximo três elementos, alto contraste, uma composição clara e lettering obrigatório de 3 a 4 palavras, "
        "safe zones e leitura em 120px. O texto da thumbnail não pode repetir o título integralmente. Remove AI tells."
    )
    governance_section = title_rules_prompt_section(governance)
    if governance_section:
        system += (
            "\n\n" + governance_section
            + "\n\nGera exactamente pelo menos 20 títulos candidatos que sigam ESTRITAMENTE estas regras — "
            "qualquer título que viole uma única regra é eliminado pelo validador."
        )
    system += " Responde apenas com JSON válido nas chaves selected_title, title_candidates, keywords e thumbnail_variants."
    user_payload = {
        "channel": context,
        "language": target_language(requested_language)[0],
        "language_name": target_language(requested_language)[1],
        "topic": topic.strip(),
        "reference_rules": reference_bundle(blueprint),
        "keywords_schema": ["lista de 8 a 15 keywords SEO curtas, sem hashtags"],
        "title_candidates_schema": {
            "title": "string",
            "formula": "string",
            "curiosity_score": "integer 0-3",
            "specificity_score": "integer 0-3",
            "emotional_score": "integer 0-3",
        },
        "thumbnail_variant_schema": {
            "concept": "string",
            "overlay_text": "required string, 3 to 4 words",
            "composition": "string",
            "color_palette": "string",
            "subject": "string",
            "image_prompt": "string describing the clean image base, without rendered text; lettering is specified separately",
            "title_synergy": "string",
            "lettering_prompt": "string describing how to render the exact overlay_text",
        },
    }
    result, titles = _title_generation_loop(settings, system, user_payload, governance)
    raw_keywords = result.get("keywords")
    keywords = [str(item).strip() for item in raw_keywords if str(item).strip()] if isinstance(raw_keywords, list) else []
    selected_title = str(result.get("selected_title") or "").strip()
    if selected_title not in {item["title"] for item in titles}:
        selected_title = titles[0]["title"]
    if not keywords:
        keywords = _keywords_from_text(topic, selected_title)

    variants_raw = result.get("thumbnail_variants")
    if not isinstance(variants_raw, list) or len(variants_raw) < 3:
        raise CreativeGenerationError("O provider deve devolver pelo menos 3 variantes de thumbnail.")
    variants: list[dict[str, Any]] = []
    for item in variants_raw[:5]:
        if not isinstance(item, dict):
            continue
        if not str(item.get("concept") or "").strip() or not str(item.get("image_prompt") or "").strip():
            continue
        overlay_text = _short_overlay(item.get("overlay_text")) or _short_overlay(topic) or "WATCH NOW"
        lettering_prompt = str(item.get("lettering_prompt") or "").strip() or (
            "Render the exact overlay_text as bold, readable, high-contrast sans-serif lettering with an outline or shadow, "
            "inside a safe zone and away from the main face or subject."
        )
        variants.append(
            {
                "concept": str(item.get("concept") or "").strip(),
                "overlay_text": overlay_text,
                "composition": str(item.get("composition") or "").strip(),
                "color_palette": str(item.get("color_palette") or "").strip(),
                "subject": str(item.get("subject") or "").strip(),
                "image_prompt": str(item.get("image_prompt") or "").strip(),
                "title_synergy": str(item.get("title_synergy") or "").strip(),
                "lettering_prompt": lettering_prompt,
                "status": "prompt_ready",
            }
        )
    if len(variants) < 3:
        raise CreativeGenerationError("As variantes de thumbnail devolvidas pelo provider estão incompletas.")
    return {
        "title": selected_title,
        "title_candidates": titles,
        "keywords": keywords[:15],
        "thumbnail_variant": variants[0],
        "thumbnail_variants": variants,
        "thumbnail_status": "prompt_ready",
        "topic_source": "llm",
        "generated_by": "configured_llm",
    }


UGC_SEGMENT_SYSTEM_PROMPT = (
    "És um realizador de anúncios UGC de produto. Responde apenas com JSON válido no formato "
    "{\"segments\":[{\"prompt\":\"...\"},{\"prompt\":\"...\"}]}. "
    "Cria exactamente dois prompts para clips consecutivos de 8 segundos cada. "
    "Preserva exactamente o produto, embalagem, cores, logótipo e objectos visíveis na imagem; não inventes, removas ou alteres características. "
    "Descreve apenas acções fisicamente possíveis, continuidade visual entre segmentos, diálogo natural quando solicitado e nenhuma legenda, texto incorporado, watermark ou interface."
)


def _ugc_fallback_prompts(instructions: str) -> list[str]:
    base = str(instructions or "Apresentar o produto de forma clara, natural e convincente.").strip()
    return [
        f"Clip UGC 1 de 8 segundos. {base} Mostrar o produto exactamente como aparece na imagem, com enquadramento estável, luz natural e uma demonstração inicial fisicamente possível. Sem texto no vídeo, sem legendas e sem watermark.",
        f"Clip UGC 2 de 8 segundos, continuidade directa do clip anterior. {base} Completar a demonstração com uma reacção humana natural e uma apresentação final do produto, sem alterar os objectos visíveis. Sem texto no vídeo, sem legendas e sem watermark.",
    ]


def generate_ugc_segment_prompts(settings: dict[str, Any], instructions: str) -> list[str]:
    """Return exactly two safe VEO prompts, accepting an explicit `---` split without LLM."""
    clean = str(instructions or "").strip()
    explicit = [part.strip() for part in re.split(r"\n\s*(?:---|===|SEGMENTO\s*2)\s*\n", clean, flags=re.IGNORECASE) if part.strip()]
    if len(explicit) == 2:
        return [
            f"Clip UGC 1 de 8 segundos. {explicit[0]} Preserve a imagem do produto. Sem texto, legendas ou watermark.",
            f"Clip UGC 2 de 8 segundos, em continuidade. {explicit[1]} Preserve a imagem do produto. Sem texto, legendas ou watermark.",
        ]
    try:
        result = _chat_json(settings, UGC_SEGMENT_SYSTEM_PROMPT, clean or "Cria uma demonstração UGC curta e natural do produto.")
        raw_segments = result.get("segments")
        if isinstance(raw_segments, list):
            prompts = [str(item.get("prompt") or "").strip() for item in raw_segments if isinstance(item, dict)]
            prompts = [item for item in prompts if item]
            if len(prompts) >= 2:
                return [f"{item} Sem texto incorporado, sem legendas e sem watermark." for item in prompts[:2]]
    except CreativeGenerationError:
        pass
    return _ugc_fallback_prompts(clean)


def generate_video_update_metadata(
    settings: dict[str, Any],
    channel: dict[str, Any],
    video: dict[str, Any],
    *,
    script: str = "",
    blueprint: dict[str, Any] | None = None,
    mode: str = "both",
) -> dict[str, str]:
    """Generate reviewed metadata for an already-published YouTube video."""
    context = channel_context(channel, blueprint)
    language_instruction = _language_instruction(video.get("default_language") or channel.get("language") or context["language"])
    fields = {"title": "title", "description": "description"} if mode == "both" else {mode: mode}
    governance = title_governance(blueprint)
    system = (
        "És um editor de metadados de YouTube. Gera apenas os campos solicitados em JSON válido. "
        f"Escreve todos os campos em {language_instruction}. Mantém o tema, o roteiro e o nicho do canal, "
        "evita clickbait falso, alegações não verificadas e menções a IA. O título deve ser claro e ter no máximo 100 caracteres; "
        "a descrição deve ser natural, informativa e preservar factos fornecidos no roteiro."
    )
    if "title" in fields:
        governance_section = title_rules_prompt_section(governance)
        if governance_section:
            system += (
                "\n\n" + governance_section
                + "\n\nO título regenerado tem de cumprir ESTRITAMENTE estas regras do blueprint."
            )
    base_user_payload = {
        "requested_fields": list(fields.values()),
        "channel": context,
        "video": {"id": video.get("id"), "title": video.get("title", ""), "description": video.get("description", ""), "language": video.get("default_language", "")},
        "script": str(script or "")[:12000],
        "requirements": {"title_max_characters": 100, "description_max_characters": 1800},
    }
    feedback = ""
    reason = ""
    title_is_valid = "title" not in fields
    result: dict[str, Any] = {}
    attempts = max(1, MAX_TITLE_GENERATION_ATTEMPTS)
    for attempt in range(1, attempts + 1):
        payload = dict(base_user_payload)
        if feedback:
            payload["system_feedback"] = feedback
        result = _chat_json(settings, system, json.dumps(payload, ensure_ascii=False))
        if "title" not in fields:
            break
        candidate = str(result.get("title") or "").strip()
        title_is_valid, reason = validate_title_with_governance(candidate, governance)
        if title_is_valid:
            break
        if attempt < attempts:
            feedback = (
                f"AVISO DO SISTEMA: O título «{candidate}» foi REJEITADO pelo validador do blueprint. "
                f"Motivo: {reason}. Gera um novo título que cumpra TODAS as regras."
            )
    if not title_is_valid:
        raise CreativeGenerationError(
            f"Após {attempts} tentativas, o título regenerado não cumpre as regras do blueprint. Último motivo: {reason}"
        )
    output: dict[str, str] = {}
    if "title" in fields:
        title = str(result.get("title") or "").strip()[:100]
        if not title:
            raise CreativeGenerationError("O provider não devolveu um título válido.")
        output["title"] = title
    if "description" in fields:
        description = str(result.get("description") or "").strip()[:1800]
        if not description:
            raise CreativeGenerationError("O provider não devolveu uma descrição válida.")
        output["description"] = description
    return output
