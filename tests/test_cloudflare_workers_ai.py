from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hermes_ui import media_generation, media_providers


def test_cloudflare_url_helpers_use_account_id():
    assert media_providers.cloudflare_workers_ai_models_url("acc/123") == "https://api.cloudflare.com/client/v4/accounts/acc%2F123/ai/models/search"
    assert media_providers.cloudflare_workers_ai_run_base_url("account-123") == "https://api.cloudflare.com/client/v4/accounts/account-123/ai/run"
    assert media_providers.cloudflare_workers_ai_run_url("account-123", "@cf/meta/model") == "https://api.cloudflare.com/client/v4/accounts/account-123/ai/run/@cf/meta/model"


def test_cloudflare_image_endpoint_uses_selected_model_and_account():
    endpoint = media_generation._image_endpoint({
        "provider": "cloudflare_workers_ai",
        "api_style": "cloudflare",
        "base_url": "https://api.cloudflare.com/client/v4",
        "account_id": "account-123",
        "model": "@cf/stabilityai/stable-diffusion-xl-base-1.0",
    })
    assert endpoint == "https://api.cloudflare.com/client/v4/accounts/account-123/ai/run/@cf/stabilityai/stable-diffusion-xl-base-1.0"


def test_cloudflare_model_listing_uses_internal_url_and_parses_names():
    source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    block = source[source.index('if provider == "cloudflare_workers_ai":'):source.index('if provider == "huggingface":', source.index('if provider == "cloudflare_workers_ai":'))]
    assert "cloudflare_workers_ai_models_url(account_id)" in block
    assert 'headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}' in block
    assert 'params = {} if page == 1 else {"page": page, "per_page": 100}' in block
    assert 'result_info.get("total_pages")' in block
    assert 'entries: Any = payload.get("result")' in block
    assert 'item.get("name") or item.get("id")' in block


def test_cloudflare_ui_hides_editable_base_url_and_renames_token():
    source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    block = source[source.index("def _render_media_provider_card"):source.index("def render_media_provider_cards")]
    assert '"Token API Workers AI"' in block
    assert 'definition.code == "cloudflare_workers_ai"' in block
    assert "cloudflare_workers_ai_run_base_url(account_id)" in block
    assert "cloudflare_workers_ai_models_url(account_id)" in source
    assert 'st.text_input("Base URL", value=display_base_url' in block
