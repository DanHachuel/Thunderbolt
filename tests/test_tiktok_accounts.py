import json
from pathlib import Path
from unittest.mock import Mock, patch

from integrations.tiktok_public import fetch_public_tiktok_profile, normalize_tiktok_reference


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
STORAGE_SOURCE = (ROOT / "hermes_ui" / "storage.py").read_text(encoding="utf-8")


def test_tiktok_reference_normalization():
    from_handle = normalize_tiktok_reference("@conta.exemplo")
    from_url = normalize_tiktok_reference("https://www.tiktok.com/@conta.exemplo/video/123")
    assert from_handle["username"] == "conta.exemplo"
    assert from_handle["handle"] == "@conta.exemplo"
    assert from_handle["url"] == "https://www.tiktok.com/@conta.exemplo"
    assert from_handle["id"] == from_url["id"]


def test_public_lookup_parses_profile_metadata_without_credentials():
    response = Mock(status_code=200, text='''<html><head>
      <meta property="og:title" content="Conta Exemplo (@conta.exemplo) | TikTok">
      <meta property="og:description" content="Bio pública de exemplo">
      <meta property="og:image" content="https://cdn.example/avatar.jpg">
    </head></html>''')
    with patch("integrations.tiktok_public.requests.get", return_value=response) as request:
        result = fetch_public_tiktok_profile("@conta.exemplo")
    assert result.ok is True
    assert result.data["username"] == "conta.exemplo"
    assert result.data["handle"] == "@conta.exemplo"
    assert result.data["name"] == "Conta Exemplo"
    assert result.data["bio"] == "Bio pública de exemplo"
    assert result.data["avatar_url"] == "https://cdn.example/avatar.jpg"
    assert request.call_args.kwargs["headers"]["User-Agent"].startswith("Thunderbolt/")


def test_public_lookup_handles_rate_limit_without_bypass():
    response = Mock(status_code=429, text="rate limited")
    with patch("integrations.tiktok_public.requests.get", return_value=response):
        result = fetch_public_tiktok_profile("@conta.exemplo")
    assert result.ok is False
    assert "bloqueou ou limitou" in result.message


def test_tiktok_accounts_backend_remains_available_without_navigation_tab():
    assert '"Contas TikTok"' in MAIN_SOURCE
    assert '"Contas TikTok": render_tiktok_accounts' not in MAIN_SOURCE
    assert '"TikTok": "tiktok_accounts"' in MAIN_SOURCE
    assert 'elif destination == "TikTok":' in MAIN_SOURCE
    assert '"Conta TikTok" if destination == "TikTok"' in MAIN_SOURCE
    assert '"tiktok_accounts": []' in STORAGE_SOURCE


def test_no_tiktok_oauth_or_batch_fields_are_added_to_account_page():
    start = MAIN_SOURCE.index("def render_tiktok_accounts():")
    end = MAIN_SOURCE.index("def render_tiktok_prompt_masters():")
    account_page = MAIN_SOURCE[start:end]
    assert "Pesquisa pública" in account_page
    assert "Cadastro manual" in account_page
    assert "video.publish" not in account_page
    assert "access_token" not in account_page
    assert "tiktok_client_key" not in account_page
    assert "tiktok_client_secret" not in account_page
