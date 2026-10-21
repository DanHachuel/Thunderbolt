import json
from pathlib import Path


def test_oracao_seed_uses_corrected_json_blueprint():
    """1.0.17: o Blueprint Oração foi substituído pela versão corrigida do autor.

    O ficheiro novo (o JSON é a lei do canal) introduz as chaves que o motor
    passou a ler: GLOBAL_TONE_DIRECTIVE, GLOBAL_BLACKLIST_WORDS,
    script_format_rules e visual_requirements; a extensão obrigatória passa a
    vir da frase «STRICTLY 7,000–9,000 characters» (o motor aceita lista OU
    frase — ver blueprint_governance._parse_character_range) e o CTA obrigatório
    vive em generation_instructions.cta_pattern.
    """
    root = Path(__file__).resolve().parents[1]
    blueprint_path = root / "seed" / "blueprints" / "BlueprintOração.json"
    payload = json.loads(blueprint_path.read_text(encoding="utf-8"))

    assert "content" not in payload

    metadata = payload["metadata"]
    assert metadata["channel_analyzed"] == "Grace for Purpose Prayers"
    assert metadata["length_compliance_mandatory"] is True
    assert metadata["character_length_requirement"] == "STRICTLY 7,000–9,000 characters"
    # 1.0.17: tom gospel explícito — nunca meditação/yoga/mindfulness.
    assert "GOSPEL PRAYER channel" in metadata["GLOBAL_TONE_DIRECTIVE"]
    assert "meditation" in metadata["GLOBAL_BLACKLIST_WORDS"]
    assert "sleep" in metadata["GLOBAL_BLACKLIST_WORDS"]
    # 1.0.17: o roteiro é 100% texto falado, pronto para TTS (sem tags).
    assert any("[Visual" in rule for rule in metadata["script_format_rules"])
    # 1.0.17: regras de imagem no JSON (o motor lê a chave, sem hardcoding).
    visual = metadata["visual_requirements"]
    assert "Waves" in visual["image_prompt_keywords"]
    assert "People" in visual["image_blacklist_keywords"]
    assert "NO HUMANS" in visual["instruction"]

    # Mandato de rotação: 11 categorias vivas + nighttime_rest BANIDA.
    rotation = payload["rotation_mandate"]
    categories = rotation["categories"]
    assert len(categories) == 11
    assert all(category["id"] != "nighttime_rest" for category in categories)
    assert rotation["hard_ban_categories"]["nighttime_rest"]
    assert rotation["selection_rules"]

    # Títulos: verdade espiritual, máximo 6 palavras, template proibido.
    title_mechanics = payload["title_analysis"]["title_mechanics"]
    assert title_mechanics["max_word_count"] == 6
    forbidden = title_mechanics["forbidden_title_patterns_critical_violation_equals_failure"]
    assert any("A [type] Prayer for" in item for item in forbidden)
    assert title_mechanics["correct_forms_use_these"]

    # Abertura temática (nunca oração directa) e CTA obrigatório com assinatura.
    assert payload["script_architecture"]["opening_pattern"]["forbidden_opening"].startswith("Do not open with")
    assert "This is Daniel." in payload["generation_instructions_for_another_model"]["cta_pattern"]

    instructions = payload["generation_instructions_for_another_model"]
    assert instructions["must_include"]
    assert instructions["must_avoid"]
    assert any("[Visual" in item for item in instructions["must_avoid"])


def test_runtime_importados_copy_matches_the_corrected_seed():
    """A cópia runtime (storage/blueprints/importados) é a mesma do seed — o
    canal activo da instância usa imediatamente o blueprint corrigido."""
    root = Path(__file__).resolve().parents[1]
    seed = (root / "seed" / "blueprints" / "BlueprintOração.json").read_bytes()
    runtime = (root / "storage" / "blueprints" / "importados" / "BlueprintOração.json").read_bytes()
    assert seed == runtime
