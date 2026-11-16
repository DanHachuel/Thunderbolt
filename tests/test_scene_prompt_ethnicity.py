"""1.1.02 — anti-viés asiático nos prompts de cena (text_to_images).

O modelo de imagem (Qwen/variantes) produz, por omissão, pessoas Leste/Sudeste
asiáticas: um prompt sem descritor étnico («A soldier in uniform») quase sempre
sai asiático. Estes testes simulam a fronteira do LLM (``route_llm_json`` e
``_detect_target_ethnicity``) e provam o comportamento REAL do gerador:

1. a etnia/contexto do roteiro é analisada num passo dedicado (``target_ethnicity``);
2. o descritor é injectado nas cenas COM pessoas — «American» e «German» num
   roteiro da 2ª Guerra, nunca «Asian»;
3. «diverse American professionals» num roteiro de finanças sem contexto explícito;
4. um descritor genérico de diversidade quando a análise não determina nada;
5. as cenas SEM pessoas ficam com o prompt original (a etnia não faz sentido aí).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import hermes_ui.text_to_images as text_to_images
from hermes_ui.provider_routing import ProviderRoutingError


def _settings() -> dict:
    return {
        "llm_provider": "openai",
        "openai_api_key": "test-key",
        "openai_base_url": "https://llm.example/v1",
        "openai_model_name": "test-model",
    }


def _channel(**over) -> dict:
    base = {
        "id": "c1",
        "name": "US Finance Daily",
        "description": "Wall Street, markets and macroeconomics",
        "niche": "finance",
        "language": "en",
    }
    base.update(over)
    return base


def _scene_router(responses: dict) -> callable:
    """Mock de ``route_llm_json`` SÓ para a geração de cenas (a etnia já vem fixa)."""

    def fake(settings, system, payload_json):
        payload = json.loads(payload_json)
        generated = []
        for item in payload.get("scenes", []):
            index = int(item.get("index") or 0)
            data = responses.get(index, {"prompt": f"scene {index}"})
            entry = {"index": item.get("index")}
            entry.update(data)
            generated.append(entry)
        return SimpleNamespace(payload={"scenes": generated})

    return fake


def _prompts_by_index(result: list[dict]) -> dict:
    return {int(item["index"]): item["prompt"] for item in result}


# ── 1.2ª Guerra: American e German, NUNCA Asian ──────────────────────────────


def test_world_war_two_scenes_get_american_and_german_never_asian(monkeypatch):
    monkeypatch.setattr(
        text_to_images,
        "_detect_target_ethnicity",
        lambda *a, **k: "Caucasian American and German soldiers",
    )
    scenes = [
        {"index": 1, "text": "American soldiers storm the beaches of Normandy"},
        {"index": 2, "text": "German officers study maps inside a bunker"},
        {"index": 3, "text": "a lone freighter on the horizon, no one aboard"},
    ]
    responses = {
        1: {"prompt": "a soldier charging through the surf", "people": True},
        2: {"prompt": "three men around a table under a lamp", "people": True},
        3: {"prompt": "a silhouetted freighter on calm water", "people": False},
    }
    monkeypatch.setattr(text_to_images, "route_llm_json", _scene_router(responses))
    prompts = _prompts_by_index(
        text_to_images.generate_image_prompts_for_scenes(scenes, "cinematic", _settings(), _channel())
    )
    assert "American" in prompts[1]
    assert "German" in prompts[1]
    assert "American" in prompts[2]
    assert "German" in prompts[2]
    assert "Asian" not in prompts[1].lower()
    assert "Asian" not in prompts[2].lower()
    # cena SEM pessoas: prompt original intacto, sem descritor étnico
    assert prompts[3] == "a silhouetted freighter on calm water"


# ── Finanças sem contexto explícito → diverse American professionals ──────────


def test_finance_scene_without_explicit_context_uses_diverse_american_professionals(monkeypatch):
    monkeypatch.setattr(
        text_to_images,
        "_detect_target_ethnicity",
        lambda *a, **k: "diverse American professionals",
    )
    scenes = [{"index": 1, "text": "the market opened volatile as traders reacted to the print"}]
    responses = {1: {"prompt": "a businessperson glued to monitors", "people": True}}
    monkeypatch.setattr(text_to_images, "route_llm_json", _scene_router(responses))
    prompts = _prompts_by_index(
        text_to_images.generate_image_prompts_for_scenes(scenes, "cinematic", _settings(), _channel())
    )
    assert "diverse american professionals" in prompts[1].lower()


# ── 4. Fallback de diversidade quando a análise não determina nada ────────────


@pytest.mark.parametrize("answered", ["", "diverse", "unknown"])
def test_undetermined_ethnicity_falls_back_to_the_explicit_diversity_descriptor(monkeypatch, answered):
    monkeypatch.setattr(text_to_images, "_detect_target_ethnicity", lambda *a, **k: answered)
    scenes = [{"index": 1, "text": "something generic happens"}]
    responses = {1: {"prompt": "a person walking a dog at dusk", "people": True}}
    monkeypatch.setattr(text_to_images, "route_llm_json", _scene_router(responses))
    prompts = _prompts_by_index(
        text_to_images.generate_image_prompts_for_scenes(scenes, "cinematic", _settings(), _channel())
    )
    assert "diverse ethnicities, mixed genders, varied ages" in prompts[1].lower()


def test_diversity_fallback_when_ethnicity_analysis_fails_end_to_end(monkeypatch):
    """O passo de análise falha, mas as cenas ainda recebem o descritor de diversidade."""

    def fake(settings, system, payload_json):
        payload = json.loads(payload_json)
        if "narration" in payload:  # chamada de análise de etnia
            raise ProviderRoutingError("analysis down")
        generated = [
            {"index": item["index"], "prompt": "a trader shouting on the floor", "people": True}
            for item in payload["scenes"]
        ]
        return SimpleNamespace(payload={"scenes": generated})

    monkeypatch.setattr(text_to_images, "route_llm_json", fake)
    prompts = _prompts_by_index(
        text_to_images.generate_image_prompts_for_scenes(
            [{"index": 1, "text": "panic on the trading floor"}], "cinematic", _settings(), _channel()
        )
    )
    assert "diverse ethnicities, mixed genders, varied ages" in prompts[1].lower()


# ── Fluxo completo: analisa e injecta (etnia determinada pelo LLM real) ───────


def test_end_to_end_flow_runs_the_analysis_step_then_injects(monkeypatch):
    calls: dict = {"analysis": "", "scene": ""}

    def fake(settings, system, payload_json):
        payload = json.loads(payload_json)
        if "narration" in payload:  # passo dedicado de análise
            calls["analysis"] = system
            return SimpleNamespace(payload={"target_ethnicity": "Caucasian American and German soldiers"})
        calls["scene"] = system
        responses = {
            1: ("a soldier holding a rifle", True),
            2: ("an empty town square at dawn", False),
        }
        generated = [
            {"index": item["index"], "prompt": responses[item["index"]][0], "people": responses[item["index"]][1]}
            for item in payload["scenes"]
        ]
        return SimpleNamespace(payload={"scenes": generated})

    monkeypatch.setattr(text_to_images, "route_llm_json", fake)
    scenes = [
        {"index": 1, "text": "Americans and Germans clash across France"},
        {"index": 2, "text": "a town square before the battle"},
    ]
    prompts = _prompts_by_index(
        text_to_images.generate_image_prompts_for_scenes(scenes, "cinematic", _settings(), _channel())
    )
    # o passo dedicado correu e pediu o campo target_ethnicity
    assert "target_ethnicity" in calls["analysis"]
    # e o gerador de cena foi instruído a representar a etnia + a marcá-la
    assert "Caucasian American and German soldiers" in calls["scene"]
    assert "people" in calls["scene"]
    assert "American" in prompts[1]
    assert "German" in prompts[1]
    assert "Asian" not in prompts[1].lower()
    # cena sem pessoas mantém-se original
    assert prompts[2] == "an empty town square at dawn"


# ── Anti-duplicação e colocação natural do descritor ──────────────────────────


def test_prompt_that_already_carries_the_ethnicity_is_not_doubled(monkeypatch):
    monkeypatch.setattr(text_to_images, "_detect_target_ethnicity", lambda *a, **k: "Caucasian American")
    scenes = [{"index": 1, "text": "a trader on Wall Street"}]
    responses = {1: {"prompt": "a Caucasian American trader on the phone", "people": True}}
    monkeypatch.setattr(text_to_images, "route_llm_json", _scene_router(responses))
    prompts = _prompts_by_index(
        text_to_images.generate_image_prompts_for_scenes(scenes, "cinematic", _settings(), _channel())
    )
    assert prompts[1].casefold().count("caucasian american") == 1


def test_inject_appearance_places_descriptor_after_the_leading_article():
    assert text_to_images._inject_appearance("A soldier in uniform", "Caucasian American") == (
        "A Caucasian American soldier in uniform"
    )


def test_inject_appearance_keeps_descriptor_when_it_overflows_the_character_limit():
    long_prompt = "a person standing near " + "waterfall rocks and ocean cliffs " * 40
    injected = text_to_images._inject_appearance(long_prompt, "Caucasian American")
    assert len(injected) <= text_to_images.SCENE_PROMPT_CHAR_LIMIT
    assert injected.startswith("a Caucasian American")


# ── Heurística de presença humana (só usada sem a flag do LLM) ────────────────


def test_scene_shows_people_prefers_the_flag_over_the_heuristic():
    assert text_to_images._scene_shows_people("a battlefield", True) is True
    assert text_to_images._scene_shows_people("a soldier in a field", False) is False
    assert text_to_images._scene_shows_people("a nurse and a doctor talking", None) is True
    assert text_to_images._scene_shows_people("a mountain range at dusk", None) is False


def test_people_free_scene_injected_via_heuristic_when_flag_absent(monkeypatch):
    """Sem a flag 'people', o regex detecta «nurse» e injecta a etnia na mesma."""
    monkeypatch.setattr(text_to_images, "_detect_target_ethnicity", lambda *a, **k: "German")
    scenes = [{"index": 1, "text": "uma cena"}]
    responses = {1: {"prompt": "a nurse crossing a dim hospital corridor"}}
    monkeypatch.setattr(text_to_images, "route_llm_json", _scene_router(responses))
    prompts = _prompts_by_index(
        text_to_images.generate_image_prompts_for_scenes(scenes, "cinematic", _settings(), _channel())
    )
    assert "German" in prompts[1]


# ── Contrato do helper de análise (leitura do campo + falha segura) ───────────


def test_detect_target_ethnicity_reads_the_field_and_sends_the_narration(monkeypatch):
    captured: dict = {}

    def fake(settings, system, user):
        captured["system"] = system
        captured["user"] = user
        return SimpleNamespace(payload={"target_ethnicity": "  German Wehrmacht officers  "})

    monkeypatch.setattr(text_to_images, "route_llm_json", fake)
    value = text_to_images._detect_target_ethnicity(
        "a samurai walks the rainy streets of Kyoto", "cinematic", _settings(), _channel()
    )
    assert value == "German Wehrmacht officers"
    assert "target_ethnicity" in captured["system"]
    assert "samurai walks the rainy streets of Kyoto" in captured["user"]


def test_detect_target_ethnicity_returns_empty_string_on_any_failure(monkeypatch):
    def boom(*a, **k):
        raise ProviderRoutingError("llm down")

    monkeypatch.setattr(text_to_images, "route_llm_json", boom)
    assert text_to_images._detect_target_ethnicity("x", "cinematic", _settings(), _channel()) == ""

    def malformed(*a, **k):  # payload sem o campo esperado
        return SimpleNamespace(payload={"unexpected": True})

    monkeypatch.setattr(text_to_images, "route_llm_json", malformed)
    assert text_to_images._detect_target_ethnicity("x", "cinematic", _settings(), _channel()) == ""


# ── O fallback de cena (LLM totalmente indisponível) NÃO injecta etnia ───────


def test_fallback_prompts_never_receive_the_ethnicity_descriptor(monkeypatch):
    """Quando a geração de cena falha, o prompt segue apenas a lei do canal —
    injectar diversidade aí violaria um canal «ABSOLUTELY NO HUMANS»."""

    def boom(*a, **k):
        raise ProviderRoutingError("llm down")

    monkeypatch.setattr(text_to_images, "route_llm_json", boom)
    prompts = _prompts_by_index(
        text_to_images.generate_image_prompts_for_scenes(
            [{"index": 1, "text": "a lone soldier waits in the rain"}], "cinematic", _settings(), _channel()
        )
    )
    assert "diverse ethnicities" not in prompts[1]
    assert "Cinematic scene" in prompts[1]