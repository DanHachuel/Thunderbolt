from pathlib import Path

from app.main import _normalise_tiktok_api_cards, _persist_tiktok_api_cards


def test_legacy_tiktok_credentials_are_migrated_to_one_card(monkeypatch):
    settings = {
        "tiktok_client_key": "legacy-client",
        "tiktok_client_secret": "legacy-secret",
    }
    writes = []
    monkeypatch.setattr("app.main.write_json", lambda name, payload: writes.append((name, payload.copy())))

    cards, changed = _normalise_tiktok_api_cards(settings)

    assert changed is True
    assert cards == [{"id": "tiktok-api-1", "client_id": "legacy-client", "client_secret": "legacy-secret"}]
    assert settings["tiktok_api_cards"] == cards
    assert writes and writes[-1][0] == "settings.json"


def test_persist_tiktok_cards_uses_first_complete_card_for_legacy_mirror(monkeypatch):
    settings = {"tiktok_client_key": "old-client", "tiktok_client_secret": "old-secret"}
    writes = []
    monkeypatch.setattr("app.main.write_json", lambda name, payload: writes.append((name, payload.copy())))

    _persist_tiktok_api_cards(
        settings,
        [
            {"id": "partial", "client_id": "first-client", "client_secret": ""},
            {"id": "complete", "client_id": "second-client", "client_secret": "second-secret"},
        ],
    )

    assert settings["tiktok_api_cards"] == [
        {"id": "partial", "client_id": "first-client", "client_secret": ""},
        {"id": "complete", "client_id": "second-client", "client_secret": "second-secret"},
    ]
    assert settings["tiktok_client_key"] == "second-client"
    assert settings["tiktok_client_secret"] == "second-secret"
    assert writes and writes[-1][0] == "settings.json"


def test_persisting_empty_tiktok_cards_clears_legacy_credentials(monkeypatch):
    settings = {
        "tiktok_api_cards": [{"id": "only", "client_id": "client", "client_secret": "secret"}],
        "tiktok_client_key": "client",
        "tiktok_client_secret": "secret",
    }
    monkeypatch.setattr("app.main.write_json", lambda *_args: None)

    _persist_tiktok_api_cards(settings, [])

    assert settings["tiktok_api_cards"] == []
    assert settings["tiktok_client_key"] == ""
    assert settings["tiktok_client_secret"] == ""


def test_normalise_tiktok_cards_keeps_first_complete_card_order(monkeypatch):
    settings = {
        "tiktok_api_cards": [
            {"id": "partial", "client_id": "partial-client", "client_secret": ""},
            {"id": "complete", "client_id": "ready-client", "client_secret": "ready-secret"},
        ]
    }
    monkeypatch.setattr("app.main.write_json", lambda *_args: None)

    cards, changed = _normalise_tiktok_api_cards(settings)

    assert changed is False
    assert [card["id"] for card in cards] == ["partial", "complete"]
    assert cards[1]["client_id"] == "ready-client"



def test_tiktok_card_renderer_exposes_only_requested_credentials_and_actions():
    source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    start = source.index("def render_tiktok_api_cards(")
    # A assinatura de render_google_accounts ganhou parâmetros; fatiar sem os parênteses.
    end = source.index("def render_google_accounts(", start)
    renderer = source[start:end]

    assert renderer.count('st.text_input("TikTok Client ID"') == 1
    assert renderer.count('st.text_input("TikTok Client Secret"') == 1
    for label in ("Testar chamada API", "Guardar card", "Apagar card", "Adicionar nova API"):
        assert label in renderer
    for forbidden_label in ("Access Token", "Redirect URI", "Scopes", "Refresh Token"):
        assert forbidden_label not in renderer


def test_tiktok_api_test_requires_oauth_without_fabricating_a_call():
    from hermes_ui.api_key_tests import test_tiktok_credentials

    result = test_tiktok_credentials("client", "secret", "")

    assert result["status"] == "unsupported"
    assert "autorização OAuth" in result["message"]
