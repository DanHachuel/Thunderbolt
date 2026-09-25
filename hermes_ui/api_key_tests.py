"""Safe, read-only API credential diagnostics used by the Settings UI.

Every check in this module is deliberately bounded and avoids uploads, posts,
actor runs, image generation and audio generation.  Results contain no secret,
URL or raw exception text; callers may persist them in local settings safely.
"""

from __future__ import annotations

import os
import logging
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import quote, urlsplit, urlunsplit

import requests

from app.modules.niche_finder.apify import APIFY_API_BASE
from integrations.openai_model_discovery import OpenAICompatibleAPIError, validate_openrouter_api_key
from hermes_ui.media_providers import cloudflare_workers_ai_models_url

DEFAULT_TIMEOUT = 20
LOGGER = logging.getLogger(__name__)


def _result(status: str, message: str, *, status_code: int | None = None) -> dict[str, Any]:
    """Build a small persistence-safe result object."""
    return {
        "ok": status == "success",
        "status": status,
        "message": message,
        "status_code": status_code,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _missing(message: str = "Introduza a credencial antes de testar.") -> dict[str, Any]:
    return _result("missing", message)


def _unsupported(message: str) -> dict[str, Any]:
    return _result("unsupported", message)


def _safe_url(value: str) -> str:
    """Keep a configured base URL's scheme/host only; never echo credentials."""
    try:
        parsed = urlsplit(str(value or "").strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ""
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))
    except ValueError:
        return ""


def _response_result(response: Any) -> dict[str, Any]:
    status_code = int(getattr(response, "status_code", 0) or 0)
    if 200 <= status_code < 300:
        return _result("success", "API Key OK", status_code=status_code)
    if status_code == 401:
        return _result("error", "O Token API Workers AI foi rejeitado ou está expirado.", status_code=status_code)
    if status_code == 403:
        return _result("error", "O token não tem a permissão Workers AI Read ou Workers AI Write neste Account ID.", status_code=status_code)
    if status_code == 404:
        return _result("error", "O endpoint de diagnóstico não está disponível.", status_code=status_code)
    if status_code == 429:
        return _result("error", "A API limitou a chamada de diagnóstico.", status_code=status_code)
    status_suffix = f" (HTTP {status_code})" if status_code else ""
    return _result("error", f"A chamada de diagnóstico falhou{status_suffix}.", status_code=status_code or None)


def _get(url: str, **kwargs: Any) -> dict[str, Any]:
    try:
        response = requests.get(url, timeout=DEFAULT_TIMEOUT, **kwargs)
    except requests.RequestException:
        return _result("error", "Não foi possível contactar o serviço.")
    return _response_result(response)


def _post(url: str, **kwargs: Any) -> dict[str, Any]:
    try:
        response = requests.post(url, timeout=DEFAULT_TIMEOUT, **kwargs)
    except requests.RequestException:
        return _result("error", "Não foi possível contactar o serviço.")
    return _response_result(response)


def test_kaggle_credentials(username: str, api_key: str) -> dict[str, Any]:
    """Validate Kaggle Basic Auth with a read-only user lookup."""
    username = str(username or "").strip()
    api_key = str(api_key or "").strip()
    if not username or not api_key:
        return _missing("Introduza o username e a API key Kaggle antes de testar.")
    return _get(f"https://www.kaggle.com/api/v1/users/list/{quote(username, safe='')}", auth=(username, api_key))


def test_apify_credentials(api_token: str) -> dict[str, Any]:
    """Validate an Apify token without starting an Actor or reading a dataset."""
    api_token = str(api_token or "").strip()
    if not api_token:
        return _missing()
    return _get(f"{APIFY_API_BASE}/users/me", headers={"Authorization": f"Bearer {api_token}"})


def test_kalodata_credentials(api_key: str, base_url: str = "https://www.kalodata.com/openapi/v1") -> dict[str, Any]:
    """Validate Kalodata with the low-cost video ranking endpoint; never expose the key."""
    api_key = str(api_key or "").strip()
    safe_base_url = _safe_url(base_url)
    if not api_key:
        return _missing("A API Key do Kalodata não está configurada.")
    if not safe_base_url:
        return _result("error", "A Base URL do Kalodata não é válida.")
    endpoint = f"{safe_base_url}/tiktok/video/rank"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "secret-key": api_key,
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "region": "US",
        "language": "en-US",
        "currency": "USD",
        "date_range": "last7Day",
        "page_number": 1,
        "page_size": 1,
    }
    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException:
        LOGGER.error("Kalodata diagnostic failed endpoint=%s error=network", endpoint)
        return _result("error", "Não foi possível contactar o serviço.")
    if response.status_code >= 400:
        detail = str(response.text or "").replace(api_key, "[REDACTED]").strip()[:500]
        LOGGER.error("Kalodata diagnostic failed status=%s endpoint=%s response=%s", response.status_code, endpoint, detail)
    return _response_result(response)


def test_innertube_api_key(api_key: str) -> dict[str, Any]:
    """Validate a global InnerTube key with a public, read-only guide request."""
    api_key = str(api_key or "").strip()
    if not api_key:
        return _missing("Introduza a INNERTUBE_API_KEY antes de testar.")
    return _post(
        f"https://www.youtube.com/youtubei/v1/guide?key={quote(api_key, safe='')}",
        json={
            "context": {
                "client": {
                    "clientName": "WEB",
                    "clientVersion": "2.20250305.01.00",
                }
            }
        },
    )


def test_nano_banana_credentials(api_key: str, model: str) -> dict[str, Any]:
    """Validate the configured Gemini image model metadata without generating an image."""
    api_key = str(api_key or "").strip()
    model = str(model or "").strip()
    if not api_key:
        return _missing()
    if not model:
        return _result("missing", "Complete a configuração do modelo antes de testar.")
    model_path = model if model.startswith("models/") else f"models/{model}"
    return _get(
        f"https://generativelanguage.googleapis.com/v1beta/{model_path}",
        headers={"x-goog-api-key": api_key},
    )


def test_canva_credentials(card: Mapping[str, Any]) -> dict[str, Any]:
    """Validate Canva with the configured API key or OAuth access token."""
    source = dict(card) if isinstance(card, Mapping) else {}
    api_key = str(source.get("api_key") or "").strip()
    oauth_token = source.get("oauth_token") if isinstance(source.get("oauth_token"), Mapping) else {}
    token = api_key or str(oauth_token.get("access_token") or "").strip()
    if not token:
        return _missing("Introduza a API key ou autorize o Canva antes de testar este provider.")
    return _get(
        "https://api.canva.com/rest/v1/users/me",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )


def test_google_lyria_credentials(api_key: str, model: str) -> dict[str, Any]:
    """Validate access to the selected Lyria model without requesting audio generation."""
    api_key = str(api_key or "").strip()
    model = str(model or "").strip()
    if not api_key:
        return _missing("Introduza a Google Lyria API key antes de testar.")
    if not model:
        return _result("missing", "Seleccione o modelo Google Lyria antes de testar.")
    return _get(
        f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model.removeprefix('models/'), safe='')}",
        headers={"x-goog-api-key": api_key},
    )


def test_media_provider_card(card: Mapping[str, Any]) -> dict[str, Any]:
    """Run a bounded, non-generative check for an image/video provider card."""
    source = dict(card) if isinstance(card, Mapping) else {}
    provider = str(source.get("provider") or "").strip().lower()
    if provider == "canva":
        return test_canva_credentials(source)
    api_key = str(source.get("api_key") or "").strip()
    model = str(source.get("model") or "").strip()
    base_url = str(source.get("base_url") or "").strip().rstrip("/")
    api_style = str(source.get("api_style") or "").strip().lower()
    if provider == "nano_banana":
        return test_nano_banana_credentials(api_key, model)
    if provider == "together_ai":
        if not base_url:
            return _result("missing", "Complete a Base URL antes de testar.")
        if not api_key:
            return _missing("Introduza a API key Together AI antes de testar.")
        return _get(_models_endpoint(base_url), headers={"Authorization": f"Bearer {api_key}"})
    if provider == "huggingface":
        if not api_key:
            return _missing("Introduza o token Hugging Face antes de testar.")
        return _get(
            "https://huggingface.co/api/models",
            headers={"Authorization": f"Bearer {api_key}"},
            params={"pipeline_tag": "text-to-image", "limit": 1},
        )
    if provider == "cloudflare_workers_ai":
        account_id = str(source.get("account_id") or "").strip()
        if not api_key:
            return _missing("Introduza o Token API Workers AI antes de testar.")
        if not account_id:
            return _result("missing", "Complete o Account ID do Cloudflare antes de testar.")
        endpoint = cloudflare_workers_ai_models_url(account_id)
        return _get(endpoint, headers={"Authorization": f"Bearer {api_key}"})
    if not base_url:
        return _result("missing", "Complete a Base URL antes de testar.")
    if provider not in {"inferenceport", "ollama", "lmstudio"} and not api_key:
        return _missing("Introduza a API key/token antes de testar este provider.")
    if provider == "heygen":
        return _get(f"{base_url}/v3/users/me", headers={"X-Api-Key": api_key})
    if provider == "kie_ai":
        return _get(f"{base_url}/chat/credit", headers={"Authorization": f"Bearer {api_key}"})
    if provider == "fal_ai":
        return _get("https://api.fal.ai/v1/models", headers={"Authorization": f"Key {api_key}"})
    if not model and provider not in {"inferenceport", "cloudflare_workers_ai", "heygen"}:
        return _result("missing", "Complete o modelo antes de testar.")
    if provider == "openrouter":
        try:
            validate_openrouter_api_key(api_key, base_url, model)
        except OpenAICompatibleAPIError as exc:
            return _result("error", str(exc)[:240])
        return _result("success", "OpenRouter API Key e modelo OK")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    if api_style in {"openai_compatible", "huggingface", "agnes", "kie"} or provider in {"pollinations", "huggingface", "agnes", "inferenceport"}:
        endpoint = _models_endpoint(base_url)
    else:
        endpoint = base_url
    return _get(endpoint, headers=headers)


def test_azure_speech_credentials(api_key: str, region: str) -> dict[str, Any]:
    """Validate Azure Speech by listing voices; this does not synthesize audio."""
    api_key = str(api_key or "").strip()
    region = str(region or "").strip().lower()
    if not api_key or not region:
        return _missing("Introduza a Azure Speech key e a região antes de testar.")
    if not region.replace("-", "").isalnum():
        return _result("error", "A região Azure Speech não é válida.")
    endpoint = f"https://{region}.tts.speech.microsoft.com/tts/cognitiveservices/voices/list"
    return _get(endpoint, headers={"Ocp-Apim-Subscription-Key": api_key})


def test_elevenlabs_credentials(api_key: str) -> dict[str, Any]:
    """Validate ElevenLabs with the documented read-only models endpoint."""
    api_key = str(api_key or "").strip()
    if not api_key:
        return _missing()
    return _get("https://api.elevenlabs.io/v1/models", headers={"xi-api-key": api_key})


def _models_endpoint(base_url: str) -> str:
    base = _safe_url(base_url)
    if not base:
        return ""
    return f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"


def test_siliconflow_credentials(api_key: str) -> dict[str, Any]:
    """Validate SiliconFlow with its read-only model catalogue."""
    api_key = str(api_key or "").strip()
    if not api_key:
        return _missing()
    return _get("https://api.siliconflow.cn/v1/models", headers={"Authorization": f"Bearer {api_key}"})


def test_minimax_credentials(api_key: str, base_url: str) -> dict[str, Any]:
    """Validate a configured MiniMax endpoint without calling text-to-audio."""
    api_key = str(api_key or "").strip()
    endpoint = _models_endpoint(base_url)
    if not api_key or not str(base_url or "").strip():
        return _missing("Introduza a MiniMax TTS key e a Base URL antes de testar.")
    if not endpoint:
        return _result("error", "A Base URL MiniMax não é válida.")
    return _get(endpoint, headers={"Authorization": f"Bearer {api_key}"})


def test_openai_compatible_voice_credentials(provider: str, api_key: str, base_url: str) -> dict[str, Any]:
    """Validate a local/custom voice service through a read-only models endpoint."""
    provider = str(provider or "serviço").strip()
    api_key = str(api_key or "").strip()
    endpoint = _models_endpoint(base_url)
    if not str(base_url or "").strip():
        return _missing(f"Introduza a Base URL de {provider} antes de testar.")
    if not endpoint:
        return _result("error", f"A Base URL de {provider} não é válida.")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    return _get(endpoint, headers=headers)


def test_suno_credentials(api_key: str, base_url: str, endpoint: str) -> dict[str, Any]:
    """Avoid a Suno generation call: custom deployments have no common safe health API."""
    if not str(api_key or "").strip() or not str(base_url or "").strip():
        return _missing("Introduza a Suno API key e a Base URL antes de testar.")
    return _unsupported("Suno requer um endpoint de diagnóstico fornecido pelo serviço; o Thunderbolt não inicia uma geração só para testar.")


def test_tiktok_credentials(client_key: str, client_secret: str, access_token: str = "") -> dict[str, Any]:
    """Validate TikTok only when an OAuth access token is available."""
    client_key = str(client_key or "").strip()
    client_secret = str(client_secret or "").strip()
    token = str(access_token or os.getenv("TIKTOK_ACCESS_TOKEN", "") or "").strip()
    if not client_key or not client_secret:
        return _missing("Introduza o Client ID e o Client Secret TikTok antes de testar.")
    if not token:
        return _unsupported("TikTok só permite uma chamada autenticada depois da autorização OAuth; conclua o Playground e guarde um access token.")
    return _get(
        "https://open.tiktokapis.com/v2/user/info/?fields=open_id",
        headers={"Authorization": f"Bearer {token}"},
    )


def test_upload_post_credentials(api_key: str, base_url: str = "https://api.upload-post.com/api") -> dict[str, Any]:
    """Validate Upload-Post through GET /uploadposts/me, never through an upload."""
    api_key = str(api_key or "").strip()
    base = _safe_url(base_url or "https://api.upload-post.com/api")
    if not api_key:
        return _missing()
    if not base:
        return _result("error", "A Base URL Upload-Post não é válida.")
    return _get(f"{base}/uploadposts/me", headers={"Authorization": f"Apikey {api_key}"})


def test_postiz_credentials(api_key: str, base_url: str = "https://api.postiz.com/public/v1") -> dict[str, Any]:
    """Validate Postiz with the read-only integrations endpoint."""
    api_key = str(api_key or "").strip()
    base = _safe_url(base_url or "https://api.postiz.com/public/v1")
    if not api_key:
        return _missing()
    if not base:
        return _result("error", "A Base URL Postiz não é válida.")
    return _get(f"{base}/integrations", headers={"Authorization": api_key})


def test_telegram_credentials(bot_token: str, chat_id: str) -> dict[str, Any]:
    """Validate the Telegram bot token with getMe without sending a message."""
    bot_token = str(bot_token or "").strip()
    chat_id = str(chat_id or "").strip()
    if not bot_token or not chat_id:
        return _missing("Introduza o Bot Token e o Chat ID Telegram antes de testar.")
    result = _get(f"https://api.telegram.org/bot{bot_token}/getMe")
    if result.get("ok"):
        result["message"] = "Bot Token Telegram válido. O Chat ID foi aceite localmente; o teste não enviou mensagem."
    return result


def test_material_source_credentials(provider: str, api_key: str) -> dict[str, Any]:
    """Run a read-only provider-specific check for material source cards."""
    provider = str(provider or "").strip().lower()
    api_key = str(api_key or "").strip()
    if not api_key:
        return _missing()
    if provider == "pexels":
        return _get("https://api.pexels.com/v1/curated", params={"per_page": 1}, headers={"Authorization": api_key})
    if provider == "pixabay":
        return _get("https://pixabay.com/api/", params={"key": api_key, "per_page": 3})
    if provider == "coverr":
        return _get("https://api.coverr.co/v1/videos", headers={"Authorization": f"Bearer {api_key}"})
    return _unsupported("Este provider de materiais não expõe um endpoint de diagnóstico seguro no cartão actual.")


def test_influencer_database(settings: Mapping[str, Any]) -> dict[str, Any]:
    """Verify the configured AI Influencers backend without generating or deleting data."""
    try:
        from hermes_ui.influencers import test_backend
        return test_backend(settings)
    except Exception:
        return _result("error", "Não foi possível verificar o backend AI Influencers.")


def test_voice_provider(provider: str, settings: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a non-generating check for one provider in the voice/music group."""
    provider = str(provider or "").strip().lower()
    if provider == "azure_speech":
        return test_azure_speech_credentials(settings.get("azure_speech_key", ""), settings.get("azure_speech_region", ""))
    if provider == "elevenlabs":
        return test_elevenlabs_credentials(settings.get("elevenlabs_api_key", ""))
    if provider == "siliconflow":
        return test_siliconflow_credentials(settings.get("siliconflow_tts_api_key", ""))
    if provider == "minimax":
        return test_minimax_credentials(settings.get("minimax_tts_api_key", ""), settings.get("minimax_tts_base_url", ""))
    if provider == "chatterbox":
        return test_openai_compatible_voice_credentials("Chatterbox", settings.get("chatterbox_api_key", ""), settings.get("chatterbox_base_url", ""))
    if provider == "sonilo":
        return test_openai_compatible_voice_credentials("Sonilo", settings.get("sonilo_api_key", ""), settings.get("sonilo_base_url", ""))
    if provider == "suno":
        return test_suno_credentials(settings.get("suno_api_key", ""), settings.get("suno_api_base_url", ""), settings.get("suno_api_endpoint", ""))
    if provider == "google_lyria":
        return test_google_lyria_credentials(settings.get("lyria_api_key", ""), settings.get("lyria_model", ""))
    return _unsupported("Este provider de voz não tem diagnóstico remoto configurado.")


__all__ = [
    "test_apify_credentials",
    "test_azure_speech_credentials",
    "test_elevenlabs_credentials",
    "test_google_lyria_credentials",
    "test_innertube_api_key",
    "test_kaggle_credentials",
    "test_influencer_database",
    "test_material_source_credentials",
    "test_minimax_credentials",
    "test_nano_banana_credentials",
    "test_openai_compatible_voice_credentials",
    "test_postiz_credentials",
    "test_siliconflow_credentials",
    "test_suno_credentials",
    "test_tiktok_credentials",
    "test_upload_post_credentials",
    "test_voice_provider",
]
