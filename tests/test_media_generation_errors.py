from hermes_ui.media_generation import MediaGenerationError, format_media_generation_error


def test_format_translates_authentication_error():
    message = format_media_generation_error(
        MediaGenerationError(
            "Todos os providers do pool de imagem falharam.",
            provider_errors=["openai: HTTP 401: invalid api key"],
        ),
        operation="refazer o lettering da thumbnail",
    )
    assert "IMG_AUTH_HTTP_401" in message
    assert "API key está ausente, inválida ou sem permissão" in message
    assert "refazer o lettering da thumbnail" in message


def test_format_translates_missing_provider_configuration():
    message = format_media_generation_error(MediaGenerationError("Não existem providers activos no pool de imagem."))
    assert "IMG_NO_ACTIVE_PROVIDER" in message
    assert "active um cartão" in message


# ── 0.9.61: cartão único em cooldown não pode envenenar o pool ───────────────


def test_cooldown_message_is_retryable_and_actionable():
    from hermes_ui.media_generation import _is_retryable_media_error

    cooldown_message = "O provider de imagem pollinations falhou: pollinations: provider em cooldown por mais de 347s"
    assert _is_retryable_media_error(cooldown_message) is True
    # O texto genérico de rota de cartão único também é retryable — um cartão
    # em cooldown não pode abortar o pool antes de os seguintes serem tentados.
    assert _is_retryable_media_error("Todos os providers do pool image falharam.") is True
    # erros definitivos continuam a abortar imediatamente
    assert _is_retryable_media_error("O provider falhou: HTTP 401: invalid api key") is False


def test_first_card_in_cooldown_falls_through_to_next_card(monkeypatch, tmp_path):
    from hermes_ui import media_generation

    cards = [
        {"id": "card-a", "provider": "pollinations", "priority": 1, "enabled": True},
        {"id": "card-b", "provider": "cloudflare_workers_ai", "priority": 2, "enabled": True},
    ]
    calls: list[str] = []

    def fake_for_card(settings, card, prompt, **kwargs):
        calls.append(card["id"])
        if card["id"] == "card-a":
            raise media_generation.MediaGenerationError(
                "O provider de imagem pollinations falhou: pollinations: provider em cooldown por mais de 347s"
            )
        return tmp_path / "image.jpg"

    monkeypatch.setattr(media_generation, "generate_image_for_card", fake_for_card)
    result = media_generation.generate_image_from_pool(
        {"media_provider_cards": cards},
        "prompt de teste",
    )
    assert result == tmp_path / "image.jpg"
    assert calls == ["card-a", "card-b"]


def test_image_card_route_error_carries_attempt_details(monkeypatch, tmp_path):
    from hermes_ui import media_generation
    from hermes_ui.provider_routing import ProviderRoutingError

    card = {"id": "card-a", "provider": "agnes", "enabled": True}
    cooldown_record = {
        "provider": "agnes",
        "status_code": None,
        "category": "cooldown",
        "error": "provider em cooldown por mais de 347s",
    }

    def fake_route(settings, *, pool, cards, request, **kwargs):
        raise ProviderRoutingError("Todos os providers do pool image falharam.", attempts=[cooldown_record])

    monkeypatch.setattr(media_generation, "route_json_request", fake_route)
    monkeypatch.setattr(media_generation, "_hydrate_media_card", lambda settings, card: dict(card))
    with __import__("pytest").raises(media_generation.MediaGenerationError) as raised:
        media_generation.generate_image_for_card(
            {"media_provider_cards": [card]},
            card,
            "prompt de teste",
        )
    message = str(raised.value)
    assert "O provider de imagem agnes falhou" in message
    assert "cooldown por mais de 347s" in message
    # os detalhes viajam no provider_errors para a tradução de códigos IMG_*
    assert raised.value.provider_errors == ["agnes: provider em cooldown por mais de 347s"]
