"""1.0.04: imagens de cena vs thumbnails.

Duas correcções mapeadas na auditoria:
1. O pipeline de cenas reutilizava a maquinaria de THUMBNAIL — a MANDATORY
   LETTERING LAYER queimava as primeiras 4 palavras do título em TODAS as
   cenas e o destino era fixo em storage/thumbnails/ (misturado com as capas
   YouTube). Agora `is_scene_image=True` usa o prompt puro e grava em
   storage/scenes/ (hash sem topic).
2. `generate_image_prompts_for_scenes` aplica a regra dos 5%: no máximo 5%
   das cenas recebem um texto curto (máx. 3 palavras) injectado no prompt.
"""
from __future__ import annotations

import json
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import hermes_ui.media_generation as media_generation
import hermes_ui.text_to_images as text_to_images
from hermes_ui.provider_routing import ProviderRoutingError
from hermes_ui.text_to_images import (
    _sanitise_text_overlay,
    _scene_text_overlay_positions,
    generate_image_prompts_for_scenes,
)

ROOT = Path(__file__).resolve().parents[1]


def _huggingface_card() -> dict:
    return {"provider": "huggingface", "api_style": "huggingface", "model": "flux", "api_key": "k", "base_url": "https://huggingface.co"}


def _fake_huggingface(captured: dict) -> types.ModuleType:
    image = Mock()
    image.save.side_effect = lambda buffer, format: buffer.write(b"scene")
    client = Mock()
    client.text_to_image.side_effect = lambda prompt, model: captured.__setitem__("prompt", prompt) or image
    fake = types.ModuleType("huggingface_hub")
    fake.InferenceClient = lambda **kwargs: client
    return fake


# ── is_scene_image: prompt puro + storage/scenes/ ───────────────────────────


def test_scene_image_uses_pure_prompt_and_scenes_folder():
    captured: dict = {}
    with tempfile.TemporaryDirectory() as temp_dir:
        with (
            patch.object(media_generation, "STORAGE", Path(temp_dir)),
            patch.object(media_generation, "ensure_storage", lambda: None),
            patch.dict(sys.modules, {"huggingface_hub": _fake_huggingface(captured)}),
        ):
            output = media_generation.generate_image_for_card(
                {},
                _huggingface_card(),
                "Cold aerial shot of a bulk carrier at dawn",
                topic="Russia's Submarines Are Hiding",
                variant_index=7,
                is_scene_image=True,
            )
        assert output.parent == Path(temp_dir) / "scenes", "imagens de cena vivem em storage/scenes/"
        assert output.name.startswith("scene-huggingface-")
        assert output.read_bytes() == b"scene"
        assert "Cold aerial shot of a bulk carrier at dawn" in captured["prompt"]
        assert "MANDATORY LETTERING" not in captured["prompt"], "cena não pode levar a lettering layer das thumbnails"
        assert "Russia's Submarines" not in captured["prompt"], "o título não entra na composição da cena"


def test_scene_destination_hash_ignores_topic(tmp_path):
    """O mesmo prompt/variante com títulos diferentes reutiliza a mesma imagem em cache."""
    captured: dict = {}

    def generate(topic: str) -> Path:
        with (
            patch.object(media_generation, "STORAGE", tmp_path),
            patch.object(media_generation, "ensure_storage", lambda: None),
            patch.dict(sys.modules, {"huggingface_hub": _fake_huggingface(captured)}),
        ):
            return media_generation.generate_image_for_card(
                {}, _huggingface_card(), "same prompt", topic=topic, variant_index=3, is_scene_image=True
            )

    assert generate("TÍTULO A") == generate("TÍTULO COMPLETAMENTE DIFERENTE")


def test_thumbnail_default_keeps_lettering_and_thumbnails_folder():
    """Restrição: sem is_scene_image, o comportamento de thumbnail real não muda."""
    captured: dict = {}
    with tempfile.TemporaryDirectory() as temp_dir:
        with (
            patch.object(media_generation, "STORAGE", Path(temp_dir)),
            patch.object(media_generation, "ensure_storage", lambda: None),
            patch.dict(sys.modules, {"huggingface_hub": _fake_huggingface(captured)}),
        ):
            output = media_generation.generate_image_for_card(
                {}, _huggingface_card(), "A dramatic thumbnail composition", topic="Russia's Submarines Are Hiding", variant_index=0
            )
        assert output.parent == Path(temp_dir) / "thumbnails"
        assert "MANDATORY LETTERING" in captured["prompt"]
        assert "RUSSIA'S SUBMARINES ARE" in captured["prompt"], "a capa continua com o headline obrigatório"


def test_image_request_scene_mode_skips_lettering_composition():
    card = {"provider": "openrouter", "api_style": "openrouter", "api_key": "secret", "base_url": "https://openrouter.ai/api/v1", "model": "m"}
    response = Mock(status_code=200)
    with (
        patch.object(media_generation.requests, "post", return_value=response) as post,
        patch.object(media_generation, "_compose_thumbnail_prompt", wraps=media_generation._compose_thumbnail_prompt) as compose,
    ):
        media_generation._image_request(card, "clean scene prompt", topic="VIDEO TITLE", is_scene_image=True)
    compose.assert_not_called()
    body = post.call_args.kwargs["json"]
    assert "clean scene prompt" in body["prompt"]
    assert "MANDATORY LETTERING" not in body["prompt"]
    assert "VIDEO TITLE" not in body["prompt"]


def test_image_request_default_mode_still_composes_lettering():
    card = {"provider": "openrouter", "api_style": "openrouter", "api_key": "secret", "base_url": "https://openrouter.ai/api/v1", "model": "m"}
    response = Mock(status_code=200)
    with (
        patch.object(media_generation.requests, "post", return_value=response),
        patch.object(media_generation, "_compose_thumbnail_prompt", wraps=media_generation._compose_thumbnail_prompt) as compose,
    ):
        media_generation._image_request(card, "clean image prompt", topic="VIDEO TITLE")
    compose.assert_called_once()


def test_canva_cards_are_skipped_for_scene_images():
    """O Canva só gera thumbnails com blueprint/título — não pode produzir cenas limpas."""
    canva = {"id": "c", "provider": "canva"}
    other = {"id": "o", "provider": "openrouter"}
    attempted: list[str] = []

    def fake_for_card(settings, card, prompt, **kwargs):
        attempted.append(str(card.get("provider")))
        return Path("ok.jpg")

    with (
        patch.object(media_generation, "media_cards_for_pool", lambda settings, pool, thumbnail_only=False: [canva, other]),
        patch.object(media_generation, "generate_image_for_card", fake_for_card),
    ):
        output = media_generation.generate_image_from_pool({}, "prompt", is_scene_image=True)
    assert output == Path("ok.jpg")
    assert attempted == ["openrouter"]


def test_canva_cards_still_used_for_thumbnails_by_default():
    canva = {"id": "c", "provider": "canva"}
    attempted: list[str] = []

    def fake_for_card(settings, card, prompt, **kwargs):
        attempted.append(str(card.get("provider")))
        return Path("thumb.jpg")

    with (
        patch.object(media_generation, "media_cards_for_pool", lambda settings, pool, thumbnail_only=False: [canva]),
        patch.object(media_generation, "generate_image_for_card", fake_for_card),
    ):
        output = media_generation.generate_image_from_pool({}, "prompt")
    assert output == Path("thumb.jpg")
    assert attempted == ["canva"]


def test_nano_banana_scene_mode_uses_pure_prompt_and_scenes_folder(tmp_path, monkeypatch):
    captured: dict = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["prompt"] = json["input"]
        return Mock(status_code=200, json=lambda: {"status": "completed"})

    import hermes_ui.thumbnail_generation as thumbnail_generation

    monkeypatch.setattr(thumbnail_generation, "GEMINI_INTERACTIONS_ENDPOINT", "http://endpoint")
    monkeypatch.setattr(thumbnail_generation.requests, "post", fake_post)
    monkeypatch.setattr(thumbnail_generation, "_extract_image_bytes", lambda payload: b"img")
    monkeypatch.setattr(thumbnail_generation, "normalize_thumbnail_bytes", lambda data, ratio: data)
    monkeypatch.setattr(thumbnail_generation, "ensure_storage", lambda: None)
    monkeypatch.setattr(thumbnail_generation, "STORAGE", tmp_path)
    settings = {"gemini_image_api_key": "k", "gemini_image_model": "gemini-3.1-flash-image"}

    output = thumbnail_generation.generate_thumbnail_image(
        settings, "Cold open over the North Atlantic", topic="VIDEO TITLE", variant_index=1, is_scene_image=True
    )
    assert output.parent == tmp_path / "scenes"
    assert output.name.startswith("scene-nano_banana-")
    assert "Cold open over the North Atlantic" in captured["prompt"]
    assert "MANDATORY LETTERING" not in captured["prompt"]


# ── Regra dos 5%: no máximo 5% das cenas com texto ──────────────────────────


def test_scene_text_positions_follow_five_percent_uniform():
    assert _scene_text_overlay_positions(0) == set()
    assert _scene_text_overlay_positions(1) == {0}
    assert _scene_text_overlay_positions(3) == {1}
    assert _scene_text_overlay_positions(20) == {10}
    assert _scene_text_overlay_positions(60) == {0, 30, 59}
    assert _scene_text_overlay_positions(100) == {0, 25, 50, 74, 99}


def test_sanitise_text_overlay_limits_to_three_words():
    assert _sanitise_text_overlay("STAY SHARP OUT THERE") == "STAY SHARP OUT"
    assert _sanitise_text_overlay("one two three four five") == "one two three"
    assert _sanitise_text_overlay("") == ""


def _scenes(count: int) -> list[dict]:
    return [{"index": position + 1, "text": f"cena {position + 1}"} for position in range(count)]


def test_generate_image_prompts_marks_five_percent_and_injects_overlay(monkeypatch):
    captured: dict = {}

    def fake_route(settings, system, payload_json):
        captured["system"] = system
        captured["payload"] = json.loads(payload_json)
        scenes_out = []
        for item in captured["payload"]["scenes"]:
            entry = {"index": item["index"], "prompt": f"prompt for scene {item['index']}"}
            if item.get("allow_text"):
                entry["text_overlay"] = "STAY SHARP OUT THERE"
            scenes_out.append(entry)
        return SimpleNamespace(payload={"scenes": scenes_out})

    monkeypatch.setattr(text_to_images, "route_llm_json", fake_route)
    result = generate_image_prompts_for_scenes(_scenes(20), "cinematic", {}, {})

    marked = [position for position, item in enumerate(captured["payload"]["scenes"]) if item.get("allow_text")]
    assert marked == [10], "20 cenas -> 5% = 1 cena marcada (posição central)"
    assert "maximum 3 words" in captured["system"]
    assert "with the text 'STAY SHARP OUT' written on it." in result[10]["prompt"]
    unmarked = [item for position, item in enumerate(result) if position != 10]
    assert all("with the text" not in item["prompt"] for item in unmarked)


def test_overlay_on_unmarked_scene_is_ignored(monkeypatch):
    def fake_route(settings, system, payload_json):
        payload = json.loads(payload_json)
        return SimpleNamespace(payload={"scenes": [{"index": item["index"], "prompt": f"p{item['index']}", "text_overlay": "NOPE NOPE"} for item in payload["scenes"]]})

    monkeypatch.setattr(text_to_images, "route_llm_json", fake_route)
    result = generate_image_prompts_for_scenes(_scenes(20), "cinematic", {}, {})
    # apenas a cena marcada (posição 10) recebe o overlay; as restantes ignoram
    assert "with the text 'NOPE NOPE' written on it." in result[10]["prompt"]
    unmarked = [item for position, item in enumerate(result) if position != 10]
    assert all("with the text" not in item["prompt"] for item in unmarked)


def test_llm_failure_yields_no_text_anywhere(monkeypatch):
    def fake_route(settings, system, payload_json):
        raise ProviderRoutingError("llm indisponível")

    monkeypatch.setattr(text_to_images, "route_llm_json", fake_route)
    result = generate_image_prompts_for_scenes(_scenes(20), "cinematic", {}, {})
    assert len(result) == 20
    assert all("with the text" not in item["prompt"] for item in result)
    assert all(item["prompt"] for item in result)


def test_pipeline_routes_request_scene_images():
    source = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")
    text_block = source.split('elif route == "text_to_images":', 1)[1].split("elif route ==", 1)[0]
    assert "is_scene_image=True" in text_block, "o loop de cenas text_to_images pede imagens de cena"
    blueprint_block = source.split("def image_provider(prompt: str) -> Path:", 1)[1].split("def tts_provider", 1)[0]
    assert "is_scene_image=True" in blueprint_block, "a rota blueprint também pede imagens de cena"
