"""1.0.69 — busca Pexels saneada, rotação de chaves e atribuição correcta.

Relato do utilizador: o vídeo "Why your rental property bleeds cash" falhou a
55% com `— API/provider: Pexels API; configuração: pexels_api_keys`. A
investigação provou três coisas:
1. a string de busca era `your,rental,property,bleeds,cash,even,great,tenants,
   finanças` — palavras soltas do título, com a metáfora viva e cedilha;
2. as âncoras de nicho NUNCA apareciam porque `"financ" in "finanças"` é falso
   em Python (ç ≠ c) — o canal do utilizador chama-se "Finanças";
3. o erro real foi **NVENC OOM** (CreateInputBuffer failed: out of memory) e o
   Thunderbolt atribuiu-o ao Pexels por ser a rota.

Estes testes prendem o contrato novo.
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_SOURCE = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. string de busca: alfanumérica, sem metáforas, com âncoras do nicho
# ---------------------------------------------------------------------------


def test_niche_anchors_match_portuguese_accents():
    """A RAIZ do relato: "financ" (ASCII) tem de casar com "Finanças" (ç)."""
    from hermes_ui.keyword_context import niche_anchor_terms

    anchors = niche_anchor_terms("Finanças", limit=4)
    assert "finance" in anchors
    assert anchors[0] == "finance"


def test_search_string_is_strictly_alphanumeric_and_has_no_stopwords():
    from hermes_ui.keyword_context import keyword_queries_enriched, safe_search_string

    tags = ["your", "rental", "property", "bleeds", "cash", "even", "great", "tenants", "finanças"]
    terms = keyword_queries_enriched(tags, "", "Finanças")
    search = safe_search_string(terms)
    assert search
    for term in search.split(","):
        assert term == term.strip()
        assert all(char.isalnum() or char == " " for char in term), f"termo não alfanumérico: {term!r}"
    assert "your" not in search.split(",")
    assert "even" not in search.split(",")
    assert "great" not in search.split(",")
    assert "bleeds" not in search.split(",")
    assert "financas" in search  # cedilha dobrada para ASCII


def test_empty_keyword_list_falls_back_to_niche_anchors():
    from hermes_ui.keyword_context import keyword_queries_enriched

    terms = keyword_queries_enriched(["your", "the", "bleeds"], "", "Finanças")
    assert terms and terms[0] == "finance", "a busca nunca fica sem contexto"


def test_health_niche_keeps_medical_terms():
    from hermes_ui.keyword_context import keyword_queries_enriched

    terms = keyword_queries_enriched(["bleeding"], "", "Saúde")
    assert "bleeding" in terms, "canal de saúde mantém o termo legítimo"


def test_blocklist_covers_inflected_forms():
    from hermes_ui.keyword_context import _has_blocked_term

    assert _has_blocked_term("bleeds cash")
    assert _has_blocked_term("bleed out")
    assert not _has_blocked_term("cash flow")


def test_worker_passes_a_safe_terms_string():
    wiring = WORKER_SOURCE.split("if terms:", 1)[1].split("language = _mpt_video_language", 1)[0]
    assert "safe_search_string(terms)" in wiring
    assert 'args.extend(["--video-terms", search_string])' in wiring


# ---------------------------------------------------------------------------
# 2. atribuição correcta: GPU vs chaves do provider
# ---------------------------------------------------------------------------


def test_gpu_failure_is_not_attributed_to_the_material_provider():
    from hermes_ui.pipeline_worker import _failure_attribution

    task = {"id": "t", "style_wide": "pexels", "material_source": "pexels"}
    metadata = _failure_attribution(
        task,
        {"video_source": "pexels"},
        "video",
        error="Falha na GPU: NVENC indisponível",
        output="CreateInputBuffer failed: out of memory (10); caiu para libx264",
    )
    assert metadata["failure_provider"] == "local_gpu"
    assert "GPU" in metadata["failure_api"]
    assert metadata["failure_config_fields"] == ""


def test_quota_failure_is_attributed_to_the_keys_with_friendly_message():
    from hermes_ui.pipeline_worker import _failure_message, _failure_attribution

    task = {"id": "t", "style_wide": "pexels", "material_source": "pexels"}
    metadata = _failure_attribution(
        task,
        {"video_source": "pexels"},
        "video",
        error="Pexels devolveu 429 Too Many Requests",
        output="pexels_api_keys: 429",
    )
    assert metadata.get("material_keys_failed") is True
    message = _failure_message("MoneyPrinterTurbo falhou", metadata)
    assert "Todas as chaves do Pexels falharam ou estão sem cota" in message
    assert "Verifique em Configurações API" in message
    # A mensagem de sistema nunca aparece sozinha no cartão.
    assert "configuração: pexels_api_keys" not in message


def test_plain_route_failure_keeps_the_standard_attribution():
    from hermes_ui.pipeline_worker import _failure_attribution

    task = {"id": "t", "style_wide": "pexels", "material_source": "pexels"}
    metadata = _failure_attribution(task, {"video_source": "pexels"}, "video", error="Motor falhou")
    assert metadata["failure_api"] == "Pexels API"
    assert metadata.get("material_keys_failed") is not True


# ---------------------------------------------------------------------------
# 3. rotação de chaves
# ---------------------------------------------------------------------------


def test_worker_orders_material_keys_by_health(monkeypatch):
    """1.0.70 - o probe usado é o das FONTES DE MATERIAIS (responde "success")."""
    import hermes_ui.api_key_tests as akt

    from hermes_ui import pipeline_worker

    monkeypatch.setattr(
        akt,
        "test_material_source_credentials",
        lambda provider, api_key: {"status": "success" if api_key == "B" else "error"},
    )
    ordered = pipeline_worker._order_material_keys_by_health(["A", "B"], "pexels")
    assert ordered == ["B"], "a chave válida vai primeiro"


def test_material_key_probe_accepts_the_real_success_status(monkeypatch):
    """1.0.70 - o probe do Pexels devolve "success" ("API Key OK"), não "ok".

    A primeira versão comparava com "ok" e usava o probe dos cartões de media
    (que exige base_url) — marcava as 3 chaves reais do utilizador como
    falhadas. Este teste impede a regressão.
    """
    import hermes_ui.api_key_tests as akt

    from hermes_ui import pipeline_worker

    monkeypatch.setattr(akt, "test_material_source_credentials", lambda provider, key: {"status": "success"})
    assert pipeline_worker._material_key_is_healthy("chave-valida", "pexels") is True
    monkeypatch.setattr(akt, "test_material_source_credentials", lambda provider, key: {"status": "error"})
    assert pipeline_worker._material_key_is_healthy("chave-morta", "pexels") is False


def test_worker_keeps_original_order_without_enough_keys():
    from hermes_ui import pipeline_worker

    assert pipeline_worker._order_material_keys_by_health(["only-one"], "pexels") == ["only-one"]
    assert pipeline_worker._order_material_keys_by_health(["a", "b"], "local") == ["a", "b"]


def test_rotation_log_message_contract():
    assert "[PEXELS] Chave" in WORKER_SOURCE
    assert "Tentando a pr\u00f3xima chave" in WORKER_SOURCE
    assert "_material_key_is_healthy" in WORKER_SOURCE


def test_worker_source_never_calls_the_material_api_for_local_gpu_failures():
    assert "_is_gpu_render_failure(combined)" in WORKER_SOURCE
