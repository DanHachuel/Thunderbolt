import json
from pathlib import Path


def test_oracao_seed_uses_corrected_json_blueprint():
    root = Path(__file__).resolve().parents[1]
    blueprint_path = root / "seed" / "blueprints" / "BlueprintOração.json"
    payload = json.loads(blueprint_path.read_text(encoding="utf-8"))

    # 0.9.90: o Blueprint Oração passou da estrutura legada (id/name/content
    # markdown) para o JSON estruturado integral (como os FINANCE 0.9.80).
    assert "content" not in payload

    metadata = payload["metadata"]
    assert metadata["channel_analyzed"] == "Grace for Purpose Prayers"
    assert metadata["strict_character_range"] == [7000, 9000]
    assert metadata["length_compliance_mandatory"] is True

    # Mandato de rotação: 12 categorias com tecto rígido no nighttime_rest.
    rotation = payload["rotation_mandate"]
    categories = rotation["categories"]
    assert len(categories) == 12
    assert [category["id"] for category in categories].count("nighttime_rest") == 1
    nighttime = next(category for category in categories if category["id"] == "nighttime_rest")
    assert "restriction" in nighttime
    assert set(rotation["category_scripture_map"]) == {category["id"] for category in categories}
    assert rotation["selection_rules"]
    assert rotation["anti_patterns_to_avoid"]

    # Títulos: verdade espiritual — nunca cenário, sintoma ou how-to.
    title_mechanics = payload["title_analysis"]["title_mechanics"]
    forbidden = title_mechanics["forbidden_title_patterns_critical_violation_equals_failure"]
    assert any("A [type] Prayer for" in item for item in forbidden)
    assert title_mechanics["validation_check_mandatory_before_finalising_any_title"]

    # Abertura temática (nunca oração directa) e CTA obrigatório com assinatura.
    assert payload["script_architecture"]["opening_pattern"]["forbidden_opening"].startswith("Do not open with")
    assert "This is Daniel." in payload["cta_pattern"]["mandatory_closing_pattern"]
    assert payload["cta_pattern"]["cta_rules"]

    instructions = payload["generation_instructions_for_another_model"]
    assert instructions["output_length_requirement"].endswith("7,000 and 9,000 characters.")
    assert instructions["must_include"]
    assert instructions["must_avoid"]
    assert instructions["hard_fail_condition"]
