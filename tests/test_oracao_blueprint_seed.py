import json
from pathlib import Path


def test_oracao_seed_uses_corrected_markdown_blueprint():
    root = Path(__file__).resolve().parents[1]
    blueprint_path = root / "seed" / "blueprints" / "BlueprintOração.json"
    payload = json.loads(blueprint_path.read_text(encoding="utf-8"))

    assert payload["id"] == "BlueprintOração"
    assert payload["name"] == "BlueprintOração"
    assert payload["metadata"]["strict_character_range"] == [7000, 9000]
    assert payload["metadata"]["length_compliance_mandatory"] is True
    assert payload["content"].startswith("# BLUEPRINT ORAÇÃO (VERSÃO MELHORADA)")
    assert "Abertura com declaração temática" in payload["content"]
    assert "NENHUM formato de aula acadêmica" in payload["content"]
    assert "O ROTEIRO COMPLETO final deve estar estritamente entre 7.000 e 9.000 caracteres." in payload["content"]
