from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STORAGE = Path(os.getenv("THUNDERBOLT_STORAGE_DIR") or ROOT / "storage")
DEFAULT_LLM_PROVIDER = "openai"
LEGACY_DEFAULT_LLM_PROVIDERS = {"", "moonshot"}
STATE = STORAGE / "state"
BLUEPRINTS = STORAGE / "blueprints"
TIKTOK_PROMPT_MASTERS = STORAGE / "tiktok" / "prompts_master"
MEDIA_DOWNLOADS = STORAGE / "downloads"
NICHES_DATA = STORAGE / "data" / "niches"
SEED_BLUEPRINTS = ROOT / "seed" / "blueprints"
SEED_TIKTOK_PROMPT_MASTERS = ROOT / "seed" / "prompt_masters"

DEFAULTS: dict[str, Any] = {
        "channels.json": [],
        "channel_videos.json": [],
        "tasks.json": [],
    "queues.json": {"niche": [], "blueprint": [], "brand": [], "script": [], "title": [], "thumbnail": [], "video": [], "edit": [], "upload": []},
    "batches.json": [],
    "uploads.json": [],
    "notifications.json": [],
    "media_downloads.json": [],
    "display_names.json": {"blueprints": {}, "prompt_masters": {}},
    "niche_apify_runs.json": [],
    "metadata_edits.json": [],
        "python_editor_edits.json": [],
        "scripts.json": [],
        "mcp_server.json": {
        "enabled": False,
        "host": "127.0.0.1",
        "port": 3031,
        "auth_token": "",
        "write_enabled": False,
    },
    "mcp_integrations.json": [
        {
            "id": "short-video-maker",
            "name": "Short Video Maker",
            "repository": "https://github.com/gyoridavid/short-video-maker",
            "protocol": "MCP + REST",
            "description": "Servidor externo para criação de vídeos curtos, com MCP e API REST.",
            "port": 3123,
            "active": False,
            "endpoint_note": "Porta documentada pelo projecto: 3123.",
        },
        {
            "id": "autovio",
            "name": "AutoVio",
            "repository": "https://github.com/Auto-Vio/autovio",
            "protocol": "MCP + REST",
            "description": "Pipeline externo de vídeo com API REST e servidor MCP separado.",
            "port": 3001,
            "active": False,
            "endpoint_note": "Porta padrão da API backend documentada pelo projecto: 3001.",
        },
        {
            "id": "openmontage",
            "name": "OpenMontage",
            "repository": "https://github.com/calesthio/OpenMontage",
            "protocol": "Agente local",
            "description": "Sistema externo de produção agentic de vídeo; não documenta um servidor MCP/HTTP padrão.",
            "port": 8000,
            "active": False,
            "endpoint_note": "Porta editável de referência; o projecto não documenta uma porta local padrão.",
        },
        {
            "id": "opencut",
            "name": "OpenCut",
            "repository": "https://github.com/opencut-app/opencut",
            "protocol": "API em desenvolvimento",
            "description": "Editor externo; a documentação actual indica API/MCP em desenvolvimento.",
            "port": 8787,
            "active": False,
            "endpoint_note": "Porta padrão da API documentada pelo projecto: 8787; frontend usa 5173.",
        },
    ],
    "settings.json": {
        "port": 3030,
        "moneyprinter_path": "",
        "script_interval_minutes": 10,
        "llm_rpm_limit": 40,
        "video_concurrency": 3,
        "upload_concurrency": 2,
        "youtube_api_key": "",
        "youtube_client_id": "",
        "youtube_client_secret": "",
        "youtube_batch_accounts": [],
        "youtube_batch_selected_account_id": "",
        "notification_preferences": {
            "video_completed": True,
            "music_completed": True,
            "standalone_script_generated": True,
            "music_lyrics_generated": True,
            "script_stage_completed": True,
            "title_generation_completed": True,
            "thumbnail_generation_completed": True,
            "blueprint_completed": True,
            "branding_completed": True,
            "niche_analysis_completed": True,
            "cuts_completed": True,
            "metadata_cleaning_completed": True,
            "python_edit_completed": True,
            "automation_completed": True,
            "automation_failed": True,
            "activity_failed": True,
            "upload_youtube_success": True,
            "upload_tiktok_success": True,
            "upload_instagram_success": True,
            "upload_facebook_pages_success": True,
            "upload_postiz_success": True,
            "upload_upload_post_success": True,
            "mcp_operation_completed": True,
        },
        "kaggle_username": "",
        "kaggle_api_key": "",
        "kaggle_kernel_slug": "thunderbolt-niche-finder",
        "apify_api_token": "",
        "apify_actor_id": "streamers~youtube-scraper",
        "apify_poll_interval_seconds": 10,
        "apify_run_timeout_seconds": 900,
        "llm_provider": DEFAULT_LLM_PROVIDER,
        "llm_provider_cards": [{
            "id": "llm-openai-default",
            "provider": "openai",
            "api_key": "",
            "model": "",
            "base_url": "https://integrate.api.nvidia.com/v1",
            "enabled": True,
            "telegram_llm": False,
        }],
        "llm_active_card_id": "llm-openai-default",
        "llm_telegram_card_id": "",
        "moonshot_api_key": "",
        "moonshot_base_url": "",
        "moonshot_model_name": "",
        "shengsuanyun_api_key": "",
        "shengsuanyun_base_url": "",
        "shengsuanyun_model_name": "",
        "openai_api_key": "",
        "openai_base_url": "https://integrate.api.nvidia.com/v1",
        "openai_model_name": "",
        "gemini_api_key": "",
        "gemini_model_name": "",
        "gemini_image_api_key": "",
        "gemini_image_model": "gemini-3.1-flash-image",
        "gemini_image_aspect_ratio": "16:9",
        "gemini_image_size": "1K",
        "deepseek_api_key": "",
        "deepseek_base_url": "",
        "deepseek_model_name": "",
        "qwen_api_key": "",
        "qwen_model_name": "",
        "azure_api_key": "",
        "azure_base_url": "",
        "azure_model_name": "",
        "azure_api_version": "2024-02-15-preview",
        "volcengine_api_key": "",
        "volcengine_base_url": "",
        "volcengine_model_name": "",
        "grok_api_key": "",
        "grok_base_url": "",
        "grok_model_name": "",
        "minimax_api_key": "",
        "minimax_base_url": "",
        "minimax_model_name": "",
        "mimo_api_key": "",
        "mimo_base_url": "",
        "mimo_model_name": "",
        "cloudflare_api_key": "",
        "cloudflare_account_id": "",
        "cloudflare_gateway_id": "",
        "cloudflare_model_name": "",
        "modelscope_api_key": "",
        "modelscope_base_url": "",
        "modelscope_model_name": "",
        "aihubmix_api_key": "",
        "aihubmix_base_url": "",
        "aihubmix_model_name": "",
        "aimlapi_api_key": "",
        "aimlapi_base_url": "",
        "aimlapi_model_name": "",
        "evolink_api_key": "",
        "evolink_base_url": "",
        "evolink_model_name": "",
        "ollama_base_url": "",
        "ollama_model_name": "",
        "oneapi_api_key": "",
        "oneapi_base_url": "",
        "oneapi_model_name": "",
        "litellm_model_name": "",
        "groq_api_key": "",
        "groq_base_url": "",
        "groq_model_name": "",
        "pollinations_api_key": "",
        "pollinations_base_url": "",
        "pollinations_model_name": "",
        "log_level": "DEBUG",
        "listen_host": "127.0.0.1",
        "listen_port": 8080,
        "ui_language": "pt",
        "video_language": "pt",
        "video_source": "pexels",
        "match_materials_to_script": False,
        "endpoint": "",
        "proxy_http": "",
        "proxy_https": "",
        "material_api_keys": {},
        "pexels_api_keys": "",
        "pixabay_api_keys": "",
        "coverr_api_keys": "",
        "wavespeed_api_keys": "",
        "loomloom_api_keys": "",
        "twelvelabs_api_keys": "",
        "sonilo_api_key": "",
        "subtitle_provider": "edge",
        "ffmpeg_path": "ffmpeg",
        "ffmpeg_version": "7.1-20240930",
        "video_codec": "h264_nvenc",
        "material_directory": "",
        "whisper_model_size": "large-v3",
        "whisper_device": "cpu",
        "whisper_compute_type": "int8",
        "azure_speech_key": "",
        "azure_speech_region": "",
        "siliconflow_tts_api_key": "",
        "minimax_tts_api_key": "",
        "minimax_tts_base_url": "",
        "minimax_tts_model_id": "speech-2.8-hd",
        "minimax_tts_voice_id": "English_expressive_narrator",
        "elevenlabs_api_key": "",
        "elevenlabs_model_id": "eleven_multilingual_v2",
        "chatterbox_base_url": "http://127.0.0.1:4123/v1",
        "chatterbox_api_key": "",
        "chatterbox_model_id": "chatterbox",
        "upload_post_enabled": False,
        "upload_post_api_key": "",
        "upload_post_username": "",
        "upload_post_platforms": "tiktok,instagram",
        "upload_post_auto_upload": False,
        "postiz_enabled": False,
        "postiz_api_key": "",
        "postiz_base_url": "https://api.postiz.com/public/v1",
        "postiz_mcp_url": "https://api.postiz.com/mcp",
        "postiz_mode": "api",
        "postiz_integration_id": "",
        "postiz_auto_publish": False,
        "tiktok_client_key": "",
        "tiktok_client_secret": "",
        "tiktok_accounts": [],
        "tiktok_redirect_uri": "http://localhost:3030/oauth/tiktok/callback",
        "tiktok_scopes": "user.info.basic,video.publish,video.upload",
        "tiktok_access_token": "",
        "tiktok_connection_status": "not_configured",
        "suno_api_key": "",
        "suno_api_base_url": "",
        "suno_api_endpoint": "/api/generate",
        "voice_preview_provider": "edge",
        "voice_preview_rate": "+0%",
        "direct_cookie_sid": "",
        "direct_cookie_ssid": "",
        "direct_cookie_hsid": "",
        "direct_cookie_apisid": "",
        "direct_cookie_sapisid": "",
        "direct_session_info": "",
        "direct_innertube_api_key": "",
        "direct_chunk_size": 262144,
    },
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed_blueprints() -> None:
    """Copy packaged seed Blueprints without overwriting local user files."""
    if not SEED_BLUEPRINTS.exists():
        return
    destination = BLUEPRINTS / "importados"
    destination.mkdir(parents=True, exist_ok=True)
    for source in sorted(SEED_BLUEPRINTS.glob("*.json")):
        target = destination / source.name
        if not target.exists():
            shutil.copy2(source, target)


def seed_prompt_masters() -> None:
    """Copy packaged TikTok Prompt Masters without overwriting user files."""
    if not SEED_TIKTOK_PROMPT_MASTERS.exists():
        return
    TIKTOK_PROMPT_MASTERS.mkdir(parents=True, exist_ok=True)
    for source in sorted(SEED_TIKTOK_PROMPT_MASTERS.glob("*.md")):
        target = TIKTOK_PROMPT_MASTERS / source.name
        if not target.exists():
            shutil.copy2(source, target)


def _migrate_settings(settings: Any) -> tuple[dict[str, Any], bool]:
    """Keep the OpenAI/NVIDIA NIM default and materialise the LLM card schema."""
    if not isinstance(settings, dict):
        return {"llm_provider": DEFAULT_LLM_PROVIDER}, True

    migrated = dict(settings)
    provider = str(migrated.get("llm_provider") or "").strip().lower()
    changed = False
    if provider in LEGACY_DEFAULT_LLM_PROVIDERS:
        migrated["llm_provider"] = DEFAULT_LLM_PROVIDER
        changed = True

    # Import localmente para evitar que o módulo de catálogo dependa do storage.
    # Settings antigos com um provider explícito continuam a ser devolvidos sem
    # alteração textual; os consumidores/UI fazem a materialização preguiçosa dos
    # cartões, evitando alterar dados durante uma simples leitura de compatibilidade.
    if "llm_provider_cards" not in migrated and provider not in LEGACY_DEFAULT_LLM_PROVIDERS:
        return settings, changed
    from hermes_ui.llm_providers import ensure_llm_provider_cards

    migrated, cards_changed = ensure_llm_provider_cards(migrated)
    return migrated, changed or cards_changed


def ensure_storage() -> None:
    for path in [STATE, BLUEPRINTS / "canais", BLUEPRINTS / "nichos", BLUEPRINTS / "importados", BLUEPRINTS / "brandings", TIKTOK_PROMPT_MASTERS, MEDIA_DOWNLOADS, STORAGE / "brand", STORAGE / "scripts", STORAGE / "thumbnails", STORAGE / "videos", STORAGE / "artifacts", STORAGE / "skills", STORAGE / "metadata_cleaner", STORAGE / "metadata_cleaner" / "outputs", STORAGE / "music", STORAGE / "voice_previews", STORAGE / "python_editor", NICHES_DATA]:
        path.mkdir(parents=True, exist_ok=True)
    seed_blueprints()
    seed_prompt_masters()
    for filename, default in DEFAULTS.items():
        target = STATE / filename
        if not target.exists():
            atomic_write(target, default)


def atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def read_json(name: str, default: Any | None = None) -> Any:
    ensure_storage()
    path = STATE / name
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if name != "settings.json":
            return data
        migrated, changed = _migrate_settings(data)
        if changed:
            atomic_write(path, migrated)
        return migrated
    except (json.JSONDecodeError, OSError):
        backup = path.with_suffix(path.suffix + f".corrupt-{datetime.now().strftime('%Y%m%d%H%M%S')}")
        if path.exists():
            shutil.copy2(path, backup)
        fallback = DEFAULTS.get(name, [] if default is None else default)
        atomic_write(path, fallback)
        return fallback


def write_json(name: str, data: Any) -> None:
    ensure_storage()
    atomic_write(STATE / name, data)


def append_json(name: str, item: dict[str, Any]) -> dict[str, Any]:
    entries = read_json(name, [])
    if not isinstance(entries, list):
        entries = []
    entries.append(item)
    write_json(name, entries)
    return item


def _display_name_key(kind: str, path: Path) -> str:
    """Return a stable storage-relative key without renaming the physical file."""
    resolved = path.resolve()
    if kind == "blueprints":
        root = BLUEPRINTS.resolve()
        try:
            return resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError("O ficheiro não pertence ao storage de Blueprints.") from exc
    if kind == "prompt_masters":
        root = TIKTOK_PROMPT_MASTERS.resolve()
        try:
            return resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError("O ficheiro não pertence ao storage de Prompt Masters.") from exc
    raise ValueError(f"Tipo de biblioteca inválido: {kind}")


def get_display_name(kind: str, path: Path, fallback: str) -> str:
    names = read_json("display_names.json", {"blueprints": {}, "prompt_masters": {}})
    if not isinstance(names, dict):
        return fallback
    entries = names.get(kind, {})
    if not isinstance(entries, dict):
        return fallback
    value = str(entries.get(_display_name_key(kind, path)) or "").strip()
    return value or fallback


def set_display_name(kind: str, path: Path, name: str) -> str:
    clean_name = " ".join(str(name).split()).strip()
    if not clean_name:
        raise ValueError("Informe um nome para a biblioteca.")
    if len(clean_name) > 120:
        raise ValueError("O nome deve ter no máximo 120 caracteres.")
    names = read_json("display_names.json", {"blueprints": {}, "prompt_masters": {}})
    if not isinstance(names, dict):
        names = {"blueprints": {}, "prompt_masters": {}}
    entries = names.get(kind)
    if not isinstance(entries, dict):
        entries = {}
        names[kind] = entries
    entries[_display_name_key(kind, path)] = clean_name
    write_json("display_names.json", names)
    return clean_name


def list_blueprint_files() -> list[Path]:
    ensure_storage()
    return sorted(BLUEPRINTS.rglob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def load_blueprint_file(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("O blueprint deve ser um objecto JSON.")
    return data


def list_prompt_master_files() -> list[Path]:
    """List only Markdown Prompt Master files stored in the TikTok area."""
    ensure_storage()
    return sorted(TIKTOK_PROMPT_MASTERS.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)


def load_prompt_master_file(path: Path) -> str:
    """Read a Prompt Master Markdown file without touching YouTube Blueprints."""
    if path.parent.resolve() != TIKTOK_PROMPT_MASTERS.resolve():
        raise ValueError("O Prompt Master deve pertencer ao storage TikTok dedicado.")
    return path.read_text(encoding="utf-8")
