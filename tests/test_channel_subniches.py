"""1.0.67 — subnichos por canal (selecção de categorias do rotation_mandate).

O utilizador escolhe, no editor do canal (Canais Youtube > Editar), quais as
categorias do ``rotation_mandate`` do blueprint o canal pode usar. O pipeline
recebe o blueprint filtrado (a LLM nem vê as categorias proibidas) e o
validador rejeita roteiros que fujam da selecção. Selecção VAZIA = usar
todas as categorias — o comportamento pré-1.0.67 fica intacto.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _blueprint(name: str) -> dict:
    return json.loads((ROOT / "seed" / "blueprints" / name).read_text(encoding="utf-8"))


def _settings():
    return {
        "llm_provider": "openai",
        "openai_api_key": "test-key",
        "openai_base_url": "https://llm.example/v1",
        "openai_model_name": "test-model",
    }


def _channel(selected: list[str] | None = None) -> dict:
    channel = {"id": "channel_1", "name": "Dark Psychology", "description": "Stoicism only", "language": "en", "default_blueprint_id": "oracao"}
    if selected is not None:
        channel["selected_subniches"] = selected
    return channel


def _video_script(words: int = 400) -> str:
    return "the anchor holds every decision " * words


# ---------------------------------------------------------------------------
# Modelo de dados: o campo novo persiste no canal
# ---------------------------------------------------------------------------


def test_create_channel_defaults_to_no_subniche_selection(tmp_path, monkeypatch):
    monkeypatch.setenv("THUNDERBOLT_STORAGE_DIR", str(tmp_path / "storage"))
    from hermes_ui import storage

    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.ensure_storage()
    from hermes_ui.domain import create_channel

    channel = create_channel("Canal subnichos")

    assert channel["selected_subniches"] == []
    stored = storage.read_json("channels.json", [])
    assert [item for item in stored if item["id"] == channel["id"]][0]["selected_subniches"] == []


def test_create_channel_accepts_selected_subniches(tmp_path, monkeypatch):
    monkeypatch.setenv("THUNDERBOLT_STORAGE_DIR", str(tmp_path / "storage"))
    from hermes_ui import storage

    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.ensure_storage()
    from hermes_ui.domain import create_channel, update_channel

    channel = create_channel(
        "Dark Psychology - Stoicism Only",
        metadata={"selected_subniches": ["peace_trust", "strength_endurance"]},
    )

    assert channel["selected_subniches"] == ["peace_trust", "strength_endurance"]
    stored = storage.read_json("channels.json", [])
    assert [item for item in stored if item["id"] == channel["id"]][0]["selected_subniches"] == ["peace_trust", "strength_endurance"]

    # update_channel persiste a troca de selecção (o selector da UI grava por aqui).
    updated = update_channel(channel["id"], {"selected_subniches": ["identity_in_christ"]})
    assert updated["selected_subniches"] == ["identity_in_christ"]
    assert storage.read_json("channels.json", [])[0]["selected_subniches"] == ["identity_in_christ"]


# ---------------------------------------------------------------------------
# Leitura do blueprint: categorias normalizadas + restrição resolvida
# ---------------------------------------------------------------------------


def test_rotation_categories_reads_both_blueprint_dialects():
    from hermes_ui.blueprint_governance import rotation_categories

    prayer = rotation_categories(_blueprint("BlueprintOração.json"))
    assert prayer
    assert prayer[0]["id"] == "identity_in_christ"
    assert prayer[0]["label"] == "Identity in Christ"
    assert "Christ In You Is Greater" in prayer[0]["example_themes"]

    finance = rotation_categories(_blueprint("FINANCE USA.json"))
    assert finance
    # FINANCE guarda os exemplos em example_topics — a normalização aceita-os.
    assert finance[0]["id"] == "money_psychology"
    assert finance[0]["example_themes"]

    assert rotation_categories({"id": "bp", "name": "sem mandate"}) == []


def test_subniche_restriction_empty_selection_means_all_categories():
    from hermes_ui.blueprint_governance import subniche_restriction

    blueprint = _blueprint("BlueprintOração.json")
    for selected in ([], None, ["categoria_inexistente"], ["", "  "]):
        restriction = subniche_restriction(blueprint, selected)
        assert restriction["active"] is False
        assert restriction["selected"] == []
        assert restriction["forbidden_terms"] == []
        # as categorias disponíveis continuam listadas (a UI precisa delas).
        assert restriction["categories"]


def test_subniche_restriction_filters_selected_and_collects_forbidden_terms():
    from hermes_ui.blueprint_governance import subniche_restriction

    blueprint = _blueprint("BlueprintOração.json")
    restriction = subniche_restriction(blueprint, ["identity_in_christ", "ghost_id"])

    assert restriction["active"] is True
    assert restriction["selected"] == ["identity_in_christ"]  # id inexistente ignorado
    assert restriction["labels"] == ["Identity in Christ"]
    assert len(restriction["categories"]) == 1
    forbidden = restriction["forbidden_terms"]
    assert "Peace, Trust & Surrender" in forbidden
    assert "Release The Outcome" in forbidden
    # termos da categoria PERMITIDA nunca são proibidos.
    assert "Identity in Christ" not in forbidden
    assert "Christ In You Is Greater" not in forbidden


def test_restrict_blueprint_filters_categories_without_touching_the_original():
    from hermes_ui.blueprint_governance import restrict_blueprint_to_subniches

    blueprint = _blueprint("BlueprintOração.json")
    original_categories = blueprint["rotation_mandate"]["categories"]

    filtered, restriction = restrict_blueprint_to_subniches(blueprint, ["identity_in_christ"])
    kept = filtered["rotation_mandate"]["categories"]

    assert [item["id"] for item in kept] == ["identity_in_christ"]
    # o resto do mandate sobrevive (propósito, princípio, banidas, regras).
    assert filtered["rotation_mandate"]["purpose"]
    assert filtered["rotation_mandate"]["selection_rules"]
    assert filtered["rotation_mandate"]["hard_ban_categories"]
    # o original NUNCA é mutado (o índice em processo é partilhado).
    assert blueprint["rotation_mandate"]["categories"] == original_categories
    assert len(original_categories) > 1
    assert restriction["active"] is True

    intact, inactive = restrict_blueprint_to_subniches(blueprint, [])
    assert inactive["active"] is False
    assert intact["rotation_mandate"]["categories"] == original_categories


def test_subniche_prompt_section_is_explicit_about_the_restriction():
    from hermes_ui.blueprint_governance import subniche_prompt_section, subniche_restriction

    blueprint = _blueprint("BlueprintOração.json")
    section = subniche_prompt_section(subniche_restriction(blueprint, ["identity_in_christ", "peace_trust"]))
    assert "RESTRIÇÃO DE SUBNICHOS" in section
    assert "Identity in Christ" in section
    assert "Peace, Trust & Surrender" in section
    assert "PROIBIDO" in section

    assert subniche_prompt_section(subniche_restriction(blueprint, [])) == ""


# ---------------------------------------------------------------------------
# Guardrail: o roteiro que foge da selecção é rejeitado pelo validador
# ---------------------------------------------------------------------------


def test_validate_rejects_script_about_a_forbidden_subniche():
    from hermes_ui.blueprint_governance import (
        script_governance,
        subniche_restriction,
        validate_script_content,
    )
    from hermes_ui.blueprint_length_guard import strip_length_governance

    blueprint = _blueprint("BlueprintOração.json")
    governance = strip_length_governance(script_governance(blueprint))
    restriction = subniche_restriction(blueprint, ["identity_in_christ"])
    governance["subniche_forbidden_terms"] = restriction["forbidden_terms"]

    rogue = "Today we walk through Peace Beyond Pressure, releasing the outcome of every plan we cannot control."
    valid, reason = validate_script_content(rogue, governance)
    assert valid is False
    assert "Peace Beyond Pressure" in reason
    assert "subnichos selecionados" in reason

    allowed = "Christ in you is greater than any fear. The power of the name carries the day."
    valid, reason = validate_script_content(allowed, governance)
    assert valid is True, reason


def test_validate_without_restriction_accepts_any_category():
    """Regressão: sem selecção de subnichos, o validador não bloqueia nada."""
    from hermes_ui.blueprint_governance import script_governance, validate_script_content
    from hermes_ui.blueprint_length_guard import strip_length_governance

    governance = strip_length_governance(script_governance(_blueprint("BlueprintOração.json")))
    assert governance["subniche_forbidden_terms"] == []

    script = "A prayer for peace beyond pressure, releasing the outcome. " * 40
    valid, reason = validate_script_content(script, governance)
    assert valid is True, reason


# ---------------------------------------------------------------------------
# Integração: o prompt e o payload do LLM só vêem as categorias escolhidas
# ---------------------------------------------------------------------------


def test_generation_restricts_prompt_and_payload_to_selected_subniches(monkeypatch):
    from hermes_ui import script_generation
    from hermes_ui.script_generation import generate_script_document

    blueprint = _blueprint("BlueprintOração.json")
    calls: list[dict] = []

    def fake_chat(settings, system, user):
        calls.append({"system": system, "user": json.loads(user)})
        return {"title": "Christ In You Is Greater", "summary": "s", "content": _video_script()}

    monkeypatch.setattr(script_generation, "_chat_json", fake_chat)
    generate_script_document(
        _settings(),
        document_type="Roteiro de vídeo",
        title="Identity in Christ",
        brief="identity in Christ",
        language="en",
        channel=_channel(["identity_in_christ"]),
        blueprint=blueprint,
        generation_settings={"target_word_count": 600},
    )

    system = calls[0]["system"]
    assert "RESTRIÇÃO DE SUBNICHOS" in system
    assert "Identity in Christ" in system
    # o JSON do blueprint que a LLM recebeu leva SÓ a categoria escolhida.
    payload_categories = calls[0]["user"]["blueprint"]["rotation_mandate"]["categories"]
    assert [item["id"] for item in payload_categories] == ["identity_in_christ"]


def test_generation_rejects_rogue_script_and_retries_with_feedback(monkeypatch):
    """O guardrail fecha o ciclo: roteiro fora da selecção é reprovado e o
    motivo volta ao LLM como feedback da tentativa seguinte."""
    from hermes_ui import script_generation
    from hermes_ui.script_generation import generate_script_document

    blueprint = _blueprint("BlueprintOração.json")
    calls: list[dict] = []

    def fake_chat(settings, system, user):
        calls.append({"system": system, "user": json.loads(user)})
        if len(calls) == 1:
            return {"title": "Release The Outcome", "summary": "s", "content": "release the outcome and peace beyond pressure " * 60}
        return {"title": "Christ In You Is Greater", "summary": "s", "content": _video_script()}

    monkeypatch.setattr(script_generation, "_chat_json", fake_chat)
    generate_script_document(
        _settings(),
        document_type="Roteiro de vídeo",
        title="Identity in Christ",
        brief="identity in Christ",
        language="en",
        channel=_channel(["identity_in_christ"]),
        blueprint=blueprint,
        generation_settings={"target_word_count": 600},
    )

    assert len(calls) == 2
    # o motivo volta ao LLM como feedback accionável (o roteiro rejeitado
    # falava de uma categoria example_theme da categoria proibida).
    assert "REJEITADO" in calls[1]["user"]["system_feedback"]
    assert "Peace Beyond Pressure" in calls[1]["user"]["system_feedback"]
    assert "subnichos selecionados" in calls[1]["user"]["system_feedback"]


def test_generation_without_selection_keeps_every_category(monkeypatch):
    """Regressão: canal sem selected_subniches → mandate completo, sem secção."""
    from hermes_ui import script_generation
    from hermes_ui.script_generation import generate_script_document

    blueprint = _blueprint("BlueprintOração.json")
    total_categories = len(blueprint["rotation_mandate"]["categories"])
    calls: list[dict] = []

    def fake_chat(settings, system, user):
        calls.append({"system": system, "user": json.loads(user)})
        return {"title": "Peace Beyond Pressure", "summary": "s", "content": _video_script()}

    monkeypatch.setattr(script_generation, "_chat_json", fake_chat)
    generate_script_document(
        _settings(),
        document_type="Roteiro de vídeo",
        title="Peace Beyond Pressure",
        brief="peace and trust",
        language="en",
        channel=_channel([]),
        blueprint=blueprint,
        generation_settings={"target_word_count": 600},
    )

    assert "RESTRIÇÃO DE SUBNICHOS" not in calls[0]["system"]
    payload_categories = calls[0]["user"]["blueprint"]["rotation_mandate"]["categories"]
    assert len(payload_categories) == total_categories


def test_generation_ignores_unknown_subniche_ids(monkeypatch):
    """Selecção só com ids que o blueprint não tem = usar todos (nunca travar o canal)."""
    from hermes_ui import script_generation
    from hermes_ui.script_generation import generate_script_document

    blueprint = _blueprint("BlueprintOração.json")
    total_categories = len(blueprint["rotation_mandate"]["categories"])
    calls: list[dict] = []

    def fake_chat(settings, system, user):
        calls.append({"system": system, "user": json.loads(user)})
        return {"title": "Peace Beyond Pressure", "summary": "s", "content": _video_script()}

    monkeypatch.setattr(script_generation, "_chat_json", fake_chat)
    generate_script_document(
        _settings(),
        document_type="Roteiro de vídeo",
        title="Peace Beyond Pressure",
        brief="peace and trust",
        language="en",
        channel=_channel(["gaslighting", "cult_psychology"]),
        blueprint=blueprint,
        generation_settings={"target_word_count": 600},
    )

    assert "RESTRIÇÃO DE SUBNICHOS" not in calls[0]["system"]
    assert len(calls[0]["user"]["blueprint"]["rotation_mandate"]["categories"]) == total_categories


# ---------------------------------------------------------------------------
# UI do canal: opções derivadas do blueprint e tolerância a blueprint novo
# ---------------------------------------------------------------------------


def test_channel_subniche_options_intersects_stored_selection(monkeypatch):
    import app.main as main_module

    blueprint = _blueprint("BlueprintOração.json")

    def fake_blueprint_for_channel(channel):
        return blueprint

    monkeypatch.setattr(main_module, "blueprint_for_channel", fake_blueprint_for_channel)

    ids, labels, selected = main_module.channel_subniche_options(
        {"id": "c", "selected_subniches": ["identity_in_christ", "sumiu_do_blueprint"]}
    )
    assert "identity_in_christ" in ids
    assert labels["identity_in_christ"] == "Identity in Christ"
    # id que não existe no blueprint não entra na selecção (evolta canal preso).
    assert selected == ["identity_in_christ"]

    summary = main_module.channel_subniche_summary({"id": "c", "selected_subniches": ["identity_in_christ"]})
    assert summary == "Identity in Christ"
    assert main_module.channel_subniche_summary({"id": "c", "selected_subniches": []}) == ""


def test_channel_subniche_options_without_rotation_mandate(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "blueprint_for_channel", lambda channel: {"id": "bp", "name": "Sem mandate"})

    ids, labels, selected = main_module.channel_subniche_options({"id": "c", "selected_subniches": ["qualquer"]})
    assert (ids, labels, selected) == ([], {}, [])


# ---------------------------------------------------------------------------
# Importação por planilha: coluna de subnichos
# ---------------------------------------------------------------------------


def test_channel_import_normalizes_subniche_column():
    from hermes_ui.channel_import import _header_match, normalize_channel_row

    # o cabeçalho da planilha cai no campo novo (exact match antes dos parciais).
    assert _header_match("Subnichos") == "selected_subniches"
    assert _header_match("Subnicho") == "selected_subniches"
    assert _header_match("Nicho") == "niche"

    row = {
        "name": "Dark Psychology",
        "url": "https://www.youtube.com/@dark",
        "selected_subniches": "peace_trust, strength_endurance | identity_in_christ",
    }
    assert normalize_channel_row(row)["selected_subniches"] == [
        "peace_trust",
        "strength_endurance",
        "identity_in_christ",
    ]

    assert normalize_channel_row({"name": "x"})["selected_subniches"] == []
    assert normalize_channel_row({"selected_subniches": ""})["selected_subniches"] == []


def test_channel_template_contains_subniche_column():
    from hermes_ui.channel_import import CHANNEL_TEMPLATE_COLUMNS

    assert "Subnichos" in CHANNEL_TEMPLATE_COLUMNS
    assert CHANNEL_TEMPLATE_COLUMNS.index("Subnichos") == CHANNEL_TEMPLATE_COLUMNS.index("Nicho") + 1
