from __future__ import annotations

from pathlib import Path
import os
import tempfile
from typing import Any

from hermes_ui.languages import language_code
from hermes_ui.material_sources import all_material_api_keys, selected_material_source

NVENC_VIDEO_CODEC = "h264_nvenc"

try:
    import toml
except ImportError:  # pragma: no cover - installation fallback
    toml = None


def _list_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").replace("\n", ",").split(",") if item.strip()]


def _set_if_present(target: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        target[key] = value


def build_moneyprinter_config(settings: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    config = dict(existing or {})
    app = dict(config.get("app") or {})
    whisper = dict(config.get("whisper") or {})
    azure = dict(config.get("azure") or {})
    siliconflow = dict(config.get("siliconflow") or {})
    minimax_tts = dict(config.get("minimax_tts") or {})
    elevenlabs = dict(config.get("elevenlabs") or {})
    chatterbox = dict(config.get("chatterbox") or {})
    proxy = dict(config.get("proxy") or {})
    ui = dict(config.get("ui") or {})

    app_map = {
        "llm_provider": "llm_provider",
        "moonshot_api_key": "moonshot_api_key",
        "moonshot_base_url": "moonshot_base_url",
        "moonshot_model_name": "moonshot_model_name",
        "shengsuanyun_api_key": "shengsuanyun_api_key",
        "shengsuanyun_base_url": "shengsuanyun_base_url",
        "shengsuanyun_model_name": "shengsuanyun_model_name",
        "openai_api_key": "openai_api_key",
        "openai_base_url": "openai_base_url",
        "openai_model_name": "openai_model_name",
        "gemini_api_key": "gemini_api_key",
        "gemini_model_name": "gemini_model_name",
        "deepseek_api_key": "deepseek_api_key",
        "deepseek_base_url": "deepseek_base_url",
        "deepseek_model_name": "deepseek_model_name",
        "qwen_api_key": "qwen_api_key",
        "qwen_model_name": "qwen_model_name",
        "azure_api_key": "azure_api_key",
        "azure_base_url": "azure_base_url",
        "azure_model_name": "azure_model_name",
        "azure_api_version": "azure_api_version",
        "volcengine_api_key": "volcengine_api_key",
        "volcengine_base_url": "volcengine_base_url",
        "volcengine_model_name": "volcengine_model_name",
        "grok_api_key": "grok_api_key",
        "grok_base_url": "grok_base_url",
        "grok_model_name": "grok_model_name",
        "minimax_api_key": "minimax_api_key",
        "minimax_base_url": "minimax_base_url",
        "minimax_model_name": "minimax_model_name",
        "mimo_api_key": "mimo_api_key",
        "mimo_base_url": "mimo_base_url",
        "mimo_model_name": "mimo_model_name",
        "cloudflare_api_key": "cloudflare_api_key",
        "cloudflare_account_id": "cloudflare_account_id",
        "cloudflare_gateway_id": "cloudflare_gateway_id",
        "cloudflare_model_name": "cloudflare_model_name",
        "modelscope_api_key": "modelscope_api_key",
        "modelscope_base_url": "modelscope_base_url",
        "modelscope_model_name": "modelscope_model_name",
        "aihubmix_api_key": "aihubmix_api_key",
        "aihubmix_base_url": "aihubmix_base_url",
        "aihubmix_model_name": "aihubmix_model_name",
        "aimlapi_api_key": "aimlapi_api_key",
        "aimlapi_base_url": "aimlapi_base_url",
        "aimlapi_model_name": "aimlapi_model_name",
        "evolink_api_key": "evolink_api_key",
        "evolink_base_url": "evolink_base_url",
        "evolink_model_name": "evolink_model_name",
        "ollama_base_url": "ollama_base_url",
        "ollama_model_name": "ollama_model_name",
        "oneapi_api_key": "oneapi_api_key",
        "oneapi_base_url": "oneapi_base_url",
        "oneapi_model_name": "oneapi_model_name",
        "litellm_model_name": "litellm_model_name",
        "groq_api_key": "groq_api_key",
        "groq_base_url": "groq_base_url",
        "groq_model_name": "groq_model_name",
        "pollinations_api_key": "pollinations_api_key",
        "pollinations_base_url": "pollinations_base_url",
        "pollinations_model_name": "pollinations_model_name",
        "log_level": "log_level",
        "listen_host": "listen_host",
        "listen_port": "listen_port",
        "video_source": "video_source",
        "endpoint": "endpoint",
        "material_directory": "material_directory",
        "match_materials_to_script": "match_materials_to_script",
        "sonilo_api_key": "sonilo_api_key",
        "sonilo_base_url": "sonilo_base_url",
        "subtitle_provider": "subtitle_provider",
        "ffmpeg_path": "ffmpeg_path",
        "video_codec": "video_codec",
        "material_directory": "material_directory",
        "match_materials_to_script": "match_materials_to_script",
        "twelvelabs_rerank_terms": "twelvelabs_rerank_terms",
    }
    for settings_key, config_key in app_map.items():
        if settings_key in settings:
            app[config_key] = settings[settings_key]
    # The bundled video pipeline is required to use NVIDIA NVENC.  The
    # MoneyPrinterTurbo runtime falls back to libx264 when this encoder is not
    # available on the host, preserving a playable output instead of failing.
    app["video_codec"] = NVENC_VIDEO_CODEC
    # Edge TTS V1 is retained as a keyless fallback, but its default 30-second
    # stream deadline is too short for longer scripts or slow networks.
    try:
        edge_tts_timeout = float(settings.get("edge_tts_timeout", 90))
    except (TypeError, ValueError):
        edge_tts_timeout = 90.0
    app["edge_tts_timeout"] = max(30, int(edge_tts_timeout))
    # A UI can store the canonical mapping while older installations still
    # expose one legacy field per source.  Export every supported source as a
    # TOML array so MoneyPrinterTurbo can rotate keys without CSV parsing.
    canonical_material_keys = all_material_api_keys(settings)
    for source, keys in canonical_material_keys.items():
        app[f"{source}_api_keys"] = _list_value(keys)
    app["video_source"] = selected_material_source(settings)
    config["app"] = app

    ui["language"] = language_code(settings.get("ui_language", ui.get("language", "pt")))
    requested_video_language = str(settings.get("video_language") or ui.get("video_language") or "").strip()
    ui["video_language"] = "" if requested_video_language.casefold() == "music" else language_code(requested_video_language)
    config["ui"] = ui

    whisper["model_size"] = settings.get("whisper_model_size", whisper.get("model_size", "large-v3"))
    whisper["device"] = settings.get("whisper_device", whisper.get("device", "cpu"))
    whisper["compute_type"] = settings.get("whisper_compute_type", whisper.get("compute_type", "int8"))
    config["whisper"] = whisper

    azure["speech_key"] = settings.get("azure_speech_key", azure.get("speech_key", ""))
    azure["speech_region"] = settings.get("azure_speech_region", azure.get("speech_region", ""))
    config["azure"] = azure

    siliconflow["api_key"] = settings.get("siliconflow_tts_api_key", siliconflow.get("api_key", ""))
    config["siliconflow"] = siliconflow

    for source, target in {
        "minimax_tts_api_key": "api_key",
        "minimax_tts_base_url": "base_url",
        "minimax_tts_model_id": "model_id",
        "minimax_tts_voice_id": "voice_id",
    }.items():
        if source in settings:
            minimax_tts[target] = settings[source]
    config["minimax_tts"] = minimax_tts

    elevenlabs["api_key"] = settings.get("elevenlabs_api_key", elevenlabs.get("api_key", ""))
    elevenlabs["model_id"] = settings.get("elevenlabs_model_id", elevenlabs.get("model_id", "eleven_multilingual_v2"))
    config["elevenlabs"] = elevenlabs

    chatterbox["base_url"] = settings.get("chatterbox_base_url", chatterbox.get("base_url", "http://127.0.0.1:4123/v1"))
    chatterbox["api_key"] = settings.get("chatterbox_api_key", chatterbox.get("api_key", ""))
    chatterbox["model_id"] = settings.get("chatterbox_model_id", chatterbox.get("model_id", "chatterbox"))
    config["chatterbox"] = chatterbox

    if settings.get("proxy_http"):
        proxy["http"] = settings["proxy_http"]
    if settings.get("proxy_https"):
        proxy["https"] = settings["proxy_https"]
    if proxy:
        config["proxy"] = proxy
    return config


def _atomic_write_text(target: Path, text: str) -> None:
    """Replace TOML atomically so a failed write cannot truncate the prior file."""
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=str(target.parent),
            prefix=f".{target.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, target)
    except Exception:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def sync_moneyprinter_config(settings: dict[str, Any], moneyprinter_path: str) -> Path | None:
    if not moneyprinter_path or toml is None:
        return None
    root = Path(moneyprinter_path).expanduser()
    if not root.exists():
        return None
    target = root / "config.toml"
    existing: dict[str, Any] = {}
    if target.exists():
        try:
            existing = toml.load(target)
        except Exception:
            existing = {}
    payload = build_moneyprinter_config(settings, existing)
    _atomic_write_text(target, toml.dumps(payload))
    return target
