"""Guardrails de TTS/legendas + tom do blueprint (1.0.17).

Correcção de 2 bugs críticos da geração de vídeos:
1. **Legendas e TTS poluídos** — o LLM deixava tags de produção
   («[Visual: ...]», «[Audio: ...]», «SCENE 1», «NARRATOR:») no meio do texto
   falado, que era lido em voz alta e queimado nas legendas (.srt). O funil
   único ``narration_text_from_script`` (TTS, MPT e burn de legendas) passa a
   remover TODO o texto entre colchetes das linhas faladas, rótulos de cena
   inteiros e prefixos de locutor (mantendo a fala).
2. **Tom e restrições ignorados** — o gerador de roteiros agora lê
   ``GLOBAL_TONE_DIRECTIVE`` e ``GLOBAL_BLACKLIST_WORDS`` do Blueprint
   corrigido e VALIDA EM CÓDIGO cada roteiro: palavra proibida ou tag de
   produção ⇒ regeneração com o motivo como feedback (loop existente,
   máx. 3 tentativas). Os requisitos visuais (``visual_requirements``)
   chegam aos geradores de imagem sem hardcoding no motor.

Critério de sucesso: o .srt e o áudio contêm APENAS palavras faladas, sem
colchetes nem tags; o roteiro é oração gospel, nunca meditação/yoga.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_ui import creative_generation, pipeline_worker, script_generation, text_to_images
from hermes_ui.blueprint_governance import (
    _parse_character_range,
    script_governance,
    script_rules_prompt_section,
    validate_script_content,
    visual_requirements_prompt_section,
)
from hermes_ui.script_generation import generate_script_document
from hermes_ui.script_voice import narration_text_from_script


ROOT = Path(__file__).resolve().parents[1]


def _blueprint() -> dict:
    return json.loads((ROOT / "seed" / "blueprints" / "BlueprintOração.json").read_text(encoding="utf-8"))


def _settings():
    return {"llm_provider": "openai", "openai_api_key": "test-key", "openai_base_url": "https://llm.example/v1", "openai_model_name": "test-model"}


def _channel():
    return {"id": "channel_1", "name": "Grace for Purpose", "description": "Oração e devoção", "language": "en", "default_blueprint_id": "oracao"}


# ---------------------------------------------------------------------------
# 1. Sanitização: nada entre colchetes chega ao TTS ou às legendas
# ---------------------------------------------------------------------------


def test_inline_production_tags_are_removed_from_spoken_lines():
    script = (
        "# Title\n"
        "The waves crash softly. [Visual: slow motion waves] The listener rests.\n"
        "A quiet piano begins. [Audio: soft instrumental]\n"
        "[SFX] The wind rises.\n"
    )
    result = narration_text_from_script(script)
    assert result == "The waves crash softly. The listener rests.\n\nA quiet piano begins.\n\nThe wind rises."
    assert "[" not in result and "]" not in result


def test_scene_labels_and_narrator_prefixes_never_reach_the_tts():
    script = (
        "# Title\n"
        "SCENE 1 — The Beach at Dawn\n"
        "NARRATOR: Lord, I lift up this listener to You.\n"
        "Scene 2: The sun rises over the mountains.\n"
        "Heavenly Father, we rest in Your promises.\n"
    )
    result = narration_text_from_script(script)
    assert "SCENE" not in result and "The Beach" not in result
    assert "NARRATOR" not in result
    # o prefixo sai, a fala fica — é a oração de intercessão
    assert "Lord, I lift up this listener to You." in result
    assert "Heavenly Father, we rest in Your promises." in result


def test_any_remaining_bracket_content_is_dropped_per_the_directive():
    # A regra do utilizador: «Remove tudo que estiver entre colchetes» —
    # aplica-se a qualquer resto (referências de rodapé, notas de edição…).
    result = narration_text_from_script("Faith over fear. [note: revisit this line] Amen.")
    assert result == "Faith over fear. Amen."


def test_markdown_links_still_resolve_to_their_text():
    assert narration_text_from_script("**This** is a [spoken](https://example.com) line.") == "This is a spoken line."


def test_moneyprinter_cli_receives_tag_free_narration_for_native_srt():
    script = (
        "# Title\n"
        "Peace be with you. [Visual: golden light through clouds]\n"
        "SCENE 3 — Mountains\n"
        "The Lord keeps you. [Audio: gentle strings]\n"
    )
    args = pipeline_worker._moneyprinter_cli_args({"video_script": script, "generation_settings": {}}, "pexels", {})
    narration = args[args.index("--video-script") + 1]
    assert "[" not in narration and "SCENE" not in narration and "Visual" not in narration
    assert "Peace be with you." in narration
    assert "The Lord keeps you." in narration


def test_burned_captions_receive_tag_free_narration(monkeypatch, tmp_path):
    """Critério de sucesso: o ficheiro de legendas (burn) contém APENAS as
    palavras faladas — sem nenhum colchete ou tag de formatação."""
    fonts_dir = tmp_path / "resource" / "fonts"
    fonts_dir.mkdir(parents=True)
    (fonts_dir / "arial.ttf").write_bytes(b"font")
    monkeypatch.setattr(
        "hermes_ui.pipeline_worker._configured_moneyprinter_root",
        lambda settings: str(tmp_path),
    )
    video = tmp_path / "video.mp4"
    video.write_bytes(b"mp4")
    script = {"content": "Grace covers you. [Visual: open Bible in nature] [Audio: soft wind]\nSCENE 4 — Still waters"}
    captured = {}

    def fake_burn(video_path, narration, config):
        captured["narration"] = narration
        return video

    monkeypatch.setattr("hermes_ui.text_to_images.burn_captions_on_video", fake_burn)
    task = {
        "generation_settings": {
            "video_source": "pexels",
            "enable_subtitles": True,
            "voiceover_mode": "tts",
            "voiceover_service": "elevenlabs",
        }
    }
    pipeline_worker._apply_mpt_captions(task, video, script, {})
    assert captured["narration"] == "Grace covers you."
    assert "[" not in captured["narration"]


# ---------------------------------------------------------------------------
# 2. Extensão obrigatória: o motor aceita lista OU frase («7,000–9,000»)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("STRICTLY 7,000–9,000 characters", (7000, 9000)),
        ("The script must have between 7000 and 9000 characters.", (7000, 9000)),
        ("7.000–9.000 caracteres", (7000, 9000)),
        ("Around 7500 characters long", None),
        ("No numbers here", None),
    ],
)
def test_parse_character_range_accepts_the_corrected_blueprint_phrase(text, expected):
    assert _parse_character_range(text) == expected


def test_script_governance_keeps_length_guardrail_with_the_string_form():
    governance = script_governance(_blueprint())
    assert governance["strict_character_range"] == (7000, 9000)
    assert governance["length_compliance_mandatory"] is True
    # a lista explícita continua a ganhar quando existe (retrocompatível)
    legacy = script_governance({"metadata": {"strict_character_range": [500, 7500], "length_compliance_mandatory": True}})
    assert legacy["strict_character_range"] == (500, 7500)


# ---------------------------------------------------------------------------
# 3. Tom + blacklist: injecção no prompt E hard guardrail pós-geração
# ---------------------------------------------------------------------------


def test_script_prompt_injects_tone_format_rules_and_blacklist():
    governance = script_governance(_blueprint())
    section = script_rules_prompt_section(governance)
    assert "GOSPEL PRAYER channel" in section
    assert "REGRAS CRÍTICAS DE FORMATO DO TEXTO" in section
    assert any("[Visual" in rule for rule in governance["format_rules"])
    assert "PALAVRAS/EXPRESSÕES PROIBIDAS NO CORPO DO TEXTO" in section
    assert "meditation" in section and "yoga" in section
    # CTA obrigatório a partir do generation_instructions (formato corrigido)
    assert "This is Daniel" in section


def test_validate_script_content_rejects_blacklisted_meditation_language():
    governance = script_governance(_blueprint())
    valid, reason = validate_script_content(
        "Close your eyes, breathe in slowly and enjoy this guided meditation.", governance
    )
    assert not valid
    assert "proibida" in reason and ("meditation" in reason or "breathe in" in reason)


def test_validate_script_content_rejects_production_tags_in_the_script():
    governance = script_governance(_blueprint())
    valid, reason = validate_script_content("Grace covers you. [Visual: waves at dawn]", governance)
    assert not valid
    assert "tags de produção" in reason


def test_validate_script_content_accepts_a_clean_intercession_prayer():
    governance = script_governance(_blueprint())
    unit = (
        "Lord, I lift up this listener to You. Cover their day with Your peace. "
        "The Lord is my shepherd; I shall not want. This is Daniel. Thank you for allowing me "
        "to pray with you today. If this daily effective prayer was a blessing, please subscribe. "
    )
    prayer = (unit * 40)[:8000]
    assert 7000 <= len(prayer) <= 9000
    valid, reason = validate_script_content(prayer, governance)
    assert valid, reason


def test_script_generation_regenerates_when_the_llm_uses_meditation_language(monkeypatch):
    """O loop de auto-correcção existente agora também apanha o tom: a 1ª
    resposta com linguagem de meditação é REJEITADA e o motivo volta ao LLM."""
    blueprint = _blueprint()
    calls = []

    def fake_chat(settings, system, user):
        calls.append({"system": system, "user": json.loads(user)})
        if len(calls) == 1:
            # linguagem de meditação (proibida) e fora da extensão obrigatória
            content = ("Breathe in deeply and relax as we begin this meditation. " * 30)[:9000]
        else:
            # oração de intercessão dentro de 7.000–9.000 caracteres
            content = ("Lord, I lift up this listener to You in faith. " * 160)[:9000]
        return {"title": "Christ In You Is Greater", "summary": "s", "content": content}

    monkeypatch.setattr(script_generation, "_chat_json", fake_chat)
    result = generate_script_document(
        _settings(),
        document_type="Roteiro de vídeo",
        title="Christ In You Is Greater",
        brief="identity in Christ",
        language="en",
        channel=_channel(),
        blueprint=blueprint,
    )

    assert len(calls) == 2
    feedback = calls[1]["user"]["system_feedback"]
    assert "REJEITADO" in feedback and "proibida" in feedback
    # o system prompt da 2ª chamada transporta a lei do canal (tom + formato)
    assert "GOSPEL PRAYER" in calls[1]["system"]
    assert "REGRAS CRÍTICAS DE FORMATO DO TEXTO" in calls[1]["system"]
    assert "NUNCA escrevas tags de produção" in calls[1]["system"]
    assert "meditation" not in result["content"].casefold()
    assert "[" not in result["content"]


# ---------------------------------------------------------------------------
# 4. visual_requirements do Blueprint → geradores de imagem (zero hardcoding)
# ---------------------------------------------------------------------------


def test_visual_requirements_prompt_section_reads_only_the_blueprint():
    section = visual_requirements_prompt_section(_blueprint())
    assert "NO HUMANS" in section
    assert "Waves" in section and "Mountains" in section
    assert "NEVER depict or evoke: People, Person, Man, Woman" in section
    # sem blueprint/sem chave → nada injectado (o motor não hardcoda regras)
    assert visual_requirements_prompt_section(None) == ""
    assert visual_requirements_prompt_section({"id": "bp", "name": "sem regras"}) == ""


def test_scene_image_prompts_receive_the_channel_visual_law(monkeypatch):
    captured = {}

    def fake_route(settings, system, user):
        captured["system"] = system
        scenes = json.loads(user)["scenes"]
        return type("Response", (), {"payload": {"scenes": [{"index": scene["index"], "prompt": f"scene {scene['index']}"} for scene in scenes]}})()

    monkeypatch.setattr(text_to_images, "route_llm_json", fake_route)
    text_to_images.generate_image_prompts_for_scenes(
        [{"index": 1, "text": "peace over the water"}], "cinematic", _settings(), _channel(), _blueprint()
    )
    assert "CHANNEL VISUAL REQUIREMENTS" in captured["system"]
    assert "NO HUMANS" in captured["system"]
    # sem blueprint o gerador continua a funcionar, sem regras injectadas
    text_to_images.generate_image_prompts_for_scenes(
        [{"index": 1, "text": "anything"}], "cinematic", _settings(), _channel(), None
    )
    assert "CHANNEL VISUAL REQUIREMENTS" not in captured["system"]


def test_thumbnail_prompt_receives_the_channel_visual_law(monkeypatch):
    captured = {}

    def fake_chat(settings, system, user):
        captured["system"] = system
        return {
            "concept": "Conceito",
            "overlay_text": "GOD IS GREATER",
            "composition": "c",
            "color_palette": "p",
            "subject": "s",
            "image_prompt": "majestic sunrise over mountains, no text",
            "title_synergy": "t",
            "lettering_prompt": "render overlay",
        }

    monkeypatch.setattr(creative_generation, "_chat_json", fake_chat)
    creative_generation.generate_thumbnail_prompt(
        _settings(), _channel(), "peace beyond pressure", blueprint=_blueprint()
    )
    assert "CHANNEL VISUAL REQUIREMENTS" in captured["system"]
    assert "NO HUMANS" in captured["system"]


def test_pipeline_passes_the_blueprint_to_the_scene_image_generator():
    source = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")
    call_block = source.split("scene_prompts = generate_image_prompts_for_scenes(", 1)[1][:600]
    assert "blueprint" in call_block, "o gerador de imagens de cena tem de receber o Blueprint activo"
