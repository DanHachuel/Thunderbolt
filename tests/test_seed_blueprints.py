"""Validação dos blueprints de seed — CI gate antes de publicar no NPM.

Os ficheiros de ``seed/blueprints/`` são copiados para o ``storage`` de todos
os utilizadores na instalação: um JSON inválido (aspas não escapadas, vírgula
a mais) quebraria a UI de quem instala o pacote. Estes testes garantem que o
seed é sempre carregável e que os blueprints que o motor de governança exige
têm as chaves obrigatórias.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEED_DIR = ROOT / "seed" / "blueprints"

# 1.0.71 — os três blueprints novos/actualizados do seed.
NEW_BLUEPRINTS = ("Filosofia_e_Estoicismo.json", "Dark_Psychology.json", "Historical_Disasters.json")

# Chaves que o motor de governança (blueprint_governance.script_governance /
# title_governance) lê em TODOS os blueprints de canal.
REQUIRED_KEYS = ("metadata", "rotation_mandate", "title_analysis")

EXPECTED_CATEGORIES = {
    "Dark_Psychology.json": {"gaslighting", "cult_psychology", "stoicism", "silence_solitude"},
    "Filosofia_e_Estoicismo.json": {"stoic_mortality", "stoic_fate", "stoic_solitude", "stoic_indifference"},
    "Historical_Disasters.json": {"economic_collapses", "natural_catastrophes", "human_error_mysteries"},
}


def test_new_seed_blueprints_exist():
    for name in NEW_BLUEPRINTS:
        assert (SEED_DIR / name).is_file(), f"seed/blueprints/{name} não existe"


def test_new_seed_blueprints_are_loadable_and_have_required_keys():
    for name in NEW_BLUEPRINTS:
        path = SEED_DIR / name
        # parse estrito: aspas não escapadas explodem aqui (e não na UI do utilizador).
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict), f"{name}: o topo do JSON não é um objecto"
        for key in REQUIRED_KEYS:
            assert key in data, f"{name}: falta a chave obrigatória «{key}»"
        categories = data["rotation_mandate"].get("categories") or []
        assert categories, f"{name}: rotation_mandate sem categorias"
        for category in categories:
            assert str(category.get("id") or "").strip(), f"{name}: categoria sem id"
            assert str(category.get("label") or "").strip(), f"{name}: categoria sem label"


def test_expected_categories_are_present():
    for name, expected in EXPECTED_CATEGORIES.items():
        data = json.loads((SEED_DIR / name).read_text(encoding="utf-8"))
        ids = {str(category.get("id")) for category in data["rotation_mandate"]["categories"]}
        assert ids == expected, f"{name}: categorias {sorted(ids)} != {sorted(expected)}"


def test_filosofia_replacement_removed_the_legacy_file():
    """1.0.71 — o blueprint antigo saiu do seed (substituição pedida).

    O runtime dos utilizadores mantém o ficheiro antigo: o seader apenas copia
    o que falta (``storage.seed_blueprints`` nunca sobrescreve).
    """
    legacy = SEED_DIR / "BlueprintFilosofiaeEstoicismo.json"
    assert not legacy.exists(), "o blueprint antigo continua no seed"
    assert (SEED_DIR / "Filosofia_e_Estoicismo.json").is_file()


def test_every_seed_json_is_loadable():
    """Varredura completa: NENHUM json do seed pode falhar no parse."""
    invalid: list[str] = []
    for path in sorted(SEED_DIR.glob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            invalid.append(f"{path.name}: {exc}")
    assert not invalid, "JSONs inválidos no seed: " + "; ".join(invalid)


def test_seed_names_are_clean_filenames():
    """Nomes de ficheiro sem espaços/vírgulas (consistência do pacote NPM)."""
    for name in NEW_BLUEPRINTS:
        assert name == name.strip()
        assert " " not in name and "," not in name


def test_new_blueprints_are_selectable_and_governed():
    """Fumo do motor: cada blueprint novo carrega pelo stem e passa pela
    governança (título + roteiro) e pela selecção de subnichos (1.0.68)."""
    from hermes_ui.blueprint_governance import (
        rotation_categories,
        script_governance,
        subniche_prompt_section,
        subniche_restriction,
        title_governance,
    )
    from hermes_ui.blueprint_length_guard import strip_length_governance
    from hermes_ui.blueprint_loader import load_blueprint

    for name in NEW_BLUEPRINTS:
        stem = name[: -len(".json")]
        blueprint = load_blueprint(stem)
        assert blueprint.get("name") or stem  # o display name nunca fica vazio
        assert script_governance(blueprint)  # dicionário de governança
        assert title_governance(blueprint)  # idem para títulos
        categories = rotation_categories(blueprint)
        assert len(categories) >= 3
        # a restrição de subnichos resolve contra as categorias reais.
        restriction = subniche_restriction(blueprint, [categories[0]["id"]])
        assert restriction["active"] is True
        assert categories[0]["id"] in restriction["selected"]
        assert subniche_prompt_section(restriction)
        # sem selecção, todas as categorias ficam disponíveis.
        full = subniche_restriction(blueprint, [])
        assert len(full["categories"]) == len(categories)
        # a extensão do blueprint continua a ser saneada (regra inviolável).
        assert strip_length_governance(script_governance(blueprint))["strict_character_range"] is None
