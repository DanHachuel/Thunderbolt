from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from threading import RLock
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

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
SEED_THUMBNAIL_BLUEPRINTS = SEED_BLUEPRINTS / "thumbnails"
SEED_TIKTOK_PROMPT_MASTERS = ROOT / "seed" / "prompt_masters"

_READ_CACHE_LOCK = RLock()
_READ_CACHE: dict[str, tuple[tuple[int, int], Any]] = {}


def _ensure_directory(path: Path) -> None:
    """Create a storage directory safely during concurrent worker shutdown/startup."""
    try:
        if path.exists() and not path.is_dir():
            try:
                path.unlink()
            except OSError:
                pass
        path.mkdir(parents=True, exist_ok=True)
    except (FileExistsError, PermissionError, OSError):
        # A concurrent worker or an interrupted Windows shutdown must not abort the UI.
        pass

DEFAULTS: dict[str, Any] = {
        "channels.json": [],
        "channel_videos.json": [],
        "tasks.json": [],
        "music_tasks.json": [],
    "queues.json": {"niche": [], "blueprint": [], "brand": [], "script": [], "title": [], "thumbnail": [], "video": [], "edit": [], "upload": []},
    "batches.json": [],
    "uploads.json": [],
    "notifications.json": [],
    "media_downloads.json": [],
    "display_names.json": {"blueprints": {}, "prompt_masters": {}, "music": {}, "music_lyrics": {}},
    "niche_apify_runs.json": [],
    "metadata_edits.json": [],
        "python_editor_edits.json": [],
        "scripts.json": [],
        "drafts.json": [],
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
        "llm_rpm_limit_enabled": False,
        "llm_rpm_window_seconds": 60,
        "provider_max_attempts": 3,
        "provider_cooldown_seconds": 2,
        "video_concurrency": 3,
        "upload_concurrency": 2,
        "youtube_api_key": "",
        "youtube_client_id": "",
        "youtube_client_secret": "",
        "youtube_batch_accounts": [],
        "youtube_batch_selected_account_id": "",
        "telegram_enabled": False,
        "telegram_bot_token": "",
        "telegram_chat_id": "",
        "telegram_proxy_url": "",
        "telegram_timeout_seconds": 15,
        "session_info_ttl_hours": 36,
        "session_info_alert_hours": 6,
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
            "session_info_expiring": True,
            "session_info_expired": True,
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
        "google_images_cards": [],
        "media_provider_cards": [{
            "id": "media-nano-banana-default",
            "provider": "nano_banana",
            "api_key": "",
            "model": "gemini-3.1-flash-image",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "enabled": True,
            "priority": 0,
            "supports_image": True,
            "supports_video": False,
            "supports_text": False,
        }],
        "media_image_active_card_id": "media-nano-banana-default",
        "media_video_active_card_id": "",
        "media_image_provider": "nano_banana",
        "media_video_provider": "",
        "media_video_pool_enabled": False,
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
        "influencer_db_backend": "SQLite",
        "influencer_supabase_url": "",
        "influencer_supabase_key": "",
        "influencer_supabase_bucket": "ai-influencers",
        "influencer_sqlite_path": "storage/state/ai_influencers.db",
        "influencer_schema_version": 1,
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
        "ffmpeg_seed_path": "",
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
        "composio_enabled": True,
        "composio_auto_upload": True,
        "composio_api_key": "",
        "composio_user_id": "thunderbolt-local",
        "composio_connected_account_id": "",
        "composio_toolkit": "upload_video",
        "composio_tool_slug": "upload_video",
        "composio_file_field": "videoFilePath",
        "composio_channel_field": "",
        "composio_privacy_status": "unlisted",
        "composio_category_id": "22",
        "composio_language": "en",
        "composio_privacy_field": "privacyStatus",
        "composio_category_field": "categoryId",
        "composio_language_field": "defaultLanguage",
        "composio_arguments_json": "{}",
        "postiz_enabled": False,
        "postiz_api_key": "",
        "postiz_base_url": "https://api.postiz.com/public/v1",
        "postiz_mcp_url": "https://api.postiz.com/mcp",
        "postiz_mode": "api",
        "postiz_integration_id": "",
        "postiz_auto_publish": False,
        "tiktok_client_key": "",
        "tiktok_client_secret": "",
        "tiktok_api_cards": [],
        "tiktok_accounts": [],
        "tiktok_redirect_uri": "http://localhost:3030/oauth/tiktok/callback",
        "tiktok_scopes": "user.info.basic,video.publish,video.upload",
        "tiktok_access_token": "",
        "tiktok_connection_status": "not_configured",
        "suno_api_key": "",
        "suno_api_base_url": "",
        "suno_api_endpoint": "/api/generate",
        "lyria_api_key": "",
        "lyria_model": "lyria-3-clip-preview",
        "jewelmusic_enabled": False,
        "jewelmusic_api_key": "",
        "jewelmusic_base_url": "https://api.jewelmusic.com",
        "jewelmusic_proxy_url": "",
        "jewelmusic_timeout_seconds": 120,
        "pushtunes_enabled": False,
        "pushtunes_executable": "pushtunes",
        "pushtunes_source": "csv",
        "pushtunes_target": "ytm",
        "pushtunes_operation": "tracks",
        "pushtunes_profile": "",
        "pushtunes_csv_file": "",
        "pushtunes_ytm_auth_file": "",
        "pushtunes_tidal_session_file": "",
        "pushtunes_playlist_name": "",
        "pushtunes_similarity": 0.8,
        "pushtunes_working_directory": "",
        "pushtunes_spotify_client_id": "",
        "pushtunes_spotify_client_secret": "",
        "pushtunes_spotify_redirect_uri": "",
        "pushtunes_timeout_seconds": 1800,
        "ytmusicapi_enabled": False,
        "ytmusicapi_auth_file": "",
        "ytmusicapi_proxy_url": "",
        "ytmusicapi_timeout_seconds": 240,
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
    _ensure_directory(destination)
    for source in sorted(SEED_BLUEPRINTS.glob("*.json")):
        target = destination / source.name
        if not target.exists():
            shutil.copy2(source, target)
    thumbnail_destination = BLUEPRINTS / "thumbnails"
    _ensure_directory(thumbnail_destination)
    legacy_thumbnail = thumbnail_destination / "FINANCE_Thumbnail_Blueprint.md"
    renamed_thumbnail = thumbnail_destination / "FINANCE USA_Thumbnail_Blueprint.md"
    if renamed_thumbnail.is_file() and not legacy_thumbnail.exists():
        renamed_thumbnail.replace(legacy_thumbnail)
    for source in sorted(SEED_THUMBNAIL_BLUEPRINTS.glob("*.md")):
        target = thumbnail_destination / source.name
        if not target.exists():
            shutil.copy2(source, target)
    pair_source = SEED_BLUEPRINTS / "thumbnail_blueprint_pairs.json"
    pair_target = BLUEPRINTS / "thumbnail_blueprint_pairs.json"
    if pair_source.exists():
        try:
            seeded_pairs = json.loads(pair_source.read_text(encoding="utf-8"))
            current_pairs = json.loads(pair_target.read_text(encoding="utf-8")) if pair_target.exists() else {}
            if isinstance(seeded_pairs, dict) and isinstance(current_pairs, dict):
                finance_ids = {
                    "blueprintcanalfinanças", "blueprintcanalfinancas", "BLUEPRINT CANAL FINANÇAS",
                    "FINANÇAS", "FINANCAS", "FINANCE", "FINANCE USA", "FINANCE BRAZIL", "FINANCE CANADA",
                    "FINANCE FRANCE", "FINANCE GERMANY", "FINANCE IRELAND", "FINANCE ISRAEL", "FINANCE ITALY",
                    "FINANCE JAPAN", "FINANCE MEXICO", "FINANCE POLONY", "FINANCE SOUTH AFRICA",
                    "FINANCE SOUTH COREA", "FINANCE SPAIN", "FINANCE UK", "FINANCE AUSTRALIA",
                }
                merged_pairs = {**seeded_pairs, **current_pairs}
                merged_pairs.update({key: "FINANCE_Thumbnail_Blueprint" for key in finance_ids})
                if merged_pairs != current_pairs:
                    atomic_write(pair_target, merged_pairs)
        except (OSError, UnicodeError, json.JSONDecodeError):
            if not pair_target.exists():
                shutil.copy2(pair_source, pair_target)


def _rename_pending_finance_thumbnail_references(value: Any) -> tuple[Any, bool]:
    """Restore the finance thumbnail name in unfinished persisted records."""
    renamed = "FINANCE USA_Thumbnail_Blueprint"
    current = "FINANCE_Thumbnail_Blueprint"
    changed = False

    def replace(item: Any) -> Any:
        nonlocal changed
        if isinstance(item, str):
            if item == renamed:
                changed = True
                return current
            return item
        if isinstance(item, list):
            return [replace(entry) for entry in item]
        if isinstance(item, dict):
            return {key: replace(entry) for key, entry in item.items()}
        return item

    return replace(value), changed


def migrate_finance_thumbnail_blueprint() -> None:
    """Restore the finance thumbnail name in pending records and map finance variants."""
    def load_state(name: str, default: Any) -> Any:
        path = STATE / name
        try:
            return _load_json_unlocked(path)
        except (OSError, json.JSONDecodeError):
            return default

    def save_state(name: str, value: Any) -> None:
        _atomic_write_unlocked(STATE / name, value)

    channels = load_state("channels.json", [])
    if isinstance(channels, list):
        updated_channels, channels_changed = _rename_pending_finance_thumbnail_references(channels)
        if channels_changed:
            save_state("channels.json", updated_channels)

    tasks = load_state("tasks.json", [])
    if isinstance(tasks, list):
        pending_tasks = []
        tasks_changed = False
        for task in tasks:
            if not isinstance(task, dict) or bool(task.get("video_ready")) or str(task.get("state") or "").casefold() == "done":
                pending_tasks.append(task)
                continue
            updated_task, changed = _rename_pending_finance_thumbnail_references(task)
            pending_tasks.append(updated_task)
            tasks_changed = tasks_changed or changed
        if tasks_changed:
            save_state("tasks.json", pending_tasks)

    batches = load_state("batches.json", [])
    if isinstance(batches, list):
        pending_batches = []
        batches_changed = False
        for batch in batches:
            status = str(batch.get("status") or batch.get("state") or "").casefold() if isinstance(batch, dict) else ""
            if status in {"done", "completed", "published", "cancelled", "canceled"}:
                pending_batches.append(batch)
                continue
            updated_batch, changed = _rename_pending_finance_thumbnail_references(batch)
            pending_batches.append(updated_batch)
            batches_changed = batches_changed or changed
        if batches_changed:
            save_state("batches.json", pending_batches)

    queues = load_state("queues.json", {})
    if isinstance(queues, dict):
        updated_queues, queues_changed = _rename_pending_finance_thumbnail_references(queues)
        if queues_changed:
            save_state("queues.json", updated_queues)


_MIGRATION_DONE = False


def migrate_tiktok_thumbnail_blueprint() -> None:
    """Adopt the vertical generic thumbnail for legacy TikTok state."""
    global _MIGRATION_DONE
    if _MIGRATION_DONE:
        return
    _MIGRATION_DONE = True

    def load_state(name: str, default: Any) -> Any:
        try:
            return _load_json_unlocked(STATE / name)
        except (OSError, json.JSONDecodeError):
            return default

    def save_state(name: str, value: Any) -> None:
        _atomic_write_unlocked(STATE / name, value)

    channels = load_state("channels.json", [])
    channel_map = {str(item.get("id") or ""): item for item in channels if isinstance(item, dict)} if isinstance(channels, list) else {}
    vertical_ids = {"Generic_Thumbnail_Blueprint", "Youtube_Generic_Thumbnail_Blueprint"}
    channel_changes = False
    if isinstance(channels, list):
        for channel in channels:
            platform = str(channel.get("platform") or "").strip().casefold()
            current = str(channel.get("thumbnail_blueprint_id") or channel.get("default_thumbnail_blueprint_id") or "").strip()
            if platform in {"tiktok", "instagram", "instagram reels"} and (not current or current in vertical_ids):
                channel["thumbnail_blueprint_id"] = "Tiktok_Generic_Thumbnail_Blueprint"
                channel["default_thumbnail_blueprint_id"] = "Tiktok_Generic_Thumbnail_Blueprint"
                channel_changes = True
        if channel_changes:
            save_state("channels.json", channels)

    tasks = load_state("tasks.json", [])
    tasks_changed = False
    if isinstance(tasks, list):
        for task in tasks:
            if not isinstance(task, dict):
                continue
            channel = channel_map.get(str(task.get("channel_id") or ""), {})
            platform = str(task.get("platform") or channel.get("platform") or "").strip().casefold()
            format_value = str(task.get("format") or (task.get("generation_settings") or {}).get("video_aspect_ratio") or "").strip().casefold()
            vertical = platform in {"tiktok", "instagram", "instagram reels"} or format_value in {"portrait", "vertical", "shorts", "9:16"}
            current = str(task.get("thumbnail_blueprint_id") or "").strip()
            if vertical and (not current or current in vertical_ids):
                task["thumbnail_blueprint_id"] = "Tiktok_Generic_Thumbnail_Blueprint"
                tasks_changed = True
        if tasks_changed:
            save_state("tasks.json", tasks)


def seed_prompt_masters() -> None:
    """Copy packaged TikTok Prompt Masters without overwriting user files."""
    if not SEED_TIKTOK_PROMPT_MASTERS.exists():
        return
    _ensure_directory(TIKTOK_PROMPT_MASTERS)
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
    # Materializar ambos os schemas durante a leitura mantém settings antigos
    # compatíveis, sem eliminar as chaves legadas que ainda são consumidas pelo
    # pipeline e pela UI.
    from hermes_ui.llm_providers import ensure_llm_provider_cards
    from hermes_ui.media_providers import ensure_media_provider_cards

    if "llm_provider_cards" in migrated or provider in LEGACY_DEFAULT_LLM_PROVIDERS:
        migrated, cards_changed = ensure_llm_provider_cards(migrated)
    else:
        cards_changed = False
    migrated, media_changed = ensure_media_provider_cards(migrated)
    return migrated, changed or cards_changed or media_changed


def ensure_storage() -> None:
    for path in [STATE, BLUEPRINTS / "canais", BLUEPRINTS / "nichos", BLUEPRINTS / "importados", BLUEPRINTS / "brandings", BLUEPRINTS / "thumbnails", TIKTOK_PROMPT_MASTERS, MEDIA_DOWNLOADS, STORAGE / "brand", STORAGE / "scripts", STORAGE / "thumbnails", STORAGE / "videos", STORAGE / "artifacts", STORAGE / "python_editor", STORAGE / "influencers", STORAGE / "metadata_cleaner", STORAGE / "metadata_cleaner" / "outputs", STORAGE / "music", STORAGE / "voice_previews", STORAGE / "python_editor", NICHES_DATA]:
        _ensure_directory(path)
    seed_blueprints()
    seed_prompt_masters()
    for filename, default in DEFAULTS.items():
        target = STATE / filename
        if not target.exists():
            atomic_write(target, default)
    migrate_finance_thumbnail_blueprint()
    migrate_tiktok_thumbnail_blueprint()


_LOCK_TIMEOUT_SECONDS = 30.0
_LOCK_POLL_SECONDS = 0.05
_LOCK_STALE_SECONDS = 120
_PROTECTED_STATE_FILES = {"channels.json", "tasks.json", "batches.json", "queues.json", "uploads.json"}
_REPLACE_RETRY_DELAYS_SECONDS = (0.05, 0.1, 0.2, 0.4, 0.8, 1.0, 1.0, 1.0)


class StorageIntegrityError(RuntimeError):
    """Raised when protected state cannot be recovered without risking data loss."""


@contextmanager
def _state_lock(path: Path, *, read_only: bool = False) -> Iterator[None]:
    """Serialise state mutations across the UI and both local workers.

    A lock file is used instead of an in-memory mutex because the launcher
    runs Streamlit and workers as separate Python processes. Stale locks from
    a machine shutdown are reclaimed after a conservative timeout.
    """
    lock_path = path.with_name(f".{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if read_only:
        # JSON writes use os.replace(), so a reader can safely read either the
        # old complete file or the new complete file. Never make page loads
        # wait for a writer/antivirus handle on Windows.
        yield
        return
    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        except PermissionError:
            if not read_only:
                raise
            # Windows pode manter um lock residual aberto por outro processo
            # (ou por antivírus). Leituras de JSON continuam seguras porque as
            # escritas usam replace atómico; não bloquear a leitura evita que
            # uma página inteira falhe por causa de um lock de metadados.
            yield
            return
        except FileExistsError:
            try:
                lock_age = time.time() - lock_path.stat().st_mtime
                owner_pid = ""
                try:
                    owner_pid = lock_path.read_text(encoding="ascii").split("pid=", 1)[1].splitlines()[0].strip()
                except (IndexError, OSError, UnicodeDecodeError):
                    pass
                owner_alive = False
                if owner_pid.isdigit():
                    try:
                        os.kill(int(owner_pid), 0)
                        owner_alive = True
                    except PermissionError:
                        owner_alive = True
                    except (ProcessLookupError, OSError):
                        owner_alive = False
                if (owner_pid and not owner_alive) or (not owner_pid and lock_age > _LOCK_STALE_SECONDS):
                    lock_path.unlink()
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Não foi possível obter o lock de storage: {path.name}")
            time.sleep(_LOCK_POLL_SECONDS)
    try:
        yield
    finally:
        try:
            os.close(descriptor)
        finally:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


def _atomic_write_unlocked(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        replace_error: PermissionError | None = None
        for delay in (0.0, *_REPLACE_RETRY_DELAYS_SECONDS):
            if delay:
                time.sleep(delay)
            try:
                os.replace(temp_name, path)
                replace_error = None
                break
            except PermissionError as exc:
                # Windows can briefly keep the destination open while Streamlit,
                # an antivirus scanner, or the previous reader releases it.
                # Keep the atomic replace, but give that transient handle time
                # to disappear instead of failing the pipeline at its next
                # progress checkpoint.
                replace_error = exc
        if replace_error is not None:
            raise replace_error
    finally:
        try:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        except OSError:
            # A scanner may also briefly hold the temporary file. The next
            # write can clean it up; never hide the replace error with cleanup.
            pass


def atomic_write(path: Path, data: Any) -> None:
    """Write JSON through a locked, same-directory temporary file and replace.

    The complete payload is flushed and fsynced before replacement, so a
    process interruption cannot leave a partially written JSON document at the
    destination, while the lock prevents another process from racing with the
    replacement.
    """
    with _state_lock(path):
        _atomic_write_unlocked(path, data)


def _corrupt_backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup = path.with_suffix(path.suffix + f".corrupt-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}")
    shutil.copy2(path, backup)
    return backup


def _load_json_unlocked(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_fingerprint(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _invalidate_read_cache(path: Path) -> None:
    with _READ_CACHE_LOCK:
        _READ_CACHE.pop(str(path), None)


def _recover_json_unlocked(name: str, path: Path, default: Any | None) -> Any:
    backup = _corrupt_backup(path)
    if name in _PROTECTED_STATE_FILES:
        candidates = sorted(path.parent.glob(f"{path.name}.corrupt-*"), key=lambda item: item.stat().st_mtime, reverse=True)
        for candidate in candidates:
            if backup is not None and candidate == backup:
                continue
            try:
                recovered = _load_json_unlocked(candidate)
            except (json.JSONDecodeError, OSError):
                continue
            _atomic_write_unlocked(path, recovered)
            return recovered
        location = str(backup or path)
        raise StorageIntegrityError(f"O ficheiro protegido {name} está corrompido. A cópia foi preservada em {location}.")
    fallback = deepcopy(DEFAULTS.get(name, [] if default is None else default))
    _atomic_write_unlocked(path, fallback)
    return fallback


def read_json(name: str, default: Any | None = None) -> Any:
    ensure_storage()
    path = STATE / name
    fingerprint = _read_fingerprint(path)
    cache_key = str(path)
    if fingerprint is not None:
        with _READ_CACHE_LOCK:
            cached = _READ_CACHE.get(cache_key)
        if cached is not None and cached[0] == fingerprint:
            return deepcopy(cached[1])
    with _state_lock(path, read_only=True):
        try:
            data = _load_json_unlocked(path)
        except (json.JSONDecodeError, OSError):
            data = _recover_json_unlocked(name, path, default)
        if name != "settings.json":
            return data
        migrated, changed = _migrate_settings(data)
        if changed:
            _atomic_write_unlocked(path, migrated)
        result = migrated
        current_fingerprint = _read_fingerprint(path)
        if current_fingerprint is not None:
            with _READ_CACHE_LOCK:
                _READ_CACHE[cache_key] = (current_fingerprint, deepcopy(result))
        return deepcopy(result)


def update_json(name: str, default: Any, mutator: Callable[[Any], Any]) -> Any:
    """Atomically mutate one JSON document under the cross-process state lock."""
    ensure_storage()
    path = STATE / name
    with _state_lock(path):
        try:
            current = _load_json_unlocked(path)
        except (json.JSONDecodeError, OSError):
            current = _recover_json_unlocked(name, path, default)
        result = mutator(current)
        _atomic_write_unlocked(path, current)
        _invalidate_read_cache(path)
        return result


def write_json(name: str, data: Any) -> None:
    """Persist a state JSON file using :func:`atomic_write`."""
    ensure_storage()
    atomic_write(STATE / name, data)
    _invalidate_read_cache(STATE / name)


def append_json(name: str, item: dict[str, Any]) -> dict[str, Any]:
    def append(entries: Any) -> dict[str, Any]:
        if not isinstance(entries, list):
            raise StorageIntegrityError(f"O ficheiro {name} não contém uma lista válida.")
        entries.append(item)
        return item

    return update_json(name, [], append)


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
    if kind in {"music", "music_lyrics"}:
        root = (STORAGE / ("music" if kind == "music" else "scripts")).resolve()
        try:
            return resolved.relative_to(root).as_posix()
        except ValueError as exc:
            label = "música" if kind == "music" else "lyrics"
            raise ValueError(f"O ficheiro não pertence ao storage de {label}.") from exc
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
    return sorted(TIKTOK_PROMPT_MASTERS.glob("*.md"), key=lambda p: (p.name.casefold(), p.name))


def load_prompt_master_file(path: Path) -> str:
    """Read a Prompt Master Markdown file without touching YouTube Blueprints."""
    if path.parent.resolve() != TIKTOK_PROMPT_MASTERS.resolve():
        raise ValueError("O Prompt Master deve pertencer ao storage TikTok dedicado.")
    return path.read_text(encoding="utf-8")
