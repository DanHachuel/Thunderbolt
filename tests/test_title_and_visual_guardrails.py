"""Guardrails de título/tema + prompts visuais em TODOS os pontos (1.0.23).

O utilizador reportou: título «Sleep in Peace: Pray Psalm 4:8 to Release Your
Worries Tonight» (11 palavras, sleep/worries) gerado pela UI, thumbnails com
«não tem um prompt de imagem» e imagens com humanos. Causas: o TEMA gerado
(que vira título em vários caminhos) e o TÍTULO do roteiro não passavam pelo
validador; o fluxo editorial marcava «prompt_ready» sem prompt; o LLM da
thumbnail podia devolver image_prompt vazio; e o FALLBACK das cenas ignorava
a lei visual (permitia humanos contra o blueprint).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_ui import creative_generation, script_generation, text_to_images
from hermes_ui.blueprint_governance import (
    validate_generated_title,
    visual_requirements_fallback_suffix,
)
from hermes_ui.creative_generation import (
    CreativeGenerationError,
    generate_thumbnail_prompt,
    generate_topic_for_channel,
)
from hermes_ui.script_generation import generate_script_document


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
ORACAO = json.loads((ROOT / "seed" / "blueprints" / "BlueprintOração.json").read_text(encoding="utf-8"))


def _settings():
    return {"llm_provider": "openai", "openai_api_key": "test-key", "openai_base_url": "https://llm.example/v1", "openai_model_name": "test-model"}


def _channel():
    return {"id": "channel_1", "name": "Grace for Purpose", "description": "Oração", "language": "en", "default_blueprint_id": "oracao"}


def _briefing(topic):
    return {
        "topic": topic,
        "angle": "identity in Christ",
        "hook": "the first seconds",
        "niche": "prayer",
        "rationale": "coerente com o canal",
    }


# ---------------------------------------------------------------------------
# Morfologia: y→ies — «Worries» e «Anxieties» já não escapam
# ---------------------------------------------------------------------------


def test_blacklist_catches_y_to_ies_plurals():
    ok, reason = validate_generated_title("Release Your Worries Tonight", ORACAO)
    assert not ok and "worry" in reason.casefold()
    ok, reason = validate_generated_title("Overcome Your Anxieties", ORACAO)
    assert not ok and "anxiety" in reason.casefold()
    # singular continua a funcionar
    ok, _ = validate_generated_title("Release Your Worry", ORACAO)
    assert not ok


def test_the_reported_evidence_title_is_rejected_on_every_criterion():
    title = "Sleep in Peace: Pray Psalm 4:8 to Release Your Worries Tonight"
    ok, reason = validate_generated_title(title, ORACAO)
    assert not ok
    assert "11 palavras" in reason  # max_word_count: 6 do blueprint
    ok, reason = validate_generated_title(title[:23], ORACAO)  # «Sleep in Peace: Pray »
    # mesmo curto, sleep está na blacklist explícita
    assert not ok


def test_worry_is_now_in_the_explicit_blacklist_of_both_copies():
    for path in (
        ROOT / "seed" / "blueprints" / "BlueprintOração.json",
        ROOT / "storage" / "blueprints" / "importados" / "BlueprintOração.json",
    ):
        data = json.loads(path.read_text(encoding="utf-8"))
        words = [str(item).casefold() for item in data.get("metadata", {}).get("GLOBAL_BLACKLIST_WORDS", [])]
        assert "worry" in words, f"'worry' em falta em {path}"


# ---------------------------------------------------------------------------
# O TEMA gerado é validado como título (vira título em vários caminhos)
# ---------------------------------------------------------------------------


def test_generated_topic_is_validated_with_retry_and_feedback(monkeypatch):
    calls = []

    def fake_chat(settings, system, user):
        calls.append({"system": system, "user": json.loads(user)})
        if len(calls) == 1:
            return _briefing("Sleep in Peace: Pray Psalm 4:8 to Release Your Worries Tonight")
        return _briefing("Peace Beyond Pressure")

    monkeypatch.setattr(creative_generation, "_chat_json", fake_chat)
    result = generate_topic_for_channel(_settings(), _channel(), ORACAO)

    assert len(calls) == 2
    assert "REJEITADO" in calls[1]["user"]["system_feedback"]
    assert result["topic"] == "Peace Beyond Pressure"


def test_generated_topic_hard_fails_after_max_attempts(monkeypatch):
    calls = []

    def fake_chat(settings, system, user):
        calls.append(1)
        return _briefing("A Nighttime Prayer for Sleep")

    monkeypatch.setattr(creative_generation, "_chat_json", fake_chat)
    with pytest.raises(CreativeGenerationError, match="regras do blueprint"):
        generate_topic_for_channel(_settings(), _channel(), ORACAO)
    assert len(calls) == creative_generation.MAX_TITLE_GENERATION_ATTEMPTS


def test_topic_flow_injects_the_blueprint_title_rules(monkeypatch):
    captured = {}

    def fake_chat(settings, system, user):
        captured["system"] = system
        return _briefing("Peace Beyond Pressure")

    monkeypatch.setattr(creative_generation, "_chat_json", fake_chat)
    generate_topic_for_channel(_settings(), _channel(), ORACAO)
    assert "REGRAS DE TÍTULO DO BLUEPRINT" in captured["system"]


# ---------------------------------------------------------------------------
# O TÍTULO do roteiro é validado no mesmo loop de auto-correcção
# ---------------------------------------------------------------------------


def _script_result(title, content="x" * 7500):
    return {"title": title, "summary": "s", "content": content}


def test_script_title_is_validated_with_retry(monkeypatch):
    calls = []

    def fake_chat(settings, system, user):
        calls.append(json.loads(user))
        if len(calls) == 1:
            return _script_result("Bedtime Prayer to Release Anxiety")
        return _script_result("Christ In You Is Greater")

    monkeypatch.setattr(script_generation, "_chat_json", fake_chat)
    result = generate_script_document(
        _settings(),
        document_type="Roteiro de vídeo",
        title="identity in Christ",
        brief="identity",
        language="en",
        blueprint=ORACAO,
    )

    assert len(calls) == 2
    assert "regras de TÍTULO" in calls[1]["system_feedback"]
    assert result["title"] == "Christ In You Is Greater"


def test_script_title_hard_fails_after_max_attempts(monkeypatch):
    calls = []

    def fake_chat(settings, system, user):
        calls.append(1)
        return _script_result("Nighttime Prayer for Insomnia")

    monkeypatch.setattr(script_generation, "_chat_json", fake_chat)
    with pytest.raises(CreativeGenerationError, match="regras do blueprint"):
        generate_script_document(
            _settings(),
            document_type="Roteiro de vídeo",
            title="tema",
            brief="tema",
            language="en",
            blueprint=ORACAO,
        )
    assert len(calls) == script_generation.MAX_SCRIPT_GENERATION_ATTEMPTS


# ---------------------------------------------------------------------------
# Thumbnail: NUNCA mais «não tem um prompt de imagem»
# ---------------------------------------------------------------------------


def test_thumbnail_prompt_never_returns_empty_when_the_llm_is_silent(monkeypatch):
    monkeypatch.setattr(
        creative_generation,
        "_chat_json",
        lambda settings, system, user: {"concept": "", "overlay_text": "GOD IS GREATER"},
    )
    result = generate_thumbnail_prompt(_settings(), _channel(), "peace", blueprint=ORACAO)

    assert result["image_prompt"].strip()
    assert result["status"] == "prompt_ready"
    # 1.0.28: o fallback da THUMBNAIL é cinematográfico e genérico — pessoas
    # são BEM-VINDAS (rostos vendem cliques); a lei visual (natureza/zero
    # humanos) NÃO se aplica a thumbnails, apenas às cenas do vídeo.
    prompt = result["image_prompt"]
    assert "Cinematic YouTube thumbnail" in prompt
    assert "Human faces" in prompt
    assert "Strictly no People" not in prompt
    assert "NO HUMANS" not in prompt
    assert "Waves" not in prompt  # keywords da lei visual não entram aqui


def test_thumbnail_prompt_fallback_without_blueprint_is_thumbnail_friendly(monkeypatch):
    monkeypatch.setattr(creative_generation, "_chat_json", lambda settings, system, user: {})
    result = generate_thumbnail_prompt(_settings(), _channel(), "tema", blueprint=None)
    # sem blueprint o fallback continua útil: ancorado no tópico, sem
    # proibições visuais — pessoas permitidas.
    assert "tema" in result["image_prompt"]
    assert "no people" not in result["image_prompt"].casefold()
    assert result["status"] == "prompt_ready"


def test_thumbnail_system_prompt_forbids_empty_image_prompt_and_allows_people(monkeypatch):
    captured = {}

    def fake_chat(settings, system, user):
        captured["system"] = system
        return {"image_prompt": "A hopeful face lit by golden sunrise light", "overlay_text": "GOD IS GREATER"}

    monkeypatch.setattr(creative_generation, "_chat_json", fake_chat)
    generate_thumbnail_prompt(_settings(), _channel(), "peace", blueprint=ORACAO)
    # a instrução anti-prompt-vazio permanece (a causa real do «não tem um
    # prompt»), mas SEM a lei visual: thumbnails podem ter pessoas.
    assert "NUNCA pode ser uma string vazia" in captured["system"]
    assert "rostos são BEM-VINDOS" in captured["system"]
    # 1.0.28: a lei visual (CHANNEL VISUAL REQUIREMENTS) NÃO entra na thumbnail.
    assert "CHANNEL VISUAL REQUIREMENTS" not in captured["system"]
    assert "ABSOLUTELY NO HUMANS" not in captured["system"]


def test_creative_payload_never_claims_prompt_ready_without_a_prompt():
    # Source-structure: o status é verdadeiro — sem image_prompt NÃO há
    # «prompt_ready» (era a fonte do «não tem um prompt de imagem»).
    assert '"prompt_ready" if image_prompt else "pending_prompt"' in MAIN_SOURCE


# ---------------------------------------------------------------------------
# Cenas: o FALLBACK também obedece à lei visual (zero humanos)
# ---------------------------------------------------------------------------


def test_scene_fallback_prompts_respect_the_visual_requirements(monkeypatch):
    from hermes_ui.text_to_images import generate_image_prompts_for_scenes

    class _RoutingError(Exception):
        pass

    monkeypatch.setattr(
        text_to_images,
        "route_llm_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(text_to_images.ProviderRoutingError("sem LLM")),
    )
    scenes = [{"index": 1, "text": "o poder da oração"}, {"index": 2, "text": "paz durante a tempestade"}]
    prompts = generate_image_prompts_for_scenes(scenes, "cinematic", _settings(), _channel(), ORACAO)

    assert len(prompts) == 2
    for scene in prompts:
        assert "Strictly no People" in scene["prompt"]
        assert "Face" in scene["prompt"]


def test_scene_fallback_without_blueprint_stays_generic(monkeypatch):
    from hermes_ui.text_to_images import generate_image_prompts_for_scenes

    monkeypatch.setattr(
        text_to_images,
        "route_llm_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(text_to_images.ProviderRoutingError("sem LLM")),
    )
    prompts = generate_image_prompts_for_scenes([{"index": 1, "text": "tema"}], "cinematic", _settings(), _channel(), None)
    assert "Cinematic scene" in prompts[0]["prompt"]
    assert "Strictly no" not in prompts[0]["prompt"]


def test_visual_fallback_suffix_composes_the_channel_law():
    suffix = visual_requirements_fallback_suffix(ORACAO)
    assert "Waves" in suffix
    assert "People" in suffix and "Face" in suffix
    assert visual_requirements_fallback_suffix(None) == ""
