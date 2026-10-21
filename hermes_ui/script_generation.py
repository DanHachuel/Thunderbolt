"""Blueprint-aware generation of video scripts and music lyrics."""

from __future__ import annotations

import json
from typing import Any

from .blueprint_governance import (
    MAX_SCRIPT_GENERATION_ATTEMPTS,
    script_governance,
    script_rules_prompt_section,
    validate_script_content,
)
from .creative_generation import CreativeGenerationError, _chat_json, channel_context, target_language


DOCUMENT_TYPES = {
    "Roteiro de vídeo": "video_script",
    "Letra de música": "music_lyrics",
}


def generate_script_document(
    settings: dict[str, Any],
    *,
    document_type: str,
    title: str,
    brief: str,
    language: str,
    channel: dict[str, Any] | None = None,
    blueprint: dict[str, Any] | None = None,
    structure_notes: str = "",
    generation_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate an editable Markdown document from the configured LLM.

    The function deliberately returns text only. It never writes to storage; the UI
    decides whether the generated draft should be saved after the user reviews it.

    1.1.x — o Blueprint activo é a lei do canal: tom (GLOBAL_TONE_DIRECTIVE /
    channel_persona / role_enforcement), extensão obrigatória
    (metadata.strict_character_range + length_compliance_mandatory), must_avoid,
    must_include e CTA obrigatório são injectados no system prompt e a extensão
    é VALIDADA EM CÓDIGO, com loop de auto-correcção quando falha.
    """
    normalized_type = DOCUMENT_TYPES.get(document_type, document_type)
    if normalized_type not in {"video_script", "music_lyrics"}:
        raise CreativeGenerationError("Escolha Roteiro de vídeo ou Letra de música.")
    if not brief.strip():
        raise CreativeGenerationError("Escreva um tema ou briefing antes de gerar o documento.")

    channel_context_value = channel_context(channel or {}, blueprint or {})
    requested_language = language or channel_context_value["language"]
    language_code, language_name = target_language(requested_language)
    blueprint_payload = blueprint or {}
    generation_settings_payload = generation_settings or {}
    governance: dict[str, Any] = {}
    if normalized_type == "video_script":
        governance = script_governance(blueprint_payload)
        target_word_count = generation_settings_payload.get("target_word_count")
        # Quando o blueprint fixa uma extensão OBRIGATÓRIA em caracteres, ela
        # substitui a referência média de palavras (nunca enviar as duas).
        length_is_mandatory = bool(governance.get("length_compliance_mandatory")) and governance.get("strict_character_range") is not None
        output_requirements = {
            "content": "roteiro completo em Markdown: título, gancho e narração integral; directivas visuais/sonoras apenas em linhas de marcação próprias ([VISUAL]/[ÁUDIO] isoladas)",
            "summary": "resumo editorial em uma frase",
        }
        system = (
            "És um roteirista editorial de vídeos faceless. Cria um roteiro original, natural e executável, "
            f"escrevendo título, resumo e conteúdo integralmente em {language_name} ({language_code}). "
            "alinhado exclusivamente ao nicho e às regras do Blueprint fornecido — o Blueprint é a LEI do canal: "
            "cumpre a sua persona, arquitectura de roteiro, extensão, must_include e must_avoid. "
            "Não inventes factos sensíveis, não uses introduções genéricas, não escrevas comentários sobre IA e não incluas um CTA vazio. "
            # 1.0.17: o texto falado é lido DIRECTAMENTE por um TTS e vira legendas
            # (.srt) — tags de produção inline eram lidas em voz alta e queimadas
            # nas legendas. A regra aplica-se a TODOS os canais; o
            # script_format_rules do blueprint pode agravá-la (100% falado).
            "O texto falado é lido DIRECTAMENTE por um TTS e vira legendas: NUNCA escrevas tags de produção "
            "inline («[Visual: ...]», «[Audio: ...]», «[SFX]», «SCENE 1», «NARRATOR:») no meio das frases — "
            "se incluíres directivas visuais/sonoras, usa linhas de marcação isoladas ([VISUAL]/[ÁUDIO]); "
            "todo o restante é apenas narração falada. "
        )
        if target_word_count and not length_is_mandatory:
            system += f"Escreve aproximadamente {int(target_word_count)} palavras; trata este valor como uma referência média e não como um limite rígido. "
        governance_section = script_rules_prompt_section(governance)
        if governance_section:
            system += "\n\n" + governance_section
        system += "Responde apenas com JSON válido nas chaves title, summary e content."
    else:
        output_requirements = {
            "content": "letra completa em Markdown, com secções [Verso], [Pré-refrão], [Refrão], [Ponte] quando fizer sentido",
            "summary": "resumo da intenção musical em uma frase",
        }
        system = (
            "És um compositor de letras originais. Cria uma letra cantável, coerente com o tema, idioma, "
            f"escrevendo título, resumo e conteúdo integralmente em {language_name} ({language_code}). "
            "Blueprint e direcção musical fornecidos. Não copies letras existentes, não cites artistas sem pedido "
            "e não acrescentes explicações dentro da letra. Responde apenas com JSON válido nas chaves title, summary e content."
        )

    user_payload = {
        "document_type": normalized_type,
        "requested_title": title.strip(),
        "brief": brief.strip(),
        "language": language_code,
        "language_name": language_name,
        "channel": channel_context_value,
        "blueprint": blueprint_payload,
        "structure_notes": structure_notes.strip(),
        "generation_settings": generation_settings_payload,
        "output_requirements": output_requirements,
    }
    feedback = ""
    content = ""
    result: dict[str, Any] = {}
    valid = True
    reason = ""
    attempts = MAX_SCRIPT_GENERATION_ATTEMPTS if normalized_type == "video_script" else 1
    for attempt in range(1, attempts + 1):
        payload = dict(user_payload)
        if feedback:
            payload["system_feedback"] = feedback
        result = _chat_json(settings, system, json.dumps(payload, ensure_ascii=False))
        content = str(result.get("content") or "").strip()
        if not content:
            raise CreativeGenerationError("O provider LLM devolveu um documento sem conteúdo.")
        if normalized_type != "video_script":
            break
        valid, reason = validate_script_content(content, governance)
        if valid:
            break
        if attempt < attempts:
            feedback = (
                f"AVISO DO SISTEMA: O roteiro anterior foi REJEITADO pelo validador do blueprint. "
                f"Motivo: {reason}. Reescreve o roteiro integralmente, cumprindo a extensão obrigatória "
                "e todas as regras do blueprint."
            )
    if normalized_type == "video_script" and not valid:
        raise CreativeGenerationError(
            f"Após {attempts} tentativas, o roteiro não cumpre a extensão exigida pelo blueprint. Último motivo: {reason}"
        )
    return {
        "document_type": normalized_type,
        "title": str(result.get("title") or title or brief).strip(),
        "summary": str(result.get("summary") or "").strip(),
        "content": content,
        "language": language_code,
        "blueprint_id": str(blueprint_payload.get("id") or ""),
        "blueprint_name": str(blueprint_payload.get("name") or "SEM BLUEPRINT CONFIGURADO"),
        "channel_id": str((channel or {}).get("id") or ""),
        "channel_name": str((channel or {}).get("name") or "Documento independente"),
        "generation_settings": generation_settings_payload,
        "generated_by": "configured_llm",
    }
