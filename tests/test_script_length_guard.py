"""1.0.45 — REGRA INVIOLÁVEL: Tempo Médio de Vídeo > limites de Blueprint.

Testes de regressão que FALHAM o build se alguém voltar a enviar regras de
contagem de caracteres dos Blueprints para a LLM ou a suprimir o alvo de
palavras do canal (o bug relatado três vezes pelo utilizador).

- Teste A (Sanitização): o blueprint com «STRICTLY 7,000–9,000 characters»
  não pode deixar rasto no prompt;
- Teste B (Injecção do Tempo): canal com 20:00 → o prompt manda escrever
  3.000 palavras / 20 minutos;
- Teste C (Prioridade): canal com 5 minutos + blueprint pedindo 10.000
  caracteres → o prompt manda 750 palavras e os 10.000 caracteres são
  ignorados;
- Teste D (Validação): a governança saneada nunca rejeita o roteiro pelo
  tamanho (o loop de auto-correcção não pode voltar a impor a range);
- Teste E (Profundidade): a remoção actua a qualquer nível de aninhamento;
- Teste F (Constituição): o AGENTS.md contém a regra;
- Teste G (Regressão do bug): um blueprint «mandatório» NUNCA suprime o
  alvo de palavras do canal.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_ui.blueprint_governance import script_governance, validate_script_content
from hermes_ui.blueprint_length_guard import (
    LENGTH_INSTRUCTION_KEYS,
    channel_length_instruction,
    sanitize_blueprint_for_prompt,
    strip_length_governance,
)
from hermes_ui.script_generation import generate_script_document


ROOT = Path(__file__).resolve().parents[1]

RIGID_BLUEPRINT = {
    "id": "bp-finance-usa",
    "name": "FINANCE USA",
    "target_niche": "finanças pessoais",
    "metadata": {
        "character_length_requirement": "STRICTLY 7,000–9,000 characters",
        "character_length_rule": "The final FULL SCRIPT must be no less than 7,000 characters and no more than 9,000 characters.",
        "strict_character_range": [7000, 9000],
        "length_compliance_mandatory": True,
        "channel_persona": {"role": "estrategista financeiro", "voice": "directa e prática"},
    },
    "generation_instructions_for_another_model": {
        "must_include": ["um exemplo numérico concreto"],
        "must_avoid": ["promessas de retorno garantido"],
        "cta_pattern": "Comenta FRENTE e recebe o plano.",
        # aninhamento real: as regras vivem dentro de sub-objectos e listas
        "output_length_requirement": "The final FULL SCRIPT must be strictly between 7,000 and 9,000 characters.",
        "hard_fail_condition": "Any FULL SCRIPT under 7,000 characters is invalid.",
        "nested": {
            "output_length_verification": "verify the character count before sending",
            "rules": [
                {"strict_character_range": [7000, 9000], "note": "lista dentro de dict dentro de dict"},
                {"character_length_requirement": "STRICTLY 7,000–9,000 characters"},
            ],
        },
    },
}


def _capture_prompt(monkeypatch, *, channel, blueprint, brief="Como sair das dívidas sem cortar tudo"):
    """Corre generate_script_document com _chat_json capturado; devolve (system, user)."""
    captured: dict[str, str] = {}

    def fake_chat(_settings, system, user_prompt):
        captured["system"] = system
        captured["user"] = user_prompt
        return {
            "title": "A matemática escondida das dívidas",
            "summary": "Um plano simples para sair das dívidas.",
            "content": "A maioria das pessoas paga caro sem perceber. " * 40,
        }

    monkeypatch.setattr("hermes_ui.script_generation._chat_json", fake_chat)
    generate_script_document(
        {},
        document_type="Roteiro de vídeo",
        title="Dívidas",
        brief=brief,
        language="Português",
        channel=channel,
        blueprint=blueprint,
    )
    return captured["system"], captured["user"]


# ---------------------------------------------------------------------------
# Teste A — sanitização (nada de contagem de caracteres chega à LLM)
# ---------------------------------------------------------------------------


def test_rigid_blueprint_length_rules_never_reach_the_prompt(monkeypatch):
    system, user = _capture_prompt(
        monkeypatch,
        channel={"id": "c1", "name": "The Financial Mechanics", "average_video_time": "20:00"},
        blueprint=RIGID_BLUEPRINT,
    )
    assert "STRICTLY 7,000" not in system
    assert "STRICTLY 7,000" not in user
    assert "character_length_requirement" not in user
    assert "strict_character_range" not in user
    assert "hard_fail_condition" not in user
    assert "length_compliance_mandatory" not in user
    assert "output_length_requirement" not in user
    assert "EXTENSÃO OBRIGATÓRIA" not in system
    assert "7,000 e 9,000" not in user


def test_sanitizer_removes_keys_at_any_nesting_level():
    clean = sanitize_blueprint_for_prompt(RIGID_BLUEPRINT)
    assert "character_length_requirement" not in clean.get("metadata", {})
    instructions = clean.get("generation_instructions_for_another_model", {})
    assert "output_length_requirement" not in instructions
    assert "hard_fail_condition" not in instructions
    nested = instructions.get("nested", {})
    assert "output_length_verification" not in nested
    for item in nested.get("rules", []):
        assert "strict_character_range" not in item
        assert "character_length_requirement" not in item
    # O que É lei do canal fica intacto (persona, must_include, CTA).
    assert clean["metadata"]["channel_persona"]["role"] == "estrategista financeiro"
    assert clean["generation_instructions_for_another_model"]["must_include"] == ["um exemplo numérico concreto"]
    assert clean["generation_instructions_for_another_model"]["cta_pattern"] == "Comenta FRENTE e recebe o plano."
    # O original NUNCA é mutado.
    assert RIGID_BLUEPRINT["metadata"]["character_length_requirement"].startswith("STRICTLY")


# ---------------------------------------------------------------------------
# Teste B — injecção do tempo do canal
# ---------------------------------------------------------------------------


def test_channel_time_is_injected_as_the_mandatory_size_instruction(monkeypatch):
    system, _user = _capture_prompt(
        monkeypatch,
        channel={"id": "c1", "name": "The Financial Mechanics", "average_video_time": "20:00"},
        blueprint=RIGID_BLUEPRINT,
    )
    assert "[INSTRUÇÃO DE TAMANHO OBRIGATÓRIA]" in system
    assert "exatamente 20 minutos de narração" in system
    assert "3,000 palavras" in system
    assert "cerca de 18,000 caracteres" in system
    assert "Ignore qualquer restrição de tamanho" in system
    # A instrução vem no TOPO — antes de tudo.
    assert system.index("[INSTRUÇÃO DE TAMANHO OBRIGATÓRIA]") < system.index("És um roteirista")


def test_channel_length_instruction_uses_150_words_per_minute():
    instruction, words, duration = channel_length_instruction({"average_video_time": "05:00"})
    assert words == 750 and duration == "05:00"
    assert "exatamente 5 minutos" in instruction
    assert "750 palavras" in instruction
    # TikTok (formato curto) também é respeitado.
    instruction_tiktok, words_tiktok, _duration = channel_length_instruction(
        {"platform": "tiktok", "average_video_time": "01:20"}
    )
    assert words_tiktok == 200
    assert "200 palavras" in instruction_tiktok


# ---------------------------------------------------------------------------
# Teste C — prioridade absoluta do canal sobre o blueprint
# ---------------------------------------------------------------------------


def test_channel_five_minutes_beats_blueprint_ten_thousand_characters(monkeypatch):
    system, user = _capture_prompt(
        monkeypatch,
        # 5 minutos no formato MM:SS do cartão do canal.
        channel={"id": "c2", "name": "Canal curto", "average_video_time": "05:00"},
        blueprint={
            **RIGID_BLUEPRINT,
            "metadata": {
                **RIGID_BLUEPRINT["metadata"],
                "character_length_requirement": "STRICTLY 9,000–11,000 characters",
                "strict_character_range": [9000, 11000],
            },
        },
    )
    assert "750 palavras" in system
    assert "exatamente 5 minutos" in system
    assert "10,000" not in system
    assert "9,000 e 11,000" not in user
    assert "STRICTLY" not in user


# ---------------------------------------------------------------------------
# Teste D — validação: a governança saneada não rejeita pelo tamanho
# ---------------------------------------------------------------------------


def test_stripped_governance_never_rejects_on_character_count():
    governance = strip_length_governance(script_governance(RIGID_BLUEPRINT))
    # 3.000 palavras ≈ 18.000 caracteres — bem acima da range do blueprint.
    long_script = "Um roteiro completo do canal com vinte minutos de narracao. " * 120
    valid, reason = validate_script_content(long_script, governance)
    assert valid is True, reason
    # As outras leis do canal continuam a valearar (produção tags reprovadas).
    tagged, tag_reason = validate_script_content("Texto falado. [Visual: ondas]", governance)
    assert tagged is False and "[Visual" in tag_reason


def test_script_governance_still_extracts_for_other_consumers():
    # A extracção original fica intacta (títulos/visuais/pipeline usam-na);
    # a sanitização acontece no ponto de uso do prompt.
    governance = script_governance(RIGID_BLUEPRINT)
    assert governance["strict_character_range"] == (7000, 9000)
    assert governance["length_compliance_mandatory"] is True
    stripped = strip_length_governance(governance)
    assert stripped["strict_character_range"] is None
    assert stripped["length_compliance_mandatory"] is False
    assert stripped["character_length_rule"] == ""


# ---------------------------------------------------------------------------
# Teste E — constituição e contrato do módulo
# ---------------------------------------------------------------------------


def test_agents_md_declares_the_inviolable_rule():
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "REGRA INVIOLÁVEL: TAMANHO DE ROTEIRO E BLUEPRINTS" in agents
    assert "average_video_time" in agents
    assert "TERMINANTEMENTE PROIBIDO" in agents
    assert "sanitize_blueprint_for_prompt" in agents
    assert "test_script_length_guard.py" in agents


def test_script_generation_source_wires_the_guard():
    source = (ROOT / "hermes_ui" / "script_generation.py").read_text(encoding="utf-8")
    assert "sanitize_blueprint_for_prompt(blueprint or {})" in source
    assert "strip_length_governance(script_governance(blueprint_payload))" in source
    assert "channel_length_instruction(channel)" in source
    assert 'system = length_instruction' in source
    # O bug das três releases: suprimir o alvo por blueprint «mandatório».
    assert "length_is_mandatory" not in source


def test_length_instruction_keys_cover_the_real_blueprints():
    for key in (
        "character_length_requirement",
        "strict_character_range",
        "character_length_rule",
        "output_length_requirement",
        "hard_fail_condition",
        "length_compliance_mandatory",
        "output_length_verification",
    ):
        assert key in LENGTH_INSTRUCTION_KEYS, key


def test_generate_script_document_without_channel_falls_back_to_default_time(monkeypatch):
    """Sem canal explícito, o padrão do canal (20:00) mantém-se a fonte única."""
    system, _user = _capture_prompt(monkeypatch, channel=None, blueprint=RIGID_BLUEPRINT)
    assert "3,000 palavras" in system
    assert "STRICTLY" not in system
