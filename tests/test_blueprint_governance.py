"""Governança dinâmica de Blueprint (1.1.x).

O motor de geração lê as regras do JSON do blueprint activo e obedece:
- system prompt dinâmico (override, regras de título, blacklist, exemplos);
- hard validation em código de cada título gerado (guardrails);
- loop de auto-correcção com feedback quando o LLM viola as regras;
- referências genéricas de título omitidas quando o blueprint tem as suas;
- roteiros validados contra a extensão obrigatória do blueprint (7000–9000).

Os testes usam os blueprints REAIS do seed (Oração, FINANCE USA) para provar
que não há hardcoding: as regras saem do próprio JSON de cada nicho.

1.0.17: o Blueprint Oração foi substituído pela versão corrigida do autor —
blacklist EXPLÍCITA (metadata.GLOBAL_BLACKLIST_WORDS inclui «sleep»), máximo
de 6 palavras no título, extensão obrigatória em FRASE e tom gospel explícito;
os guardrails de TTS/legendas vivem em test_script_tts_guardrails.py.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_ui import creative_generation, script_generation
from hermes_ui.blueprint_governance import (
    DEFAULT_MAX_TITLE_WORDS,
    MAX_SCRIPT_GENERATION_ATTEMPTS,
    MAX_TITLE_GENERATION_ATTEMPTS,
    has_blueprint_title_rules,
    script_governance,
    title_governance,
    validate_generated_title,
)
from hermes_ui.creative_generation import (
    CreativeGenerationError,
    generate_creative_package,
    generate_title_and_keywords,
    generate_video_update_metadata,
    reference_bundle,
)
from hermes_ui.script_generation import generate_script_document


ROOT = Path(__file__).resolve().parents[1]


def _blueprint(name: str) -> dict:
    return json.loads((ROOT / "seed" / "blueprints" / name).read_text(encoding="utf-8"))


def _settings():
    return {"llm_provider": "openai", "openai_api_key": "test-key", "openai_base_url": "https://llm.example/v1", "openai_model_name": "test-model"}


def _channel():
    return {"id": "channel_1", "name": "Grace for Purpose", "description": "Oração e devoção", "language": "en", "default_blueprint_id": "oracao"}


def _titles_payload(titles):
    return {
        "selected_title": titles[0] if titles else "",
        "title_candidates": [
            {"title": title, "formula": "custom", "curiosity_score": 2, "specificity_score": 2, "emotional_score": 2}
            for title in titles
        ],
        "keywords": ["prayer", "faith"],
    }


def _variants_payload():
    variant = {
        "concept": "Conceito",
        "overlay_text": "GOD IS GREATER",
        "composition": "sujeito central",
        "color_palette": "azul e dourado",
        "subject": "orante",
        "image_prompt": "YouTube thumbnail, no text",
        "title_synergy": "complementa o título",
        "lettering_prompt": "render overlay",
    }
    return [dict(variant) for _ in range(3)]


# ---------------------------------------------------------------------------
# Derivação e validação (blueprint Oração real, sem hardcoding)
# ---------------------------------------------------------------------------


def test_oracao_validator_rejects_reported_failure_titles():
    blueprint = _blueprint("BlueprintOração.json")
    failures = [
        "Night Prayer for Anxiety",
        "A Nighttime Prayer for Overthinking",
        "Bedtime Prayer to Release Anxiety",
        "Why Common Daily Prayers Often Fail",
        "How to Genuinely Reconnect with God",
        "Overwhelmed at Night? This Prayer Stops Racing Thoughts Instantly",
        "Release Worry and Sleep in God's Peace Tonight",
        "A scripture-based morning prayer for peace when the day already feels heavy, spoken calmly over soft music and sunrise nature footage",
    ]
    for title in failures:
        valid, reason = validate_generated_title(title, blueprint)
        assert not valid, f"«{title}» devia ser rejeitado ({reason})"


def test_oracao_validator_accepts_canonical_titles():
    blueprint = _blueprint("BlueprintOração.json")
    canonical = [
        "Peace Beyond Pressure",
        "The Strength You Carry",
        "Put God First",
        "When God Says Wait",
        "A House Built on The Rock",
        "A Hunger For His Word",
        "Doors That Only God Can Open",
        "Anointed By The Spirit",
        "The Power of The Name",
        "Release The Outcome",
    ]
    for title in canonical:
        valid, reason = validate_generated_title(title, blueprint)
        assert valid, f"«{title}» devia ser aceite ({reason})"


def test_oracao_blacklist_now_bans_the_former_sleep_canonical():
    """1.0.17: o blueprint corrigido bane globalmente «sleep» (o canal saiu do
    nicho bedtime) — o antigo canónico «He Gives His Beloved Sleep» é rejeitado
    pela blacklist EXPLÍCITA do metadata.GLOBAL_BLACKLIST_WORDS."""
    blueprint = _blueprint("BlueprintOração.json")
    valid, reason = validate_generated_title("He Gives His Beloved Sleep", blueprint)
    assert not valid
    assert "sleep" in reason


def test_oracao_governance_derives_rules_from_the_json():
    blueprint = _blueprint("BlueprintOração.json")
    governance = title_governance(blueprint)
    assert governance["active"] is True
    assert has_blueprint_title_rules(blueprint) is True
    # 1.0.17: blacklist EXPLÍCITA de metadata.GLOBAL_BLACKLIST_WORDS (o
    # blueprint corrigido deixa de derivar as palavras de listas entre
    # parênteses — as regras saem literalmente do JSON do autor).
    blacklist = " ".join(governance["blacklist_words"]).casefold()
    for word in ("meditation", "yoga", "mindfulness", "nighttime", "bedtime", "anxiety", "sleep"):
        assert word in blacklist, f"'{word}' devia constar da blacklist"
    # 1.0.17: o blueprint corrigido fixa o máximo em 6 palavras (era o default 15).
    assert governance["max_word_count"] == 6
    templates = " | ".join(template["literal"] for template in governance["forbidden_templates"])
    assert "A [type] Prayer for [problem]" in templates
    assert "Why" in governance["forbidden_starts"]
    assert "How" in governance["forbidden_starts"]
    # calibração: 'The'/'A' iniciais não podem estar banidos — os canónicos começam assim
    assert "The" not in governance["forbidden_starts"]
    assert "A" not in governance["forbidden_starts"]
    # exemplos correctos injectados no prompt
    assert "Peace Beyond Pressure" in governance["correct_examples"]


def test_finance_governance_does_not_block_its_own_titles():
    blueprint = _blueprint("FINANCE USA.json")
    governance = title_governance(blueprint)
    assert governance["active"] is True
    assert not governance["forbidden_starts"]
    for title in (
        "The Math That Will Blow Your Mind",
        "They Are About to Reset Your Savings",
        "If You Want to Invest, This Is What to Do",
    ):
        valid, reason = validate_generated_title(title, blueprint)
        assert valid, f"«{title}»: {reason}"


def test_word_cap_applies_even_without_blueprint():
    long_title = " ".join(["palavra"] * (DEFAULT_MAX_TITLE_WORDS + 1))
    valid, reason = validate_generated_title(long_title, None)
    assert not valid
    assert f"limite máximo é {DEFAULT_MAX_TITLE_WORDS}" in reason


def test_minimal_blueprint_is_inactive_but_keeps_word_cap():
    minimal = {"id": "bp-history", "name": "História"}
    governance = title_governance(minimal)
    assert governance["active"] is False
    assert not governance["blacklist_words"]
    assert not governance["forbidden_starts"]
    assert not governance["forbidden_templates"]
    valid, _ = validate_generated_title("Título livre de exemplo", minimal)
    assert valid


def test_explicit_override_fields_win_over_derivation():
    blueprint = {
        "SYSTEM_PROMPT_OVERRIDE": "Directriz especial do canal.",
        "GLOBAL_TONE_DIRECTIVE": "Isto é um canal devocional, não de terapia do sono.",
        "metadata": {"GLOBAL_BLACKLIST_WORDS": ["segredo"]},
        "title_analysis": {"title_mechanics": {"absolute_rules": ["Regra explícita"], "max_word_count": 6}},
    }
    governance = title_governance(blueprint)
    assert governance["system_prompt_override"] == "Directriz especial do canal."
    assert governance["absolute_rules"] == ["Regra explícita"]
    assert "segredo" in governance["blacklist_words"]
    assert governance["max_word_count"] == 6
    valid, reason = validate_generated_title("O grande segredo revelado", blueprint)
    assert not valid and "segredo" in reason
    script = script_governance(blueprint)
    assert script["tone_directive"] == "Isto é um canal devocional, não de terapia do sono."
    assert "segredo" in script["blacklist_words"]


# ---------------------------------------------------------------------------
# Referências genéricas: sem prompt bleed
# ---------------------------------------------------------------------------


def test_reference_bundle_skips_title_formulas_for_rule_blueprints():
    blueprint = _blueprint("BlueprintOração.json")
    assert "[title_formulas]" not in reference_bundle(blueprint)
    assert "[viral_titles]" not in reference_bundle(blueprint)
    # as referências de thumbnail/humanização continuam a aplicar-se
    assert "[thumbnail_checklist]" in reference_bundle(blueprint)
    # sem regras próprias → bundle completo (retrocompatível)
    assert "[title_formulas]" in reference_bundle()
    assert "[title_formulas]" in reference_bundle({"id": "bp", "name": "x"})


# ---------------------------------------------------------------------------
# Loop de auto-correcção de títulos
# ---------------------------------------------------------------------------


def test_title_generation_retries_with_feedback_until_valid(monkeypatch):
    blueprint = _blueprint("BlueprintOração.json")
    calls = []

    def fake_chat(settings, system, user):
        calls.append({"system": system, "user": json.loads(user)})
        if len(calls) == 1:
            return _titles_payload([f"Night Prayer for Anxiety {index}" for index in range(20)])
        return _titles_payload([f"Peace Beyond Pressure {index}" for index in range(20)])

    monkeypatch.setattr(creative_generation, "_chat_json", fake_chat)
    result = generate_title_and_keywords(_settings(), _channel(), "peace under pressure", blueprint)

    assert len(calls) == 2
    feedback = calls[1]["user"]["system_feedback"]
    assert "REJEITADOS" in feedback
    assert "Night Prayer for Anxiety" in feedback
    # o system prompt transporta a lei do canal
    assert "REGRAS DE TÍTULO DO BLUEPRINT" in calls[1]["system"]
    assert "Peace Beyond Pressure" in calls[1]["system"]
    assert "PALAVRAS/EXPRESSÕES TERMINANTEMENTE PROIBIDAS" in calls[1]["system"]
    # nenhum rejeitado sobrevive na lista final
    assert result["title"] == "Peace Beyond Pressure 0"
    assert len(result["title_candidates"]) == 20
    assert all("Anxiety" not in item["title"] for item in result["title_candidates"])


def test_title_generation_hard_fails_after_max_attempts(monkeypatch):
    blueprint = _blueprint("BlueprintOração.json")
    calls = []

    def fake_chat(settings, system, user):
        calls.append(user)
        return _titles_payload([f"Night Prayer for Anxiety {index}" for index in range(20)])

    monkeypatch.setattr(creative_generation, "_chat_json", fake_chat)
    with pytest.raises(CreativeGenerationError, match="20 títulos"):
        generate_title_and_keywords(_settings(), _channel(), "peace", blueprint)
    assert len(calls) == MAX_TITLE_GENERATION_ATTEMPTS


def test_creative_package_retry_flow_keeps_valid_titles_and_variants(monkeypatch):
    blueprint = _blueprint("BlueprintOração.json")
    calls = []

    def fake_chat(settings, system, user):
        calls.append(json.loads(user))
        if len(calls) == 1:
            return {**_titles_payload([f"Night Prayer for Anxiety {index}" for index in range(20)]), "thumbnail_variants": _variants_payload()}
        return {**_titles_payload([f"The Strength You Carry {index}" for index in range(20)]), "thumbnail_variants": _variants_payload()}

    monkeypatch.setattr(creative_generation, "_chat_json", fake_chat)
    result = generate_creative_package(_settings(), _channel(), "strength", blueprint)

    assert len(calls) == 2
    assert result["title"] == "The Strength You Carry 0"
    assert len(result["title_candidates"]) == 20
    assert all("Anxiety" not in item["title"] for item in result["title_candidates"])
    assert len(result["thumbnail_variants"]) == 3
    assert result["thumbnail_status"] == "prompt_ready"


# ---------------------------------------------------------------------------
# Roteiros: extensão obrigatória do blueprint (7000–9000) validada em código
# ---------------------------------------------------------------------------


def test_oracao_script_governance_extracts_channel_law():
    blueprint = _blueprint("BlueprintOração.json")
    governance = script_governance(blueprint)
    # 1.0.17: o intervalo vem da FRASE «STRICTLY 7,000–9,000 characters» — o
    # blueprint corrigido já não traz a lista strict_character_range.
    assert governance["strict_character_range"] == (7000, 9000)
    assert governance["length_compliance_mandatory"] is True
    # 1.0.17: tom gospel EXPLÍCITO do metadata.GLOBAL_TONE_DIRECTIVE (não
    # derivado da persona) e CTA do generation_instructions.cta_pattern.
    assert "GOSPEL PRAYER" in governance["tone_directive"]
    assert "This is Daniel" in governance["mandatory_cta"]
    # 1.0.17: formato para TTS + requisitos visuais saem do próprio JSON.
    assert any("[Visual" in rule for rule in governance["format_rules"])
    assert "Waves" in governance["visual_requirements"]["prompt_keywords"]
    assert "People" in governance["visual_requirements"]["blacklist_keywords"]


def test_script_length_guardrail_retries_until_compliant(monkeypatch):
    """1.0.45 — REGRA INVIOLÁVEL: a extensão do blueprint NUNCA manda no roteiro.

    O canal (tempo médio) é a única fonte de verdade: um roteiro curto
    NÃO é rejeitado por contagem de caracteres — o alvo de palavras é
    injectado no topo do prompt e a lei de tom do blueprint permanece.
    """
    blueprint = _blueprint("BlueprintOração.json")
    calls = []

    def fake_chat(settings, system, user):
        calls.append({"system": system, "user": json.loads(user)})
        return {"title": "Christ In You Is Greater", "summary": "s", "content": "x" * 500}

    monkeypatch.setattr(script_generation, "_chat_json", fake_chat)
    result = generate_script_document(
        _settings(),
        document_type="Roteiro de vídeo",
        title="Christ In You Is Greater",
        brief="identity in Christ",
        language="en",
        channel=_channel(),
        blueprint=blueprint,
        generation_settings={"target_word_count": 1200},
    )

    # Sem retry por caracteres: uma chamada basta (o validador deixou de
    # impor a range do blueprint).
    assert len(calls) == 1
    system = calls[0]["system"]
    # O alvo do canal (settings do canal ou tempo médio) está no prompt…
    assert "1,200 palavras" in system
    assert "[INSTRUÇÃO DE TAMANHO OBRIGATÓRIA]" in system
    # …e a range do blueprint desapareceu (sanitização 1.0.45).
    assert "7000" not in system
    assert "EXTENSÃO OBRIGATÓRIA" not in system
    assert "STRICTLY" not in system
    # A lei do canal que não é de tamanho permanece intacta.
    assert "This is Daniel" in system
    assert len(result["content"]) == 500


def test_script_length_guardrail_hard_fails(monkeypatch):
    """1.0.45 — o roteiro curto NUNCA mais falha por contagem de caracteres."""
    blueprint = _blueprint("BlueprintOração.json")
    calls = []

    def fake_chat(settings, system, user):
        calls.append({"system": system, "user": json.loads(user)})
        return {"title": "t", "summary": "s", "content": "x" * 500}

    monkeypatch.setattr(script_generation, "_chat_json", fake_chat)
    # Sem canal explícito: o padrão do canal (20:00) é a fonte única.
    result = generate_script_document(
        _settings(),
        document_type="Roteiro de vídeo",
        title="Christ In You Is Greater",
        brief="identity",
        language="en",
        blueprint=blueprint,
    )
    assert result["content"] == "x" * 500
    assert len(calls) == 1
    # A range de caracteres do blueprint não chega ao prompt.
    assert "EXTENSÃO OBRIGATÓRIA" not in calls[0]["system"]
    assert "7000" not in calls[0]["system"]
    assert "STRICTLY" not in calls[0]["system"]


def test_script_without_blueprint_range_keeps_word_count_reference(monkeypatch):
    captured = {}

    def fake_chat(settings, system, user):
        captured["system"] = system
        return {"title": "t", "summary": "s", "content": "# Roteiro"}

    monkeypatch.setattr(script_generation, "_chat_json", fake_chat)
    generate_script_document(
        _settings(),
        document_type="Roteiro de vídeo",
        title="As muralhas esquecidas",
        brief="Explicar o mistério de uma cidade antiga.",
        language="01 — Inglês",
        channel={"id": "c", "name": "History Vault"},
        blueprint={"id": "bp-history", "name": "História"},
        generation_settings={"target_word_count": 900},
    )
    # 1.0.45: sem range no blueprint, o alvo de palavras do canal lidera
    # (instrução obrigatória no topo) — e a range continua ausente.
    assert "900 palavras" in captured["system"]
    assert "EXTENSÃO OBRIGATÓRIA" not in captured["system"]
    assert "STRICTLY" not in captured["system"]


# ---------------------------------------------------------------------------
# Metadados de vídeos publicados: o título regenerado também é validado
# ---------------------------------------------------------------------------


def test_update_metadata_validates_regenerated_title(monkeypatch):
    blueprint = _blueprint("BlueprintOração.json")
    calls = []

    def fake_chat(settings, system, user):
        calls.append(json.loads(user))
        if len(calls) == 1:
            return {"title": "Night Prayer for Anxiety", "description": "descrição"}
        return {"title": "Peace Beyond Pressure", "description": "descrição"}

    monkeypatch.setattr(creative_generation, "_chat_json", fake_chat)
    output = generate_video_update_metadata(
        _settings(),
        _channel(),
        {"id": "video-1", "title": "antigo", "description": "antiga", "default_language": "en"},
        blueprint=blueprint,
        mode="both",
    )
    assert len(calls) == 2
    assert "REJEITADO" in calls[1]["system_feedback"]
    assert output["title"] == "Peace Beyond Pressure"
    assert output["description"] == "descrição"


def test_update_metadata_hard_fails_on_invalid_title(monkeypatch):
    blueprint = _blueprint("BlueprintOração.json")

    def fake_chat(settings, system, user):
        return {"title": "Night Prayer for Anxiety"}

    monkeypatch.setattr(creative_generation, "_chat_json", fake_chat)
    with pytest.raises(CreativeGenerationError, match="blueprint"):
        generate_video_update_metadata(
            _settings(),
            _channel(),
            {"id": "video-1", "title": "antigo", "default_language": "en"},
            blueprint=blueprint,
            mode="title",
        )
