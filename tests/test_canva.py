from pathlib import Path
import tempfile
from unittest.mock import Mock, patch

import pytest

from hermes_ui.canva_auth import authorization_url, create_pkce_pair, generate_code_challenge, generate_code_verifier
from hermes_ui.canva_client import CanvaClient
from hermes_ui.media_providers import media_cards_for_pool, normalize_media_card


def test_pkce_authorization_url_contains_required_parameters():
    verifier, challenge = create_pkce_pair()
    url = authorization_url("client", "http://127.0.0.1:3030/", state="state", code_challenge=challenge)
    assert len(verifier) >= 43
    assert "code_challenge_method=S256" in url
    assert "client_id=client" in url
    assert "state=state" in url
    assert "asset%3Aread" in url
    assert "asset%3Awrite" in url
    assert "design%3Ameta%3Aread" in url
    assert "design%3Acontent%3Aread" in url
    assert "design%3Acontent%3Awrite" in url


def test_pkce_pair_meets_canva_rfc7636_requirements():
    verifier = generate_code_verifier()
    challenge = generate_code_challenge(verifier)
    assert 43 <= len(verifier) <= 128
    assert all(char.isascii() and (char.isalnum() or char in "-._~") for char in verifier)
    assert len(challenge) == 43
    assert "=" not in challenge
    assert challenge == generate_code_challenge(verifier)


def test_authorization_url_rejects_code_challenge_placeholder():
    with pytest.raises(ValueError, match="placeholder"):
        authorization_url("client", "http://127.0.0.1:3030/oauth/redirect", "asset:read", "state", "<CODE_CHALLENGE>")


def test_canva_export_poll_and_download():
    card = {"client_id": "id", "client_secret": "secret", "oauth_token": {"access_token": "token", "expires_at": 9999999999}, "export_format": "png", "export_quality": "regular"}
    responses = [
        Mock(status_code=200, json=lambda: {"design": {"id": "design-1"}}),
        Mock(status_code=200, json=lambda: {"job": {"id": "job-1", "status": "in_progress"}}),
        Mock(status_code=200, json=lambda: {"job": {"id": "job-1", "status": "success", "urls": ["https://cdn.example/thumb.png"]}}),
    ]
    with tempfile.TemporaryDirectory() as temp_dir:
        card["output_path"] = str(Path(temp_dir) / "thumbnail.png")
        client = CanvaClient(card)
        with patch("hermes_ui.canva_client.requests.request", side_effect=responses) as request, patch("hermes_ui.canva_client.requests.get", return_value=Mock(content=b"png", status_code=200, raise_for_status=lambda: None)):
            with patch("hermes_ui.canva_client.time.sleep"):
                with pytest.raises(ValueError):
                    client.create_design(8001, 720)
                output = client.create_and_export_thumbnail(title="Topic", width=1280, height=720)
                assert output.read_bytes() == b"png"
    assert request.call_count == 3


def test_canva_is_thumbnail_only_and_never_video():
    card = normalize_media_card({"provider": "canva", "id": "canva-1", "enabled": True})
    assert card["supports_image"] is True
    assert card["supports_video"] is False
    assert card["thumbnail_only"] is True
    assert card in media_cards_for_pool({"media_provider_cards": [card]}, "image", thumbnail_only=True)
    assert card not in media_cards_for_pool({"media_provider_cards": [card]}, "image")
    assert media_cards_for_pool({"media_provider_cards": [card]}, "video") == []


def test_canva_export_defaults_and_combined_dimensions_are_normalized():
    card = normalize_media_card({"provider": "canva", "thumbnail_width": "1792 x 1024", "export_quality": "regular", "export_format": "unknown"})
    assert card["export_quality"] == "medium"
    assert card["export_format"] == "png"
    assert card["thumbnail_width"] == "1792"
    assert card["thumbnail_height"] == "1024"


def test_canva_export_defaults_are_medium_png_1280x720():
    card = normalize_media_card({"provider": "canva"})
    assert card["export_quality"] == "medium"
    assert card["export_format"] == "png"
    assert (card["thumbnail_width"], card["thumbnail_height"]) == ("1280", "720")


def test_canva_authorization_uses_form_submit_button_when_embedded():
    source = Path("app/main.py").read_text(encoding="utf-8")
    start = source.index('def _render_media_provider_card')
    end = source.index('def render_media_provider_cards', start)
    canva_block = source[start:end]
    assert 'authorize_clicked = st.form_submit_button' in canva_block
    assert 'st.link_button("Abrir autorização Canva"' not in canva_block


def test_launcher_routes_canva_callback_to_api_settings_page():
    source = Path("scripts/cli.mjs").read_text(encoding="utf-8")
    assert 'requestUrl.pathname === "/oauth/redirect"' in source
    assert 'requestUrl.searchParams.set("page", "Configuração API")' in source
    assert 'Location: `${requestUrl.pathname}${requestUrl.search}`' in source


def test_canva_authorization_persists_credentials_before_callback():
    source = Path("app/main.py").read_text(encoding="utf-8")
    start = source.index('def _render_media_provider_card')
    end = source.index('def render_media_provider_cards', start)
    canva_block = source[start:end]
    assert 'if authorize_clicked:' in canva_block
    assert '_persist_media_cards(settings, cards' in canva_block
    assert canva_block.index('if authorize_clicked:') < canva_block.index('elif refresh_clicked:')


def test_canva_oauth_transaction_survives_streamlit_session_refresh():
    source = Path("app/main.py").read_text(encoding="utf-8")
    providers = Path("hermes_ui/media_providers.py").read_text(encoding="utf-8")
    assert 'oauth_pending.get("state")' in source
    assert 'oauth_pending.get("code_verifier")' in source
    assert 'extra_values["oauth_pending"]' in source
    assert 'result["oauth_pending"]' in providers
from pathlib import Path
from unittest.mock import Mock, patch

from hermes_ui.api_key_tests import test_canva_credentials as _test_canva_credentials
from hermes_ui.api_key_tests import test_media_provider_card as _test_media_provider_card


def test_canva_test_accepts_oauth_access_token():
    response = Mock(status_code=200)
    with patch("hermes_ui.api_key_tests.requests.get", return_value=response) as request:
        result = _test_media_provider_card({"provider": "canva", "oauth_token": {"access_token": "oauth-token"}})
    assert result["status"] == "success"
    request.assert_called_once_with(
        "https://api.canva.com/rest/v1/users/me",
        headers={"Authorization": "Bearer oauth-token", "Accept": "application/json"},
        timeout=20,
    )


def test_canva_test_accepts_legacy_api_key():
    response = Mock(status_code=200)
    with patch("hermes_ui.api_key_tests.requests.get", return_value=response):
        result = _test_canva_credentials({"provider": "canva", "api_key": "canva-token"})
    assert result["status"] == "success"


def test_canva_test_does_not_require_model_or_generic_api_key():
    result = _test_media_provider_card({"provider": "canva", "oauth_token": {}})
    assert result["status"] == "missing"
    assert "API key ou autorize" in result["message"]


def test_thumbnail_gallery_does_not_use_deprecated_container_width_image_argument():
    source = Path("app/main.py").read_text(encoding="utf-8")
    start = source.index("def render_thumbnails")
    end = source.index("def ", start + len("def render_thumbnails"))
    block = source[start:end]
    assert 'st.image(str(image_path), width="stretch")' not in block
    # Commit 6f1219b passou a carregar os bytes pela cache _file_bytes em vez de
    # image_path.read_bytes(); o intent anti-use_container_width é mantido.
    assert "image_bytes = _file_bytes(image_path)" in block
    assert "st.image(image_bytes)" in block
    assert "data=image_bytes" in block
