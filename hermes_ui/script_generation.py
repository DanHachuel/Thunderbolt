"""Blueprint-aware generation of video scripts and music lyrics."""

from __future__ import annotations

import json
from typing import Any

from .blueprint_governance import (
    MAX_SCRIPT_GENERATION_ATTEMPTS,
    script_governance,
    script_rules_prompt_section,
    title_governance,
    validate_script_content,
    validate_title_with_governance,
)
from .blueprint_length_guard import (
    channel_length_instruction,
    length_instruction_for_words,
    sanitize_blueprint_for_prompt,
    strip_length_governance,
)
from .creative_generation import CreativeGenerationError, _chat_json, channel_context, target_language
from .video_length import channel_video_length


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
    channel_persona / role_enforcement), must_avoid, must_include e CTA
    obrigatório são injectados no system prompt. 1.0.45 — REGRA INVIOLÁVEL
    (AGENTS.md): o ``average_video_time`` do canal é a ÚNICA fonte de verdade
    para o tamanho do roteiro; as regras de contagem de caracteres dos
    Blueprints são REMOVIDAS antes de qualquer ida à LLM
    (``sanitize_blueprint_for_prompt``) e a instrução de tamanho do canal vai
    no TOPO do system prompt (``channel_length_instruction``).
    """
    normalized_type = DOCUMENT_TYPES.get(document_type, document_type)
    if normalized_type not in {"video_script", "music_lyrics"}:
        raise CreativeGenerationError("Escolha Roteiro de vídeo ou Letra de música.")
    if not brief.strip():
        raise CreativeGenerationError("Escreva um tema ou briefing antes de gerar o documento.")

    channel = channel or {}
    # 1.0.45 — SANITIZAÇÃO: as chaves de comprimento do blueprint NUNCA
    # chegam à LLM (a qualquer profundidade). O original fica intacto para
    # títulos/visuais; tudo o que segue usa a cópia limpa.
    blueprint_payload = sanitize_blueprint_for_prompt(blueprint or {})
    channel_context_value = channel_context(channel, blueprint_payload)
    requested_language = language or channel_context_value["language"]
    language_code, language_name = target_language(requested_language)
    generation_settings_payload = generation_settings or {}
    governance: dict[str, Any] = {}
    length_instruction = ""
    if normalized_type == "video_script":
        # 1.0.45 — a governança de roteiro perde as regras de comprimento
        # (sem secção «EXTENSÃO OBRIGATÓRIA», sem validação dura de caracteres).
        governance = strip_length_governance(script_governance(blueprint_payload))
        # 1.0.45 — o tamanho vem do canal: o ``target_word_count`` explícito
        # (derivado do Tempo Médio do cartão) vence o padrão; NUNCA suprimido
        # por regra de blueprint.
        target_word_count = int(generation_settings_payload.get("target_word_count") or 0)
        length_instruction, _instruction_words, _instruction_duration = channel_length_instruction(channel)
        if target_word_count:
            length_instruction, _words, _duration = length_instruction_for_words(
                target_word_count, _instruction_duration
            )
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
        # 1.0.45 — a instrução de tamanho do canal vai no TOPO do prompt:
        # antes de tudo, com a ordem explícita de ignorar restrições
        # residuais de tamanho do Blueprint (regra imutável).
        if length_instruction:
            system = length_instruction + "\n\n" + system
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
    # 1.0.23: o TÍTULO do roteiro também é gerado e vira o título do vídeo
    # (rascunhos → pipeline) — validado pela lei do blueprint como qualquer
    # título (guardrails 1.0.11), no mesmo loop de auto-correcção.
    title_governance_value = title_governance(blueprint_payload) if normalized_type == "video_script" else {}
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
            title_valid, title_reason = validate_title_with_governance(
                str(result.get("title") or ""), title_governance_value
            )
            if not title_valid:
                valid = False
                reason = f"o título «{result.get('title')}» viola as regras de título do blueprint ({title_reason})"
        if valid:
            break
        if attempt < attempts:
            feedback = (
                f"AVISO DO SISTEMA: O roteiro anterior foi REJEITADO pelo validador do blueprint. "
                f"Motivo: {reason}. Reescreve o roteiro integralmente, cumprindo a extensão obrigatória "
                "e todas as regras do blueprint (incluindo as regras de TÍTULO)."
            )
    if normalized_type == "video_script" and not valid:
        raise CreativeGenerationError(
            f"Após {attempts} tentativas, o roteiro não cumpre as regras do blueprint. Último motivo: {reason}"
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
