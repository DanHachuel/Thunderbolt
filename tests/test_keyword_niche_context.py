"""1.0.62 — contexto de nicho nas keywords (fim do literalismo de metáforas).

O relato do utilizador: um canal de finanças com o título «Why your rental
property bleeds cash» gerou imagens de ARTÉRIAS e HEMÁCEIAS — a metáfora
corporal foi extraída literalmente e enviada ao Pexels/Pixabay como termo de
busca. Estes testes prendem a defesa em três camadas:

1. o SYSTEM PROMPT do `generate_video_keywords` proíbe o literalismo e
   ancora o nicho (exemplo «bleeding cash» -> finance/business/money);
2. a rede pós-LLM (`sanitize_visual_keywords`) remove/bloqueia termos
   corporais fora de um canal de SAÚDE e substitui-os pelos termos do
   nicho (por muito que a LLM falhe);
3. a busca enviada ao provedor (`--video-terms` / `web_images_search`) sai
   enriquecida com os âncoras do nicho à frente.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from hermes_ui import creative_generation, keyword_context, pipeline_worker


ROOT = Path(__file__).resolve().parents[1]
CREATIVE_SOURCE = (ROOT / "hermes_ui" / "creative_generation.py").read_text(encoding="utf-8")
WORKER_SOURCE = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")

FINANCE_CHANNEL = {"id": "c1", "name": "Finanças", "language": "pt", "niche": "finanças"}
FINANCE_BLUEPRINT = {
    "id": "FINANCE USA",
    "name": "FINANCE USA",
    "target_niche": "finanças, investimentos e economia pessoal",
}
HEALTH_CHANNEL = {"id": "c2", "name": "Saúde", "language": "pt", "niche": "saúde"}


# ---------------------------------------------------------------------------
# 1. Prompt: nicho âncora + proibição do literalismo
# ---------------------------------------------------------------------------


def test_keywords_system_prompt_anchors_the_niche_and_forbids_literal_metaphors():
    prompt = _keywords_system_prompt()
    assert "visual researcher" in prompt
    assert "NEVER extract literal words that are used as metaphors" in prompt
    assert "bleeding cash" in prompt
    assert "finance, business, money, investment" in prompt
    assert "NEVER 'blood' or 'arteries'" in prompt
    assert "match the channel's niche" in prompt


def _keywords_system_prompt() -> str:
    """Extrai o system prompt real usado pelo gerador de keywords."""
    captured: dict[str, str] = {}

    def fake_chat(settings, system_prompt, user_prompt):
        captured["system"] = system_prompt
        return {"keywords": ["finance", "money"]}

    original = creative_generation._chat_json
    creative_generation._chat_json = fake_chat
    try:
        creative_generation.generate_video_keywords(
            {}, FINANCE_CHANNEL, "Why your rental property bleeds cash", "roteiro", FINANCE_BLUEPRINT
        )
    finally:
        creative_generation._chat_json = original
    return captured["system"]


def test_keywords_prompt_receives_the_blueprint_niche_in_the_payload():
    """O nicho do blueprint chega ao payload do utilizador (não só ao system)."""
    captured: dict[str, str] = {}

    def fake_chat(settings, system_prompt, user_prompt):
        captured["user"] = user_prompt
        return {"keywords": ["finance"]}

    original = creative_generation._chat_json
    creative_generation._chat_json = fake_chat
    try:
        creative_generation.generate_video_keywords(
            {}, FINANCE_CHANNEL, "tema", "roteiro", FINANCE_BLUEPRINT
        )
    finally:
        creative_generation._chat_json = original
    import json

    payload = json.loads(captured["user"])
    assert payload["channel"]["blueprint_id"] == "FINANCE USA"
    assert "finanças" in payload["channel"]["blueprint_niche"]


# ---------------------------------------------------------------------------
# 2. Rede pós-LLM (blacklist de metáforas)
# ---------------------------------------------------------------------------


def test_metaphor_keywords_are_removed_outside_health_channels():
    cleaned = keyword_context.sanitize_visual_keywords(
        ["bleeding cash", "blood", "arteries", "finance", "money"], "finanças", "FINANCE USA"
    )
    lowered = [item.casefold() for item in cleaned]
    assert "finance" in lowered and "money" in lowered
    assert not any(keyword_context._has_blocked_term(item) for item in cleaned)
    # A lista não fica vazia: preenchida com os termos do nicho.
    assert len(cleaned) >= 6


def test_health_channel_keeps_medical_terms():
    cleaned = keyword_context.sanitize_visual_keywords(
        ["blood", "hospital", "medical"], "saúde", "SAÚDE"
    )
    assert [item.casefold() for item in cleaned] == ["blood", "hospital", "medical"]


def test_blocklist_matches_multi_word_and_substring_terms():
    assert keyword_context._has_blocked_term("bleeding cash")
    assert keyword_context._has_blocked_term("red blood cells under microscope")
    assert keyword_context._has_blocked_term("artery anatomy")
    # Política CONSERVADORA fora da saúde: «bleeding edge technology» também
    # sai — a decisão é remover a raiz («bleeding»), não adivinhar o sentido.
    assert keyword_context._has_blocked_term("bleeding edge technology")
    assert not keyword_context._has_blocked_term("business meeting")
    assert not keyword_context._has_blocked_term("cash flow charts")


def test_niche_anchor_terms_are_derived_from_the_niche_or_blueprint():
    anchors = keyword_context.niche_anchor_terms("finanças", "FINANCE USA")
    assert anchors[:4] == ["finance", "money", "business", "investment"]
    rental = keyword_context.niche_anchor_terms("real estate", limit=2)
    assert rental == ["real estate", "property"]
    assert keyword_context.niche_anchor_terms("nichо desconhecido", limit=2) == ["business", "office"]


def test_generate_video_keywords_sanitizes_the_llm_answer():
    """Mesmo que a LLM devolva a metáfora, ela não passa (rede pós-LLM)."""
    original = creative_generation._chat_json
    creative_generation._chat_json = lambda *_a, **_k: {
        "keywords": ["bleeding cash", "blood", "finance", "money", "investment"]
    }
    try:
        keywords = creative_generation.generate_video_keywords(
            {}, FINANCE_CHANNEL, "Why your rental property bleeds cash", "roteiro", FINANCE_BLUEPRINT
        )
    finally:
        creative_generation._chat_json = original
    lowered = [item.casefold() for item in keywords]
    assert "bleeding cash" not in lowered
    assert not any(keyword_context._has_blocked_term(item) for item in keywords)
    assert "finance" in lowered and "money" in lowered


def test_keywords_fallback_is_sanitized_too():
    original = creative_generation._chat_json
    creative_generation._chat_json = lambda *_a, **_k: {"keywords": []}
    try:
        keywords = creative_generation.generate_video_keywords(
            {}, FINANCE_CHANNEL, "blood and arteries everywhere", "roteiro", FINANCE_BLUEPRINT
        )
    finally:
        creative_generation._chat_json = original
    assert not any(keyword_context._has_blocked_term(item) for item in keywords)


# ---------------------------------------------------------------------------
# 3. Busca enriquecida (o que o provedor recebe)
# ---------------------------------------------------------------------------


def test_keyword_queries_put_the_niche_anchors_first():
    queries = keyword_context.keyword_queries_enriched(
        ["rental property", "cash flow", "bleeding cash"], "finanças", "FINANCE USA", limit=10
    )
    assert queries[:4] == ["finance", "money", "business", "investment"]
    lowered = [item.casefold() for item in queries]
    assert "bleeding cash" not in lowered
    assert "rental property" in lowered and "cash flow" in lowered


# ---------------------------------------------------------------------------
# Contratos do worker (o caminho real da busca)
# ---------------------------------------------------------------------------


def test_video_terms_leave_the_worker_enriched_with_the_niche(tmp_path: Path):
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    import json

    (tmp_path / "state" / "channels.json").write_text(
        json.dumps([{"id": "ch-1", "name": "Finanças", "niche": "finanças"}]), encoding="utf-8"
    )
    original_read = pipeline_worker.read_json
    pipeline_worker.read_json = lambda name, fallback=[]: (
        [{"id": "ch-1", "name": "Finanças", "niche": "finanças"}]
        if name == "channels.json"
        else original_read(name, fallback)
    )
    try:
        args = pipeline_worker._moneyprinter_cli_args(
            {
                "id": "t1",
                "channel_id": "ch-1",
                "blueprint_name": "FINANCE USA",
                "video_keywords": ["rental property", "bleeding cash"],
            },
            "pexels",
            {},
        )
    finally:
        pipeline_worker.read_json = original_read
    terms = args[args.index("--video-terms") + 1].split(",")
    assert terms[:4] == ["finance", "money", "business", "investment"]
    assert "bleeding cash" not in [term.casefold() for term in terms]
    assert "rental property" in terms


def test_web_images_query_carries_the_niche_context():
    assert "keyword_queries_enriched(" in WORKER_SOURCE
    assert 'query = " ".join(scene_terms[:4])' in WORKER_SOURCE
    # A query nunca é o texto cru: os âncoras do nicho vêm à frente.
    block = WORKER_SOURCE.split("for scene_index, scene in enumerate(scenes, start=1):", 1)[1]
    assert "keyword_queries_enriched(" in block.split("output_path =", 1)[0]


def test_persisted_keywords_are_sanitized_in_the_creative_stage():
    assert "sanitize_visual_keywords(" in WORKER_SOURCE
    block = WORKER_SOURCE.split("keywords = keywords or (", 1)[1].split("title_candidates =", 1)[0]
    assert "sanitize_visual_keywords(" in block


def test_creative_generation_uses_the_shared_module():
    assert "from .keyword_context import" in CREATIVE_SOURCE
    assert CREATIVE_SOURCE.count("sanitize_visual_keywords(") >= 2  # keywords + pacote criativo


def test_keyword_context_module_contracts():
    assert hasattr(keyword_context, "NICHE_METAPHOR_BLOCKLIST")
    assert "bleeding" in keyword_context.NICHE_METAPHOR_BLOCKLIST
    assert "arteries" in keyword_context.NICHE_METAPHOR_BLOCKLIST
    assert hasattr(keyword_context, "GENERIC_ANCHORS")
    assert inspect.signature(keyword_context.sanitize_visual_keywords).parameters["minimum"].default == 6
