import os
import sys
import io
import shutil
import subprocess

os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"
os.environ["CLICK_NO_WIN_CONSOLE"] = "1"
os.environ["PYTHONLEGACYWINDOWSSTDIO"] = "1"

def _force_utf8_stream(stream: object) -> object:
    if os.name != "nt":
        return stream
    buffer = getattr(stream, "buffer", None)
    if buffer is not None and not getattr(stream, "_thunderbolt_utf8", False):
        wrapped = io.TextIOWrapper(buffer, encoding="utf-8", errors="replace", line_buffering=True)
        setattr(wrapped, "_thunderbolt_utf8", True)
        return wrapped
    return stream

_original_stdout, _original_stderr = sys.stdout, sys.stderr
sys.stdout = _force_utf8_stream(sys.stdout)
sys.stderr = _force_utf8_stream(sys.stderr)

import hashlib
from html import escape
import json
import mimetypes
import re
import inspect
import time
from contextlib import nullcontext
from datetime import date, datetime, timezone
import uuid
from pathlib import Path
from typing import Any

import requests
import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx


def _has_script_context() -> bool:
    return get_script_run_ctx() is not None

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@st.cache_data(show_spinner=False, max_entries=256)
def _cached_file_bytes(path_string: str, modified_ns: int, size: int) -> bytes:
    """Cache card/download payloads while invalidating automatically after file changes."""
    del modified_ns, size
    return Path(path_string).read_bytes()


def _file_bytes(path: Path | None) -> bytes:
    if not path or not path.is_file():
        return b""
    stat = path.stat()
    return _cached_file_bytes(str(path.resolve()), int(stat.st_mtime_ns), int(stat.st_size))


def _render_local_video_player(path: Path, *, width: int | str = "stretch") -> None:
    """Render a local video through Streamlit without loading it into Python memory."""
    if not path.is_file():
        st.warning(f"Vídeo não encontrado: {path.name}")
        return
    video_kwargs: dict[str, Any] = {"format": mimetypes.guess_type(path.name)[0] or "video/mp4"}
    # ``width`` was added to st.video after the minimum Streamlit version used
    # by the launcher. Omit it on older installations so the native player
    # still renders instead of failing with an unexpected-keyword error.
    try:
        video_signature = inspect.signature(st.video)
    except (TypeError, ValueError):
        video_signature = None
    if video_signature is None or "width" in video_signature.parameters:
        video_kwargs["width"] = width
    # Streamlit's local media handler reliably resolves a string path. Passing
    # Path directly can leave the browser player waiting indefinitely on some
    # supported Streamlit versions.
    st.video(str(path), **video_kwargs)


def _load_local_env() -> None:
    for env_path in (ROOT / ".env", Path.cwd() / ".env"):
        try:
            if not env_path.is_file():
                continue
            for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("'\"")
                if key:
                    os.environ.setdefault(key, value)
        except OSError as exc:
            print(f"DEBUG: não foi possível ler {env_path}: {exc}")


_load_local_env()

try:
    APP_VERSION = json.loads((ROOT / "package.json").read_text(encoding="utf-8")).get("version", "")
except (OSError, json.JSONDecodeError):
    APP_VERSION = ""


def display_version(version: str) -> str:
    """Keep the project version label in the two-digit patch convention."""
    parts = str(version or "").strip().split(".")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        return f"{int(parts[0])}.{int(parts[1])}.{int(parts[2]):02d}"
    return str(version or "")


APP_VERSION_LABEL = display_version(APP_VERSION)

from hermes_ui.domain import STAGES, create_batch, create_channel, create_tasks_for_batch, delete_channel, delete_task, pipeline_summary, remake_video_task, retry_task_with_current_settings, set_channel_defaults, stop_task_by_user, transition_task, update_channel, update_channel_video
from hermes_ui.channel_import import build_channel_template_xlsx, channel_is_duplicate, find_duplicate_channel, parse_channel_workbook, resolve_blueprint, resolve_google_account, resolve_voice
from hermes_ui.drafts import list_drafts, save_draft
from hermes_ui.automation_worker import create_video_now_for_channel, load_worker_status
from hermes_ui.pipeline_worker import load_pipeline_worker_status, recover_stale_tasks, STALE_TASK_SECONDS, WORKER_HEARTBEAT_TIMEOUT_SECONDS
from hermes_ui.storage import BLUEPRINTS, DEFAULT_LLM_PROVIDER, MEDIA_DOWNLOADS, STORAGE, TIKTOK_PROMPT_MASTERS, atomic_write, ensure_storage, get_display_name, list_blueprint_files, list_prompt_master_files, load_blueprint_file, load_prompt_master_file, now, read_json, set_display_name, update_json, write_json
from app.modules.niche_finder.apify import ApifyError, DEFAULT_ACTOR_ID, abort_actor_run, build_actor_input, get_dataset_items, normalize_video_items, start_actor_run, wait_for_actor_run
from app.modules.niche_finder.data_loader import DatasetError, load_analysis_data
from app.modules.niche_finder.kaggle_runner import KaggleNicheError
from app.modules.niche_finder.summarizer import summarize_items
from app.modules.token_optimizer.cache_manager import clear_derived_cache
from app.modules.token_optimizer.compressor import check_installation
from app.modules.token_optimizer.config import DEFAULTS as TOKEN_OPTIMIZER_DEFAULTS
from app.modules.token_optimizer.metrics import get_stats as get_token_optimizer_stats
from app.influencers_ui import render_ai_influencer_characters, render_ai_influencer_content, render_ai_influencers_api_status, render_motion_control, render_ugc_products
from app.social_networks_ui import render_instagram_automation, render_meta_api_cards, render_social_networks
from hermes_ui.blueprints import create_blueprint_from_link, list_branding_files, save_generated_blueprint
from hermes_ui.thumbnail_blueprints import generate_thumbnail_blueprint, list_thumbnail_blueprint_documents, resolve_thumbnail_blueprint, save_thumbnail_blueprint, save_thumbnail_blueprint_pair, save_thumbnail_blueprint_pairs, thumbnail_blueprint_associations, thumbnail_blueprint_catalog, thumbnail_blueprint_for_blueprint, thumbnail_blueprint_for_channel
from hermes_ui.metadata_cleaner import build_description, clean_video_metadata, list_edit_records, metadata_manifest, normalize_tags, save_edit_record, store_external_video
from hermes_ui.python_editor import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS, PythonEditorError, change_speed, editor_manifest, extract_audio, list_edit_records as list_python_editor_records, list_generated_videos, list_scripts, list_video_files, read_script, remove_audio, replace_audio, resize_video, save_edit_record as save_python_editor_record, save_script, store_uploaded_asset, trim_video
from hermes_ui.cuts import CutsError, download_direct_video_url, generate_clips, list_generated_videos as list_cut_generated_videos, list_runs as list_cut_runs, list_video_files as list_cut_video_files, manifest_bytes as cut_manifest_bytes, store_uploaded_video, zip_run as zip_cut_run
from hermes_ui.mcp import detect_local_service, install_skill_locally, load_integrations, load_server_config, read_packaged_skill, save_server_config, update_integration
from hermes_ui.mcp_server import server_status, start_server, stop_server
from hermes_ui.material_sources import apply_material_source_cards_to_settings, ensure_material_source_cards, material_source_catalog, material_source_definition, new_material_card, normalize_material_card, selected_material_source
from hermes_ui.llm_providers import LLM_CARDS_KEY, LLM_PROVIDER_CATALOG, apply_llm_cards_to_settings, ensure_llm_provider_cards, new_llm_card, normalize_llm_card, provider_definition, test_llm_provider_card, stamp_test_result
from hermes_ui.media_providers import FULL_IA_VIDEO_PROVIDER_CODES, KIE_MEDIA_MODEL_CATALOG, MEDIA_CARDS_KEY, MEDIA_IMAGE_ACTIVE_CARD_KEY, MEDIA_VIDEO_ACTIVE_CARD_KEY, apply_media_provider_cards_to_settings, cloudflare_workers_ai_models_url, cloudflare_workers_ai_run_base_url, ensure_media_provider_cards, media_cards_for_pool, media_provider_catalog, media_provider_definition, new_media_card, normalize_media_card
from hermes_ui.media_generation import GOOGLE_IMAGES_COPYRIGHT_WARNING, ensure_google_images_cards, google_images_cards, new_google_images_card, test_google_images_card
from hermes_ui.music import create_music_task, list_music_files, list_music_tasks, materialize_suno_audio, request_suno_generation, run_music_task, store_music_file, store_voiceover_file, transition_music_task
from hermes_ui.music_generation import MUSIC_GENRES, MUSIC_VOCAL_OPTIONS, generate_music_fields
from hermes_ui.media_downloader import AUDIO_FORMATS, IMAGE_CONTAINERS, IMAGE_QUALITY_OPTIONS, VIDEO_CONTAINERS, VIDEO_QUALITY_OPTIONS, MediaDownloadError, build_download_options, clear_media_download_history, dependency_status, download_media, list_media_downloads, media_download_file
from hermes_ui.notifications import clear_notifications, list_notifications, mark_all_notifications_read, mark_notification_read, notification_event_catalog, notification_preferences, record_notification, reconcile_persisted_notifications as _do_reconcile_persisted_notifications, save_notification_preferences, unread_notification_count
from hermes_ui.influencers import BACKEND_OPTIONS, DOCUMENT_EXTENSIONS, IMAGE_EXTENSIONS, backend_name, backend_status, get_repository, test_backend
from hermes_ui.logs import list_logs, logs_to_rows
from hermes_ui.languages import FLAG_DATA_URIS_BY_ISO, LANGUAGE_CODES, VIDEO_LANGUAGE_CODES, LANGUAGE_FLAG_DATA_URIS, language_code, language_label, replace_flag_emojis, ui_language_menu_label, ui_text, video_language_label, video_language_options
from hermes_ui.countries import COUNTRY_OPTIONS
from hermes_ui.api_key_tests import test_apify_credentials, test_influencer_database, test_innertube_api_key, test_kaggle_credentials, test_kalodata_credentials, test_material_source_credentials, test_media_provider_card, test_nano_banana_credentials, test_postiz_credentials, test_telegram_credentials, test_tiktok_credentials, test_upload_post_credentials, test_voice_provider
from hermes_ui.tutorials import tutorial_body, tutorial_caption, tutorial_title
from hermes_ui.update_manager import check_version, restart_current_process, update_to_latest

from hermes_ui.script_documents import delete_script_document, list_script_documents, read_script_document, save_script_document, script_storage_path, update_script_document, update_script_document_metadata
from hermes_ui.script_generation import generate_script_document
from hermes_ui.video_length import DEFAULT_AVERAGE_VIDEO_TIME, channel_video_length, channel_video_time_value, default_average_video_time, length_generation_settings, words_from_channel_time
from hermes_ui.voice_preview import DEFAULT_SAMPLE, load_preview_file, synthesize_preview
from hermes_ui.elevenlabs_voices import ElevenLabsVoicesError, cached_personal_voices, fetch_personal_voices, personal_voice_options
from hermes_ui.thumbnail_generation import ThumbnailGenerationError, generate_thumbnail_image
from hermes_ui.thumbnails import (
    generate_thumbnail_for_task,
    list_thumbnail_tasks,
    regenerate_thumbnail,
    regenerate_thumbnail_lettering,
    regenerate_thumbnail_prompt,
    regenerate_thumbnail_prompt_and_image,
    upload_thumbnail_image,
)
from hermes_ui.draft_video import DRAFT_SETTING_SECTIONS, missing_content_fields, missing_setting_sections, normalise_saved_script, setting_widget_suffixes
from hermes_ui.creative_generation import CreativeGenerationError, generate_creative_package, generate_thumbnail_prompt, generate_title_and_keywords, generate_topic_for_channel, generate_video_description, generate_video_keywords, generate_video_update_metadata
from hermes_ui.media_generation import MediaGenerationError, format_media_generation_error, generate_image_for_card, generate_video_for_card
from hermes_ui.growth_youtube import list_analyses, run_audit
from hermes_ui.growth_tiktok import render_growth_tiktok
from hermes_ui.growth_instagram import render_growth_instagram
from hermes_ui.growth_facebook_pages import render_growth_facebook_pages
from hermes_ui.growth_bilibili import render_growth_bilibili
from hermes_ui.facebook_automation import caption_images, collect_images, create_post, generate_article, generate_theme, list_posts, publish_to_facebook, save_post
from hermes_ui.canva_auth import authorization_url, create_pkce_pair, create_state, exchange_code
from integrations.platforms import IntegrationResult, TikTokAdapter, YouTubeAdapter, fetch_channel_videos_public
from integrations.tiktok_public import fetch_public_tiktok_profile, normalize_tiktok_reference
from integrations.youtube_update import YOUTUBE_UPDATE_VIDEO, YouTubeVideoUpdater
from integrations.postiz import PostizAdapter
from integrations.upload_post import UploadPostAdapter, UPLOAD_POST_PLATFORM_OPTIONS, normalize_upload_post_platforms
from integrations.bilibili_upload import BilibiliApiAdapter, BILIBILI_DEFAULT_TID, BILIBILI_VIDEO_EXTENSIONS, normalise_bilibili_api_cards
from integrations.distrokid_upload import DistroKidAdapter, DISTROKID_AUDIO_EXTENSIONS, DISTROKID_COVER_EXTENSIONS, close_distrokid_session
from integrations.music_uploads import JewelMusicAdapter, PushtunesAdapter, YTMusicApiAdapter, MUSIC_UPLOAD_EXTENSIONS, PUSHTUNES_OPERATIONS, PUSHTUNES_SOURCES, PUSHTUNES_TARGETS, YT_MUSIC_UPLOAD_EXTENSIONS
from integrations.upload_routing import OFFICIAL_DAILY_LIMIT, _composio_upload, _resolve_channel_composio, official_upload_count, resolve_youtube_account, upload_with_default_route
from integrations.youtube_direct_upload import YouTubeDirectUploader
from integrations.youtube_direct_credentials import delete_credentials_document, direct_account_status, document_status, ensure_credentials_document, load_credentials_document, merge_credentials_document, parse_credentials_document, save_credentials_document, update_credentials_document_session_info
from integrations.session_info_health import check_account_session_info_health
from integrations.youtube_session_manager import renew_account_session
from integrations.youtube_batch import account_key as youtube_batch_account_key, account_status as youtube_batch_account_status, authorize_account as authorize_youtube_batch_account, delete_account_token as delete_youtube_batch_token, list_my_channels as list_youtube_batch_channels, loopback_redirect_uri
from integrations.youtube_upload import authorize_youtube_agent
from integrations.tiktok_public import fetch_public_tiktok_profile
from integrations.youtube_growth_api import find_account_for_channel as find_youtube_growth_account
from integrations.local_runtime import MoneyPrinterRuntime
from integrations.moneyprinter_config import sync_moneyprinter_config
from integrations.openai_model_discovery import DEFAULT_NVIDIA_NIM_BASE_URL
from integrations.composio_upload import ComposioUploadError, authorize_toolkit, discover_tools, execute_upload, parse_arguments, test_configuration

DEFAULT_UI_LANGUAGE = "en"


def reconcile_persisted_notifications(*, force: bool = False) -> int:
    """Run reconciliation once per Streamlit session until a real mutation forces it."""
    result_key = "_reconcile_persisted_notifications_result"
    dirty_key = "_reconcile_persisted_notifications_dirty"
    if not force and not st.session_state.get(dirty_key, False) and result_key in st.session_state:
        return int(st.session_state[result_key] or 0)
    result = _do_reconcile_persisted_notifications()
    st.session_state[result_key] = int(result or 0)
    st.session_state[dirty_key] = False
    return int(result or 0)

AI_STYLE_OPTIONS = [
    "Natural Realista",
    "Cocomelon style",
    "Retro 90s Cartoon",
    "Wool sculpture miniatures",
    "LEGO Style",
    "Paper cutout style",
    "Anime Style",
    "Studio Ghibli Style",
    "Stop Motion Style (Massinha)",
    "Ukiyo Style",
    "Pixel Animation",
    "Pixar Style",
]

WIDE_STYLE_OPTIONS = [
    "Montage: Pexels/Pixabay",
    "Montage: Text-to-Images",
    "Montage: Google Imagem API",
    "Full IA: Text-to-Video",
    "Remotion",
]
VIDEO_SOURCE_VALUES = {
    "Montage: Pexels/Pixabay": "pexels",
    "Montage: Text-to-Images": "text_to_images",
    "Montage: Google Imagem API": "google_images",
    "Full IA: Text-to-Video": "full_ia",
    "Remotion": "remotion",
}
VIDEO_SOURCE_LABELS = {value: label for label, value in VIDEO_SOURCE_VALUES.items()}
VIDEO_SOURCE_LABELS.update({
    "pixabay": "Montage: Pexels/Pixabay",
    "music": "Only Music",
    "only_music": "Only Music",
    "music_clip": "Clipes de Música",
    "music_clips": "Clipes de Música",
    "clips": "Clipes de Música",
})
UNAVAILABLE_VIDEO_SOURCES = {"remotion", "music_clips"}
CHANNEL_ASPECT_RATIO_OPTIONS = ["Landscape 16:9", "Portrait 9:16", "Square 1:1"]
CHANNEL_FORMAT_OPTIONS = ["wide", "Shorts", "Music"]


def channel_video_source_value(value: Any) -> str:
    raw = str(value or "").strip()
    if raw in WIDE_STYLE_OPTIONS:
        return raw
    if raw.casefold() == "pexels/pixabay":
        return "Montage: Pexels/Pixabay"
    if raw.casefold() == "apenas música" or raw.casefold() == "apenas musica":
        return "Only Music"
    if raw.casefold() == "full_ia":
        return "Full IA: Text-to-Video"
    return VIDEO_SOURCE_LABELS.get(raw.casefold(), VIDEO_SOURCE_LABELS.get(raw, WIDE_STYLE_OPTIONS[0]))


def channel_video_source_storage(value: str) -> str:
    raw = str(value or "").strip()
    if raw in VIDEO_SOURCE_VALUES:
        return VIDEO_SOURCE_VALUES[raw]
    if raw.casefold() in {"apenas música", "apenas musica", "music", "only_music"}:
        return "only_music"
    if raw.casefold() in {"music_clip", "music_clips", "clips", "clipes de música", "clipes de musica"}:
        return "music_clips"
    if raw.casefold() == "full_ia":
        return "full_ia"
    if raw.casefold() == "pexels/pixabay":
        return "pexels"
    if raw.casefold() == "pixabay":
        return "pexels"
    return raw
MATERIAL_SOURCE_OPTIONS = ["Pexels", "Pixabay"]

VIDEO_LANGUAGE_OPTIONS = [
    "00 – Apenas Música de Fundo (Sem Falas)",
    "01 – Inglês",
    "02 – Norueguês",
    "03 – Dinamarquês",
    "04 – Sueco",
    "05 – Holandês",
    "06 – Alemão",
    "07 – Luxemburguês",
    "08 – Finlandês",
    "09 – Hebraico",
    "10 – Japonês",
    "11 – Árabe (Golfo)",
    "12 – Islandês",
    "13 – Espanhol (Espanha)",
    "14 – Francês",
    "15 – Italiano",
    "16 – Coreano",
    "16 – Irlandês",
    "17 – Estoniano",
    "18 – Grego",
    "19 – Esloveno",
    "20 – Polonês",
    "21 – Tcheco",
    "22 – Lituano",
    "23 – Português (Portugal)",
    "24 – Eslovaco",
    "25 – Letão",
    "26 – Ucraniano",
    "27 – Húngaro",
    "28 – Afrikaans",
    "29 – Turco",
    "30 – Romeno",
    "31 – Russo",
    "32 – Croata",
    "33 – Árabe (Magreb)",
    "34 – Sérvio",
    "35 – Búlgaro",
    "36 – Português (Brasil)",
    "37 – Cantonês",
    "38 – Persa (Farsi)",
    "39 – Mandarim",
    "40 – Malaio",
    "41 – Espanhol (LatAm)",
    "42 – Vietnamita",
    "43 – Filipino (Tagalog)",
    "44 – Indonésio",
    "45 – Malayalam",
    "46 – Tailandês",
    "47 – Télugo",
    "48 – Tamil",
    "49 – Bengali",
    "50 – Hausa",
]

# Mantemos esta lista histórica para preservar Blueprints, testes e tarefas antigas.
# A criação de vídeos usa exclusivamente os dez códigos canónicos do MoneyPrinterTurbo;
# os quatro idiomas adicionais pertencem apenas ao selector da UI.
VIDEO_LANGUAGE_SELECTION_OPTIONS = ["music", *VIDEO_LANGUAGE_CODES, *[item for item in VIDEO_LANGUAGE_OPTIONS if item not in {"01 – Inglês", "06 – Alemão", "15 – Italiano", "29 – Turco", "31 – Russo", "36 – Português (Brasil)", "39 – Mandarim", "41 – Espanhol (LatAm)", "42 – Vietnamita", "44 – Indonésio"}]]

VIDEO_FORMAT_OPTIONS = ["wide", "shorts", "music"]
VIDEO_CONCATENATION_OPTIONS = ["Random Concatenation (Recommended)", "Sequential Concatenation"]
VIDEO_TRANSITION_OPTIONS = ["None", "Fade", "Dissolve"]
VIDEO_ENCODER_OPTIONS = ["Default (Recommended)", "H.264", "H.265"]
VOICEOVER_MODE_OPTIONS = ["Auto", "Upload", "None"]
VOICEOVER_SERVICE_OPTIONS = ["Azure Speech SDK V2", "Azure TTS V1", "ElevenLabs"]
VOICEOVER_VOLUME_OPTIONS = ["20%", "40%", "60%", "80%", "100%"]
VOICEOVER_SPEED_OPTIONS = ["0.5x", "0.75x", "1.0x", "1.25x", "1.5x", "2.0x"]
BACKGROUND_MUSIC_SOURCE_OPTIONS = ["Ficheiro existente", "Carregar ficheiro", "Criar via Suno API", "Random Background Music", "Sem música"]
BACKGROUND_MUSIC_VOLUME_OPTIONS = ["0%", "10%", "20%", "30%", "50%", "75%", "100%"]
SUBTITLE_FONT_OPTIONS = ["MicrosoftYaHeiBold.ttc", "Arial.ttf", "DejaVuSans.ttf"]
SUBTITLE_POSITION_OPTIONS = ["Bottom (Recommended)", "Top", "Center"]

ensure_storage()
st.set_page_config(page_title="Thunderbolt", page_icon="T", layout="wide", initial_sidebar_state="expanded")

theme_base = (st.get_option("theme.base") or "dark").lower()
_THEME_BOOTSTRAP = """
<script>
(() => {
    const STYLE_ID = "thunderbolt-light-theme-style";
    const COLOR = "#7A6FE4";
    const getStoredTheme = () => {
        try {
            return JSON.parse(window.localStorage.getItem("stActiveTheme-/-v2") || '"System"');
        } catch (_error) {
            return "System";
        }
    };
    const isLightTheme = () => {
        const selected = getStoredTheme();
        if (selected === "Light") return true;
        if (selected === "Dark") return false;
        return window.matchMedia("(prefers-color-scheme: light)").matches;
    };
    const applyTheme = () => {
        const existing = document.getElementById(STYLE_ID);
        if (!isLightTheme()) {
            if (existing) existing.remove();
            return;
        }
        const style = existing || document.createElement("style");
        style.id = STYLE_ID;
        style.textContent = `
:root { --primary-bg-color: ${COLOR}; }
html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stAppViewContainer"] > .main {
    min-height: 100vh !important;
    margin: 0 !important;
    background: ${COLOR} !important;
    background-image: none !important;
}
[data-testid="stSidebar"] {
    background: ${COLOR} !important;
    background-image: none !important;
}
`;
        if (!existing) document.head.appendChild(style);
    };
    applyTheme();
    window.setInterval(applyTheme, 500);
})();
</script>
"""
_html_parameters = inspect.signature(st.html).parameters
_html_options = {}
if "unsafe_allow_javascript" in _html_parameters:
    _html_options["unsafe_allow_javascript"] = True
st.html(_THEME_BOOTSTRAP, **_html_options)

_FLAG_RENDER_BOOTSTRAP = r"""
<script>
(() => {
    const FLAG_DATA_URIS = %s;
    const FLAG_PATTERN = /[\u{1F1E6}-\u{1F1FF}]{2}/gu;
    const toIso = (pair) => [...pair].map((character) => String.fromCharCode(65 + character.codePointAt(0) - 0x1F1E6)).join("");
    const replaceTextNode = (node) => {
        if (!node.nodeValue || !node.parentElement || node.parentElement.closest("img,script,style,noscript,textarea,input,option")) return;
        if (!FLAG_PATTERN.test(node.nodeValue)) {
            FLAG_PATTERN.lastIndex = 0;
            return;
        }
        FLAG_PATTERN.lastIndex = 0;
        const fragment = document.createDocumentFragment();
        let cursor = 0;
        for (const match of node.nodeValue.matchAll(FLAG_PATTERN)) {
            const iso = toIso(match[0]);
            const source = FLAG_DATA_URIS[iso];
            if (!source) continue;
            if (match.index > cursor) fragment.appendChild(document.createTextNode(node.nodeValue.slice(cursor, match.index)));
            const image = document.createElement("img");
            image.src = source;
            image.alt = iso;
            image.className = "tb-flag-icon";
            image.dataset.tbFlag = iso.toLowerCase();
            fragment.appendChild(image);
            cursor = match.index + match[0].length;
        }
        if (cursor === 0) return;
        if (cursor < node.nodeValue.length) fragment.appendChild(document.createTextNode(node.nodeValue.slice(cursor)));
        node.replaceWith(fragment);
    };
    const scan = (root = document.body) => {
        if (!root) return;
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        const nodes = [];
        let node;
        while ((node = walker.nextNode())) nodes.push(node);
        nodes.forEach(replaceTextNode);
    };
    const start = () => {
        scan();
        if (!document.body || window.__thunderboltFlagObserver) return;
        let scheduled = false;
        const observer = new MutationObserver(() => {
            if (scheduled) return;
            scheduled = true;
            window.requestAnimationFrame(() => { scheduled = false; scan(); });
        });
        observer.observe(document.body, { childList: true, subtree: true });
        window.__thunderboltFlagObserver = observer;
    };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
    else start();
})();
</script>
""" % json.dumps(FLAG_DATA_URIS_BY_ISO)
st.html(_FLAG_RENDER_BOOTSTRAP, **_html_options)

st.markdown("""
<style>
/*
   MoneyPrinterTurbo deixa a maior parte das cores a cargo do tema nativo do
   Streamlit. O Thunderbolt segue o mesmo princípio: componentes próprios usam
   currentColor/color-mix e nunca uma paleta escura fixa.
*/
:root { --tb-accent:#35a7ff; --tb-gold:#c59b55; }
.tb-flag-icon { width:1.2em; height:0.82em; object-fit:cover; vertical-align:-0.08em; margin:0 .1em; border-radius:2px; display:inline-block; }
[data-testid="stAppViewContainer"] { background:transparent; color:inherit; }
[data-testid="stSidebar"] { background:rgba(128,128,128,.04); border-right:1px solid rgba(128,128,128,.20); }
[data-testid="stSidebar"] { background:color-mix(in srgb, currentColor 4%, transparent); border-right:1px solid color-mix(in srgb, currentColor 16%, transparent); }
[data-testid="stSidebar"] .block-container { padding-top:0.28rem; padding-bottom:0.45rem; }
[data-testid="stSidebar"] > div:first-child { padding-top:0.28rem; }
[data-testid="stSidebar"] .tb-brand { display:flex; align-items:baseline; gap:0.42rem; margin:0 0 0.68rem 0; white-space:nowrap; }
[data-testid="stSidebar"] .tb-brand-name { color:inherit; font-size:1.38rem; line-height:1.15; font-weight:750; letter-spacing:-0.02em; }
[data-testid="stSidebar"] .tb-brand-version { color:inherit; opacity:.62; font-size:0.92rem; line-height:1; font-weight:500; }
[data-testid="stSidebar"] [data-testid="stButton"] { margin:0.025rem 0 !important; }
[data-testid="stSidebar"] [data-testid="stButton"] button { min-height:1.72rem; height:1.72rem; justify-content:flex-start !important; text-align:left !important; padding:0.10rem 0.52rem; border-radius:7px; border:1px solid transparent; font-size:0.86rem; font-weight:550; }
[data-testid="stSidebar"] [data-testid="stButton"] button > div { width:100% !important; justify-content:flex-start !important; text-align:left !important; }
[data-testid="stSidebar"] [data-testid="stButton"] button [data-testid="stMarkdownContainer"] { flex:1 1 auto !important; width:100% !important; text-align:left !important; }
[data-testid="stSidebar"] [data-testid="stButton"] p { margin:0; line-height:1; width:100%; text-align:left !important; }
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] { background:transparent; color:inherit; }
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"]:hover { background:rgba(128,128,128,.08); border-color:rgba(128,128,128,.25); color:inherit; }
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"]:hover { background:color-mix(in srgb, currentColor 8%, transparent); border-color:color-mix(in srgb, currentColor 18%, transparent); color:inherit; }
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] { background:#7c3aed !important; color:#ffffff !important; border-color:#8b5cf6 !important; }
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"]:hover { background:#6d28d9 !important; color:#ffffff !important; border-color:#a78bfa !important; }
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] span,
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] span { color:inherit; }
[data-testid="stSidebar"] [data-testid="stExpander"] { border:0 !important; background:transparent !important; margin:0.02rem 0 !important; }
[data-testid="stSidebar"] [data-testid="stExpander"] details { border:0 !important; background:transparent !important; }
[data-testid="stSidebar"] [data-testid="stExpander"] summary { min-height:1.72rem; padding:0.10rem 0.52rem !important; border-radius:7px; color:inherit; font-size:0.86rem; font-weight:650; }
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover { background:rgba(128,128,128,.08); }
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover { background:color-mix(in srgb, currentColor 8%, transparent); }
[data-testid="stSidebar"] [data-testid="stExpander"] summary p { margin:0; line-height:1; }
[data-testid="stSidebar"] [data-testid="stExpander"] > div { padding:0 0 0 0.42rem !important; }
[data-testid="stSidebar"] [data-testid="stExpander"] > div [data-testid="stButton"] button { padding-left:0.92rem; font-size:0.83rem; min-height:1.62rem; height:1.62rem; }
.content-card { box-sizing:border-box; padding:1rem 1.1rem; border:1px solid rgba(128,128,128,.28); border-radius:14px; background:rgba(128,128,128,.10); color:inherit; min-height:110px; box-shadow:0 4px 14px rgba(0,0,0,.12); }
.content-card { border:1px solid color-mix(in srgb, currentColor 18%, transparent); background:color-mix(in srgb, currentColor 5%, transparent); box-shadow:0 4px 14px color-mix(in srgb, currentColor 12%, transparent); }
.content-label { color:inherit; opacity:.72; font-size:.8rem; text-transform:uppercase; letter-spacing:.07em; }
.content-value { color:inherit; font-size:1.8rem; font-weight:700; margin-top:.3rem; }
.content-card .small-muted { color:inherit; opacity:.72; }
.stage { border-left:3px solid var(--tb-accent); padding:.65rem .8rem; margin:.4rem 0; background:rgba(128,128,128,.06); border-radius:8px; }
.stage { background:color-mix(in srgb, currentColor 4%, transparent); }
.small-muted { color:inherit; opacity:.65; font-size:.85rem; }
.tb-cuts-hero { max-width:860px; margin:0 auto 1.1rem; padding:1.6rem 1.4rem 1.35rem; text-align:center; border:1px solid rgba(128,128,128,.28); border-radius:18px; background:rgba(128,128,128,.06); box-shadow:0 18px 48px rgba(0,0,0,.12); }
.tb-cuts-hero { border:1px solid color-mix(in srgb, currentColor 18%, transparent); background:radial-gradient(circle at 50% 0, color-mix(in srgb, var(--tb-gold) 16%, transparent), transparent 58%), color-mix(in srgb, currentColor 4%, transparent); box-shadow:0 18px 48px color-mix(in srgb, currentColor 12%, transparent); }
.tb-cuts-hero .tb-cuts-kicker { color:var(--tb-gold); font-size:.68rem; letter-spacing:.18em; text-transform:uppercase; font-weight:700; }
.tb-cuts-hero h2 { color:inherit; font-family:Georgia,serif; font-size:2rem; font-weight:500; margin:.42rem 0 .25rem; text-transform:lowercase; }
.tb-cuts-hero p { color:inherit; opacity:.68; margin:0 auto; max-width:620px; font-size:.9rem; }
[data-testid="stRadio"] [role="radiogroup"] { gap:.6rem; }
[data-testid="stRadio"] label { border:1px solid rgba(128,128,128,.28); border-radius:12px; padding:.65rem .8rem; background:rgba(128,128,128,.06); min-height:4.3rem; }
[data-testid="stRadio"] label { border:1px solid color-mix(in srgb, currentColor 18%, transparent); background:color-mix(in srgb, currentColor 4%, transparent); }
[data-testid="stRadio"] label:has(input:checked) { border-color:var(--tb-gold); background:rgba(197,155,85,.24); }
[data-testid="stRadio"] label:has(input:checked) { background:linear-gradient(145deg, color-mix(in srgb, var(--tb-gold) 24%, transparent), color-mix(in srgb, currentColor 6%, transparent)); }
.tb-api-status { display:inline-flex; align-items:center; gap:.38rem; margin:.08rem 0 .55rem; padding:.18rem .55rem; border-radius:999px; font-size:.78rem; font-weight:700; line-height:1.2; border:1px solid rgba(128,128,128,.24); }
.tb-api-status__dot { display:inline-flex; align-items:center; justify-content:center; width:1rem; height:1rem; border-radius:50%; font-size:.68rem; font-weight:800; }
.tb-api-status--missing { color:#9a6700; background:rgba(245,158,11,.16); border-color:rgba(245,158,11,.45); }
.tb-api-status--missing .tb-api-status__dot { color:#fff; background:#d99000; }
.tb-api-status--local { color:#2563eb; background:rgba(59,130,246,.10); border-color:rgba(59,130,246,.35); }
.tb-api-status--ready { color:#15803d; background:rgba(34,197,94,.12); border-color:rgba(34,197,94,.36); }
.tb-api-status--ready .tb-api-status__dot { color:#fff; background:#16a34a; }
.tb-api-status--error { color:#b91c1c; background:rgba(239,68,68,.10); border-color:rgba(239,68,68,.34); }
.tb-api-status--error .tb-api-status__dot { color:#fff; background:#dc2626; }
[data-testid="stStatusWidget"] { border-color:rgba(128,128,128,.28) !important; background:rgba(128,128,128,.06) !important; }
[data-testid="stStatusWidget"] { border-color:color-mix(in srgb, currentColor 18%, transparent) !important; background:color-mix(in srgb, currentColor 4%, transparent) !important; }
/* O menu de idiomas usa layout nativo da aplicação; o toolbar do Streamlit não é alterado. */

/* Cores dos chips por identidade da plataforma, sem depender da ordem de selecção. */
[data-testid="stMultiSelectTagsContainer"] span[data-tag] { color:#ffffff !important; border:0 !important; font-weight:700 !important; }
[data-testid="stMultiSelectTagsContainer"] span[data-tag] span[title],
[data-testid="stMultiSelectTagsContainer"] span[data-tag] button,
[data-testid="stMultiSelectTagsContainer"] span[data-tag] svg { color:#ffffff !important; fill:#ffffff !important; }
[data-testid="stMultiSelectTagsContainer"] span[data-tag][aria-label="YouTube"] { background:#ff0000 !important; }
[data-testid="stMultiSelectTagsContainer"] span[data-tag][aria-label="TikTok"] { background:#000000 !important; }
[data-testid="stMultiSelectTagsContainer"] span[data-tag][aria-label="Instagram"] { background:#e1306c !important; }
[data-testid="stMultiSelectTagsContainer"] span[data-tag][aria-label="Facebook Pages"] { background:#1877f2 !important; }
/* Compatibilidade com versões BaseWeb que usam data-baseweb=tag. */
[data-testid="stMultiSelect"] [data-baseweb="tag"] { color:#ffffff !important; border:0 !important; font-weight:700 !important; }
[data-testid="stMultiSelect"] [data-baseweb="tag"]:has(button[aria-label*="YouTube"]) { background:#ff0000 !important; }
[data-testid="stMultiSelect"] [data-baseweb="tag"]:has(button[aria-label*="TikTok"]) { background:#000000 !important; }
[data-testid="stMultiSelect"] [data-baseweb="tag"]:has(button[aria-label*="Instagram"]) { background:#e1306c !important; }
[data-testid="stMultiSelect"] [data-baseweb="tag"]:has(button[aria-label*="Facebook Pages"]) { background:#1877f2 !important; }
[data-testid="stMultiSelect"] [data-baseweb="tag"] svg { color:#ffffff !important; fill:#ffffff !important; }
/* Notificações globais: o histórico continua persistente, mas os avisos surgem sem abrir a aba. */
[data-testid="stToastContainer"] { top:auto !important; right:1rem !important; bottom:1rem !important; left:auto !important; z-index:100000 !important; }
[data-testid="stToast"] { max-width:min(28rem, calc(100vw - 2rem)); }
</style>
""", unsafe_allow_html=True)


def current_ui_language() -> str:
    """Return the session language without hitting disk on every widget render."""
    cached = st.session_state.get("ui_language")
    if cached:
        return language_code(cached)
    requested = ""
    try:
        requested = str(st.query_params.get("lang") or "").strip()
    except Exception:
        requested = ""
    if requested:
        normalized = language_code(requested)
    else:
        # A raiz do launcher é o idioma padrão do sistema. A mudança explícita
        # de idioma continua a chegar por ?lang=..., incluindo a rota /en.
        normalized = DEFAULT_UI_LANGUAGE
    st.session_state["ui_language"] = normalized
    return normalized


_CONTENT_TRANSLATED_STREAMLIT_METHODS = {
    "title", "header", "subheader", "caption", "write", "markdown", "info", "warning", "error", "success",
    "button", "form_submit_button", "text_input", "text_area", "selectbox", "radio", "checkbox", "file_uploader",
    "date_input", "number_input", "multiselect", "toggle", "select_slider", "expander", "tabs",
}
_OPTION_TRANSLATED_STREAMLIT_METHODS = {"selectbox", "radio", "multiselect", "select_slider", "tabs"}
_STREAMLIT_I18N_INSTALLED = False


def _translated_option_label(value: Any, selected_language: str, formatter: Any = None) -> str:
    """Return a valid Streamlit display label without changing the stored option value."""
    formatted = formatter(value) if formatter is not None else value
    if isinstance(formatted, str):
        return ui_text(formatted, selected_language)
    return str(formatted)


def _translate_streamlit_arguments(method_name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    if not args and "label" not in kwargs:
        return args, kwargs
    selected_language = str(st.session_state.get("ui_language") or current_ui_language())
    translated_args = list(args)
    if translated_args and isinstance(translated_args[0], str):
        translated_args[0] = ui_text(translated_args[0], selected_language)
    elif isinstance(kwargs.get("label"), str):
        kwargs["label"] = ui_text(kwargs["label"], selected_language)
    if method_name == "markdown" and translated_args and isinstance(translated_args[0], str):
        translated_args[0] = replace_flag_emojis(translated_args[0])
        kwargs.setdefault("unsafe_allow_html", True)
    for keyword in ("placeholder", "help"):
        if isinstance(kwargs.get(keyword), str):
            kwargs[keyword] = ui_text(kwargs[keyword], selected_language)
    has_options = len(translated_args) >= 2 or "options" in kwargs
    if method_name in _OPTION_TRANSLATED_STREAMLIT_METHODS and has_options:
        existing_format_func = kwargs.get("format_func")
        if existing_format_func is None:
            kwargs["format_func"] = lambda value, language=selected_language: _translated_option_label(value, language)
        else:
            kwargs["format_func"] = lambda value, formatter=existing_format_func, language=selected_language: _translated_option_label(value, language, formatter)
    return tuple(translated_args), kwargs


def install_streamlit_content_translation() -> None:
    """Translate visible widget labels at render time while preserving stored option values."""
    global _STREAMLIT_I18N_INSTALLED
    if _STREAMLIT_I18N_INSTALLED:
        return
    for method_name in _CONTENT_TRANSLATED_STREAMLIT_METHODS:
        original = getattr(st, method_name)

        def translated_method(*args: Any, __method_name: str = method_name, __original: Any = original, **kwargs: Any):
            translated_args, translated_kwargs = _translate_streamlit_arguments(__method_name, args, kwargs)
            return __original(*translated_args, **translated_kwargs)

        setattr(st, method_name, translated_method)
    _STREAMLIT_I18N_INSTALLED = True


install_streamlit_content_translation()


NOTIFICATION_TOAST_INTERVAL = "3s"
NOTIFICATION_TOAST_MAX_PER_CYCLE = 3
NOTIFICATION_TOAST_SEEN_KEY = "_thunderbolt_notification_toast_seen_ids"
NOTIFICATION_TOAST_INITIALISED_KEY = "_thunderbolt_notification_toast_initialised"


def _notification_toast_seen_ids() -> set[str]:
    raw = st.session_state.get(NOTIFICATION_TOAST_SEEN_KEY, [])
    if isinstance(raw, (list, tuple, set)):
        return {str(item) for item in raw if str(item).strip()}
    return set()


def _save_notification_toast_seen_ids(notification_ids: set[str]) -> None:
    # Limitar o estado evita crescimento indefinido numa sessão longa.
    st.session_state[NOTIFICATION_TOAST_SEEN_KEY] = sorted(notification_ids)[-500:]


def _render_notification_toast_cycle() -> None:
    """Reconcile completions and display only new unread notifications in this session."""
    try:
        reconcile_persisted_notifications()
    except Exception:
        # A camada visual nunca deve interromper o pipeline ou os workers.
        return
    entries = list_notifications(limit=5, unread_only=True)
    current_ids = {str(item.get("id") or "") for item in entries if str(item.get("id") or "")}
    seen_ids = _notification_toast_seen_ids()
    if not st.session_state.get(NOTIFICATION_TOAST_INITIALISED_KEY, False):
        # Não transformar o histórico antigo numa avalanche de pop-ups ao abrir a UI.
        seen_ids.update(current_ids)
        _save_notification_toast_seen_ids(seen_ids)
        st.session_state[NOTIFICATION_TOAST_INITIALISED_KEY] = True
        return

    pending = [item for item in reversed(entries) if str(item.get("id") or "") not in seen_ids]
    for item in pending[:NOTIFICATION_TOAST_MAX_PER_CYCLE]:
        notification_id = str(item.get("id") or "")
        if not notification_id:
            continue
        title = str(item.get("title") or item.get("label") or "Notificação").strip()
        message = str(item.get("message") or "").strip()
        body = f"**{title}**"
        if message:
            body = f"{body}\n\n{message}"
        if hasattr(st, "toast"):
            st.toast(body)
        seen_ids.add(notification_id)
    _save_notification_toast_seen_ids(seen_ids)


def render_global_notification_toasts() -> None:
    """Render notifications once per app run; never start a background timer."""
    if not _has_script_context():
        return
    _render_notification_toast_cycle()


def localized_tab_labels(labels: list[str], language: str | None = None) -> list[str]:
    """Translate Streamlit tab labels while keeping widget keys and behaviour stable."""
    selected_language = language_code(language or current_ui_language())
    return [ui_text(label, selected_language) for label in labels]


def render_localized_tabs(labels: list[str], language: str | None = None):
    """Render a tab group with labels translated for the selected UI language."""
    return st.tabs(localized_tab_labels(labels, language))


def save_ui_language(value: str) -> str:
    normalized = language_code(value)
    settings = read_json("settings.json", {})
    settings["ui_language"] = normalized
    write_json("settings.json", settings)
    try:
        sync_moneyprinter_config(settings, str(settings.get("moneyprinter_path") or ""))
    except Exception:
        # The selector remains usable even when no MoneyPrinterTurbo path exists.
        pass
    st.session_state["ui_language"] = normalized
    return normalized


def normalize_video_language(value: Any, default: str = "pt") -> str:
    raw = str(value or "").strip()
    return "music" if raw.casefold() == "music" else language_code(raw, default=default)


def save_video_language(value: str) -> str:
    normalized = normalize_video_language(value)
    settings = read_json("settings.json", {})
    settings["video_language"] = normalized
    write_json("settings.json", settings)
    try:
        sync_moneyprinter_config(settings, str(settings.get("moneyprinter_path") or ""))
    except Exception:
        pass
    st.session_state["video_language"] = normalized
    return normalized


def render_ui_language_picker(language: str) -> None:
    """Render the native MoneyPrinterTurbo-style picker with local SVG flags."""
    current = language_code(language)
    current_flag_uri = LANGUAGE_FLAG_DATA_URIS[current]
    option_flag_css = "\n".join(
        f'''[role="listbox"][aria-label="Language"] [role="option"][aria-posinset="{position}"] [data-item-hl]::before {{ content: ""; display: inline-block; width: 1.5rem; height: 1rem; margin-right: .55rem; flex: 0 0 auto; vertical-align: middle; background: url("{LANGUAGE_FLAG_DATA_URIS[code]}") center / cover no-repeat; border-radius: 2px; box-shadow: 0 0 0 1px rgba(255,255,255,.18); }}'''
        for position, code in enumerate(LANGUAGE_CODES, start=1)
    )
    st.markdown(
        f'''<style>
        [data-testid="stSelectbox"]:has(input[aria-label="Language"]) label {{ display: block !important; visibility: visible !important; }}
        [data-testid="stSelectbox"]:has(input[aria-label="Language"]) input {{ background-image: url("{current_flag_uri}") !important; background-repeat: no-repeat !important; background-position: .65rem center !important; background-size: 1.5rem 1rem !important; padding-left: 2.55rem !important; }}
        [role="listbox"][aria-label="Language"] [data-item-hl] {{ display: flex; align-items: center; }}
        {option_flag_css}
        </style>''',
        unsafe_allow_html=True,
    )
    _spacer, language_col = st.columns([5.2, 1.5])
    with language_col:
        selected = st.selectbox(
            "Language",
            list(LANGUAGE_CODES),
            index=list(LANGUAGE_CODES).index(current),
            format_func=ui_language_menu_label,
            key="top_language_code_selector",
            label_visibility="visible",
        )
    if selected != current:
        save_ui_language(selected)
        try:
            st.query_params["lang"] = selected
        except Exception:
            pass
        st.rerun()


def card(label: str, value: str | int, note: str = ""):
    st.markdown(f'<div class="content-card"><div class="content-label">{label}</div><div class="content-value">{value}</div><div class="small-muted">{note}</div></div>', unsafe_allow_html=True)


def _library_card_key(kind: str, path: Path) -> str:
    return hashlib.sha1(f"{kind}:{path.resolve()}".encode("utf-8")).hexdigest()[:12]


def _video_thumbnail(path: Path) -> bytes | None:
    """Create a small cached preview frame for a local video card."""
    if not path.is_file():
        return None
    thumbnail_dir = STORAGE / "ui_cache" / "video_thumbnails"
    thumbnail_dir.mkdir(parents=True, exist_ok=True)
    target = thumbnail_dir / f"{hashlib.sha1(str(path.resolve()).encode('utf-8')).hexdigest()}.jpg"
    try:
        if target.is_file() and target.stat().st_mtime >= path.stat().st_mtime:
            return target.read_bytes()
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return None
        completed = subprocess.run(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", "00:00:01", "-i", str(path), "-frames:v", "1", "-vf", "scale=640:-2", str(target)],
            capture_output=True,
            check=False,
            timeout=20,
        )
        if completed.returncode == 0 and target.is_file():
            return target.read_bytes()
    except (OSError, subprocess.SubprocessError):
        return None
    return None


def _render_library_name_editor(kind: str, path: Path, current_name: str) -> str:
    """Render the inline name editor while keeping the physical filename unchanged."""
    edit_key = f"rename_{kind}_{_library_card_key(kind, path)}"
    if st.session_state.get(edit_key):
        with st.form(f"{edit_key}_form", border=False):
            edited_name = st.text_input("Nome de apresentação", value=current_name, max_chars=120, key=f"{edit_key}_input")
            save_col, cancel_col = st.columns(2)
            with save_col:
                save_name = st.form_submit_button("Guardar nome", type="primary", width="stretch")
            with cancel_col:
                cancel_name = st.form_submit_button("Cancelar", width="stretch")
        if save_name:
            try:
                set_display_name(kind, path, edited_name)
                st.session_state.pop(edit_key, None)
                st.success("Nome actualizado.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        if cancel_name:
            st.session_state.pop(edit_key, None)
            st.rerun()
    return edit_key


def _render_card_pencil(edit_key: str) -> None:
    if st.button("✏️", help="Editar nome de apresentação", key=f"pencil_{edit_key}", type="tertiary", width="stretch"):
        st.session_state[edit_key] = True
        st.rerun()


def channel_options() -> list[dict]:
    return [c for c in read_json("channels.json", []) if c.get("active", True)]


@st.cache_data(ttl=30, show_spinner=False)
def blueprint_catalog() -> list[tuple[str, str]]:
    options = [("", "Sem Blueprint padrão")]
    for path in list_blueprint_files():
        try:
            data = load_blueprint_file(path)
            identifier = str(data.get("id") or path.stem)
            label = get_display_name("blueprints", path, str(data.get("name") or data.get("title") or path.stem))
            options.append((identifier, label))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return options


def blueprint_for_channel(channel: dict) -> dict[str, Any]:
    """Resolve a channel Blueprint by id, filename stem or display name."""
    blueprint_id = str(channel.get("default_blueprint_id") or channel.get("blueprint_id") or "").strip()
    if not blueprint_id:
        return {}
    for path in list_blueprint_files():
        try:
            data = load_blueprint_file(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        identifiers = {str(data.get("id") or ""), path.stem, str(data.get("name") or ""), get_display_name("blueprints", path, str(data.get("name") or path.stem))}
        if blueprint_id in identifiers:
            resolved = dict(data)
            resolved.setdefault("id", blueprint_id)
            resolved["name"] = get_display_name("blueprints", path, str(data.get("name") or path.stem))
            return resolved
    return {"id": blueprint_id, "name": blueprint_id}


def _resolve_saved_script_blueprint(record: dict[str, Any], channel: dict[str, Any]) -> tuple[str, str]:
    """Resolve legacy script Blueprint metadata from channel fields or its saved name."""
    blueprint_id = str(
        channel.get("default_blueprint_id")
        or channel.get("blueprint_id")
        or record.get("blueprint_id")
        or ""
    ).strip()
    blueprint_name = str(
        channel.get("default_blueprint_name")
        or channel.get("blueprint_name")
        or channel.get("blueprint")
        or record.get("blueprint_name")
        or record.get("blueprint")
        or ""
    ).strip()
    resolved = blueprint_for_channel(channel) if blueprint_id else {}
    resolved_name = str(resolved.get("name") or "").strip()
    if resolved_name and (resolved_name.casefold() != blueprint_id.casefold() or not blueprint_name):
        blueprint_name = resolved_name
    wanted = {value.casefold() for value in (blueprint_id, blueprint_name) if value}
    if wanted:
        for path in list_blueprint_files():
            try:
                data = load_blueprint_file(path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            display_name = get_display_name("blueprints", path, str(data.get("name") or data.get("title") or path.stem)).strip()
            identifiers = {
                str(data.get("id") or "").strip(),
                path.stem.strip(),
                str(data.get("name") or "").strip(),
                str(data.get("title") or "").strip(),
                display_name,
            }
            normalized_identifiers = {value.casefold() for value in identifiers if value}
            # Legacy records may contain a friendly alias such as MILITAR,
            # while the catalog identifier is the filename stem.
            matches_alias = any(
                wanted_value == identifier
                or wanted_value.endswith(identifier)
                or identifier.endswith(wanted_value)
                for wanted_value in wanted
                for identifier in normalized_identifiers
            )
            if matches_alias:
                return str(data.get("id") or path.stem).strip(), display_name
    return blueprint_id, blueprint_name or (blueprint_id if blueprint_id else "SEM BLUEPRINT CONFIGURADO")


def _script_channel(record: dict[str, Any], channels: list[dict[str, Any]]) -> dict[str, Any]:
    channel_id = str(record.get("channel_id") or "").strip()
    channel_name = str(record.get("channel_name") or record.get("channel") or "").strip().casefold()
    return next(
        (
            channel
            for channel in channels
            if isinstance(channel, dict)
            and (
                (channel_id and str(channel.get("id") or "").strip() == channel_id)
                or (channel_name and str(channel.get("name") or "").strip().casefold() == channel_name)
            )
        ),
        {},
    )


def _backfill_saved_script_blueprints(records: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Attach every saved video script to its channel or stored Blueprint."""
    channels = [item for item in read_json("channels.json", []) if isinstance(item, dict)]
    updated_records: list[dict[str, Any]] = []
    for record in records if records is not None else list_script_documents():
        if str(record.get("document_type") or "video_script").strip() != "video_script":
            continue
        channel = _script_channel(record, channels)
        blueprint_id, blueprint_name = _resolve_saved_script_blueprint(record, channel)
        current_id = str(record.get("blueprint_id") or "").strip()
        current_name = str(record.get("blueprint_name") or record.get("blueprint") or "").strip()
        if current_id == blueprint_id and current_name == blueprint_name:
            updated_records.append(record)
            continue
        try:
            updated = update_script_document_metadata(
                str(record.get("id") or ""),
                {"blueprint_id": blueprint_id, "blueprint": blueprint_name},
            )
        except (FileNotFoundError, OSError, ValueError):
            updated = {**record, "blueprint_id": blueprint_id, "blueprint_name": blueprint_name}
        updated_records.append(updated)
    return updated_records


def channel_video_language(channel: dict[str, Any] | None, fallback: str = "pt") -> str:
    """Return the channel's canonical video language, preserving legacy labels."""
    if not isinstance(channel, dict):
        return normalize_video_language(fallback)
    return normalize_video_language(channel.get("language") or fallback)


def channel_blueprint_summary(channel: dict) -> dict[str, str]:
    blueprint = blueprint_for_channel(channel)
    configured_id = str(channel.get("default_blueprint_id") or channel.get("blueprint_id") or "").strip()
    if not configured_id:
        return {"id": "", "name": "SEM BLUEPRINT CONFIGURADO", "voice": str(channel.get("default_voice") or channel.get("voice") or "")}
    return {
        "id": configured_id,
        "name": str(blueprint.get("name") or configured_id),
        "voice": str(channel.get("default_voice") or channel.get("voice") or ""),
    }


def render_channel_blueprint_panel(channel: dict, *, compact: bool = False) -> None:
    summary = channel_blueprint_summary(channel)
    voice = summary["voice"] or "Sem voz padrão"
    video_language = language_label(channel_video_language(channel))
    if summary["name"] == "SEM BLUEPRINT CONFIGURADO":
        st.warning(f"**SEM BLUEPRINT CONFIGURADO** · configure um Blueprint padrão na aba Canais. · **Idioma:** {video_language}")
    elif compact:
        st.caption(f"**Blueprint:** {summary['name']} · **Voz:** {voice} · **Idioma:** {video_language}")
    else:
        st.info(f"**Blueprint utilizado pelo canal:** {summary['name']} · `{summary['id']}` · **Voz:** {voice} · **Idioma:** {video_language}")


def render_channel_thumbnail_blueprint_panel(channel: dict, *, compact: bool = False) -> None:
    document = thumbnail_blueprint_for_channel(channel)
    name = str(document.get("name") or "SEM THUMBNAIL BLUEPRINT CONFIGURADO")
    if name == "SEM THUMBNAIL BLUEPRINT CONFIGURADO":
        st.warning("**SEM THUMBNAIL BLUEPRINT CONFIGURADO** · associe um Thumbnail Blueprint na aba Thumbnail Blueprints.")
    elif compact:
        st.caption(f"**Thumbnail Blueprint:** {name}")
    else:
        st.info(f"**Thumbnail Blueprint utilizado pelo canal:** {name} · apenas leitura")


def render_tiktok_prompt_master_panel(channel: dict, *, compact: bool = False) -> None:
    """Mostrar a configuração editorial TikTok sem exigir um Blueprint YouTube."""
    prompt_id = str(channel.get("default_prompt_master") or channel.get("prompt_master") or "").strip()
    _prompt_ids, prompt_labels = _tiktok_prompt_options()
    prompt_name = prompt_labels.get(prompt_id, prompt_id)
    if not prompt_id:
        st.warning("**SEM PROMPT MASTER CONFIGURADO** · configure um Prompt Master padrão na aba Canais Tiktok.")
    elif compact:
        st.caption(f"**Prompt Master TikTok:** {prompt_name}")
    else:
        st.info(f"**Prompt Master utilizado pelo canal TikTok:** {prompt_name} · `{prompt_id}`")


def creative_payload_from_result(channel: dict, topic: str, creative: dict, topic_source: str = "manual") -> dict[str, Any]:
    variant = creative.get("thumbnail_variant") or {}
    return {
        "topic": topic.strip(),
        "topic_source": topic_source,
        "title": str(creative.get("title") or topic).strip(),
        "title_candidates": creative.get("title_candidates") or [],
        "keywords": creative.get("keywords") or [],
        "thumbnail_variant": variant,
        "thumbnail_variants": creative.get("thumbnail_variants") or [],
        "thumbnail_prompt": str(variant.get("image_prompt") or ""),
        "thumbnail_text": str(variant.get("overlay_text") or ""),
        "thumbnail_status": str(creative.get("thumbnail_status") or "prompt_ready"),
        "blueprint_id": str(channel.get("default_blueprint_id") or channel.get("blueprint_id") or ""),
        "blueprint_name": str(channel_blueprint_summary(channel).get("name") or "SEM BLUEPRINT CONFIGURADO"),
        "thumbnail_blueprint_id": str(channel.get("default_thumbnail_blueprint_id") or channel.get("thumbnail_blueprint_id") or ""),
        "voice": str(channel.get("default_voice") or channel.get("voice") or ""),
        "ai_generation": {"creative": creative},
    }


def generate_topic_for_ui(settings: dict[str, Any], channel: dict, user_context: str = "") -> dict[str, Any]:
    return generate_topic_for_channel(settings, channel, blueprint_for_channel(channel), user_context=user_context)


def resolve_video_subject_for_generation(
    settings: dict[str, Any],
    channel: dict,
    entered_subject: str,
    blueprint: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Keep the user's Video Subject or generate one only when the field is empty."""
    manual_subject = str(entered_subject or "").strip()
    if manual_subject:
        return manual_subject, None

    selected_blueprint = blueprint if isinstance(blueprint, dict) else blueprint_for_channel(channel)
    topic_result = generate_topic_for_channel(settings, channel, selected_blueprint)
    generated_subject = str(topic_result.get("topic") or "").strip()
    if not generated_subject:
        raise CreativeGenerationError("A IA não devolveu um Video Subject válido.")
    return generated_subject, topic_result


def generate_video_content_for_ui(
    settings: dict[str, Any],
    channel: dict,
    subject: str,
    language: str,
    generation_settings: dict[str, Any] | None = None,
    blueprint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate the subject, script and English keywords in one MoneyPrinter-style action."""
    subject, topic_result = resolve_video_subject_for_generation(settings, channel, subject, blueprint)

    blueprint = blueprint if isinstance(blueprint, dict) else blueprint_for_channel(channel)
    generation_settings = {
        **(generation_settings or {}),
        **length_generation_settings(channel, blueprint),
    }
    script_result = generate_script_document(
        settings,
        document_type="Roteiro de vídeo",
        title=subject,
        brief=subject,
        language=str(language or channel.get("language") or "Português"),
        channel=channel,
        blueprint=blueprint,
        structure_notes=str((generation_settings or {}).get("script_structure_notes") or ""),
        generation_settings=generation_settings,
    )
    script = str(script_result.get("content") or "").strip()
    keywords = generate_video_keywords(
        settings,
        channel,
        subject,
        script,
        blueprint,
        language=str(language or channel.get("language") or "Português"),
    )
    return {
        "topic": subject,
        "topic_result": topic_result,
        "script_result": script_result,
        "script": script,
        "keywords": keywords,
        "topic_source": "llm" if topic_result else "manual",
    }


def _generate_video_content_callback(prefix: str, channel: dict, fallback_language: str, blueprint: dict[str, Any] | None = None) -> None:
    """Streamlit callback for the single button below Subject, Script and Keywords."""
    settings = read_json("settings.json", {})
    generation_settings = {
        "video_subject": str(st.session_state.get(f"{prefix}_video_subject") or "").strip(),
        "script_language": str(st.session_state.get(f"{prefix}_script_language") or fallback_language or "pt"),
        "script_structure_notes": str(st.session_state.get(f"{prefix}_script_structure_notes") or "").strip(),
        "generate_script_with_ai": True,
    }
    try:
        result = generate_video_content_for_ui(
            settings,
            channel,
            generation_settings["video_subject"],
            generation_settings["script_language"],
            generation_settings=generation_settings,
            blueprint=blueprint,
        )
        st.session_state[f"{prefix}_video_subject"] = result["topic"]
        st.session_state[f"{prefix}_video_script"] = result["script"]
        st.session_state[f"{prefix}_video_keywords"] = ", ".join(result["keywords"])
        if prefix == "pipeline_scripts":
            script_result = result.get("script_result") or {}
            st.session_state["script_draft"] = {
                "title": result["topic"],
                "summary": str(script_result.get("summary") or ""),
                "content": result["script"],
                "keywords": result["keywords"],
            }
            st.session_state["script_draft_title"] = result["topic"]
            st.session_state["script_draft_summary"] = str(script_result.get("summary") or "")
            st.session_state["script_draft_content"] = result["script"]
            st.session_state["script_draft_keywords"] = ", ".join(result["keywords"])
        st.session_state[f"{prefix}_topic"] = result["topic"]
        st.session_state[f"{prefix}_topic_meta"] = result.get("topic_result") or {
            "topic": result["topic"],
            "topic_source": result.get("topic_source", "manual"),
        }
        # A subject change invalidates a previously generated title/thumbnail package.
        st.session_state.pop(f"{prefix}_creative_payload", None)
        st.session_state[f"{prefix}_generate_content_notice"] = "Tema, roteiro e palavras-chave gerados com IA."
        st.session_state.pop(f"{prefix}_generate_content_error", None)
    except CreativeGenerationError as exc:
        st.session_state[f"{prefix}_generate_content_error"] = str(exc)
        st.session_state.pop(f"{prefix}_generate_content_notice", None)


def _save_pipeline_draft_callback(
    prefix: str,
    draft_kind: str,
    page_title: str,
    *,
    channel: dict[str, Any] | None = None,
    blueprint: dict[str, Any] | None = None,
    document_type: str = "video_script",
    title: str = "",
    brief: str = "",
) -> None:
    """Persist the current editable pipeline fields as a local draft."""
    channel = channel or {}
    blueprint = blueprint or {}
    is_script_draft = prefix == "pipeline_scripts"
    subject = str(st.session_state.get(f"{prefix}_video_subject") or "").strip()
    script = str(st.session_state.get(f"{prefix}_video_script") or "").strip()
    keywords = str(st.session_state.get(f"{prefix}_video_keywords") or (st.session_state.get("script_draft_keywords") if is_script_draft else "") or "").strip()
    draft_title = str((st.session_state.get("script_draft_title") if is_script_draft else "") or title or subject or page_title).strip()
    draft_brief = str((st.session_state.get("script_brief") if is_script_draft else "") or brief or subject).strip()
    draft_content = str((st.session_state.get("script_draft_content") if is_script_draft else "") or script).strip()
    if not any((draft_title, draft_brief, draft_content, keywords)):
        st.session_state[f"{prefix}_save_draft_error"] = "Preencha pelo menos um campo antes de guardar o rascunho."
        st.session_state.pop(f"{prefix}_save_draft_notice", None)
        return

    record = save_draft(
        {
            "draft_kind": draft_kind,
            "page": page_title,
            "title": draft_title,
            "brief": draft_brief,
            "content": draft_content,
            "video_subject": subject,
            "video_script": script,
            "video_keywords": keywords,
            "generation_settings": dict(st.session_state.get(f"{prefix}_generation_settings") or {}),
            "summary": str((st.session_state.get("script_draft_summary") if is_script_draft else "") or "").strip(),
            "document_type": document_type,
            "language": str(st.session_state.get(f"{prefix}_script_language") or "").strip(),
            "channel_id": str(channel.get("id") or ""),
            "channel_name": str(channel.get("name") or "Documento independente"),
            "blueprint_id": str(blueprint.get("id") or ""),
            "blueprint_name": str(blueprint.get("name") or "SEM BLUEPRINT CONFIGURADO"),
        }
    )
    st.session_state[f"{prefix}_save_draft_notice"] = f"Rascunho guardado localmente: {record['id']}."
    st.session_state.pop(f"{prefix}_save_draft_error", None)


def _video_topic_source(subject: str, prefix: str = "new_video") -> str:
    meta = st.session_state.get(f"{prefix}_topic_meta") or {}
    generated_topic = str(meta.get("topic") or "").strip() if isinstance(meta, dict) else ""
    return "llm" if generated_topic and generated_topic == str(subject or "").strip() and meta.get("topic_source") == "llm" else "manual"


def generate_creative_for_ui(settings: dict[str, Any], channel: dict, topic: str, topic_source: str = "manual") -> dict[str, Any]:
    creative = generate_creative_package(
        settings,
        channel,
        topic,
        blueprint_for_channel(channel),
        language=str(channel.get("language") or "Português"),
    )
    payload = creative_payload_from_result(channel, topic, creative, topic_source=topic_source)
    creative_key = hashlib.sha1(json.dumps({"channel_id": channel.get("id") or "", "topic": topic, "titles": payload.get("title_candidates", [])}, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    record_notification(
        "title_generation_completed",
        f"Títulos gerados: {payload.get('title') or topic or 'Vídeo'}",
        f"O pacote de títulos para {channel.get('name') or 'o canal seleccionado'} terminou de ser gerado.",
        metadata={"channel_name": channel.get("name") or "", "topic": topic},
        dedupe_key=f"titles:{creative_key}",
    )
    return payload


def generate_editorial_for_ui(settings: dict[str, Any], channel: dict, topic: str, topic_source: str = "manual") -> dict[str, Any]:
    """Generate title and keywords only; thumbnail prompt/image stay in the later pipeline stages."""
    editorial = generate_title_and_keywords(
        settings,
        channel,
        topic,
        blueprint_for_channel(channel),
        language=str(channel.get("language") or "Português"),
    )
    keywords = [str(item).strip() for item in editorial.get("keywords", []) if str(item).strip()]
    return {
        "topic": topic.strip(),
        "topic_source": topic_source or "manual",
        "title": str(editorial.get("title") or topic).strip(),
        "title_candidates": editorial.get("title_candidates") or [],
        "keywords": keywords[:15],
        "thumbnail_variant": {},
        "thumbnail_variants": [],
        "thumbnail_prompt": "",
        "thumbnail_text": "",
        "thumbnail_status": "pending_prompt",
        "generation_settings": {"video_keywords": keywords[:15]},
        "ai_generation": {"editorial": editorial},
    }


def generate_thumbnail_for_ui(
    settings: dict[str, Any],
    channel: dict[str, Any],
    topic: str,
    *,
    title: str = "",
    topic_source: str = "manual",
) -> dict[str, Any]:
    """Generate exactly one thumbnail brief for an existing video topic/title."""
    topic = str(topic or "").strip()
    if not topic:
        raise CreativeGenerationError("É necessário um tópico antes de gerar a thumbnail.")
    script_blueprint = blueprint_for_channel(channel)
    visual_blueprint = thumbnail_blueprint_for_channel(channel)
    if visual_blueprint.get("content"):
        script_blueprint = {**script_blueprint, "thumbnail_blueprint_rules": visual_blueprint.get("content", "")}
    variant = generate_thumbnail_prompt(
        settings,
        channel,
        topic,
        blueprint=script_blueprint,
        language=str(channel.get("language") or "Português"),
    )
    return {
        "topic": topic,
        "title": str(title or topic).strip(),
        "topic_source": topic_source or "manual",
        "thumbnail_variant": variant,
        "thumbnail_variants": [variant],
        "thumbnail_prompt": variant.get("image_prompt", ""),
        "thumbnail_text": variant.get("overlay_text", ""),
        "thumbnail_status": "prompt_ready",
        "title_candidates": [],
        "ai_generation": {"thumbnail": variant},
    }


def generate_thumbnail_variants_for_ui(
    settings: dict[str, Any],
    channel: dict[str, Any],
    topic: str,
    count: int,
    *,
    title: str = "",
    topic_source: str = "manual",
) -> dict[str, Any]:
    """Generate one independent thumbnail brief for each video in a batch."""
    count = max(1, min(int(count or 1), 100))
    variants: list[dict[str, Any]] = []
    for _index in range(count):
        generated = generate_thumbnail_for_ui(
            settings,
            channel,
            topic,
            title=title,
            topic_source=topic_source,
        )
        variants.append(dict(generated["thumbnail_variant"]))
    first = variants[0]
    return {
        "topic": topic,
        "title": str(title or topic).strip(),
        "topic_source": topic_source or "manual",
        "thumbnail_variant": first,
        "thumbnail_variants": variants,
        "thumbnail_prompt": first.get("image_prompt", ""),
        "thumbnail_text": first.get("overlay_text", ""),
        "thumbnail_status": "prompt_ready",
        "title_candidates": [],
        "ai_generation": {"thumbnail_variants": variants},
    }


def valid_hhmm(value: str) -> bool:
    return bool(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(value or "").strip()))


@st.cache_data(ttl=30, show_spinner=False)
def voice_catalog(current: str = "") -> list[str]:
    voices = [""]
    voice_file = ROOT / "integrations" / "data" / "azure_voices.json"
    try:
        voice_data = json.loads(voice_file.read_text(encoding="utf-8"))
        voices.extend(f"{item.get('name', '')}-{item.get('gender', '')}" for item in voice_data if item.get("name"))
    except (OSError, json.JSONDecodeError):
        pass
    for voice_id in personal_voice_options(read_json("settings.json", {})):
        if voice_id not in voices:
            voices.append(voice_id)
    for candidate in (current, "en-US-AriaNeural-Female", "pt-BR-FranciscaNeural-Female", "pt-BR-AntonioNeural-Male"):
        if candidate and candidate not in voices:
            voices.append(candidate)
    return voices


def render_video_generation_settings(
    prefix: str,
    *,
    current_language: str = "",
    channel: dict[str, Any] | None = None,
    default_aspect_ratio: str = "Landscape 16:9",
    generate_content_callback: Any | None = None,
    save_draft_callback: Any | None = None,
    sections: set[str] | None = None,
    include_content: bool = True,
) -> dict[str, Any]:
    """Render shared settings, optionally limiting the visible video sections."""
    settings: dict[str, Any] = {}
    visible_sections = sections if sections is not None else {"Configurações de vídeo", "Configurações de áudio", "Configurações de legendas"}

    if include_content:
        st.markdown("### Video Subject Settings")
        subject_cols = st.columns(2)
        with subject_cols[0]:
            settings["video_subject"] = st.text_input(
                "Video Subject",
                value=str(st.session_state.get(f"{prefix}_video_subject", "")),
                key=f"{prefix}_video_subject",
                placeholder="Ex.: How AI is changing everyday life",
            )
            normalized_current_language = normalize_video_language(current_language)
            if channel is not None:
                channel_id = str(channel.get("id") or channel.get("name") or "")
                channel_language_state_key = f"{prefix}_language_channel_id"
                if st.session_state.get(channel_language_state_key) != channel_id:
                    channel_language = channel_video_language(channel, fallback=normalized_current_language)
                    st.session_state[f"{prefix}_script_language"] = channel_language
                    st.session_state[channel_language_state_key] = channel_id
                normalized_current_language = normalize_video_language(st.session_state.get(f"{prefix}_script_language") or normalized_current_language)
            settings["script_language"] = st.selectbox(
                "Script Language",
                VIDEO_LANGUAGE_SELECTION_OPTIONS,
                index=VIDEO_LANGUAGE_SELECTION_OPTIONS.index(normalized_current_language) if normalized_current_language in VIDEO_LANGUAGE_SELECTION_OPTIONS else 0,
                format_func=video_language_label,
                key=f"{prefix}_script_language",
            )
        with subject_cols[1]:
            st.markdown("**Advanced Script Settings**")
            settings["script_structure_notes"] = st.text_area(
                "Estrutura e notas opcionais",
                value=str(st.session_state.get(f"{prefix}_script_structure_notes", "")),
                key=f"{prefix}_script_structure_notes",
                height=100,
                placeholder="Ex.: gancho forte, 6 cenas, narração documental…",
            )
            settings["generate_script_with_ai"] = st.checkbox("Generate Script & Keywords with AI", value=True, key=f"{prefix}_generate_script_with_ai")
        settings["video_script"] = st.text_area(
            "Video Script (Optional)",
            value=str(st.session_state.get(f"{prefix}_video_script", "")),
            key=f"{prefix}_video_script",
            height=130,
        )
        settings["video_keywords"] = st.text_area(
            "Video Keywords (English, Optional)",
            value=str(st.session_state.get(f"{prefix}_video_keywords", "")),
            key=f"{prefix}_video_keywords",
            height=90,
        )
        if generate_content_callback is not None:
            st.button(
                "Gerar tópico, roteiro e palavras-chave com IA",
                key=f"{prefix}_generate_video_content",
                width="stretch",
                type="secondary",
                icon=":material/auto_awesome:",
                on_click=generate_content_callback,
            )
            if st.session_state.get(f"{prefix}_generate_content_notice"):
                st.success(st.session_state[f"{prefix}_generate_content_notice"])
            if st.session_state.get(f"{prefix}_generate_content_error"):
                st.error(st.session_state[f"{prefix}_generate_content_error"])
        if save_draft_callback is not None:
            st.button(
                "Salvar rascunho",
                key=f"{prefix}_save_draft",
                width="stretch",
                type="secondary",
                icon=":material/save:",
                on_click=save_draft_callback,
            )
            if st.session_state.get(f"{prefix}_save_draft_notice"):
                st.success(st.session_state[f"{prefix}_save_draft_notice"])
            if st.session_state.get(f"{prefix}_save_draft_error"):
                st.error(st.session_state[f"{prefix}_save_draft_error"])

    if "Configurações de vídeo" in visible_sections:
        with st.expander("Configurações de vídeo", expanded=False):
            st.markdown("### Video Settings")
            video_cols = st.columns(2)
            with video_cols[0]:
                source_state_key = f"{prefix}_video_source"
                if st.session_state.get(source_state_key) not in WIDE_STYLE_OPTIONS:
                    st.session_state[source_state_key] = channel_video_source_value(st.session_state.get(source_state_key) or (channel or {}).get("style_wide") or WIDE_STYLE_OPTIONS[0])
                settings["video_source"] = st.selectbox("Video Source", WIDE_STYLE_OPTIONS, key=f"{prefix}_video_source")
                if settings["video_source"] == "Montage: Pexels/Pixabay":
                    configured_material_source = selected_material_source(read_json("settings.json", {}))
                    material_source_labels = {"pexels": "Pexels", "pixabay": "Pixabay"}
                    configured_material_label = material_source_labels.get(configured_material_source, "Pexels")
                    settings["material_source"] = st.selectbox(
                        "Stock Material Source",
                        MATERIAL_SOURCE_OPTIONS,
                        index=MATERIAL_SOURCE_OPTIONS.index(configured_material_label),
                        key=f"{prefix}_material_source",
                    )
                else:
                    settings["material_source"] = ""
                if settings["video_source"] == "Full IA: Text-to-Video":
                    settings["style_ia"] = st.selectbox("Estilo IA", AI_STYLE_OPTIONS, key=f"{prefix}_style_ia")
                else:
                    settings["style_ia"] = ""
                if settings["video_source"] == "Montage: Text-to-Images":
                    defaults = read_json("settings.json", {})
                    settings["text_to_images_scene_duration"] = st.number_input("Duração alvo das cenas (segundos)", min_value=1, max_value=30, value=int(defaults.get("text_to_images_scene_duration", 5)), key=f"{prefix}_text_to_images_scene_duration")
                    settings["text_to_images_fps"] = st.number_input("FPS Montage: Text-to-Images", min_value=1, max_value=60, value=int(defaults.get("text_to_images_fps", 30)), key=f"{prefix}_text_to_images_fps")
                    settings["text_to_images_ken_burns"] = st.checkbox("Usar efeito Ken Burns", value=bool(defaults.get("text_to_images_ken_burns", False)), key=f"{prefix}_text_to_images_ken_burns")
                    settings["text_to_images_style"] = st.selectbox("Estilo visual das imagens", AI_STYLE_OPTIONS, key=f"{prefix}_text_to_images_style")
                else:
                    settings["text_to_images_scene_duration"] = 5
                    settings["text_to_images_fps"] = 30
                    settings["text_to_images_ken_burns"] = False
                    settings["text_to_images_style"] = ""
                if settings["video_source"] != "Only Music":
                    settings["video_format"] = st.selectbox("Formato", VIDEO_FORMAT_OPTIONS, key=f"{prefix}_video_format")
                    settings["video_concatenation_mode"] = st.selectbox("Video Concatenation Mode", VIDEO_CONCATENATION_OPTIONS, key=f"{prefix}_video_concatenation")
                    settings["match_visuals_to_script_order"] = st.checkbox("Match Visuals to Script Order", value=False, key=f"{prefix}_match_visuals")
                    settings["video_transition_mode"] = st.selectbox("Video Transition Mode", VIDEO_TRANSITION_OPTIONS, key=f"{prefix}_video_transition")
                else:
                    settings["video_format"] = "music"
                    settings["video_concatenation_mode"] = "none"
                    settings["match_visuals_to_script_order"] = False
                    settings["video_transition_mode"] = "none"
            with video_cols[1]:
                if settings["video_source"] != "Only Music":
                    aspect_options = ["Portrait 9:16", "Landscape 16:9", "Square 1:1"]
                    if f"{prefix}_video_aspect_ratio" not in st.session_state:
                        st.session_state[f"{prefix}_video_aspect_ratio"] = default_aspect_ratio
                    settings["video_aspect_ratio"] = st.selectbox("Proporção do vídeo", aspect_options, index=aspect_options.index(st.session_state[f"{prefix}_video_aspect_ratio"]) if st.session_state[f"{prefix}_video_aspect_ratio"] in aspect_options else 0, key=f"{prefix}_video_aspect_ratio")
                    settings["maximum_clip_duration"] = st.selectbox("Maximum Clip Duration (seconds)", [3, 5, 8, 10, 15], key=f"{prefix}_maximum_clip_duration")
                    settings["videos_per_run"] = st.selectbox("Videos per Run", list(range(1, 11)), key=f"{prefix}_videos_per_run")
                    settings["video_encoder"] = st.selectbox("Video Encoder", VIDEO_ENCODER_OPTIONS, key=f"{prefix}_video_encoder")
                else:
                    st.caption("Only Music não usa formato, clips, encoder ou áudio de narração.")
                    settings["video_aspect_ratio"] = "Landscape 16:9"
                    settings["maximum_clip_duration"] = 5
                    settings["videos_per_run"] = 1
                    settings["video_encoder"] = "default"

    if "Configurações de áudio" in visible_sections and settings.get("video_source") != "Only Music":
        with st.expander("Configurações de áudio", expanded=False):
            st.markdown("### Audio Settings")
            audio_cols = st.columns(2)
            with audio_cols[0]:
                settings["voiceover_mode"] = st.radio("Voiceover Mode", VOICEOVER_MODE_OPTIONS, horizontal=True, key=f"{prefix}_voiceover_mode")
                settings["voiceover_file"] = str(st.session_state.get(f"{prefix}_voiceover_file", "") or "")
                if settings["voiceover_mode"] == "Upload":
                    st.caption("Carregue uma narração pronta; o ficheiro será usado directamente pelo MoneyPrinterTurbo.")
                    uploaded_voiceover = st.file_uploader(
                        "Ficheiro de narração",
                        type=["mp3", "mpeg", "wav", "m4a", "aac", "flac", "ogg"],
                        key=f"{prefix}_voiceover_upload",
                    )
                    if uploaded_voiceover is not None and st.button("Guardar áudio de narração", key=f"{prefix}_voiceover_store", width="stretch"):
                        try:
                            stored_voiceover = store_voiceover_file(uploaded_voiceover.name, uploaded_voiceover.getvalue())
                            st.session_state[f"{prefix}_voiceover_file"] = str(stored_voiceover)
                            settings["voiceover_file"] = str(stored_voiceover)
                            st.success(f"Narração guardada em `{stored_voiceover}`")
                        except (OSError, ValueError) as exc:
                            st.error(str(exc))
                    stored_voiceover_value = str(st.session_state.get(f"{prefix}_voiceover_file", "") or "")
                    if stored_voiceover_value and Path(stored_voiceover_value).is_file():
                        st.audio(stored_voiceover_value)
                        settings["voiceover_file"] = stored_voiceover_value
                configured_voice_settings = read_json("settings.json", {})
                configured_azure_voice = bool(
                    str(configured_voice_settings.get("azure_speech_key") or "").strip()
                    and str(configured_voice_settings.get("azure_speech_region") or "").strip()
                )
                voice_service_default = "Azure Speech SDK V2" if configured_azure_voice else "Azure TTS V1"
                if str(st.session_state.get(f"{prefix}_voice", "")).strip() in personal_voice_options(configured_voice_settings):
                    voice_service_default = "ElevenLabs"
                voice_service_index = VOICEOVER_SERVICE_OPTIONS.index(voice_service_default)
                settings["voiceover_service"] = st.selectbox(
                    "Voiceover Service",
                    VOICEOVER_SERVICE_OPTIONS,
                    index=voice_service_index,
                    key=f"{prefix}_voiceover_service",
                    help="Azure Speech SDK V2 usa a key/região configuradas e não depende do stream edge_tts. Azure TTS V1 usa edge_tts e pode funcionar sem key Azure.",
                )
                if channel is not None:
                    channel_id = str(channel.get("id") or channel.get("name") or "")
                    channel_voice = str(channel.get("default_voice") or channel.get("voice") or "").strip()
                    channel_state_key = f"{prefix}_voice_channel_id"
                    if st.session_state.get(channel_state_key) != channel_id:
                        st.session_state[f"{prefix}_voice"] = channel_voice
                        st.session_state[channel_state_key] = channel_id
                current_voice = str(st.session_state.get(f"{prefix}_voice", ""))
                voice_options = voice_catalog(current_voice)
                personal_options = personal_voice_options(configured_voice_settings)
                settings["voice"] = st.selectbox(
                    "Voice (match script language)",
                    voice_options,
                    format_func=lambda value: personal_options.get(value, value) if value else "Sem voz seleccionada",
                    key=f"{prefix}_voice",
                )
                volume_speed_cols = st.columns(2)
                with volume_speed_cols[0]:
                    settings["voiceover_volume"] = st.selectbox("Voiceover Volume", VOICEOVER_VOLUME_OPTIONS, index=VOICEOVER_VOLUME_OPTIONS.index("100%"), key=f"{prefix}_voiceover_volume")
                with volume_speed_cols[1]:
                    settings["voiceover_speed"] = st.selectbox("Voiceover Speed", VOICEOVER_SPEED_OPTIONS, index=VOICEOVER_SPEED_OPTIONS.index("1.0x"), key=f"{prefix}_voiceover_speed")
                st.button("Preview Voice", key=f"{prefix}_preview_voice", disabled=True, help="A pré-visualização de voz será ligada ao provider configurado.")
            with audio_cols[1]:
                background_music_label = "Fonte da música de fundo" if current_ui_language() == "pt" else "Background Music Source"
                settings["background_music_source"] = st.selectbox(background_music_label, BACKGROUND_MUSIC_SOURCE_OPTIONS, index=3, key=f"{prefix}_background_music_source")
                settings["background_music_volume"] = st.selectbox("Background Music Volume", BACKGROUND_MUSIC_VOLUME_OPTIONS, index=2, key=f"{prefix}_background_music_volume")

    if "Configurações de legendas" in visible_sections:
        with st.expander("Configurações de legendas", expanded=False):
            st.markdown("### Subtitle Settings")
            subtitle_cols = st.columns(2)
            with subtitle_cols[0]:
                settings["enable_subtitles"] = st.checkbox("Enable Subtitles", value=True, key=f"{prefix}_enable_subtitles")
                settings["subtitle_font"] = st.selectbox("Font", SUBTITLE_FONT_OPTIONS, key=f"{prefix}_subtitle_font")
                settings["subtitle_position"] = st.selectbox("Position", SUBTITLE_POSITION_OPTIONS, key=f"{prefix}_subtitle_position")
                settings["subtitle_color"] = st.color_picker("Color", "#FFFFFF", key=f"{prefix}_subtitle_color")
                settings["subtitle_background"] = st.checkbox("Background", value=True, key=f"{prefix}_subtitle_background")
                settings["subtitle_background_color"] = st.color_picker("Background Color", "#000000", key=f"{prefix}_subtitle_background_color")
                settings["subtitle_rounded_background"] = st.checkbox("Rounded Background", value=False, key=f"{prefix}_subtitle_rounded_background")
            with subtitle_cols[1]:
                settings["subtitle_font_size"] = st.slider("Font Size", min_value=12, max_value=96, value=60, key=f"{prefix}_subtitle_font_size")
                settings["subtitle_outline"] = st.color_picker("Outline", "#000000", key=f"{prefix}_subtitle_outline")
                settings["subtitle_outline_width"] = st.slider("Outline Width", min_value=0.0, max_value=5.0, value=1.5, step=0.25, key=f"{prefix}_subtitle_outline_width")
                st.button("Restore Subtitle Defaults", key=f"{prefix}_restore_subtitle_defaults", disabled=True, help="Os valores predefinidos já estão activos nesta configuração.")
    return settings


def channel_default_options(channel: dict) -> tuple[list[str], dict[str, str], str, list[str], str]:
    """Return synchronised Blueprint and voice options for a channel editor."""
    blueprint_items = blueprint_catalog()
    blueprint_ids = [item[0] for item in blueprint_items]
    blueprint_labels = {item[0]: item[1] for item in blueprint_items}
    current_blueprint = str(channel.get("default_blueprint_id") or channel.get("blueprint_id") or "")
    if current_blueprint and current_blueprint not in blueprint_ids:
        blueprint_ids.append(current_blueprint)
        blueprint_labels[current_blueprint] = current_blueprint
    current_voice = str(channel.get("default_voice") or channel.get("voice") or "")
    voice_options = voice_catalog(current_voice)
    return blueprint_ids, blueprint_labels, current_blueprint, voice_options, current_voice


def channel_niche_label(channel: dict) -> str:
    """Return the channel niche/reference label shown under the channel name."""
    niche = str(channel.get("niche") or "").strip()
    if niche:
        return niche
    references = channel.get("reference_channels")
    if isinstance(references, list):
        values = [str(item).strip() for item in references if str(item).strip()]
        if values:
            return ", ".join(values)
    blueprint = blueprint_for_channel(channel)
    metadata = blueprint.get("metadata") if isinstance(blueprint.get("metadata"), dict) else {}
    return str(blueprint.get("target_niche") or blueprint.get("niche") or metadata.get("target_niche") or metadata.get("niche") or "SEM NICHO CONFIGURADO").strip()


def _merge_channel_videos(channel_id: str, videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing = read_json("channel_videos.json", [])
    if not isinstance(existing, list):
        existing = []
    other_channels = [item for item in existing if isinstance(item, dict) and str(item.get("channel_id")) != str(channel_id)]
    current_by_id = {str(item.get("id")): item for item in existing if isinstance(item, dict) and str(item.get("channel_id")) == str(channel_id)}
    merged: list[dict[str, Any]] = []
    for video in videos:
        item = dict(current_by_id.get(str(video.get("id")), {}))
        item.update(video)
        item["channel_id"] = str(channel_id)
        item.setdefault("status", "publicado")
        merged.append(item)
    write_json("channel_videos.json", other_channels + merged)
    return merged


def channel_videos_for(channel: dict, limit: int = 10) -> list[dict[str, Any]]:
    channel_id = str(channel.get("id") or "")
    stored = read_json("channel_videos.json", [])
    videos = [item for item in stored if isinstance(item, dict) and str(item.get("channel_id")) == channel_id]
    videos.sort(key=lambda item: str(item.get("published_at") or item.get("created_at") or ""), reverse=True)
    return videos[:limit]


def render_channel_video_editor(video: dict, channel_id: str) -> None:
    video_id = str(video.get("id") or "")
    edit_key = f"channel_video_edit_{video_id}"
    if st.button("Editar vídeo", key=f"edit_channel_video_{video_id}", width="stretch"):
        st.session_state[edit_key] = True
        st.rerun()
    if st.session_state.get(edit_key):
        with st.form(f"channel_video_form_{video_id}"):
            edited_title = st.text_input("Título", value=str(video.get("title") or ""))
            edited_status = st.selectbox("Estado", ["planejamento", "produção", "finalizado", "agendado", "publicado"], index=["planejamento", "produção", "finalizado", "agendado", "publicado"].index(str(video.get("status") or "publicado")) if str(video.get("status") or "publicado") in {"planejamento", "produção", "finalizado", "agendado", "publicado"} else 4)
            edited_date = st.text_input("Data de publicação", value=str(video.get("published_at") or ""))
            edited_url = st.text_input("URL", value=str(video.get("url") or ""))
            edited_notes = st.text_area("Notas", value=str(video.get("notes") or ""), height=80)
            save_video = st.form_submit_button("Guardar alteração", type="primary")
        if save_video:
            update_channel_video(video_id, {"title": edited_title.strip(), "status": edited_status, "published_at": edited_date.strip(), "url": edited_url.strip(), "notes": edited_notes.strip()})
            st.session_state.pop(edit_key, None)
            st.success("Vídeo actualizado.")
            st.rerun()


def render_channel_videos(channel: dict) -> None:
    channel_id = str(channel.get("id") or "")
    with st.expander("Últimos 10 vídeos publicados", expanded=False):
        st.caption("A lista usa o feed público do YouTube, sem Data API Key. Pode actualizar manualmente e editar os metadados locais apresentados.")
        refresh_col = st.columns(1)[0]
        with refresh_col:
            if st.button("Actualizar últimos 10 vídeos", key=f"refresh_channel_videos_{channel_id}", width="stretch"):
                result = fetch_channel_videos_public(channel, limit=10)
                if result.ok:
                    videos = _merge_channel_videos(channel_id, result.data.get("videos", []))
                    st.session_state[f"channel_videos_{channel_id}"] = videos
                    st.success(result.message)
                    st.rerun()
                else:
                    st.warning(result.message)
        videos = st.session_state.get(f"channel_videos_{channel_id}") or channel_videos_for(channel, limit=10)
        if not videos:
            st.info("Ainda não existem vídeos sincronizados. Clique em **Actualizar últimos 10 vídeos**.")
            return
        for video in videos[:10]:
            with st.container(border=True):
                cols = st.columns([0.7, 3.4, 1.4, 1.1])
                with cols[0]:
                    if video.get("thumbnail_url"):
                        st.image(video["thumbnail_url"], width=64)
                    else:
                        st.markdown("### YT")
                with cols[1]:
                    st.write(f"**{video.get('title', 'Vídeo sem título')}**")
                    st.caption(f"{video.get('published_at') or 'Sem data'} · {video.get('url') or 'Sem URL'}")
                with cols[2]:
                    st.caption(str(video.get("status") or "publicado").title())
                with cols[3]:
                    render_channel_video_editor(video, channel_id)


def render_channel_audio_subtitle_defaults(channel: dict) -> None:
    """Render and persist the audio/subtitle defaults used by channel automations."""
    channel_id = str(channel.get("id") or "")
    subtitle_font = str(channel.get("default_subtitle_font") or SUBTITLE_FONT_OPTIONS[0])
    subtitle_position = str(channel.get("default_subtitle_position") or SUBTITLE_POSITION_OPTIONS[0])
    music_source = str(channel.get("default_background_music_source") or "Sem música")
    music_volume = str(channel.get("default_background_music_volume") or "20%")
    with st.expander("Configurações de legendas", expanded=False):
        subtitle_cols = st.columns(2)
        with subtitle_cols[0]:
            enable_subtitles = st.checkbox("Enable Subtitles", value=bool(channel.get("default_enable_subtitles", True)), key=f"channel_default_subtitles_{channel_id}")
            selected_font = st.selectbox("Font", SUBTITLE_FONT_OPTIONS, index=SUBTITLE_FONT_OPTIONS.index(subtitle_font) if subtitle_font in SUBTITLE_FONT_OPTIONS else 0, key=f"channel_default_subtitle_font_{channel_id}")
            selected_position = st.selectbox("Position", SUBTITLE_POSITION_OPTIONS, index=SUBTITLE_POSITION_OPTIONS.index(subtitle_position) if subtitle_position in SUBTITLE_POSITION_OPTIONS else 0, key=f"channel_default_subtitle_position_{channel_id}")
            subtitle_color = st.color_picker("Color", str(channel.get("default_subtitle_color") or "#FFFFFF"), key=f"channel_default_subtitle_color_{channel_id}")
            subtitle_background = st.checkbox("Background", value=bool(channel.get("default_subtitle_background", True)), key=f"channel_default_subtitle_background_{channel_id}")
            subtitle_background_color = st.color_picker("Background Color", str(channel.get("default_subtitle_background_color") or "#000000"), key=f"channel_default_subtitle_background_color_{channel_id}")
            subtitle_rounded_background = st.checkbox("Rounded Background", value=bool(channel.get("default_subtitle_rounded_background", False)), key=f"channel_default_subtitle_rounded_background_{channel_id}")
        with subtitle_cols[1]:
            subtitle_font_size = st.slider("Font Size", min_value=12, max_value=96, value=int(channel.get("default_subtitle_font_size") or 60), key=f"channel_default_subtitle_font_size_{channel_id}")
            subtitle_outline = st.color_picker("Outline", str(channel.get("default_subtitle_outline") or "#000000"), key=f"channel_default_subtitle_outline_{channel_id}")
            subtitle_outline_width = st.slider("Outline Width", min_value=0.0, max_value=5.0, value=float(channel.get("default_subtitle_outline_width") or 1.5), step=0.25, key=f"channel_default_subtitle_outline_width_{channel_id}")
        if st.button("Guardar configurações de legendas", type="primary", key=f"save_channel_subtitle_defaults_{channel_id}", width="stretch"):
            update_channel(channel_id, {
                "default_enable_subtitles": bool(enable_subtitles), "default_subtitle_font": selected_font, "default_subtitle_position": selected_position,
                "default_subtitle_color": subtitle_color, "default_subtitle_background": bool(subtitle_background), "default_subtitle_background_color": subtitle_background_color,
                "default_subtitle_rounded_background": bool(subtitle_rounded_background), "default_subtitle_font_size": int(subtitle_font_size),
                "default_subtitle_outline": subtitle_outline, "default_subtitle_outline_width": float(subtitle_outline_width),
            })
            st.success("Default de legendas guardado para este canal.")
            st.rerun()
    with st.expander("Configurações de Audio", expanded=False):
        selected_music_source = st.selectbox("Fonte da música de fundo", BACKGROUND_MUSIC_SOURCE_OPTIONS, index=BACKGROUND_MUSIC_SOURCE_OPTIONS.index(music_source) if music_source in BACKGROUND_MUSIC_SOURCE_OPTIONS else BACKGROUND_MUSIC_SOURCE_OPTIONS.index("Sem música"), key=f"channel_default_music_source_{channel_id}")
        selected_music_volume = st.selectbox("Volume da música de fundo", BACKGROUND_MUSIC_VOLUME_OPTIONS, index=BACKGROUND_MUSIC_VOLUME_OPTIONS.index(music_volume) if music_volume in BACKGROUND_MUSIC_VOLUME_OPTIONS else 2, key=f"channel_default_music_volume_{channel_id}")
        if st.button("Guardar configurações de Audio", type="primary", key=f"save_channel_audio_defaults_{channel_id}", width="stretch"):
            update_channel(channel_id, {"default_background_music_source": selected_music_source, "default_background_music_volume": selected_music_volume})
            st.success("Default de Audio guardado para este canal.")
            st.rerun()


def render_channel_video_defaults(channel: dict) -> None:
    """Render and persist the video defaults used by this channel."""
    channel_id = str(channel.get("id") or "")
    source = channel_video_source_value(channel.get("default_video_source") or channel.get("style_wide"))
    aspect_ratio = str(channel.get("default_video_aspect_ratio") or channel.get("video_aspect_ratio") or "Landscape 16:9")
    encoder = str(channel.get("default_video_encoder") or VIDEO_ENCODER_OPTIONS[0])
    maximum_clip_duration = int(channel.get("default_maximum_clip_duration") or 5)
    videos_per_run = int(channel.get("default_videos_per_run") or 1)
    concatenation_mode = str(channel.get("default_video_concatenation_mode") or VIDEO_CONCATENATION_OPTIONS[0])
    transition_mode = str(channel.get("default_video_transition_mode") or VIDEO_TRANSITION_OPTIONS[0])
    with st.expander("Configurações de vídeo", expanded=False):
        video_cols = st.columns(2)
        with video_cols[0]:
            selected_source = st.selectbox(
                "Fonte do vídeo",
                WIDE_STYLE_OPTIONS,
                index=WIDE_STYLE_OPTIONS.index(source) if source in WIDE_STYLE_OPTIONS else 0,
                key=f"channel_default_video_source_{channel_id}",
            )
            selected_aspect_ratio = st.selectbox(
                "Proporção do vídeo",
                CHANNEL_ASPECT_RATIO_OPTIONS,
                index=CHANNEL_ASPECT_RATIO_OPTIONS.index(aspect_ratio) if aspect_ratio in CHANNEL_ASPECT_RATIO_OPTIONS else 0,
                key=f"channel_default_video_aspect_ratio_{channel_id}",
            )
            selected_concatenation = st.selectbox(
                "Video Concatenation Mode",
                VIDEO_CONCATENATION_OPTIONS,
                index=VIDEO_CONCATENATION_OPTIONS.index(concatenation_mode) if concatenation_mode in VIDEO_CONCATENATION_OPTIONS else 0,
                key=f"channel_default_video_concatenation_{channel_id}",
            )
            selected_transition = st.selectbox(
                "Video Transition Mode",
                VIDEO_TRANSITION_OPTIONS,
                index=VIDEO_TRANSITION_OPTIONS.index(transition_mode) if transition_mode in VIDEO_TRANSITION_OPTIONS else 0,
                key=f"channel_default_video_transition_{channel_id}",
            )
        with video_cols[1]:
            selected_maximum_clip_duration = st.selectbox(
                "Maximum Clip Duration (seconds)",
                [3, 5, 8, 10, 15],
                index=[3, 5, 8, 10, 15].index(maximum_clip_duration) if maximum_clip_duration in [3, 5, 8, 10, 15] else 3,
                key=f"channel_default_maximum_clip_duration_{channel_id}",
            )
            selected_videos_per_run = st.selectbox(
                "Videos per Run",
                list(range(1, 11)),
                index=videos_per_run - 1 if 1 <= videos_per_run <= 10 else 0,
                key=f"channel_default_videos_per_run_{channel_id}",
            )
            selected_encoder = st.selectbox(
                "Video Encoder",
                VIDEO_ENCODER_OPTIONS,
                index=VIDEO_ENCODER_OPTIONS.index(encoder) if encoder in VIDEO_ENCODER_OPTIONS else 0,
                key=f"channel_default_video_encoder_{channel_id}",
            )
            match_visuals = st.checkbox(
                "Match Visuals to Script Order",
                value=bool(channel.get("default_match_visuals_to_script_order", False)),
                key=f"channel_default_match_visuals_{channel_id}",
            )
        if st.button("Guardar configurações de vídeo", type="primary", key=f"save_channel_video_defaults_{channel_id}", width="stretch"):
            update_channel(channel_id, {
                "default_video_source": channel_video_source_storage(selected_source),
                "default_video_aspect_ratio": selected_aspect_ratio,
                "default_video_concatenation_mode": selected_concatenation,
                "default_video_transition_mode": selected_transition,
                "default_maximum_clip_duration": int(selected_maximum_clip_duration),
                "default_videos_per_run": int(selected_videos_per_run),
                "default_video_encoder": selected_encoder,
                "default_match_visuals_to_script_order": bool(match_visuals),
                "style_wide": channel_video_source_storage(selected_source),
                "video_aspect_ratio": selected_aspect_ratio,
            })
            st.success("Default de vídeo guardado para este canal.")
            st.rerun()


def render_channel_edit_form(channel: dict, youtube_account_ids: list[str], youtube_account_labels: dict[str, str], youtube_accounts_by_id: dict[str, dict[str, Any]]) -> None:
    channel_id = str(channel["id"])
    blueprint_ids, blueprint_labels, current_blueprint, voice_options, current_voice = channel_default_options(channel)
    account_ids = list(youtube_account_ids)
    current_account = str(channel.get("google_account_id") or "")
    if current_account and current_account not in account_ids:
        account_ids.append(current_account)
        youtube_account_labels[current_account] = "Conta Google não configurada"
    with st.form(f"channel_edit_form_{channel_id}"):
        st.subheader("Editar canal")
        edit_cols = st.columns(2)
        with edit_cols[0]:
            edited_name = st.text_input("Nome do canal", value=str(channel.get("name") or ""))
            edited_url = st.text_input("URL", value=str(channel.get("url") or ""))
            edited_handle = st.text_input("Handle", value=str(channel.get("handle") or ""))
            country_options = [""] + list(COUNTRY_OPTIONS)
            current_country = str(channel.get("country") or "")
            edited_country = st.selectbox("País", country_options, index=country_options.index(current_country) if current_country in country_options else 0)
            language_options = VIDEO_LANGUAGE_SELECTION_OPTIONS
            edited_language = st.selectbox("Idioma do roteiro", language_options, index=language_options.index(normalize_video_language(channel.get("language") or "pt")) if normalize_video_language(channel.get("language") or "pt") in language_options else 0, format_func=video_language_label)
            edited_style = st.selectbox("Fonte do vídeo", WIDE_STYLE_OPTIONS, index=WIDE_STYLE_OPTIONS.index(channel_video_source_value(channel.get("style_wide"))) if channel_video_source_value(channel.get("style_wide")) in WIDE_STYLE_OPTIONS else 0)
            edited_aspect = st.selectbox("Proporção do vídeo", CHANNEL_ASPECT_RATIO_OPTIONS, index=CHANNEL_ASPECT_RATIO_OPTIONS.index(str(channel.get("video_aspect_ratio") or "Landscape 16:9")) if str(channel.get("video_aspect_ratio") or "Landscape 16:9") in CHANNEL_ASPECT_RATIO_OPTIONS else 0)
            edited_niche = st.text_input("Nicho", value=str(channel.get("niche") or channel_niche_label(channel) if channel_niche_label(channel) != "SEM NICHO CONFIGURADO" else "") )
            edited_subscribers = st.text_input("Inscritos", value=_channel_count_text(channel.get("subscriber_count")))
            edited_videos = st.text_input("Vídeos", value=_channel_count_text(channel.get("video_count")))
            edited_views = st.text_input("Visualizações", value=_channel_count_text(channel.get("view_count")))
        with edit_cols[1]:
            edited_blueprint = st.selectbox("Blueprint Padrão", blueprint_ids, index=blueprint_ids.index(current_blueprint) if current_blueprint in blueprint_ids else 0, format_func=lambda item: blueprint_labels.get(item, item or "Sem Blueprint padrão"))
            edited_voice = st.selectbox("Narrador/Voz Padrão", voice_options, index=voice_options.index(current_voice) if current_voice in voice_options else 0, format_func=lambda item: item or "Sem voz padrão")
            edited_account = st.selectbox("Conta Google para Upload directo", account_ids, index=account_ids.index(current_account) if current_account in account_ids else 0, format_func=lambda item: youtube_account_labels.get(item, item or "Sem conta Google associada"))
            composio_data = channel.get("composio") if isinstance(channel.get("composio"), dict) else {}
            edited_composio_account_id = st.text_input("Connected account ID do Composio", value=str(composio_data.get("connected_account_id") or channel.get("composio_connected_account_id") or ""), help="ID técnico ca_... devolvido pelo Composio; não use o nome do canal.")
            st.text_input("YouTube Channel ID", value=str(composio_data.get("channel_id_youtube") or channel.get("youtube_channel_id") or ""), disabled=True)
            edited_description = st.text_area("Descrição", value=str(channel.get("description") or ""), height=100)
            edited_automation = st.toggle("Automação ON", value=bool(channel.get("automation_on", False)), key=f"edit_automation_{channel_id}")
            edited_time = st.text_input("Horário diário (HH:MM)", value=str(channel.get("automation_time") or "00:00"))
        save_channel = st.form_submit_button("Guardar alterações", type="primary", width="stretch")
        cancel_edit = st.form_submit_button("Cancelar edição")
    if cancel_edit:
        st.session_state.pop(f"edit_channel_{channel_id}", None)
        st.rerun()
    if save_channel:
        if not edited_name.strip():
            st.error("Informe o nome do canal.")
        elif not valid_hhmm(edited_time):
            st.error("O horário diário deve estar no formato HH:MM.")
        else:
            update_channel(channel_id, {
                "name": edited_name.strip(), "url": edited_url.strip(), "handle": edited_handle.strip(), "language": edited_language,
                "style_wide": channel_video_source_storage(edited_style), "video_aspect_ratio": edited_aspect,
                "niche": edited_niche.strip(), "reference_channels": [item.strip() for item in re.split(r"[,|]", edited_niche) if item.strip()], "country": edited_country.strip(),
                "default_blueprint_id": edited_blueprint.strip(), "blueprint_id": edited_blueprint.strip(),
                "default_voice": edited_voice.strip(), "voice": edited_voice.strip(),
                "google_account_id": edited_account.strip(), "google_account_email": str(youtube_accounts_by_id.get(edited_account, {}).get("email", "")),
                "composio_connected_account_id": edited_composio_account_id.strip() if edited_composio_account_id.strip().startswith("ca_") else "",
                "composio": {**(channel.get("composio") if isinstance(channel.get("composio"), dict) else {}), "connected_account_id": edited_composio_account_id.strip()} if edited_composio_account_id.strip().startswith("ca_") else {},
                "description": edited_description.strip(), "automation_on": bool(edited_automation), "automation_time": edited_time.strip(),
                "subscriber_count": _channel_count_value(edited_subscribers) or None, "video_count": _channel_count_value(edited_videos) or None, "view_count": _channel_count_value(edited_views) or None,
            })
            st.session_state.pop(f"edit_channel_{channel_id}", None)
            st.success("Canal actualizado.")
            st.rerun()
    if st.button("Descobrir automaticamente", key=f"discover_composio_{channel_id}"):
        try:
            resolved = _resolve_channel_composio(read_json("settings.json", {}), channel)
            st.success(f"Connected Account ID resolvido: {resolved.get('connected_account_id')}")
            st.rerun()
        except ComposioUploadError as exc:
            st.error(str(exc))


def render_home_update_controls() -> None:
    """Render update controls and only show actionable or execution-related notices."""
    cache_key = "home_update_version_check"
    checked_at_key = "home_update_version_checked_at"
    if not st.session_state.get(cache_key) or time.monotonic() - float(st.session_state.get(checked_at_key, 0)) > 300:
        st.session_state[cache_key] = check_version(APP_VERSION)
        st.session_state[checked_at_key] = time.monotonic()
    version_status = st.session_state[cache_key]
    notice_signature = f"{version_status.latest_version}|{version_status.update_available}|{version_status.error}"
    if st.session_state.get("home_update_notice_signature") != notice_signature:
        st.session_state["home_update_notice_signature"] = notice_signature
        st.session_state["home_update_notice_dismissed"] = False

    update_result = st.session_state.get("home_update_result")
    notice_message = ""
    notice_kind = ""
    if update_result is not None and (not update_result.ok or update_result.restart_required):
        notice_message = str(update_result.message or "").strip()
        notice_kind = "success" if update_result.ok else "error"
    elif version_status.update_available:
        notice_message = f"Nova versão disponível: {display_version(version_status.latest_version)}. A versão actual é {APP_VERSION_LABEL or 'desconhecida'}."
        notice_kind = "info"
    notice_visible = bool(notice_message) and not st.session_state.get("home_update_notice_dismissed")

    update_area, notice_area, close_area = st.columns([1.45, 3.55, 0.42], gap="small")
    with update_area:
        st.markdown(
            """
            <style>
            div[data-testid="stButton"] button[kind="primary"] {
                background: linear-gradient(135deg, #2563eb 0%, #7c3aed 100%);
                color: #ffffff;
                border: 1px solid #8b5cf6;
                font-weight: 700;
                box-shadow: 0 8px 20px rgba(79, 70, 229, 0.28);
            }
            div[data-testid="stButton"] button[kind="primary"]:hover {
                border-color: #c4b5fd;
                filter: brightness(1.08);
            }
            div[data-testid="stAlert"] {
                width: fit-content;
                max-width: 100%;
                min-height: 0;
                padding: 0.45rem 0.75rem;
                margin: 0.2rem 0 0;
                display: inline-flex;
                align-items: center;
            }
            div[data-testid="stAlert"] p {
                margin: 0;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Atualizar Versão", key="home_update_version", type="primary", icon=":material/system_update:"):
            with st.spinner("A instalar a versão mais recente…"):
                update_result = update_to_latest(APP_VERSION)
                st.session_state["home_update_result"] = update_result
                st.session_state["home_update_notice_dismissed"] = False
                if update_result.ok and update_result.restart_required:
                    st.success("Actualização concluída. A reiniciar o Thunderbolt para aplicar a nova versão…")
                    time.sleep(0.8)
                    restart_current_process()
    if notice_visible:
        with notice_area:
            if notice_kind == "info":
                st.info(notice_message)
            elif notice_kind == "success":
                st.success(notice_message)
            else:
                st.error(notice_message)
        with close_area:
            if st.button("×", key="home_update_notice_close", help="Fechar este aviso"):
                st.session_state["home_update_notice_dismissed"] = True
                st.rerun()


def _growth_score_color(score: float) -> str:
    if score <= 30:
        return "#ef4444"
    if score < 70:
        return "#f59e0b"
    return "#22c55e"


def _growth_channel_metrics(channel: dict[str, Any]) -> tuple[list[dict[str, Any]], float]:
    """Calculate transparent local growth notes without fabricating Studio metrics."""
    channel_id = str(channel.get("id") or "")
    tasks = [item for item in read_json("tasks.json", []) if isinstance(item, dict) and str(item.get("channel_id") or "") == channel_id]
    completed = [item for item in tasks if str(item.get("state") or item.get("status") or "").lower() == "done"]
    with_thumbnail = [item for item in tasks if str(item.get("thumbnail_path") or (item.get("artifacts") or {}).get("thumbnail") or "").strip()]
    with_title = [item for item in tasks if str(item.get("title") or "").strip()]
    subscriber_count = channel.get("subscriber_count")
    view_count = channel.get("view_count")
    video_count = channel.get("video_count")

    def number(value: Any) -> float | None:
        try:
            return float(value) if value is not None and str(value).strip() else None
        except (TypeError, ValueError):
            return None

    subscribers, views, videos = number(subscriber_count), number(view_count), number(video_count)
    demand = 70 if views is not None and views >= 1_000_000 else 55 if views is not None and views >= 100_000 else 50
    thumbnail = round((len(with_thumbnail) / len(tasks)) * 100) if tasks else 50
    title = round((len(with_title) / len(tasks)) * 100) if tasks else 50
    conversion = round(min(100, (subscribers / views) * 10000)) if subscribers is not None and views and views > 0 else 50
    cadence = round(min(100, len(tasks) * 12.5)) if tasks else 50
    metrics = [
        {"label": "Demanda validada", "score": demand, "value": f"{views:,.0f} visualizações" if views is not None else "Sem dados de visualizações", "source": "Canal YouTube" if views is not None else "Requer dados do canal"},
        {"label": "Qualidade da thumbnail", "score": thumbnail, "value": f"{len(with_thumbnail)}/{len(tasks)} tarefas com thumbnail" if tasks else "Sem tarefas analisadas", "source": "Artefactos locais"},
        {"label": "Qualidade do título", "score": title, "value": f"{len(with_title)}/{len(tasks)} tarefas com título" if tasks else "Sem tarefas analisadas", "source": "Artefactos locais"},
        {"label": "Hook — retenção inicial", "score": 50, "value": "Sem dados de retenção", "source": "Requer YouTube Studio"},
        {"label": "Ritmo e edição", "score": 50, "value": "Sem gráfico de retenção", "source": "Requer YouTube Studio"},
        {"label": "Origem do tráfego", "score": 50, "value": "Sem distribuição de tráfego", "source": "Requer YouTube Studio"},
        {"label": "Conversão em inscritos", "score": conversion, "value": f"{subscribers:,.0f} inscritos / {views:,.0f} visualizações" if subscribers is not None and views is not None else "Sem dados de inscritos e visualizações", "source": "Canal YouTube" if subscribers is not None and views is not None else "Requer dados do canal"},
        {"label": "Cadência de publicação", "score": cadence, "value": f"{len(tasks)} tarefas locais" if tasks else "Sem tarefas locais", "source": "Pipeline local"},
    ]
    available = [metric["score"] for metric in metrics if metric["source"] not in {"Requer YouTube Studio", "Requer dados do canal"}]
    overall = round(sum(available) / len(available)) if available else 50
    return metrics, overall


def render_growth_youtube():
    st.title("Growth Youtube")
    st.caption("Auditoria pública baseada nos 3 pilares críticos e nas métricas secundárias do agente Growth.")
    growth_settings = read_json("settings.json", {})
    youtube_data_api_ready = bool(str(growth_settings.get("youtube_api_key") or os.getenv("YOUTUBE_API_KEY") or "").strip())
    channels = [item for item in read_json("channels.json", []) if isinstance(item, dict) and item.get("active", True) and is_youtube_channel_record(item)]
    if not channels:
        st.info("Cadastre pelo menos um canal YouTube em Canais YouTube para iniciar a análise.")
        return
    selector_col, action_col = st.columns([1.05, 1.15], gap="small")
    with selector_col:
        selected = st.selectbox("Canal a analisar", channels, format_func=lambda item: str(item.get("name") or "Canal sem nome"), key="growth_youtube_channel")
    with action_col:
        action_button_col, action_status_col = st.columns([1.15, 0.85], gap="small")
        with action_button_col:
            st.write("")
            analyse_clicked = st.button("ANALISAR CANAL", type="primary", width="stretch", key="growth_youtube_analyse")
        with action_status_col:
            if st.session_state.get("growth_analysis_status") == "complete":
                st.markdown('<div style="padding-top:9px;color:#22c55e;font-weight:700;white-space:nowrap;">✓ Análise concluída</div>', unsafe_allow_html=True)
    matched_growth_account = find_youtube_growth_account(selected, growth_settings)
    analytics_accounts_ready = bool(matched_growth_account and youtube_batch_account_status(matched_growth_account, STORAGE).ok)
    st.markdown("**Estado das APIs de Growth**")
    api_status_cols = st.columns(2, gap="small")
    with api_status_cols[0]:
        st.caption("YouTube Data API v3: Metadados públicos")
        _api_status_badge("Configured" if youtube_data_api_ready else "Missing configuration", "ready" if youtube_data_api_ready else "missing")
    with api_status_cols[1]:
        st.caption("YouTube Analytics API: Métricas internas")
        _api_status_badge("Configured" if analytics_accounts_ready else "Missing configuration", "ready" if analytics_accounts_ready else "missing")
    if analyse_clicked:
        settings = read_json("settings.json", {})
        llm_settings, _ = ensure_llm_provider_cards(settings)
        vision_card = next((card for card in llm_settings.get(LLM_CARDS_KEY, []) if isinstance(card, dict) and card.get("provider") == "nvidia_nim_paligemma" and card.get("enabled", True)), None)
        with st.status("A preparar a análise pública…", expanded=True) as status:
            try:
                record = run_audit(selected, settings, vision_card=vision_card, progress=st.write)
                st.session_state["growth_last_analysis_code"] = record["code"]
                st.session_state["growth_analysis_status"] = "complete"
                status.update(label="Análise concluída", state="complete")
            except Exception as exc:
                st.session_state["growth_analysis_status"] = "failed"
                status.update(label="Análise falhou", state="error")
                st.error(str(exc)[:500])
    records = list_analyses()
    selected_record = next((item for item in reversed(records) if str(item.get("channel_id")) == str(selected.get("id"))), None)
    metrics = selected_record.get("metrics", []) if selected_record else [
        {"label": label, "score": 0, "value": "Aguardando análise", "diagnosis": "Clique em ANALISAR CANAL para preencher esta métrica."}
        for label in ("Demanda validada", "Qualidade da thumbnail", "Qualidade do título", "Hook — retenção inicial", "Ritmo e edição", "Origem do tráfego", "Conversão em inscritos", "Cadência de publicação")
    ]
    overall = int(selected_record.get("overall_score", 0)) if selected_record else None
    if selected_record:
        analytics_state = (selected_record.get("analytics") or {}).get("status", "not_connected")
        if analytics_state == "ready":
            st.success("Dados internos activos: YouTube Analytics OAuth aplicado à análise.")
        elif analytics_state in {"requires_authorization", "not_connected"}:
            st.info("Dados públicos activos. Para CTR, retenção, tráfego, RPM e demografia, autorize a conta Google proprietária do canal; os valores privados não são estimados como reais.")
        else:
            st.warning("A consulta YouTube Analytics não ficou disponível; os cartões afectados estão marcados como estimados ou indisponíveis.")
    color = _growth_score_color(overall) if overall is not None else "#64748b"
    score_text = str(overall) if overall is not None else "—"
    score_suffix = "/100" if overall is not None else ""
    summary_col, download_col = st.columns([3.25, 1], gap="large")
    with summary_col:
        st.markdown(
            f'<div style="border:1px solid #263447;border-radius:12px;padding:18px;margin:12px 0 20px;background:#101722;display:flex;align-items:center;justify-content:space-between;min-height:76px;">'
            f'<div><div style="font-size:13px;color:#94a3b8;text-transform:uppercase;letter-spacing:.08em;">Nota geral do canal</div><div style="font-size:18px;font-weight:700;margin-top:5px;">{str(selected.get("name") or "Canal")}</div></div>'
            f'<div style="font-size:42px;font-weight:800;color:{color};line-height:1;">{score_text}<span style="font-size:16px;color:#94a3b8;">{score_suffix}</span></div></div>',
            unsafe_allow_html=True,
        )
    with download_col:
        st.write("")
        if selected_record and selected_record.get("report_path"):
            report_path = Path(str(selected_record["report_path"]))
            if report_path.is_file():
                st.download_button("BAIXAR ANALISE COMPLETA", report_path.read_bytes(), file_name=report_path.name, mime="text/markdown", width="stretch", key=f"growth_download_{selected_record['code']}")
        else:
            st.button("BAIXAR ANALISE COMPLETA", disabled=True, width="stretch", key="growth_download_disabled")
    st.subheader("Dashboard de Growth")
    st.caption("Visão híbrida: os 3 pilares críticos em destaque e os 5 pilares operacionais abaixo. Vermelho: 0–30 · Amarelo: 31–69 · Verde: 70–100.")
    source_names = {"public": "PÚBLICO", "paligemma": "PALIGEMMA", "estimated": "DADO ESTIMADO", "unavailable": "INDISPONÍVEL", "youtube_analytics_oauth": "ANALYTICS OAUTH"}
    metric_by_label = {str(item.get("label")): item for item in metrics}
    videos = selected_record.get("videos", []) if selected_record else []
    analytics_values = (selected_record.get("analytics") or {}).get("values", {}) if selected_record else {}

    def display_value(value: Any, suffix: str = "") -> str:
        if value is None or value == "" or value == "—":
            return "—"
        return f"{value}{suffix}"

    def number_value(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def status_for(value: Any, target: Any = None, *, direction: str = "above", available: bool = True) -> tuple[str, str]:
        if not available or value is None or target is None:
            return "A verificar", "#94a3b8"
        current, goal = number_value(value), number_value(target)
        if current is None or goal is None:
            return "A verificar", "#94a3b8"
        passed = current >= goal if direction == "above" else current <= goal
        return ("Meta atingida", "#22c55e") if passed else ("Atenção", "#facc15")

    def text_status(value: Any, expected: set[str], *, available: bool = True) -> tuple[str, str]:
        if not available or value is None or value == "—":
            return "A verificar", "#94a3b8"
        return ("Meta atingida", "#22c55e") if str(value).casefold() in {item.casefold() for item in expected} else ("Atenção", "#facc15")

    def avg_video_field(field: str) -> float | None:
        values = [number_value(video.get(field)) for video in videos]
        values = [value for value in values if value is not None and value > 0]
        return sum(values) / len(values) if values else None

    avg_views = avg_video_field("view_count")
    avg_thumb_score = number_value(metric_by_label.get("Qualidade da thumbnail", {}).get("score"))
    title_score = number_value(metric_by_label.get("Qualidade do título", {}).get("score"))
    hook_score = number_value(metric_by_label.get("Hook — retenção inicial", {}).get("score"))
    average_percentage = number_value(analytics_values.get("averageViewPercentage"))
    average_duration = number_value(analytics_values.get("averageViewDuration"))
    gained = number_value(analytics_values.get("subscribersGained"))
    views_total = number_value(analytics_values.get("views")) or sum(number_value(video.get("view_count")) or 0 for video in videos)
    conversion = (gained / views_total * 100) if gained is not None and views_total else None
    niche = str(selected.get("niche") or selected.get("description") or "—")
    vision_values = [video.get("vision") or {} for video in videos if (video.get("vision") or {}).get("status") == "analisado"]
    contrast = next((str(item.get("contrast")).strip() for item in vision_values if item.get("contrast")), None)
    emotion = next((str(item.get("emotion")).strip() for item in vision_values if item.get("emotion")), None)
    cards = [
        ("Validação de Nicho", metric_by_label.get("Demanda validada", {}).get("score", 0), True, [("Nicho Detectado", niche, "RPM > $7", text_status(niche, {niche}, available=niche != "—")), ("Teto da Concorrência", "—", "> 500k", status_for(None)), ("Média de Views (5 vídeos)", f"{avg_views:,.0f}" if avg_views is not None else "—", "> 50k", status_for(avg_views, 50000)), ("Impressões (48h iniciais)", display_value(analytics_values.get("impressions")), "> 10k", status_for(analytics_values.get("impressions"), 10000)), ("Tráfego de Pesquisa (%)", "—", "15–40%", status_for(None))]),
        ("Thumbnail", metric_by_label.get("Qualidade da thumbnail", {}).get("score", 0), True, [("CTR (Click-Through Rate)", "—", "> 6%", status_for(None)), ("Qualidade Visual (Thumb)", f"{avg_thumb_score / 10:.1f}/10" if avg_thumb_score is not None else "—", "> 7/10", status_for(avg_thumb_score, 70)), ("Contraste da Thumbnail", contrast or "—", "Alto", text_status(contrast, {"alto", "high"}, available=bool(contrast))), ("Emoção Predominante", emotion or "—", "Medo/Surpresa", text_status(emotion, {"medo", "surpresa", "fear", "surprise"}, available=bool(emotion)))]),
        ("Título dos Vídeos", metric_by_label.get("Qualidade do título", {}).get("score", 0), True, [("Score do Título (SEO)", f"{title_score / 10:.1f}/10" if title_score is not None else "—", "> 8/10", status_for(title_score, 80)), ("Gatilho Mental no Título", "—", "> 70%", status_for(None)), ("Palavra-chave no Título", "—", "Sim", text_status(None, {"sim"}, available=False))]),
        ("Hook e Retenção", metric_by_label.get("Hook — retenção inicial", {}).get("score", 0), False, [("Queda nos Primeiros 30s", "—", "< 20%", status_for(None)), ("Retenção Média (%)", display_value(average_percentage, "%"), "> 50%", status_for(average_percentage, 50)), ("Hook (Primeiros 15s)", "Forte" if hook_score is not None and hook_score >= 70 else "—", "Promessa clara", text_status("forte" if hook_score is not None and hook_score >= 70 else None, {"forte"}, available=hook_score is not None))]),
        ("Ritmo e Edição", metric_by_label.get("Ritmo e edição", {}).get("score", 0), False, [("Pico de Abandono", "—", "Queda suave", status_for(None)), ("Tempo Médio (AVD)", f"{average_duration / 60:.1f} min" if average_duration is not None else "—", "> 4 min", status_for(average_duration, 240)), ("Estrutura do Roteiro", "Clara" if hook_score is not None and hook_score >= 60 else "—", "Clara", text_status("clara" if hook_score is not None and hook_score >= 60 else None, {"clara"}, available=hook_score is not None)), ("Densidade de Palavras-chave", "—", "> 3", status_for(None))]),
        ("Tráfego e Algoritmo", metric_by_label.get("Origem do tráfego", {}).get("score", 0), False, [("Origem: Browse (%)", "—", "> 50%", status_for(None)), ("Origem: Inscritos (%)", "—", "< 30%", status_for(None))]),
        ("Conversão e Engajamento", metric_by_label.get("Conversão em inscritos", {}).get("score", 0), False, [("Taxa Conversão (Subs/Views)", display_value(conversion, "%") if conversion is not None else "—", "> 1.5%", status_for(conversion, 1.5)), ("Taxa de Likes (Likes/Views)", "—", "> 4%", status_for(None))]),
        ("Consistência e Saúde", metric_by_label.get("Cadência de publicação", {}).get("score", 0), False, [("Cadência de Postagem", "—", "≤ 7 dias", status_for(None)), ("Biblioteca Perene (%)", "—", "> 40%", status_for(None)), ("Crescimento Líquido de Subs", display_value((gained or 0) - (number_value(analytics_values.get("subscribersLost")) or 0)) if gained is not None else "—", "Positivo", ("Meta atingida", "#22c55e") if gained is not None and (gained - (number_value(analytics_values.get("subscribersLost")) or 0)) > 0 else status_for(None))]),
    ]

    def growth_card(card_data: tuple[str, Any, bool, list[tuple[str, str, str, tuple[str, str]]]]) -> str:
        title, raw_score, featured_card, rows = card_data
        score = int(number_value(raw_score) or 0)
        source = source_names.get(str(metric_by_label.get(title, {}).get("source", "unknown")), "A VERIFICAR")
        row_html = "".join(f'<tr><td>{escape(label)}</td><td><b>{escape(str(value))}</b></td><td>{escape(target)}</td><td><span style="color:{colour};font-weight:700;">● {escape(status)}</span></td></tr>' for label, value, target, (status, colour) in rows)
        return f'<div style="min-height:{"350px" if featured_card else "280px"};border:1px solid #2b3b52;border-radius:14px;padding:16px;background:linear-gradient(145deg,#111c2b,#0b121c);box-shadow:0 8px 22px rgba(0,0,0,.16);"><div style="font-size:11px;font-weight:800;letter-spacing:.08em;color:#7dd3fc;text-transform:uppercase;">{escape(source)}</div><div style="font-size:{"19px" if featured_card else "16px"};font-weight:750;color:#f8fafc;margin-top:8px;">{escape(title)}</div><div style="display:flex;align-items:baseline;gap:5px;margin:8px 0 10px;"><span style="font-size:{"38px" if featured_card else "30px"};font-weight:850;color:{_growth_score_color(score)};">{score}</span><span style="font-size:13px;color:#94a3b8;">/100</span></div><div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:11px;color:#cbd5e1;"><thead><tr><th style="text-align:left;padding:5px 3px;border-bottom:1px solid #334155;">KPI</th><th style="text-align:left;padding:5px 3px;border-bottom:1px solid #334155;">Valor</th><th style="text-align:left;padding:5px 3px;border-bottom:1px solid #334155;">Meta</th><th style="text-align:left;padding:5px 3px;border-bottom:1px solid #334155;">Status</th></tr></thead><tbody>{row_html}</tbody></table></div></div>'

    st.markdown('<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:14px 0 18px;">' + "".join(growth_card(item) for item in cards[:3]) + '</div>', unsafe_allow_html=True)
    st.markdown('<div style="display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin:0 0 18px;">' + "".join(growth_card(item) for item in cards[3:]) + '</div>', unsafe_allow_html=True)
    st.caption("Legenda: ● Verde = meta atingida · ● Amarelo = atenção · ● Vermelho = crítico · Cinzento = dado não disponível na fonte autorizada.")
    st.divider()
    history_tab, dashboard_tab = st.tabs(["Últimas análises", "Leitura estratégica"])
    with dashboard_tab:
        st.write("Priorize primeiro as métricas abaixo de 70. Thumbnail + Título devem ser optimizados antes de alterações de conteúdo; Hook, Ritmo e Tráfego ficam pendentes de dados do YouTube Studio quando não houver dados públicos.")
    with history_tab:
        if not records:
            st.info("Ainda não existem análises guardadas.")
        for record in reversed(records[-20:]):
            row = st.columns([2, 1, 2.2, 1.2, 1, 1.4])
            row[0].write(f"**{record.get('channel_name', 'Canal')}**")
            row[1].write(str(record.get("platform", "YouTube")))
            row[2].caption(str(record.get("code", "")))
            row[3].caption(str(record.get("created_at", "")).replace("T", " ")[:19])
            row[4].write(f"{record.get('overall_score', '—')}/100" if record.get("overall_score") is not None else "—")
            report_path = Path(str(record.get("report_path") or ""))
            if report_path.is_file():
                row[5].download_button("Análise", report_path.read_bytes(), file_name=report_path.name, mime="text/markdown", key=f"growth_history_{record.get('code')}")
            elif record.get("status") == "failed":
                row[5].caption("Falhou")


def render_dashboard():
    ui_language = current_ui_language()
    st.title("Thunderbolt Dashboard")
    st.caption(ui_text("Interface local para operação e automação de conteúdo faceless", ui_language))
    summary = pipeline_summary()
    active_note = f'{summary["active_channels"]} {ui_text("activos", ui_language)}'
    cards = [
        ("Canais", summary["channels"], active_note),
        ("Tarefas", summary["total_tasks"], ui_text("total registado", ui_language)),
        ("A fazer", summary["pending"], ui_text("na pipeline", ui_language)),
        ("Em execução", summary["doing"], ui_text("a decorrer", ui_language)),
        ("Concluídos", summary["done"], ui_text("artefactos prontos", ui_language)),
        ("Falhas", summary["failed"], ui_text("requerem atenção", ui_language)),
    ]
    cols = st.columns(6)
    for col, (label, value, note) in zip(cols, cards):
        with col:
            card(ui_text(label, ui_language), value, note)
    st.divider()
    st.subheader(ui_text("Pipeline Vídeos", ui_language))
    st.caption(ui_text("Filas locais e dependências da cascata", ui_language))
    queues = read_json("queues.json", {})
    area_cards = [
        ("Pipeline Vídeos", summary["total_tasks"], ui_text("total registado", ui_language)),
        ("Pipeline Músicas", len(list_music_files()), ui_text("na biblioteca", ui_language)),
        ("AI Influencers", "—", ui_text("módulos disponíveis", ui_language)),
    ]
    area_cols = st.columns(3)
    for col, (label, value, note) in zip(area_cols, area_cards):
        with col:
            card(ui_text(label, ui_language), value, note)
    st.divider()
    blueprint_count = len(list_blueprint_files())
    for row_start in range(0, len(STAGES), 3):
        queue_cols = st.columns(3)
        for col, stage in zip(queue_cols, STAGES[row_start:row_start + 3]):
            with col:
                if stage == "blueprint":
                    queue_note = f'{ui_text("na biblioteca", ui_language)} · {len(queues.get(stage, []))} {ui_text("tarefa(s) na fila", ui_language)}'
                    card(ui_text("Blueprints", ui_language), blueprint_count, queue_note)
                else:
                    card(ui_text(stage.title(), ui_language), len(queues.get(stage, [])), ui_text("fila", ui_language))


def render_blueprints():
    st.title("Blueprints Youtube")
    st.caption(f"Biblioteca local lida directamente de `{BLUEPRINTS}`")
    blueprint_tab = st.container()
    with blueprint_tab:
        st.subheader("Criar blueprint a partir de link")
        with st.form("create_blueprint_from_link"):
            source_url = st.text_input("Link do canal ou vídeo YouTube", placeholder="https://www.youtube.com/@canal ou https://youtu.be/video")
            blueprint_name = st.text_input("Nome do Blueprint", placeholder="Ex.: Filosofia sombria — Canal X")
            channel_name = st.text_input("Nome do canal, se conhecido")
            niche = st.text_input("Nicho alvo", placeholder="Ex.: filosofia, história, finanças pessoais")
            language = st.selectbox("Idioma do blueprint", ["Português (pt-BR)", "English", "Español"])
            creation_type = st.radio("O que deseja criar?", ["Apenas Blueprint", "Blueprint + Branding completo"], horizontal=True)
            create_submitted = st.form_submit_button("Criar a partir do link", type="primary")
        if create_submitted:
            if not blueprint_name.strip():
                st.error("Informe o nome do Blueprint antes de criar.")
            else:
                try:
                    blueprint, branding = create_blueprint_from_link(source_url, niche, language, creation_type == "Blueprint + Branding completo", channel_name, blueprint_name)
                    blueprint_path, branding_path = save_generated_blueprint(blueprint, branding)
                    record_notification("blueprint_completed", f"Blueprint criado: {blueprint_path.stem}", "O Blueprint foi criado e guardado no storage local.", metadata={"name": blueprint_path.stem}, dedupe_key=f"blueprint:{blueprint_path}:{blueprint_path.stat().st_mtime_ns}")
                    st.success(f"Blueprint criado: {blueprint_path.name}")
                    if branding_path:
                        record_notification("branding_completed", f"Branding criado: {branding_path.stem}", "O Branding foi criado e guardado no storage local.", metadata={"name": branding_path.stem}, dedupe_key=f"branding:{branding_path}:{branding_path.stat().st_mtime_ns}")
                        st.success(f"Branding completo criado: {branding_path.name}")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        st.divider()
        st.subheader("Importar blueprint JSON")
        uploaded = st.file_uploader("Subir novo blueprint JSON", type=["json"], key="blueprint_upload")
        target_folder = st.selectbox("Pasta", ["importados", "canais", "nichos"], key="blueprint_target_folder")
        if uploaded and st.button("Guardar blueprint JSON", type="secondary"):
            try:
                data = json.loads(uploaded.getvalue().decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("O JSON raiz deve ser um objecto.")
                safe_name = Path(uploaded.name).stem.replace(" ", "-") + ".json"
                destination = BLUEPRINTS / target_folder / safe_name
                if destination.exists() and not st.checkbox("Confirmar substituição", key="confirm_blueprint_replace"):
                    st.warning("O ficheiro já existe. Confirme a substituição.")
                else:
                    atomic_write(destination, data)
                    record_notification("blueprint_completed", f"Blueprint guardado: {destination.stem}", "O Blueprint importado foi guardado no storage local.", metadata={"name": destination.stem}, dedupe_key=f"blueprint:{destination}:{destination.stat().st_mtime_ns}")
                    st.success(f"Blueprint guardado em {destination}")
                    st.rerun()
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                st.error(f"JSON inválido: {exc}")
        files = list_blueprint_files()
        st.subheader(f"Blueprints existentes ({len(files)})")
        search = st.text_input("Pesquisar blueprints", key="blueprint_search")
        if not files:
            st.info("Ainda não existem blueprints na pasta local.")
        for path in files:
            try:
                data = load_blueprint_file(path)
                fallback_title = str(data.get("channel_name") or data.get("name") or data.get("title") or path.stem)
                title = get_display_name("blueprints", path, fallback_title)
                if search and search.lower() not in f"{title}\n{path.name}".lower():
                    continue
                card_key = _library_card_key("blueprints", path)
                header_cols = st.columns([0.93, 0.07], vertical_alignment="center")
                with header_cols[0]:
                    with st.expander(title):
                        st.json(data)
                with header_cols[1]:
                    _render_card_pencil(f"rename_blueprints_{card_key}")
                _render_library_name_editor("blueprints", path, title)
            except Exception as exc:
                with st.expander(f"Inválido — {path.stem}"):
                    st.error(str(exc))


def render_youtube_brandings():
    st.title("Brandings Youtube")
    st.caption(f"Brandings gerados ou importados da pasta `{BLUEPRINTS / 'brandings'}`")
    branding_upload = st.file_uploader("Subir Branding JSON", type=["json"], key="branding_upload")
    if branding_upload and st.button("Guardar Branding", type="secondary"):
        try:
            data = json.loads(branding_upload.getvalue().decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("O JSON raiz deve ser um objecto.")
            target = BLUEPRINTS / "brandings" / (Path(branding_upload.name).stem.replace(" ", "-") + ".json")
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(target, data)
            record_notification("branding_completed", f"Branding guardado: {target.stem}", "O Branding importado foi guardado no storage local.", metadata={"name": target.stem}, dedupe_key=f"branding:{target}:{target.stat().st_mtime_ns}")
            st.success(f"Branding guardado em {target}")
            st.rerun()
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            st.error(f"Branding JSON inválido: {exc}")
    branding_files = list_branding_files()
    st.write(f"{len(branding_files)} branding(s) encontrado(s)")
    branding_search = st.text_input("Pesquisar brandings", key="branding_search")
    if not branding_files:
        st.info("Ainda não existem brandings na pasta local.")
    for path in branding_files:
        if branding_search and branding_search.lower() not in path.name.lower():
            continue
        try:
            data = load_blueprint_file(path)
            title = data.get("name") or data.get("identity", {}).get("channel_name") or path.stem
            with st.expander(f"{title} — {path.name}"):
                st.caption(f"Blueprint associado: {data.get('blueprint_id') or 'não associado'}")
                st.json(data)
        except Exception as exc:
            with st.expander(f"Inválido — {path.stem}"):
                st.error(str(exc))


def render_facebook_blueprints():
    root = STORAGE / "facebook" / "blueprints"
    root.mkdir(parents=True, exist_ok=True)
    st.title("Facebook Blueprint")
    st.caption(f"Biblioteca de modelos para conteúdos Facebook e Instagram · armazenamento em `{root}`")
    with st.form("facebook_blueprint_upload_form"):
        uploaded = st.file_uploader("Adicionar Facebook Blueprint", type=["md"], key="facebook_blueprint_upload")
        submitted = st.form_submit_button("Guardar Facebook Blueprint", type="primary")
    if submitted:
        if uploaded is None:
            st.error("Seleccione um ficheiro Markdown antes de guardar.")
        else:
            target = root / Path(uploaded.name).name
            target.write_bytes(uploaded.getvalue())
            st.success(f"Facebook Blueprint guardado: {target.name}")
            st.rerun()
    files = sorted(root.glob("*.md"))
    if not files:
        st.info("Ainda não existem Facebook Blueprints. Adicione um ficheiro Markdown para o disponibilizar nas contas Instagram.")
    for path in files:
        with st.expander(path.stem, expanded=False):
            st.caption(f"Ficheiro: `{path.name}`")
            st.code(path.read_text(encoding="utf-8"), language="markdown")


def render_thumbnail_blueprints():
    st.title("Thumbnail Blueprints")
    st.caption(f"Documentos de estilo visual por nicho · armazenamento em `{BLUEPRINTS / 'thumbnails'}`")
    st.info("Crie uma regra visual reutilizável a partir das thumbnails públicas de um canal concorrente. O documento gerado é separado do Blueprint de roteiro e será aplicado automaticamente ao canal associado.")
    with st.form("create_thumbnail_blueprint_from_link"):
        source_url = st.text_input("Link do canal ou vídeo YouTube", placeholder="https://www.youtube.com/@canal ou https://youtu.be/video")
        niche = st.text_input("Nicho (usado no nome do ficheiro)", placeholder="Ex.: Militar")
        channel_name = st.text_input("Nome do canal concorrente (opcional)")
        sample_limit = st.slider("Vídeos públicos para analisar", 3, 10, 10)
        submitted = st.form_submit_button("Analisar e criar Thumbnail Blueprint", type="primary")
    if submitted:
        if not source_url.strip() or not niche.strip():
            st.error("Informe o link do YouTube e o nicho antes de criar.")
        else:
            try:
                public = fetch_channel_videos_public(source_url, limit=sample_limit)
                if not public.ok and not public.data.get("videos"):
                    raise ValueError(public.message)
                document = generate_thumbnail_blueprint(read_json("settings.json", {}), source_url=source_url.strip(), niche=niche.strip(), channel_name=channel_name.strip(), videos=public.data.get("videos", []))
                path = save_thumbnail_blueprint(document)
                st.success(f"Thumbnail Blueprint criado: {path.name} · {len(document.get('sample_videos', []))} referência(s) analisada(s).")
                st.rerun()
            except (ValueError, OSError) as exc:
                st.error(str(exc))
    st.divider()
    st.subheader("Thumbnail Blueprints existentes")
    search = st.text_input("Pesquisar Thumbnail Blueprints", key="thumbnail_blueprint_search")
    documents = list_thumbnail_blueprint_documents()
    if not documents:
        st.info("Ainda não existem Thumbnail Blueprints. Use um link público do YouTube para criar o primeiro.")
    for path in documents:
        if search and search.casefold() not in path.name.casefold():
            continue
        with st.container(border=True):
            st.markdown(f"### {path.stem}")
            st.caption(f"Ficheiro: `{path.name}`")
            pair_options = blueprint_catalog()
            pair_ids = [item[0] for item in pair_options]
            pair_labels = {item[0]: item[1] for item in pair_options}
            existing_pairs = thumbnail_blueprint_associations()
            associated = [key for key, value in existing_pairs.items() if value == path.stem]
            pair = st.multiselect("Blueprints de roteiro associados", pair_ids, default=[item for item in associated if item in pair_ids], format_func=lambda item: pair_labels.get(item, item or "Sem Blueprint padrão"), key=f"thumbnail_card_pair_{path.stem}")
            if st.button("Guardar associação deste card", key=f"thumbnail_card_pair_save_{path.stem}"):
                try:
                    save_thumbnail_blueprint_pairs(path.stem, pair)
                    st.success("Associações guardadas; todos os Blueprints selecionados usarão esta Thumbnail Blueprint automaticamente.")
                except ValueError as exc:
                    st.error(str(exc))
            with st.expander("Abrir documento completo", expanded=False):
                st.code(path.read_text(encoding="utf-8"), language="markdown")
    st.divider()
    st.subheader("Associar ao canal e ao Blueprint de roteiro")
    channels = read_json("channels.json", [])
    thumbnail_options = thumbnail_blueprint_catalog()
    thumbnail_ids = [item[0] for item in thumbnail_options]
    thumbnail_labels = {item[0]: item[1] for item in thumbnail_options}
    blueprint_options = blueprint_catalog()
    blueprint_ids = [item[0] for item in blueprint_options]
    blueprint_labels = {item[0]: item[1] for item in blueprint_options}
    for channel in channels:
        channel_id = str(channel.get("id") or "")
        if not channel_id:
            continue
        with st.container(border=True):
            st.write(f"**{channel.get('name', 'Canal')}**")
            cols = st.columns(3)
            current_thumb = str(channel.get("default_thumbnail_blueprint_id") or channel.get("thumbnail_blueprint_id") or "")
            current_script = str(channel.get("default_blueprint_id") or channel.get("blueprint_id") or "")
            with cols[0]:
                thumb = st.selectbox("Thumbnail Blueprint", thumbnail_ids, index=thumbnail_ids.index(current_thumb) if current_thumb in thumbnail_ids else 0, format_func=lambda item: thumbnail_labels.get(item, item), key=f"thumbnail_blueprint_channel_{channel_id}")
            with cols[1]:
                script = st.selectbox("Blueprint de roteiro associado", blueprint_ids, index=blueprint_ids.index(current_script) if current_script in blueprint_ids else 0, format_func=lambda item: blueprint_labels.get(item, item or "Sem Blueprint padrão"), key=f"thumbnail_script_blueprint_channel_{channel_id}")
            with cols[2]:
                if st.button("Guardar par", key=f"thumbnail_blueprint_save_{channel_id}", width="stretch"):
                    update_channel(channel_id, {"thumbnail_blueprint_id": thumb, "default_thumbnail_blueprint_id": thumb, "blueprint_id": script, "default_blueprint_id": script})
                    if script:
                        save_thumbnail_blueprint_pair(thumb, script)
                    st.success("Par Blueprint de roteiro + Thumbnail Blueprint guardado.")
                    st.rerun()
def _tiktok_accounts_from_settings(settings: dict[str, Any]) -> list[dict[str, Any]]:
    raw_accounts = settings.get("tiktok_accounts")
    if not isinstance(raw_accounts, list) or not raw_accounts:
        raw_accounts = settings.get("tiktok_profiles", [])
    if not isinstance(raw_accounts, list):
        return []
    accounts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_accounts:
        if not isinstance(raw, dict):
            continue
        try:
            reference = normalize_tiktok_reference(str(raw.get("url") or raw.get("handle") or raw.get("username") or raw.get("id") or ""))
        except ValueError:
            continue
        account = {**raw, **reference}
        account["name"] = str(raw.get("name") or raw.get("label") or reference["username"]).strip()
        account["bio"] = str(raw.get("bio") or raw.get("description") or "").strip()
        account["source"] = str(raw.get("source") or raw.get("origin") or "manual").strip()
        key = account["id"]
        if key in seen:
            continue
        seen.add(key)
        accounts.append(account)
    return accounts


def _save_tiktok_accounts(accounts: list[dict[str, Any]]) -> None:
    settings = read_json("settings.json", {})
    settings["tiktok_accounts"] = accounts
    write_json("settings.json", settings)


def _upsert_tiktok_account(account: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    settings = read_json("settings.json", {})
    accounts = _tiktok_accounts_from_settings(settings)
    normalized = normalize_tiktok_reference(str(account.get("url") or account.get("handle") or account.get("username") or ""))
    merged = {**account, **normalized}
    merged["name"] = str(account.get("name") or normalized["username"]).strip() or normalized["username"]
    existing_index = next((index for index, item in enumerate(accounts) if item.get("id") == normalized["id"] or item.get("username") == normalized["username"]), None)
    created = existing_index is None
    if existing_index is None:
        accounts.append(merged)
    else:
        accounts[existing_index] = {**accounts[existing_index], **merged}
    _save_tiktok_accounts(accounts)
    return accounts, created


def _tiktok_account_metric(account: dict[str, Any], key: str, label: str) -> str:
    value = account.get(key)
    return f"{label}: {value:,}" if isinstance(value, int) else f"{label}: —"


def render_tiktok_accounts():
    st.title("Contas TikTok")
    st.caption("Pesquisa pública e cadastro manual de contas TikTok para alimentar o selector de destino no Upload. Esta área não usa OAuth, API de publicação nem lote.")
    settings = read_json("settings.json", {})
    accounts = _tiktok_accounts_from_settings(settings)

    search_tab, manual_tab, library_tab = render_localized_tabs(["Pesquisa pública", "Cadastro manual", "Contas cadastradas"])
    with search_tab:
        st.subheader("Pesquisar perfil público")
        st.info("A pesquisa consulta apenas a página pública do perfil e pode devolver dados incompletos. Se o TikTok bloquear a consulta, utilize o cadastro manual.")
        with st.form("tiktok_public_lookup_form"):
            lookup_source = st.text_input("URL pública ou @handle", placeholder="https://www.tiktok.com/@conta ou @conta", key="tiktok_public_lookup_source")
            lookup_submitted = st.form_submit_button("Pesquisar perfil público", type="primary", width="stretch")
        if lookup_submitted:
            result = fetch_public_tiktok_profile(lookup_source)
            st.session_state["tiktok_public_lookup"] = {"ok": result.ok, "message": result.message, "data": result.data}
            (st.success if result.ok else st.warning)(result.message)
        lookup = st.session_state.get("tiktok_public_lookup", {})
        lookup_data = lookup.get("data") if isinstance(lookup, dict) else None
        if isinstance(lookup_data, dict) and lookup_data.get("url"):
            with st.container(border=True):
                st.subheader(str(lookup_data.get("name") or lookup_data.get("handle") or "Perfil TikTok"))
                st.caption(f"{lookup_data.get('handle', '')} · {lookup_data.get('public_url') or lookup_data.get('url')}")
                if lookup_data.get("bio"):
                    st.write(lookup_data["bio"])
                metric_cols = st.columns(4)
                with metric_cols[0]: st.metric("Seguidores", lookup_data.get("subscriber_count") if lookup_data.get("subscriber_count") is not None else "—")
                with metric_cols[1]: st.metric("Seguindo", lookup_data.get("following_count") if lookup_data.get("following_count") is not None else "—")
                with metric_cols[2]: st.metric("Gostos", lookup_data.get("likes_count") if lookup_data.get("likes_count") is not None else "—")
                with metric_cols[3]: st.metric("Vídeos", lookup_data.get("video_count") if lookup_data.get("video_count") is not None else "—")
                display_name = st.text_input("Nome da conta", value=str(lookup_data.get("name") or lookup_data.get("username") or ""), key="tiktok_lookup_display_name")
                notes = st.text_area("Observações internas", value=str(lookup_data.get("notes") or ""), key="tiktok_lookup_notes", height=80)
                if st.button("Cadastrar conta TikTok", type="primary", width="stretch", key="tiktok_register_public_account"):
                    try:
                        stored = {**lookup_data, "name": display_name.strip() or lookup_data.get("username", ""), "notes": notes.strip(), "source": "public_lookup"}
                        _upsert_tiktok_account(stored)
                        st.session_state.pop("tiktok_public_lookup", None)
                        st.success("Conta TikTok cadastrada e disponível no selector de Upload.")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

    with manual_tab:
        st.subheader("Cadastrar conta manualmente")
        with st.form("tiktok_manual_account_form"):
            manual_source = st.text_input("@handle ou URL pública", placeholder="@minhaconta", key="tiktok_manual_source")
            manual_name = st.text_input("Nome da conta", placeholder="Nome de apresentação", key="tiktok_manual_name")
            manual_notes = st.text_area("Observações internas", height=90, key="tiktok_manual_notes")
            manual_submitted = st.form_submit_button("Guardar cadastro manual", type="primary", width="stretch")
        if manual_submitted:
            try:
                reference = normalize_tiktok_reference(manual_source)
                _upsert_tiktok_account({**reference, "name": manual_name.strip() or reference["username"], "notes": manual_notes.strip(), "source": "manual"})
                st.success("Conta TikTok cadastrada manualmente.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    with library_tab:
        st.subheader(f"Contas TikTok cadastradas ({len(accounts)})")
        if not accounts:
            st.info("Ainda não existem contas TikTok. Use Pesquisa pública ou Cadastro manual para adicionar a primeira conta.")
        for account in accounts:
            account_id = str(account.get("id") or account.get("username"))
            with st.container(border=True):
                card_cols = st.columns([0.18, 2.7, 1.1, 1.1, 0.8])
                with card_cols[0]:
                    if account.get("avatar_url"):
                        st.image(account["avatar_url"], width=52)
                    else:
                        st.markdown("### TT")
                with card_cols[1]:
                    st.write(f"**{account.get('name') or account.get('username')}**")
                    st.caption(f"{account.get('handle') or '@' + str(account.get('username', ''))} · {account.get('public_url') or account.get('url')}")
                    st.caption(str(account.get("source") or "manual").replace("_", " ").title())
                with card_cols[2]: st.caption(_tiktok_account_metric(account, "subscriber_count", "Seguidores"))
                with card_cols[3]: st.caption(_tiktok_account_metric(account, "video_count", "Vídeos"))
                with card_cols[4]:
                    if st.button("Apagar", key=f"delete_tiktok_account_{account_id}"):
                        _save_tiktok_accounts([item for item in accounts if str(item.get("id")) != account_id])
                        st.success("Conta TikTok removida.")
                        st.rerun()
                with st.expander("Editar conta", expanded=False):
                    with st.form(f"edit_tiktok_account_{account_id}"):
                        edited_name = st.text_input("Nome da conta", value=str(account.get("name") or account.get("username") or ""), key=f"edit_tiktok_name_{account_id}")
                        edited_source = st.text_input("@handle ou URL pública", value=str(account.get("public_url") or account.get("url") or account.get("handle") or ""), key=f"edit_tiktok_source_{account_id}")
                        edited_notes = st.text_area("Observações internas", value=str(account.get("notes") or ""), key=f"edit_tiktok_notes_{account_id}", height=80)
                        edit_submitted = st.form_submit_button("Guardar conta", type="primary", width="stretch")
                    if edit_submitted:
                        try:
                            reference = normalize_tiktok_reference(edited_source)
                            updated = {**account, **reference, "name": edited_name.strip() or reference["username"], "notes": edited_notes.strip(), "source": account.get("source") or "manual"}
                            _upsert_tiktok_account(updated)
                            st.success("Conta TikTok actualizada.")
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))


def render_tiktok_prompt_masters():
    st.title("Prompts Master")
    st.caption(f"Biblioteca exclusiva para vídeos TikTok. Os ficheiros ficam em `{TIKTOK_PROMPT_MASTERS}` e nunca entram na pasta de Blueprints YouTube.")

    upload_tab, library_tab = render_localized_tabs(["Upload", "Biblioteca"])
    with upload_tab:
        st.subheader("Adicionar Prompt Master")
        st.info("Use ficheiros Markdown `.md`. Cada Prompt Master é guardado como um ficheiro independente no storage TikTok.")
        uploaded_prompt = st.file_uploader("Subir Prompt Master (.md)", type=["md"], key="tiktok_prompt_master_upload")
        if uploaded_prompt is not None:
            uploaded_name = Path(uploaded_prompt.name).stem
            prompt_name = st.text_input("Nome do Prompt Master", value=uploaded_name, key="tiktok_prompt_master_name")
            replace_prompt = st.checkbox("Permitir substituir um ficheiro existente", key="tiktok_prompt_master_replace")
            if st.button("Guardar Prompt Master", type="primary", width="stretch", key="save_tiktok_prompt_master"):
                safe_stem = re.sub(r"[^A-Za-z0-9À-ÿ._-]+", "-", prompt_name.strip() or uploaded_name).strip(".-") or "prompt-master"
                destination = TIKTOK_PROMPT_MASTERS / f"{safe_stem}.md"
                if destination.exists() and not replace_prompt:
                    st.warning("Já existe um Prompt Master com esse nome. Active a substituição para o actualizar.")
                else:
                    try:
                        content = uploaded_prompt.getvalue().decode("utf-8-sig")
                        if not content.strip():
                            raise ValueError("O ficheiro Markdown está vazio.")
                        destination.write_text(content.rstrip() + "\n", encoding="utf-8")
                        st.success(f"Prompt Master guardado em `{destination}`.")
                        st.rerun()
                    except UnicodeDecodeError:
                        st.error("O ficheiro deve estar codificado em UTF-8.")
                    except OSError as exc:
                        st.error(f"Não foi possível guardar o Prompt Master: {exc}")

    with library_tab:
        files = list_prompt_master_files()
        st.subheader(f"Prompts Master existentes ({len(files)})")
        search = st.text_input("Pesquisar Prompt Master", key="tiktok_prompt_master_search", placeholder="Nome ou conteúdo")
        visible_files: list[Path] = []
        for path in files:
            try:
                content = load_prompt_master_file(path)
            except (OSError, ValueError):
                content = ""
            display_heading = get_display_name("prompt_masters", path, next((line.lstrip("#").strip() for line in content.splitlines() if line.startswith("#")), path.stem))
            if search and search.lower() not in f"{display_heading}\n{path.name}\n{content}".lower():
                continue
            visible_files.append(path)
        if not visible_files:
            st.info("Ainda não existem Prompt Master que correspondam à pesquisa.")
        for path in visible_files:
            try:
                content = load_prompt_master_file(path)
                fallback_heading = next((line.lstrip("#").strip() for line in content.splitlines() if line.startswith("#")), path.stem)
                heading = get_display_name("prompt_masters", path, fallback_heading)
                card_key = _library_card_key("prompt_masters", path)
                header_cols = st.columns([0.93, 0.07], vertical_alignment="center")
                with header_cols[0]:
                    with st.expander(heading, expanded=False):
                        edited_content = st.text_area("Conteúdo Markdown", value=content, height=360, key=f"tiktok_prompt_master_editor_{path.stem}")
                        prompt_cols = st.columns(3)
                        with prompt_cols[0]:
                            if st.button("Guardar alterações", type="primary", width="stretch", key=f"save_prompt_master_{path.stem}"):
                                path.write_text(edited_content.rstrip() + "\n", encoding="utf-8")
                                st.success("Prompt Master actualizado.")
                                st.rerun()
                        with prompt_cols[1]:
                            st.download_button("Descarregar", data=content.encode("utf-8"), file_name=path.name, mime="text/markdown", width="stretch", key=f"download_prompt_master_{path.stem}")
                        with prompt_cols[2]:
                            if st.button("Apagar", width="stretch", key=f"delete_prompt_master_{path.stem}"):
                                path.unlink(missing_ok=True)
                                st.success("Prompt Master removido da biblioteca TikTok.")
                                st.rerun()
                        st.markdown(content)
                with header_cols[1]:
                    _render_card_pencil(f"rename_prompt_masters_{card_key}")
                _render_library_name_editor("prompt_masters", path, heading)
            except (OSError, ValueError) as exc:
                with st.expander(f"Ficheiro inválido — {path.stem}"):
                    st.error(str(exc))


def format_metric_number(value: Any) -> str:
    if value in (None, ""):
        return "—"
    try:
        normalized = str(value).strip().replace(".", "").replace(",", "")
        return f"{int(normalized):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(value)


def classify_channel_platform(channel: Any) -> str:
    """Classify channels while keeping legacy YouTube records visible."""
    if not isinstance(channel, dict):
        return "unknown"
    value = str(channel.get("platform") or "").strip().casefold().replace(" ", "")
    if value in {"youtube", "yt"}:
        return "youtube"
    if value in {"tiktok", "tik-tok", "tt"}:
        return "tiktok"
    if value in {"instagram", "ig"}:
        return "instagram"
    if value in {"facebook", "facebook_page", "facebook_pages", "fb"}:
        return "facebook"
    if value in {"bilibili", "bili"}:
        return "bilibili"
    def has_tiktok_marker(item: Any) -> bool:
        if isinstance(item, dict):
            return any(has_tiktok_marker(key) or has_tiktok_marker(value) for key, value in item.items())
        if isinstance(item, (list, tuple, set)):
            return any(has_tiktok_marker(value) for value in item)
        normalized = str(item or "").strip().casefold().replace(" ", "")
        return "tiktok" in normalized or normalized == "tik-tok"
    return "tiktok" if has_tiktok_marker(channel) else "youtube"


def _tiktok_channel_records() -> list[dict[str, Any]]:
    return [channel for channel in read_json("channels.json", []) if classify_channel_platform(channel) == "tiktok"]


@st.fragment
def _render_bilibili_automation_cards() -> None:
    if not _has_script_context():
        return
    st.divider()
    st.subheader("Vídeos cadastrados Bilibili")
    st.caption("Esta fila mostra exclusivamente tarefas associadas a canais Bilibili.")
    tasks = load_automation_tasks_for_platform("bilibili")
    if not tasks:
        st.info("Ainda não existem vídeos Bilibili cadastrados.")
        return
    for task in tasks:
        task_id = str(task.get("id") or "")
        with st.container(border=True):
            card_cols = st.columns([2.25, 1.55, 1.05, 2.15], gap="small")
            script_path = _task_artifact_path(task, "script")
            video_path = _task_artifact_path(task, "video")
            thumbnail_path = _task_thumbnail_path(task)
            with card_cols[0]:
                if thumbnail_path:
                    st.image(str(thumbnail_path), width=180, caption="Thumbnail")
                else:
                    st.caption("Thumbnail ainda não pronta")
                st.write(f"**{task.get('title') or task.get('topic') or 'Vídeo Bilibili'}**")
                st.caption(f"{task.get('channel_name') or 'Canal Bilibili'} · {task_id}")
            with card_cols[1]:
                _render_video_task_state(task)
            with card_cols[2]:
                st.caption("Plataforma")
                st.write("Bilibili")
            with card_cols[3]:
                state = str(task.get("state") or "")
                start_col, stop_col, delete_col = st.columns(3)
                with start_col:
                    if st.button("Start", key=f"bilibili_automation_start_{task_id}", width="stretch", disabled=state not in {"to_do", "blocked", "failed"}):
                        if _start_pipeline_task(task_id, state):
                            st.rerun(scope="fragment")
                with stop_col:
                    if st.button("Stop", key=f"bilibili_automation_stop_{task_id}", width="stretch", disabled=state != "doing"):
                        stop_task_by_user(task_id)
                        st.rerun(scope="fragment")
                script_download_col, video_download_col = st.columns(2, gap="small")
                with script_download_col:
                    st.download_button(
                        "Baixar Roteiro",
                        data=_file_bytes(script_path),
                        file_name=_automation_download_name("Script", task, script_path, ".md"),
                        mime="text/markdown",
                        key=f"bilibili_automation_download_script_{task_id}",
                        width="stretch",
                        disabled=script_path is None,
                    )
                with video_download_col:
                    st.download_button(
                        "Baixar Vídeo",
                        data=_file_bytes(video_path),
                        file_name=_automation_download_name("Vídeo", task, video_path, ".mp4"),
                        mime="video/mp4",
                        key=f"bilibili_automation_download_video_{task_id}",
                        width="stretch",
                        disabled=video_path is None,
                    )
                if st.button(
                    "Refazer Vídeo",
                    key=f"bilibili_automation_remake_video_{task_id}",
                    icon=":material/refresh:",
                    type="primary",
                    width="stretch",
                    disabled=state == "doing",
                    help="Refaz o áudio e o vídeo do zero, mantendo o roteiro, tags, voz, thumbnail e demais artefactos criativos.",
                ):
                    if _remake_video_from_card(task):
                        st.rerun(scope="fragment")
                with delete_col:
                    if st.button("Apagar", key=f"bilibili_automation_delete_{task_id}", width="stretch", disabled=state == "doing"):
                        delete_task(task_id)
                        st.rerun(scope="fragment")


def render_bilibili_automation() -> None:
    st.title("Automação Bilibili")
    st.caption("Fila de produção Bilibili com o mesmo fluxo de regeneração de áudio e vídeo das restantes automações.")
    _render_bilibili_automation_cards()


def _tiktok_avatar_url(value: dict[str, Any]) -> str:
    for key in ("avatar_url", "thumbnail_url", "profile_image_url", "avatar", "image_url"):
        candidate = value.get(key)
        if isinstance(candidate, dict):
            candidate = candidate.get("url") or candidate.get("src")
        if str(candidate or "").strip():
            return str(candidate).strip()
    return ""


def _tiktok_prompt_options() -> tuple[list[str], dict[str, str]]:
    files = list_prompt_master_files()
    labels = {path.name: get_display_name("prompt_masters", path, path.stem) for path in files}
    return [""] + [path.name for path in files], {"": "Sem Prompt Master padrão", **labels}


def render_tiktok_channels():
    st.title("Canais Tiktok")
    st.caption("Canais de Shorts em formato Portrait 9:16. A pesquisa usa exclusivamente a página pública do TikTok, sem API.")
    settings = read_json("settings.json", {})
    channels = _tiktok_channel_records()
    import_tab, spreadsheet_tab, manual_tab = render_localized_tabs(["Importar do Tiktok", "Canais em lote Planilha", "Cadastro manual"])
    prompt_ids, prompt_labels = _tiktok_prompt_options()
    _, _, _, voice_options, _ = channel_default_options({})
    with import_tab:
        st.caption("A pesquisa consulta exclusivamente a página pública do TikTok. Não existe método alternativo nem utilização de API.")
        st.divider()
        st.subheader("Importar novo canal pela página pública")
        source = st.text_input("URL pública ou @handle", placeholder="https://www.tiktok.com/@conta", key="tiktok_channel_source")
        lookup_cols = st.columns([1, 1])
        with lookup_cols[0]:
            if st.button("Buscar no Tiktok", type="primary", width="stretch", key="tiktok_channel_lookup"):
                result = fetch_public_tiktok_profile(source)
                st.session_state["tiktok_channel_import"] = {"ok": result.ok, "message": result.message, "data": result.data}
        with lookup_cols[1]:
            if st.button("Limpar importação", width="stretch", key="tiktok_channel_clear"):
                for key in ("tiktok_channel_import", "tiktok_import_language", "tiktok_import_niche", "tiktok_import_prompt", "tiktok_import_description"):
                    st.session_state.pop(key, None)
                st.rerun()
        imported_state = st.session_state.get("tiktok_channel_import", {})
        if imported_state.get("message"):
            (st.success if imported_state.get("ok") else st.warning)(imported_state["message"])
        imported = imported_state.get("data") if imported_state.get("ok") else {}
        if imported:
            st.caption("Dados encontrados na página pública. Reveja os cartões e edite os campos antes de guardar.")
            with st.container(border=True):
                profile_cols = st.columns([0.8, 2.2, 1, 1, 1])
                with profile_cols[0]:
                    avatar = _tiktok_avatar_url(imported)
                    if avatar:
                        st.image(avatar, width=82)
                    else:
                        st.markdown("### TT")
                with profile_cols[1]:
                    st.markdown(f"### {imported.get('name') or imported.get('username') or 'Perfil TikTok'}")
                    st.write(imported.get("handle") or f"@{imported.get('username', '')}")
                    st.caption(imported.get("public_url") or imported.get("url") or "Página pública")
                with profile_cols[2]:
                    st.metric("Seguidores", format_metric_number(imported.get("subscriber_count")))
                with profile_cols[3]:
                    st.metric("Curtidas", format_metric_number(imported.get("likes_count")))
                with profile_cols[4]:
                    st.metric("Vídeos", format_metric_number(imported.get("video_count")))
                if imported.get("bio"):
                    st.caption(f"Descrição pública: {imported['bio']}")
            with st.container(border=True):
                st.markdown("**Dados do canal a cadastrar**")
                data_cols = st.columns(3)
                with data_cols[0]:
                    st.write(f"**Nome:** {imported.get('name') or imported.get('username') or '—'}")
                    st.write(f"**Handle:** {imported.get('handle') or '—'}")
                with data_cols[1]:
                    st.write(f"**URL:** {imported.get('public_url') or imported.get('url') or '—'}")
                    st.write(f"**Origem:** {imported.get('metrics_source') or 'tiktok_public_page'}")
                with data_cols[2]:
                    st.write("**Formato:** Portrait 9:16")
                    st.write("**Consulta:** Página pública")
            with st.form("tiktok_channel_import_form"):
                name = st.text_input("Nome canal", value=str(imported.get("name") or imported.get("username") or ""))
                url = st.text_input("URL canal", value=str(imported.get("public_url") or imported.get("url") or ""))
                handle = st.text_input("Handle canal", value=str(imported.get("handle") or ""))
                language = st.selectbox("Idioma do roteiro", VIDEO_LANGUAGE_SELECTION_OPTIONS, format_func=video_language_label, key="tiktok_import_language")
                source_value = st.selectbox("Fonte do vídeo", WIDE_STYLE_OPTIONS, key="tiktok_import_source")
                aspect_value = st.selectbox("Proporção do vídeo", CHANNEL_ASPECT_RATIO_OPTIONS, index=1, key="tiktok_import_aspect")
                niche = st.text_input("Nicho", key="tiktok_import_niche")
                prompt = st.selectbox("Prompt Master padrão", prompt_ids, format_func=lambda item: prompt_labels.get(item, item), key="tiktok_import_prompt")
                voice = st.selectbox("Narrador/Voz Padrão", voice_options, format_func=lambda item: item or "Sem voz padrão", key="tiktok_import_voice")
                automation_on = st.toggle("Automação ON", value=False, key="tiktok_import_automation")
                automation_time = st.text_input("Horário diário (HH:MM)", value="00:00", key="tiktok_import_automation_time")
                description = st.text_area("Descrição", value=str(imported.get("bio") or ""), key="tiktok_import_description")
                if st.form_submit_button("Cadastrar canal TikTok", type="primary"):
                    if not valid_hhmm(automation_time):
                        st.error("O horário diário deve estar no formato HH:MM.")
                        st.stop()
                    channel = create_channel(name.strip(), url.strip(), {"platform": "tiktok", "handle": handle.strip(), "language": language, "niche": niche.strip(), "description": description.strip(), "default_prompt_master": prompt, "prompt_master": prompt, "default_voice": voice, "voice": voice, "style_wide": channel_video_source_storage(source_value), "video_aspect_ratio": aspect_value, "format": "Shorts", "automation_on": automation_on, "automation_time": automation_time.strip(), "metrics_source": "tiktok_public_page", "subscriber_count": imported.get("subscriber_count"), "video_count": imported.get("video_count")})
                    avatar_url = _tiktok_avatar_url(imported)
                    update_channel(channel["id"], {"platform": "tiktok", "default_prompt_master": prompt, "prompt_master": prompt, "avatar_url": avatar_url, "thumbnail_url": avatar_url})
                    st.session_state.pop("tiktok_channel_import", None)
                    st.success(f"Canal {channel['name']} cadastrado.")
                    st.rerun()
        st.divider()
        st.subheader(f"Canais TikTok cadastrados ({len(channels)})")
        tiktok_channel_search = st.text_input(
            "Pesquisar nomes dos canais TikTok",
            key="tiktok_registered_channels_search",
            placeholder="Digite o nome do canal",
        )
        visible_tiktok_channels = [
            channel for channel in channels
            if not tiktok_channel_search.strip()
            or tiktok_channel_search.strip().casefold() in str(channel.get("name") or "").casefold()
        ]
        if channels and visible_tiktok_channels:
            for channel in visible_tiktok_channels:
                channel_id = str(channel.get("id") or "")
                with st.container(border=True):
                    card_cols = st.columns([0.7, 2.55, 1.15, 1.05, 1.05, 1.25, 1.35], gap="small")
                    with card_cols[0]:
                        avatar_url = _tiktok_avatar_url(channel)
                        if avatar_url:
                            st.image(avatar_url, width=58)
                        else:
                            st.markdown("### TT")
                    with card_cols[1]:
                        st.markdown(f"**{channel.get('name') or 'Perfil TikTok'}**")
                        st.caption(f"{channel.get('handle') or 'sem handle'} · {channel.get('url') or 'sem URL'}")
                        st.caption(channel.get("description") or "Perfil carregado da página pública do TikTok.")
                        st.caption(f"Nicho: {channel.get('niche') or 'não configurado'}")
                    with card_cols[2]:
                        tiktok_url = _tiktok_channel_url(channel)
                        if tiktok_url:
                            st.link_button("Abrir canal", tiktok_url, type="primary", width="content")
                    with card_cols[3]:
                        st.metric("Seguidores", format_metric_number(channel.get("subscriber_count")))
                    with card_cols[4]:
                        st.metric("Curtidas", format_metric_number(channel.get("likes_count")))
                    with card_cols[5]:
                        st.metric("Vídeos", format_metric_number(channel.get("video_count")))
                    with card_cols[6]:
                        if st.button("↻", key=f"refresh_tiktok_metrics_{channel_id}", help="Actualizar Seguidores, Vídeos e Curtidas", width="stretch"):
                            with st.spinner("A actualizar métricas TikTok…"):
                                refreshed, message = _refresh_tiktok_channel_metrics(channel)
                            (st.success if refreshed else st.warning)(message)
                            if refreshed:
                                st.rerun()
                        active = st.toggle("Activo", value=bool(channel.get("active", True)), key=f"tiktok_import_card_active_{channel_id}")
                        if active != bool(channel.get("active", True)):
                            update_channel(channel_id, {"active": active})
                            st.rerun()
                    with st.expander("Detalhes e configuração do canal", expanded=False):
                        prompt_file = TIKTOK_PROMPT_MASTERS / str(channel.get("default_prompt_master") or channel.get("prompt_master") or "")
                        prompt_content = load_prompt_master_file(prompt_file) if prompt_file.is_file() else ""
                        calculated_time, calculated_source, calculated_words = _channel_average_video_time(channel, prompt_master=prompt_content)
                        average_video_time = st.text_input("Tempo Medio de Video", value=channel_video_time_value(channel), key=f"tiktok_channel_average_video_time_{channel_id}", help=f"Referência: {calculated_words or 0} palavras · {calculated_source}.")
                        if st.button("Guardar tempo", key=f"save_tiktok_channel_average_video_time_{channel_id}", width="stretch"):
                            if not valid_hhmm(average_video_time):
                                st.error("Use o formato MM:SS, por exemplo 12:00.")
                            else:
                                update_channel(channel_id, {"average_video_time": average_video_time.strip() or DEFAULT_AVERAGE_VIDEO_TIME, "average_video_word_count": words_from_channel_time(average_video_time)})
                                st.success("Tempo médio do canal TikTok guardado.")
                                st.rerun()
                        if st.button("Editar", key=f"tiktok_import_card_edit_{channel_id}"):
                            st.session_state[f"tiktok_edit_{channel_id}"] = not st.session_state.get(f"tiktok_edit_{channel_id}", False)
                            st.rerun()
                        if st.button("Apagar card", key=f"tiktok_import_card_delete_{channel_id}"):
                            st.session_state[f"tiktok_delete_{channel_id}"] = True
                            st.rerun()
                        summary_cols = st.columns(4, gap="medium")
                        with summary_cols[0]:
                            st.markdown("**Blueprint Padrão**")
                            st.caption(prompt_labels.get(str(channel.get("default_prompt_master") or channel.get("prompt_master") or ""), "Sem Blueprint padrão"))
                        with summary_cols[1]:
                            st.markdown("**Nicho**")
                            st.caption(channel_niche_label(channel))
                        with summary_cols[2]:
                            st.markdown("**Narrador/Voz Padrão**")
                            st.caption(str(channel.get("default_voice") or channel.get("voice") or "Sem voz padrão"))
                        with summary_cols[3]:
                            st.markdown("**Idioma**")
                            st.caption(video_language_label(normalize_video_language(channel.get("language") or "pt")))
                        st.caption(f"Fonte do vídeo: {channel_video_source_value(channel.get('style_wide'))} · Proporção: {channel.get('video_aspect_ratio') or 'Portrait 9:16'}")
                        with st.expander("Configurações de vídeo", expanded=False):
                            video_settings_cols = st.columns(3, gap="small")
                            current_source = channel_video_source_value(channel.get("style_wide"))
                            current_aspect = str(channel.get("video_aspect_ratio") or "Portrait 9:16")
                            current_format = str(channel.get("format") or "Shorts")
                            with video_settings_cols[0]:
                                video_source = st.selectbox(
                                    "Fonte do vídeo",
                                    WIDE_STYLE_OPTIONS,
                                    index=WIDE_STYLE_OPTIONS.index(current_source) if current_source in WIDE_STYLE_OPTIONS else 0,
                                    key=f"tiktok_video_settings_source_{channel_id}",
                                )
                            with video_settings_cols[1]:
                                video_aspect = st.selectbox(
                                    "Proporção do vídeo",
                                    CHANNEL_ASPECT_RATIO_OPTIONS,
                                    index=CHANNEL_ASPECT_RATIO_OPTIONS.index(current_aspect) if current_aspect in CHANNEL_ASPECT_RATIO_OPTIONS else 1,
                                    key=f"tiktok_video_settings_aspect_{channel_id}",
                                )
                            with video_settings_cols[2]:
                                video_format = st.selectbox(
                                    "Formato",
                                    CHANNEL_FORMAT_OPTIONS,
                                    index=CHANNEL_FORMAT_OPTIONS.index(current_format) if current_format in CHANNEL_FORMAT_OPTIONS else 1,
                                    key=f"tiktok_video_settings_format_{channel_id}",
                                )
                            if st.button("Guardar configurações de vídeo", key=f"tiktok_video_settings_save_{channel_id}", width="stretch", type="primary"):
                                update_channel(
                                    channel_id,
                                    {
                                        "style_wide": channel_video_source_storage(video_source),
                                        "video_aspect_ratio": video_aspect,
                                        "format": video_format,
                                        "platform": "tiktok",
                                    },
                                )
                                st.success("Configurações de vídeo TikTok guardadas.")
                                st.rerun()
                        if st.session_state.get(f"tiktok_delete_{channel_id}"):
                            st.warning("Apagar este canal TikTok e os dados locais associados?")
                            confirm_cols = st.columns(2)
                            with confirm_cols[0]:
                                if st.button("Confirmar apagar", type="primary", key=f"tiktok_confirm_delete_{channel_id}"):
                                    delete_channel(channel_id)
                                    st.session_state.pop(f"tiktok_delete_{channel_id}", None)
                                    st.rerun()
                            with confirm_cols[1]:
                                if st.button("Cancelar", key=f"tiktok_cancel_delete_{channel_id}"):
                                    st.session_state.pop(f"tiktok_delete_{channel_id}", None)
                                    st.rerun()
                        if st.session_state.get(f"tiktok_edit_{channel_id}"):
                            with st.form(f"tiktok_edit_form_{channel_id}"):
                                edit_name = st.text_input("Nome do canal", value=str(channel.get("name") or ""))
                                edit_url = st.text_input("URL pública", value=str(channel.get("url") or ""))
                                edit_handle = st.text_input("Handle", value=str(channel.get("handle") or ""))
                                edit_language = st.selectbox("Idioma do roteiro", VIDEO_LANGUAGE_SELECTION_OPTIONS, index=VIDEO_LANGUAGE_SELECTION_OPTIONS.index(normalize_video_language(channel.get("language") or "pt")) if normalize_video_language(channel.get("language") or "pt") in VIDEO_LANGUAGE_SELECTION_OPTIONS else 0, format_func=video_language_label)
                                edit_source = st.selectbox("Fonte do vídeo", WIDE_STYLE_OPTIONS, index=WIDE_STYLE_OPTIONS.index(channel_video_source_value(channel.get("style_wide"))) if channel_video_source_value(channel.get("style_wide")) in WIDE_STYLE_OPTIONS else 0)
                                edit_aspect = st.selectbox("Proporção do vídeo", CHANNEL_ASPECT_RATIO_OPTIONS, index=CHANNEL_ASPECT_RATIO_OPTIONS.index(str(channel.get("video_aspect_ratio") or "Portrait 9:16")) if str(channel.get("video_aspect_ratio") or "Portrait 9:16") in CHANNEL_ASPECT_RATIO_OPTIONS else 1)
                                edit_niche = st.text_input("Nicho", value=str(channel.get("niche") or ""))
                                edit_voice = st.selectbox("Narrador/Voz Padrão", voice_options, index=voice_options.index(str(channel.get("default_voice") or channel.get("voice") or "")) if str(channel.get("default_voice") or channel.get("voice") or "") in voice_options else 0, format_func=lambda item: item or "Sem voz padrão")
                                edit_automation = st.toggle("Automação ON", value=bool(channel.get("automation_on", False)), key=f"tiktok_edit_automation_{channel_id}")
                                edit_time = st.text_input("Horário diário (HH:MM)", value=str(channel.get("automation_time") or "00:00"))
                                st.caption(f"Fonte do vídeo: {channel_video_source_value(channel.get('style_wide'))}")
                                edit_description = st.text_area("Descrição", value=str(channel.get("description") or ""))
                                if st.form_submit_button("Guardar edição", type="primary"):
                                    if not valid_hhmm(edit_time):
                                        st.error("O horário diário deve estar no formato HH:MM.")
                                    else:
                                        update_channel(channel_id, {"name": edit_name.strip(), "url": edit_url.strip(), "handle": edit_handle.strip(), "language": edit_language, "niche": edit_niche.strip(), "reference_channels": [edit_niche.strip()] if edit_niche.strip() else [], "default_voice": edit_voice, "voice": edit_voice, "style_wide": channel_video_source_storage(edit_source), "video_aspect_ratio": edit_aspect, "automation_on": edit_automation, "automation_time": edit_time.strip(), "description": edit_description.strip(), "platform": "tiktok"})
                                        st.session_state.pop(f"tiktok_edit_{channel_id}", None)
                                        st.rerun()
                        render_channel_audio_subtitle_defaults(channel)
                        with st.expander("Últimos 10 vídeos publicados", expanded=False):
                            recent_videos = channel_videos_for(channel, limit=10)
                            if not recent_videos:
                                st.info("Ainda não existem vídeos públicos sincronizados para este canal TikTok.")
                            for recent_video in recent_videos[:10]:
                                video_cols = st.columns([0.7, 3.5, 1.2])
                                with video_cols[0]:
                                    if recent_video.get("thumbnail_url"):
                                        st.image(recent_video["thumbnail_url"], width=64)
                                    else:
                                        st.markdown("### TT")
                                with video_cols[1]:
                                    st.write(f"**{recent_video.get('title') or 'Vídeo sem título'}**")
                                    st.caption(f"{recent_video.get('published_at') or 'Sem data'} · {recent_video.get('url') or 'Sem URL'}")
                                with video_cols[2]:
                                    st.caption(str(recent_video.get("status") or "publicado").title())
        elif not channels:
            st.info("Ainda não existem canais TikTok cadastrados. Use o campo abaixo para pesquisar e cadastrar um perfil público.")
        else:
            st.info("Nenhum canal TikTok corresponde à pesquisa.")
    with spreadsheet_tab:
        uploaded = st.file_uploader("Upload da planilha de canais TikTok", type=["xlsx", "xls"], key="tiktok_channel_spreadsheet")
        if uploaded and st.button("Ler e cadastrar planilha TikTok", type="primary", key="tiktok_read_sheet"):
            rows, warnings = parse_channel_workbook(uploaded.getvalue(), uploaded.name)
            for warning in warnings:
                st.warning(warning)
            created = 0
            for row in rows:
                candidate = {"name": row.get("name", ""), "handle": row.get("handle", ""), "url": row.get("url", "")}
                if find_duplicate_channel(candidate, channels):
                    continue
                created_channel = create_channel(str(row.get("name") or row.get("handle") or "TikTok"), str(row.get("url") or ""), {"platform": "tiktok", "handle": row.get("handle", ""), "language": language_code(row.get("language") or "pt"), "niche": row.get("niche", ""), "description": row.get("description", ""), "default_prompt_master": row.get("prompt_master", ""), "prompt_master": row.get("prompt_master", ""), "default_voice": row.get("voice", ""), "voice": row.get("voice", ""), "style_wide": "portrait", "video_aspect_ratio": "Portrait 9:16", "automation_on": bool(row.get("automation_on", False)), "automation_time": row.get("automation_time") or "00:00"})
                update_channel(created_channel["id"], {"platform": "tiktok"})
                created += 1
            st.success(f"{created} canal(is) TikTok cadastrado(s).")
            st.rerun()
        st.caption("A planilha usa os campos de URL, nome, handle, idioma, nicho, Prompt Master, descrição e horário.")
        st.divider()
        st.subheader(f"Canais TikTok cadastrados ({len(channels)})")
        if channels:
            st.dataframe(
                [{k: c.get(v, "") for k, v in {"URL canal": "url", "Nome canal": "name", "Handle canal": "handle", "Idioma": "language", "Nicho": "niche", "Prompt Master": "default_prompt_master", "Narrador/Voz Padrão": "default_voice", "Estilo wide": "style_wide", "Automação ligada": "automation_on", "Horário diário (HH:MM)": "automation_time", "Proporção": "video_aspect_ratio", "Activo": "active", "Descrição": "description"}.items()} for c in channels],
                width="stretch",
                hide_index=True,
                height=360,
            )
        else:
            st.info("Ainda não existem canais TikTok cadastrados.")
    with manual_tab:
        with st.form("tiktok_channel_manual_form"):
            url = st.text_input("URL canal", placeholder="https://www.tiktok.com/@conta", key="tiktok_manual_channel_url")
            name = st.text_input("Nome canal", key="tiktok_manual_channel_name")
            handle = st.text_input("Handle canal", key="tiktok_manual_channel_handle")
            language = st.selectbox("Idioma do roteiro", VIDEO_LANGUAGE_SELECTION_OPTIONS, format_func=video_language_label, key="tiktok_manual_channel_language")
            source_value = st.selectbox("Fonte do vídeo", WIDE_STYLE_OPTIONS, key="tiktok_manual_channel_source")
            aspect_value = st.selectbox("Proporção do vídeo", CHANNEL_ASPECT_RATIO_OPTIONS, index=1, key="tiktok_manual_channel_aspect")
            niche = st.text_input("Nicho", key="tiktok_manual_channel_niche")
            prompt = st.selectbox("Prompt Master padrão", prompt_ids, format_func=lambda item: prompt_labels.get(item, item), key="tiktok_manual_channel_prompt")
            voice = st.selectbox("Narrador/Voz Padrão", voice_options, format_func=lambda item: item or "Sem voz padrão", key="tiktok_manual_channel_voice")
            automation_on = st.toggle("Automação ON", value=False, key="tiktok_manual_channel_automation")
            automation_time = st.text_input("Horário diário (HH:MM)", value="00:00", key="tiktok_manual_channel_automation_time")
            st.caption("Estilo wide: Portrait 9:16")
            description = st.text_area("Descrição", key="tiktok_manual_channel_description")
            if st.form_submit_button("Guardar canal manual", type="primary"):
                reference = normalize_tiktok_reference(url or handle)
                if not valid_hhmm(automation_time):
                    st.error("O horário diário deve estar no formato HH:MM.")
                    st.stop()
                channel = create_channel(name.strip() or reference["username"], reference["url"], {"platform": "tiktok", "handle": reference["handle"], "language": language, "niche": niche.strip(), "description": description.strip(), "default_prompt_master": prompt, "prompt_master": prompt, "default_voice": voice, "voice": voice, "style_wide": channel_video_source_storage(source_value), "video_aspect_ratio": aspect_value, "format": format_value, "automation_on": automation_on, "automation_time": automation_time.strip()})
                update_channel(channel["id"], {"platform": "tiktok"})
                st.success("Canal TikTok cadastrado.")
                st.rerun()
def is_youtube_channel_record(channel: Any) -> bool:
    """Return whether a persisted channel is explicitly identified as YouTube."""
    return classify_channel_platform(channel) == "youtube"


def _channel_count_value(value: Any) -> int:
    if value in (None, ""):
        return 0
    text = str(value).strip().replace(" ", "")
    if "." in text or "," in text:
        return int(re.sub(r"[^0-9]", "", text) or 0)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _channel_count_text(value: Any) -> str:
    parsed = _channel_count_value(value)
    return f"{parsed:,}".replace(",", ".") if parsed else ""


def _format_channel_count(value: Any) -> str:
    """Mostrar contadores inteiros com ponto a cada três algarismos."""
    if value is None or str(value).strip() == "":
        return "—"
    try:
        return f"{_channel_count_value(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(value)


def _channel_average_video_time(channel: dict[str, Any], *, prompt_master: str = "") -> tuple[str, str, int]:
    blueprint = blueprint_for_channel(channel) if is_youtube_channel_record(channel) else {}
    words, duration, source = channel_video_length(channel, blueprint, prompt_master)
    return duration, source, words


def _refresh_youtube_channel_metrics(channel: dict[str, Any], youtube: YouTubeAdapter) -> tuple[bool, str]:
    channel_ref = str(channel.get("youtube_channel_id") or channel.get("youtube_id") or channel.get("url") or channel.get("handle") or "")
    if not channel_ref:
        return False, "Este canal não tem URL, handle ou ID YouTube para actualizar as métricas."
    try:
        result = youtube.fetch_channel(channel_ref) if youtube.api_key else youtube.fetch_channel_public(channel_ref)
        if not result.ok and youtube.api_key:
            public_result = youtube.fetch_channel_public(channel_ref)
            if public_result.ok:
                result = public_result
    except Exception as exc:
        return False, f"Não foi possível actualizar as métricas YouTube ({type(exc).__name__}). Tente novamente."
    if not result.ok or not isinstance(result.data, dict):
        return False, result.message
    data = result.data
    updates = {
        "metrics_source": data.get("metrics_source", "youtube_public_page"),
        "last_public_lookup_at": data.get("last_public_lookup_at", now()),
    }
    for field in ("youtube_id", "name", "handle", "url", "thumbnail_url", "subscriber_count", "video_count", "view_count"):
        if data.get(field) is not None and data.get(field) != "":
            updates[field] = data[field]
    update_channel(str(channel["id"]), updates)
    return True, "Métricas YouTube actualizadas."


def _refresh_tiktok_channel_metrics(channel: dict[str, Any]) -> tuple[bool, str]:
    channel_ref = str(channel.get("url") or channel.get("handle") or "").strip()
    if not channel_ref:
        return False, "Este canal não tem URL ou handle TikTok para actualizar as métricas."
    try:
        result = fetch_public_tiktok_profile(channel_ref)
    except Exception as exc:
        return False, f"Não foi possível actualizar as métricas TikTok ({type(exc).__name__}). Tente novamente."
    if not result.ok or not isinstance(result.data, dict):
        return False, result.message
    data = result.data
    updates = {
        "metrics_source": data.get("metrics_source", "tiktok_public_page"),
        "last_public_lookup_at": data.get("last_public_lookup_at", now()),
    }
    for field in ("subscriber_count", "likes_count", "video_count", "view_count", "name", "handle", "url", "avatar_url", "thumbnail_url"):
        if data.get(field) is not None and data.get(field) != "":
            updates[field] = data[field]
    update_channel(str(channel["id"]), updates)
    return True, "Métricas TikTok actualizadas."


def _tiktok_channel_url(channel: dict[str, Any]) -> str:
    source = str(channel.get("url") or channel.get("handle") or channel.get("username") or "").strip()
    if not source:
        return ""
    try:
        return str(normalize_tiktok_reference(source).get("url") or "").strip()
    except ValueError:
        return source if source.startswith(("http://", "https://")) else ""


def render_facebook_pages():
    st.title("Facebook Pages")
    st.caption("Cadastre páginas públicas do Facebook por URL. Esta área aceita apenas páginas Facebook e não perfis pessoais.")
    with st.form("facebook_page_form"):
        form_cols = st.columns(2)
        with form_cols[0]:
            name = st.text_input("Nome da página", key="facebook_page_name")
            url = st.text_input("URL pública da página", placeholder="https://www.facebook.com/suapagina", key="facebook_page_url")
            country_options = [""] + list(COUNTRY_OPTIONS)
            country = st.selectbox("País", country_options, key="facebook_page_country")
        with form_cols[1]:
            description = st.text_area("Descrição", key="facebook_page_description")
            niche = st.text_input("Nicho", key="facebook_page_niche")
            active = st.toggle("Activo", value=True, key="facebook_page_active")
        submitted = st.form_submit_button("Guardar página Facebook", type="primary", width="stretch")
    if submitted:
        normalized_url = url.strip()
        if not name.strip():
            st.error("Informe o nome da página.")
        elif not normalized_url.startswith(("https://www.facebook.com/", "https://facebook.com/", "http://www.facebook.com/", "http://facebook.com/")):
            st.error("Informe uma URL pública válida de uma página Facebook.")
        else:
            existing = [item for item in read_json("channels.json", []) if isinstance(item, dict)]
            duplicate = next((item for item in existing if classify_channel_platform(item) == "facebook" and str(item.get("url") or "").strip().casefold() == normalized_url.casefold()), None)
            if duplicate:
                st.warning("Esta página Facebook já está cadastrada.")
            else:
                page = create_channel(name.strip(), normalized_url, {
                    "platform": "facebook",
                    "social_network": "Facebook Pages",
                    "country": country.strip(),
                    "description": description.strip(),
                    "niche": niche.strip(),
                    "active": bool(active),
                    "metrics_source": "public_url",
                })
                update_channel(page["id"], {"platform": "facebook", "social_network": "Facebook Pages"})
                st.success(f"Página {page['name']} guardada.")
                st.rerun()

    pages = [item for item in read_json("channels.json", []) if isinstance(item, dict) and classify_channel_platform(item) == "facebook"]
    st.divider()
    st.subheader(f"Facebook Pages cadastradas ({len(pages)})")
    if not pages:
        st.info("Nenhuma página Facebook cadastrada.")
        return
    for page in pages:
        page_id = str(page.get("id") or "")
        with st.container(border=True):
            header_cols = st.columns([0.7, 2.75, 1.15, 1.1, 1.0, 1.35, 1.35])
            with header_cols[0]:
                st.markdown("### FB")
            with header_cols[1]:
                page_country = str(page.get("country") or "").strip()
                st.write(f"**{page.get('name', 'Sem nome')}**{f' · {page_country}' if page_country else ''}")
                st.caption(page.get("niche") or "SEM NICHO CONFIGURADO")
                st.caption(page.get("url") or "sem URL")
            with header_cols[2]:
                if page.get("url"):
                    st.link_button("Abrir página", str(page["url"]), type="primary", width="content")
            with header_cols[3]:
                st.metric("País", page_country or "—")
            with header_cols[4]:
                st.metric("Estado", "Activo" if page.get("active", True) else "Inactivo")
            with header_cols[5]:
                st.caption("Facebook Page")
            with header_cols[6]:
                active_value = st.toggle("Activo", value=bool(page.get("active", True)), key=f"facebook_active_{page_id}")
                if active_value != bool(page.get("active", True)):
                    update_channel(page_id, {"active": active_value})
                    st.rerun()
            with st.expander("Detalhes e configuração da página", expanded=False):
                with st.form(f"facebook_page_edit_{page_id}"):
                    edited_name = st.text_input("Nome da página", value=str(page.get("name") or ""))
                    edited_url = st.text_input("URL pública", value=str(page.get("url") or ""))
                    edit_country_options = [""] + list(COUNTRY_OPTIONS)
                    current_page_country = str(page.get("country") or "")
                    edited_country = st.selectbox("País", edit_country_options, index=edit_country_options.index(current_page_country) if current_page_country in edit_country_options else 0)
                    edited_description = st.text_area("Descrição", value=str(page.get("description") or ""))
                    edited_niche = st.text_input("Nicho", value=str(page.get("niche") or ""))
                    save_page = st.form_submit_button("Guardar alterações", type="primary")
                action_cols = st.columns(2)
                with action_cols[0]:
                    if save_page:
                        if not edited_name.strip() or not edited_url.strip().startswith(("https://www.facebook.com/", "https://facebook.com/", "http://www.facebook.com/", "http://facebook.com/")):
                            st.error("Informe o nome e uma URL pública válida de uma página Facebook.")
                        else:
                            update_channel(page_id, {"name": edited_name.strip(), "url": edited_url.strip(), "country": edited_country.strip(), "description": edited_description.strip(), "niche": edited_niche.strip()})
                            st.success("Página Facebook actualizada.")
                            st.rerun()
                with action_cols[1]:
                    if st.button("Apagar", key=f"facebook_delete_{page_id}"):
                        delete_channel(page_id)
                        st.success("Página Facebook apagada.")
                        st.rerun()


def render_channels():
    st.title("Canais Youtube")
    st.caption("Escolha entre importar dados públicos do YouTube ou preencher o canal manualmente.")
    settings = read_json("settings.json", {})
    youtube = YouTubeAdapter(settings=settings)
    youtube_accounts = [account for account in settings.get("youtube_batch_accounts", []) if isinstance(account, dict) and account.get("id")]
    youtube_account_ids = [""] + [str(account["id"]) for account in youtube_accounts]
    youtube_account_labels = {"": "Sem conta Google associada"}
    youtube_account_labels.update({str(account["id"]): f"{account.get('label', 'Canais YouTube')} — {account.get('email', 'sem e-mail')}" for account in youtube_accounts})
    youtube_accounts_by_id = {str(account["id"]): account for account in youtube_accounts}
    import_tab, spreadsheet_tab, batch_tab, manual_tab = render_localized_tabs(["Importar do YouTube", "Canais em lote Planilha", "Canais em lote gmail", "Cadastro manual"])

    with import_tab:
        st.caption("A pesquisa pública funciona sem API Key. A Data API é opcional e fica disponível numa opção separada para métricas oficiais.")
        lookup_cols = st.columns([2.2, 1.0], gap="medium")
        with lookup_cols[0]:
            source = st.text_input("URL, handle ou ID do canal", placeholder="https://youtube.com/@seucanal", key="youtube_channel_source")
        with lookup_cols[1]:
            lookup_mode = st.selectbox(
                "Método de consulta",
                ["Página pública — sem API Key", "YouTube Data API — API Key opcional"],
                key="youtube_channel_lookup_mode",
            )
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("Buscar no YouTube", type="primary", width="stretch", key="youtube_channel_lookup"):
                search_source = str(source or "").strip()
                st.session_state.pop("yt_import", None)
                st.session_state.pop("yt_message", None)
                st.session_state.pop("yt_ok", None)
                if not search_source:
                    st.session_state["yt_message"] = "Introduza um URL youtube.com, um handle @nome ou um ID de canal UC... antes de pesquisar."
                    st.session_state["yt_ok"] = False
                else:
                    try:
                        with st.spinner("A pesquisar o canal no YouTube…"):
                            if lookup_mode.startswith("Página pública"):
                                result = youtube.fetch_channel_public(search_source)
                            elif not youtube.api_key:
                                result = IntegrationResult(False, "A YouTube Data API Key não está configurada. Escolha a opção Página pública — sem API Key ou configure a chave em Configurações > Contas Google.", {"status": "api_key_not_configured"})
                            else:
                                result = youtube.fetch_channel(search_source)
                        st.session_state["yt_import"] = result.data if isinstance(result.data, dict) else {}
                        st.session_state["yt_message"] = result.message
                        st.session_state["yt_ok"] = result.ok
                    except Exception as exc:
                        st.session_state["yt_import"] = {}
                        st.session_state["yt_message"] = f"A pesquisa do YouTube falhou ({type(exc).__name__}). Confirme o URL/handle e tente novamente. Detalhe: {str(exc)[:240]}"
                        st.session_state["yt_ok"] = False
        with col2:
            if st.button("Limpar importação", width="stretch", key="youtube_channel_clear"):
                for key in ("yt_import", "yt_message", "yt_ok"):
                    st.session_state.pop(key, None)
                st.rerun()
        if st.session_state.get("yt_message"):
            (st.success if st.session_state.get("yt_ok") else st.warning)(st.session_state["yt_message"])
        imported = st.session_state.get("yt_import", {}) if st.session_state.get("yt_ok") else {}
        blueprint_items = blueprint_catalog()
        blueprint_ids = [item[0] for item in blueprint_items]
        blueprint_labels = {item[0]: item[1] for item in blueprint_items}
        imported_blueprint = imported.get("default_blueprint_id") or imported.get("blueprint_id", "")
        if imported_blueprint not in blueprint_ids:
            blueprint_ids.append(imported_blueprint)
            blueprint_labels[imported_blueprint] = imported_blueprint or "Sem Blueprint padrão"
        if imported:
            st.caption("Dados encontrados. Reveja ou edite os campos antes de guardar.")
            with st.form("channel_import_form"):
                name = st.text_input("Nome do canal", value=imported.get("name", ""), key="yt_import_name")
                url = st.text_input("URL", value=imported.get("url", source if source.startswith("http") else ""), key="yt_import_url")
                handle = st.text_input("Handle", value=imported.get("handle", ""), key="yt_import_handle")
                language = st.selectbox("Idioma do roteiro", VIDEO_LANGUAGE_SELECTION_OPTIONS, index=VIDEO_LANGUAGE_SELECTION_OPTIONS.index(normalize_video_language(imported.get("language") or "pt")) if normalize_video_language(imported.get("language") or "pt") in VIDEO_LANGUAGE_SELECTION_OPTIONS else 0, format_func=video_language_label, key="yt_import_language")
                import_country_options = [""] + list(COUNTRY_OPTIONS)
                import_country = st.selectbox("País", import_country_options, index=import_country_options.index(str(imported.get("country") or "")) if str(imported.get("country") or "") in import_country_options else 0, key="yt_import_country")
                style = st.selectbox("Fonte do vídeo", WIDE_STYLE_OPTIONS, index=0, key="yt_import_style")
                video_aspect_ratio = st.selectbox("Proporção do vídeo", CHANNEL_ASPECT_RATIO_OPTIONS, key="yt_import_aspect_ratio")
                blueprint = st.selectbox("Blueprint Padrão", blueprint_ids, index=blueprint_ids.index(imported_blueprint) if imported_blueprint in blueprint_ids else 0, format_func=lambda item: blueprint_labels.get(item, item or "Sem Blueprint padrão"), key="yt_import_blueprint")
                voice_options = voice_catalog(imported.get("default_voice") or imported.get("voice", ""))
                current_voice = imported.get("default_voice") or imported.get("voice", "")
                voice = st.selectbox("Narrador/Voz Padrão", voice_options, index=voice_options.index(current_voice) if current_voice in voice_options else 0, format_func=lambda item: item or "Sem voz padrão", key="yt_import_voice")
                imported_account_id = str(imported.get("google_account_id", ""))
                google_account_id = st.selectbox("Conta Google para Upload directo", youtube_account_ids, index=youtube_account_ids.index(imported_account_id) if imported_account_id in youtube_account_ids else 0, format_func=lambda item: youtube_account_labels.get(item, item), key="yt_import_google_account_id")
                st.caption("O DELEGATED_SESSION_ID é lido exclusivamente do documento JSON da conta Google associada.")
                automation_on = st.toggle("Automação ON", value=bool(imported.get("automation_on", False)), key="yt_import_automation_on")
                automation_time = st.text_input("Horário diário (HH:MM)", value=imported.get("automation_time", "00:00"), key="yt_import_automation_time")
                description = st.text_area("Descrição", value=imported.get("description", ""), key="yt_import_description")
                niche = st.text_input("Nicho", value=imported.get("niche", ""), key="yt_import_niche")
                metrics = st.columns(3)
                with metrics[0]: subscriber_count = st.number_input("Inscritos", min_value=0, value=int(imported.get("subscriber_count") or 0), key="yt_import_subscribers")
                with metrics[1]: video_count = st.number_input("Vídeos", min_value=0, value=int(imported.get("video_count") or 0), key="yt_import_videos")
                with metrics[2]: view_count = st.number_input("Visualizações", min_value=0, value=int(imported.get("view_count") or 0), key="yt_import_views")
                submitted = st.form_submit_button("Guardar canal importado", type="primary")
                if submitted:
                    if not name.strip():
                        st.error("Informe o nome do canal antes de guardar.")
                    elif not valid_hhmm(automation_time):
                        st.error("O horário diário deve estar no formato HH:MM, por exemplo 08:30.")
                    else:
                        metadata = {
                            **imported,
                            "handle": handle.strip(),
                            "description": description.strip(),
                            "niche": niche.strip(),
                            "reference_channels": [item.strip() for item in re.split(r"[,|]", niche) if item.strip()],
                            "language": language, "country": import_country.strip(),
                            "style_wide": channel_video_source_storage(style), "video_aspect_ratio": video_aspect_ratio, "format": "wide",
                            "blueprint_id": blueprint.strip(),
                            "default_blueprint_id": blueprint.strip(),
                            "default_voice": voice.strip(),
                            "voice": voice.strip(),
                            "google_account_id": google_account_id.strip(),
                            "google_account_email": str(youtube_accounts_by_id.get(google_account_id, {}).get("email", "")),
                            "automation_on": bool(automation_on),
                            "automation_time": automation_time.strip() if valid_hhmm(automation_time) else "00:00",
                            "subscriber_count": int(subscriber_count) or None,
                            "video_count": int(video_count) or None,
                            "view_count": int(view_count) or None,
                            "metrics_source": imported.get("metrics_source", "youtube_public_page"),
                            "platform": "youtube",
                        }
                        channel = create_channel(name, url, metadata)
                        st.success(f"Canal {channel['name']} guardado.")
                        st.rerun()
        else:
            st.info("Introduza um URL, handle ou ID e clique em Buscar no YouTube. Não é necessária API Key na opção pública.")

    with spreadsheet_tab:
        st.caption("Carregue uma planilha Excel (.xlsx ou .xls). Os cabeçalhos e valores são interpretados, normalizados e associados aos cadastros existentes antes da gravação.")
        download_col, help_col = st.columns([1.35, 2.65])
        with download_col:
            st.download_button(
                "Baixar planilha modelo",
                data=build_channel_template_xlsx(),
                file_name="modelo_canais_youtube.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
                key="download_channel_spreadsheet_template",
            )
        with help_col:
            st.caption("O modelo inclui as 15 colunas aceitas. Deixe campos não utilizados vazios; a Descrição será pesquisada publicamente pelo handle, URL ou nome quando estiver vazia.")

        uploaded_sheet = st.file_uploader(
            "Upload da planilha de canais",
            type=["xlsx", "xls"],
            key="channel_spreadsheet_upload",
            help="Apenas a primeira aba do arquivo será importada. Linhas sem URL, nome e handle são ignoradas.",
        )
        if st.button("Ler e preparar planilha", type="primary", width="stretch", key="read_channel_spreadsheet"):
            if uploaded_sheet is None:
                st.error("Selecione um arquivo Excel antes de continuar.")
            else:
                try:
                    spreadsheet_rows, spreadsheet_warnings = parse_channel_workbook(uploaded_sheet.getvalue(), uploaded_sheet.name)
                    st.session_state["channel_spreadsheet_rows"] = spreadsheet_rows
                    st.session_state["channel_spreadsheet_warnings"] = spreadsheet_warnings
                    st.session_state.pop("channel_spreadsheet_result", None)
                    if spreadsheet_rows:
                        st.success(f"{len(spreadsheet_rows)} linha(s) de canal preparada(s) para revisão.")
                    else:
                        st.warning("A planilha não contém linhas com URL, nome ou handle de canal.")
                except ValueError as exc:
                    st.session_state.pop("channel_spreadsheet_rows", None)
                    st.error(str(exc))

        spreadsheet_warnings = st.session_state.get("channel_spreadsheet_warnings", [])
        for spreadsheet_warning in spreadsheet_warnings:
            st.warning(spreadsheet_warning)
        spreadsheet_result = st.session_state.get("channel_spreadsheet_result")
        if isinstance(spreadsheet_result, dict):
            if spreadsheet_result.get("created"):
                st.success(f"Canais cadastrados: {', '.join(spreadsheet_result['created'])}")
            if spreadsheet_result.get("skipped"):
                st.info(f"Já cadastrados e não duplicados: {', '.join(spreadsheet_result['skipped'])}")
            for spreadsheet_error in spreadsheet_result.get("errors", []):
                st.warning(spreadsheet_error)

        spreadsheet_rows = st.session_state.get("channel_spreadsheet_rows", [])
        if spreadsheet_rows:
            blueprint_items = blueprint_catalog()
            voice_options = voice_catalog()
            spreadsheet_accounts = [account for account in settings.get("youtube_batch_accounts", []) if isinstance(account, dict) and account.get("id")]
            existing_spreadsheet_channels = [channel for channel in read_json("channels.json", []) if isinstance(channel, dict)]
            preview_rows = []
            for row in spreadsheet_rows:
                resolved_blueprint = resolve_blueprint(row.get("blueprint"), blueprint_items)
                resolved_voice = resolve_voice(row.get("voice"), voice_options)
                resolved_account, _ = resolve_google_account(row.get("google_account"), spreadsheet_accounts)
                preview_rows.append({
                    "Linha": row.get("_source_row", "—"),
                    "Nome": row.get("name") or "—",
                    "Handle": row.get("handle") or "—",
                    "Blueprint interpretado": resolved_blueprint or "—",
                    "Voz interpretada": resolved_voice or "—",
                    "Idioma": language_code(row.get("language")) if row.get("language") else "—",
                    "Descrição": "Preencher via YouTube" if not row.get("description") else "Da planilha",
                    "Estado": "Já cadastrado" if find_duplicate_channel({"name": row.get("name"), "handle": row.get("handle"), "url": row.get("url")}, existing_spreadsheet_channels) else "Novo",
                })
            st.dataframe(preview_rows, width="stretch", hide_index=True, height=min(420, 86 + 38 * len(preview_rows)))
            st.caption("Blueprints e vozes são resolvidos pelos catálogos atuais. Por exemplo, `finanças`, `blueprint_finanças` e `Blueprint Canal Finanças` apontam para o mesmo Blueprint quando ele existe.")
            if st.button("Cadastrar canais da planilha", type="primary", width="stretch", key="import_channel_spreadsheet"):
                created_names: list[str] = []
                skipped_names: list[str] = []
                spreadsheet_errors: list[str] = []
                current_channels = list(existing_spreadsheet_channels)
                for row in spreadsheet_rows:
                    row_label = str(row.get("name") or row.get("handle") or row.get("url") or f"Linha {row.get('_source_row', '?')}")
                    candidate = {"name": row.get("name", ""), "handle": row.get("handle", ""), "url": row.get("url", "")}
                    duplicate = find_duplicate_channel(candidate, current_channels)
                    if duplicate:
                        skipped_names.append(f"{row_label} (linha {row.get('_source_row', '?')})")
                        continue
                    automation_time = str(row.get("automation_time") or "").strip()
                    if automation_time and not valid_hhmm(automation_time):
                        spreadsheet_errors.append(f"{row_label} (linha {row.get('_source_row', '?')}): horário inválido; a linha não foi cadastrada.")
                        continue
                    try:
                        resolved_blueprint = resolve_blueprint(row.get("blueprint"), blueprint_items)
                        resolved_voice = resolve_voice(row.get("voice"), voice_options)
                        google_account_id, google_account_email = resolve_google_account(row.get("google_account"), spreadsheet_accounts)
                        description = str(row.get("description") or "").strip()
                        description_status = "da planilha"
                        if not description:
                            lookup_source = str(row.get("handle") or row.get("url") or row.get("name") or "").strip()
                            if lookup_source:
                                description_result = youtube.fetch_channel_public(lookup_source)
                                description = str(description_result.data.get("description") or "").strip()
                                if not description and youtube.api_key:
                                    api_description_result = youtube.fetch_channel(lookup_source)
                                    description = str(api_description_result.data.get("description") or "").strip()
                                description_status = "buscada no YouTube" if description else "não encontrada"
                        style_value = str(row.get("style_wide") or "").strip()
                        metadata = {
                            "handle": str(row.get("handle") or "").strip(),
                            "description": description,
                            "niche": str(row.get("niche") or "").strip(),
                            "reference_channels": [item.strip() for item in re.split(r"[,|]", str(row.get("niche") or "")) if item.strip()],
                            "language": language_code(row.get("language")) if row.get("language") else "",
                            "style_wide": style_value,
                            "blueprint_id": resolved_blueprint,
                            "default_blueprint_id": resolved_blueprint,
                            "default_voice": resolved_voice,
                            "voice": resolved_voice,
                            "google_account_id": google_account_id,
                            "google_account_email": google_account_email,
                            "automation_on": bool(row.get("automation_on")) if row.get("automation_on") is not None else False,
                            "automation_time": automation_time,
                            "delegated_session_id": str(row.get("delegated_session_id") or "").strip(),
                            "active": bool(row.get("active")) if row.get("active") is not None else True,
                            "default_video_duration_minutes": row.get("duration_minutes"),
                            "metrics_source": "spreadsheet",
                            "import_source": "spreadsheet",
                            "description_source": description_status,
                            "platform": "youtube",
                        }
                        created = create_channel(str(row.get("name") or "").strip(), str(row.get("url") or "").strip(), metadata)
                        current_channels.append(created)
                        created_names.append(row_label)
                    except Exception as exc:
                        spreadsheet_errors.append(f"{row_label} (linha {row.get('_source_row', '?')}): {exc}")
                st.session_state["channel_spreadsheet_result"] = {"created": created_names, "skipped": skipped_names, "errors": spreadsheet_errors}
                st.session_state.pop("channel_spreadsheet_rows", None)
                st.rerun()

    with batch_tab:
        st.caption("Esta subaba usa a conta Google/YouTube seleccionada para listar os canais que ela gere. Não lê a caixa Gmail e não usa e-mails como pesquisa pública.")
        accounts = [account for account in settings.get("youtube_batch_accounts", []) if isinstance(account, dict) and account.get("id")]
        if not accounts:
            st.info("Nenhuma conta Google/YouTube disponível para a lista em lote; a lista permanece vazia.")
        else:
            account_ids = [str(account["id"]) for account in accounts]
            account_labels = {str(account["id"]): f"{account.get('email', 'Conta Google')} — {account.get('label', 'Canais YouTube')}" for account in accounts}
            default_account_id = str(settings.get("youtube_batch_selected_account_id") or account_ids[0])
            if default_account_id not in account_ids:
                default_account_id = account_ids[0]
            selected_account_id = st.selectbox("Conta Google/YouTube", account_ids, index=account_ids.index(default_account_id), format_func=lambda item: account_labels.get(item, item), key="batch_selected_account_id")
            selected_account = next(account for account in accounts if str(account["id"]) == selected_account_id)
            account_status = youtube_batch_account_status(selected_account, STORAGE)
            (st.success if account_status.ok else st.warning)(account_status.message)
            auth_cols = st.columns([1, 2])
            with auth_cols[0]:
                if st.button("Autorizar conta Google", type="secondary", width="stretch", key="batch_authorize_account"):
                    result = authorize_youtube_batch_account(selected_account, STORAGE)
                    (st.success if result.ok else st.error)(result.message)
                    if result.ok:
                        st.rerun()
            with auth_cols[1]:
                st.caption("A autorização é feita no browser do sistema e fica guardada separadamente para esta conta.")
            batch_key = f"youtube_batch_channels_{selected_account_id}"
            if st.button("Listar canais desta conta", type="primary", width="stretch", key="batch_list_channels"):
                result = list_youtube_batch_channels(selected_account, STORAGE)
                st.session_state[batch_key] = result.data.get("channels", []) if result.ok else []
                st.session_state[f"{batch_key}_message"] = result.message
                st.session_state[f"{batch_key}_ok"] = result.ok
            if st.session_state.get(f"{batch_key}_message"):
                (st.success if st.session_state.get(f"{batch_key}_ok") else st.error)(st.session_state[f"{batch_key}_message"])
            listed_channels = st.session_state.get(batch_key, [])
            if listed_channels:
                channel_by_id = {str(channel.get("youtube_channel_id")): channel for channel in listed_channels if channel.get("youtube_channel_id")}
                channel_labels = {channel_id: f"{channel.get('name', channel_id)} — {channel.get('handle') or channel_id}" for channel_id, channel in channel_by_id.items()}
                existing_channels = read_json("channels.json", [])
                existing_ids = {str(channel.get("youtube_channel_id")) for channel in existing_channels if channel.get("youtube_channel_id")}
                existing_count = sum(1 for channel_id in channel_by_id if channel_id in existing_ids)
                st.caption(f"{len(listed_channels)} canal(is) listado(s); {existing_count} já cadastrado(s). A API devolveu a lista da conta autenticada, não uma caixa Gmail.")
                blueprint_items = blueprint_catalog()
                blueprint_ids = [item[0] for item in blueprint_items]
                blueprint_labels = {item[0]: item[1] for item in blueprint_items}
                voice_options = voice_catalog()
                with st.form("batch_channel_import_form"):
                    selected_channel_ids = st.multiselect("Canais a cadastrar", list(channel_by_id), default=list(channel_by_id), format_func=lambda item: channel_labels.get(item, item), key="batch_channel_ids")
                    defaults_cols = st.columns(4)
                    with defaults_cols[0]:
                        batch_blueprint = st.selectbox("Blueprint padrão", blueprint_ids, format_func=lambda item: blueprint_labels.get(item, item or "Sem Blueprint padrão"), key="batch_channel_blueprint")
                    with defaults_cols[1]:
                        batch_voice = st.selectbox("Voz padrão", voice_options, format_func=lambda item: item or "Sem voz padrão", key="batch_channel_voice")
                    with defaults_cols[2]:
                        batch_language = st.selectbox("Idioma", list(LANGUAGE_CODES), index=list(LANGUAGE_CODES).index("pt"), format_func=language_label, key="batch_channel_language")
                    with defaults_cols[3]:
                        batch_style = st.selectbox("Estilo wide", ["Pexels/Pixabay", "full_ia", "Apenas Música"], key="batch_channel_style")
                    import_selected = st.form_submit_button("Cadastrar canais seleccionados", type="primary", width="stretch")
                if import_selected:
                    created_names = []
                    skipped_names = []
                    failed_names = []
                    style_value = {"Pexels/Pixabay": "pexels", "full_ia": "full_ia", "Apenas Música": "music"}.get(batch_style, batch_style)
                    for channel_id in selected_channel_ids:
                        data = channel_by_id[channel_id]
                        if channel_id in existing_ids:
                            skipped_names.append(data.get("name", channel_id))
                            continue
                        try:
                            create_channel(data.get("name", channel_id), data.get("url", ""), {
                                **data,
                                "youtube_channel_id": channel_id,
                                "google_account_id": str(selected_account.get("id", "")),
                                "google_account_email": str(selected_account.get("email", "")),
                                "blueprint_id": batch_blueprint.strip(),
                                "default_blueprint_id": batch_blueprint.strip(),
                                "default_voice": batch_voice.strip(),
                                "voice": batch_voice.strip(),
                                "language": batch_language,
                                "style_wide": style_value,
                                "last_youtube_sync": now(),
                                "platform": "youtube",
                            })
                            created_names.append(data.get("name", channel_id))
                        except Exception as exc:
                            failed_names.append(f"{data.get('name', channel_id)}: {exc}")
                    if created_names:
                        st.success(f"Canais cadastrados: {', '.join(created_names)}")
                    if skipped_names:
                        st.info(f"Já existentes e não duplicados: {', '.join(skipped_names)}")
                    if failed_names:
                        st.error(f"Falhas: {'; '.join(failed_names)}")

    with manual_tab:
        st.caption("Este fluxo não consulta o YouTube e não exige API Key. Preencha os dados que quiser e guarde o canal localmente.")
        with st.form("channel_manual_form"):
            name = st.text_input("Nome do canal", key="manual_channel_name")
            url = st.text_input("URL do canal", placeholder="https://youtube.com/@seucanal", key="manual_channel_url")
            handle = st.text_input("Handle", placeholder="@seucanal", key="manual_channel_handle")
            description = st.text_area("Descrição", key="manual_channel_description")
            niche = st.text_input("Nicho", placeholder="Ex.: História militar, mistérios, ciência", key="manual_channel_niche")
            language = st.selectbox("Idioma", list(LANGUAGE_CODES), index=list(LANGUAGE_CODES).index("pt"), format_func=language_label, key="manual_channel_language")
            manual_country_options = [""] + list(COUNTRY_OPTIONS)
            manual_country = st.selectbox("País", manual_country_options, key="manual_channel_country")
            style = st.selectbox("Estilo wide", ["Pexels/Pixabay", "full_ia", "Apenas Música"], index=0, key="manual_channel_style")
            manual_blueprint_items = blueprint_catalog()
            manual_blueprint_ids = [item[0] for item in manual_blueprint_items]
            manual_blueprint_labels = {item[0]: item[1] for item in manual_blueprint_items}
            blueprint = st.selectbox("Blueprint Padrão", manual_blueprint_ids, format_func=lambda item: manual_blueprint_labels.get(item, item or "Sem Blueprint padrão"), key="manual_channel_blueprint")
            voice_options = voice_catalog()
            voice = st.selectbox("Narrador/Voz Padrão", voice_options, format_func=lambda item: item or "Sem voz padrão", key="manual_channel_voice")
            google_account_id = st.selectbox("Conta Google para Upload directo", youtube_account_ids, format_func=lambda item: youtube_account_labels.get(item, item), key="manual_channel_google_account_id")
            st.caption("O DELEGATED_SESSION_ID é lido exclusivamente do documento JSON da conta Google associada.")
            automation_on = st.toggle("Automação ON", value=False, key="manual_channel_automation_on")
            automation_time = st.text_input("Horário diário (HH:MM)", value="00:00", key="manual_channel_automation_time")
            thumbnail_url = st.text_input("URL da imagem do canal", key="manual_channel_thumbnail")
            metrics = st.columns(3)
            with metrics[0]: subscriber_count = st.number_input("Inscritos", min_value=0, value=0, key="manual_channel_subscribers")
            with metrics[1]: video_count = st.number_input("Vídeos", min_value=0, value=0, key="manual_channel_videos")
            with metrics[2]: view_count = st.number_input("Visualizações", min_value=0, value=0, key="manual_channel_views")
            submitted = st.form_submit_button("Guardar canal manual", type="primary")
            if submitted:
                if not name.strip():
                    st.error("Informe o nome do canal.")
                elif not valid_hhmm(automation_time):
                    st.error("O horário diário deve estar no formato HH:MM, por exemplo 08:30.")
                else:
                    channel = create_channel(name, url, {
                        "handle": handle.strip(),
                        "description": description.strip(),
                        "niche": niche.strip(),
                        "reference_channels": [item.strip() for item in re.split(r"[,|]", niche) if item.strip()],
                        "language": language, "country": manual_country.strip(),
                        "style_wide": {"Pexels/Pixabay": "pexels", "full_ia": "full_ia", "Apenas Música": "music"}.get(style, style),
                        "blueprint_id": blueprint.strip(),
                        "default_blueprint_id": blueprint.strip(),
                        "default_voice": voice.strip(),
                        "voice": voice.strip(),
                        "google_account_id": google_account_id.strip(),
                        "google_account_email": str(youtube_accounts_by_id.get(google_account_id, {}).get("email", "")),
                        "automation_on": bool(automation_on),
                        "automation_time": automation_time.strip(),
                        "thumbnail_url": thumbnail_url.strip(),
                        "subscriber_count": int(subscriber_count) or None,
                        "video_count": int(video_count) or None,
                        "view_count": int(view_count) or None,
                        "metrics_source": "manual",
                        "platform": "youtube",
                    })
                    st.success(f"Canal {channel['name']} guardado manualmente.")
                    st.rerun()

    channels = [channel for channel in read_json("channels.json", []) if is_youtube_channel_record(channel)]
    st.divider()
    st.subheader(f"Canais Youtube cadastrados ({len(channels)})")
    filter_cols = st.columns([1, 1], gap="small")
    with filter_cols[0]:
        youtube_channel_search = st.text_input(
            "Pesquisar nomes dos canais YouTube",
            key="youtube_registered_channels_search",
            placeholder="Digite o nome do canal",
        )
    with filter_cols[1]:
        youtube_country_options = [""] + list(COUNTRY_OPTIONS)
        youtube_country_filter = st.selectbox(
            "Filtrar por País",
            youtube_country_options,
            format_func=lambda value: value or "Todos os países",
            key="youtube_registered_country_filter",
        )
        if st.button("Filtrar", type="primary", width="content", key="youtube_registered_country_filter_apply"):
            st.session_state["youtube_registered_country_filter_applied"] = youtube_country_filter
    applied_country = str(st.session_state.get("youtube_registered_country_filter_applied") or "").strip()
    visible_registered_channels = [
        channel for channel in channels
        if not youtube_channel_search.strip()
        or youtube_channel_search.strip().casefold() in str(channel.get("name") or "").casefold()
    ]
    visible_registered_channels = [
        channel for channel in visible_registered_channels
        if not applied_country or str(channel.get("country") or "").strip() == applied_country
    ]
    if not channels:
        st.info("Nenhum canal YouTube cadastrado.")
        return
    if not visible_registered_channels:
        st.info("Nenhum canal YouTube corresponde à pesquisa.")
        return
    for channel in visible_registered_channels:
        channel_id = str(channel["id"])
        edit_key = f"edit_channel_{channel_id}"
        with st.container(border=True):
            header_cols = st.columns([0.7, 2.75, 1.15, 1.1, 1.0, 1.35, 1.35])
            channel_url = str(channel.get("url") or "").strip()
            if not channel_url:
                channel_id_or_handle = str(channel.get("youtube_channel_id") or channel.get("youtube_id") or channel.get("handle") or "").strip()
                if channel_id_or_handle:
                    if channel_id_or_handle.startswith("http"):
                        channel_url = channel_id_or_handle
                    elif channel_id_or_handle.startswith("UC"):
                        channel_url = f"https://www.youtube.com/channel/{channel_id_or_handle}"
                    elif channel_id_or_handle.startswith(("@", "channel/")):
                        channel_url = f"https://www.youtube.com/{channel_id_or_handle}"
                    else:
                        channel_url = f"https://www.youtube.com/@{channel_id_or_handle}"
            with header_cols[0]:
                if channel.get("thumbnail_url"):
                    st.image(channel["thumbnail_url"], width=64)
                else:
                    st.markdown("### YT")
            with header_cols[1]:
                country_label = str(channel.get("country") or "").strip()
                st.write(f"**{channel.get('name', 'Sem nome')}**{f' · {country_label}' if country_label else ''}")
                st.caption(channel_niche_label(channel))
                st.caption(f"{channel.get('handle') or channel.get('url') or 'sem URL'} · {channel.get('metrics_source', 'manual')}")
            with header_cols[2]:
                if channel_url:
                    st.link_button("Abrir canal", channel_url, type="primary", width="content")
            with header_cols[3]:
                st.metric("Inscritos", _format_channel_count(channel.get("subscriber_count")))
            with header_cols[4]:
                st.metric("Vídeos", _format_channel_count(channel.get("video_count")))
            with header_cols[5]:
                st.metric("Visualizações", _format_channel_count(channel.get("view_count")))
            with header_cols[6]:
                if st.button("↻", key=f"refresh_youtube_metrics_{channel_id}", help="Actualizar Inscritos, Vídeos e Visualizações", width="stretch"):
                    with st.spinner("A actualizar métricas YouTube…"):
                        refreshed, message = _refresh_youtube_channel_metrics(channel, youtube)
                    (st.success if refreshed else st.warning)(message)
                    if refreshed:
                        st.rerun()
                active = st.toggle("Activo", value=channel.get("active", True), key=f"active_{channel_id}")
                if active != channel.get("active"):
                    update_channel(channel_id, {"active": active})
                    st.rerun()
                delete_key = f"delete_pending_{channel_id}"
            with st.expander("Detalhes e configuração do canal", expanded=False):
                calculated_time, calculated_source, calculated_words = _channel_average_video_time(channel)
                with st.expander("Tempo Medio de Video", expanded=False):
                    average_video_time = st.text_input("Tempo Medio de Video", value=channel_video_time_value(channel), key=f"youtube_channel_average_video_time_{channel_id}", help=f"Referência: {calculated_words or 0} palavras · {calculated_source}.")
                    if st.button("Guardar Tempo Medio de Video", key=f"save_youtube_channel_average_video_time_{channel_id}", type="primary", width="stretch"):
                        if not valid_hhmm(average_video_time):
                            st.error("Use o formato MM:SS, por exemplo 12:00.")
                        else:
                            update_channel(channel_id, {"average_video_time": average_video_time.strip() or DEFAULT_AVERAGE_VIDEO_TIME, "average_video_word_count": words_from_channel_time(average_video_time)})
                            st.success("Tempo médio do canal YouTube guardado.")
                            st.rerun()
                if st.session_state.get(edit_key):
                    render_channel_edit_form(channel, youtube_account_ids, youtube_account_labels, youtube_accounts_by_id)
                else:
                    summary = channel_blueprint_summary(channel)
                    render_channel_thumbnail_blueprint_panel(channel, compact=True)
                    channel_language = language_label(channel.get("language") or "pt")
                    block_cols = st.columns(4, gap="small")
                    with block_cols[0]:
                        st.markdown(f"**Blueprint Padrão**\n\n{summary['name']}")
                    with block_cols[1]:
                        st.markdown(f"**Nicho**\n\n{channel_niche_label(channel)}")
                    with block_cols[2]:
                        st.markdown(f"**Narrador/Voz Padrão**\n\n{summary['voice'] or 'Sem voz padrão'}")
                    with block_cols[3]:
                        st.markdown(f"**Idioma**\n\n{channel_language}")

                action_cols = st.columns(2)
                with action_cols[0]:
                    if st.button("Editar", key=f"edit_channel_button_{channel_id}", type="primary", width="stretch"):
                        st.session_state[edit_key] = True
                        st.rerun()
                with action_cols[1]:
                    if st.button("Apagar", key=f"delete_{channel_id}", width="stretch"):
                        st.session_state[delete_key] = True
                        st.rerun()
                if st.session_state.get(delete_key):
                    st.warning("Apagar este canal YouTube e os dados locais associados?")
                    confirm_cols = st.columns(2)
                    with confirm_cols[0]:
                        if st.button("Confirmar apagar", type="primary", key=f"confirm_delete_{channel_id}"):
                            removed = delete_channel(channel_id)
                            st.session_state.pop(delete_key, None)
                            if removed is None:
                                st.error("O canal já não existe ou não pôde ser removido.")
                            else:
                                st.success(f"Canal {removed.get('name') or channel_id} apagado.")
                                st.rerun()
                    with confirm_cols[1]:
                        if st.button("Cancelar", key=f"cancel_delete_{channel_id}"):
                            st.session_state.pop(delete_key, None)
                            st.rerun()
                channel_account_ids = list(youtube_account_ids)
                current_channel_account_id = str(channel.get("google_account_id", ""))
                if current_channel_account_id and current_channel_account_id not in channel_account_ids:
                    channel_account_ids.append(current_channel_account_id)
                    youtube_account_labels[current_channel_account_id] = "Conta Google não configurada"
                with st.expander("Upload directo — documento da conta deste canal", expanded=False):
                    st.caption("O DELEGATED_SESSION_ID é individual deste canal. Guarde-o aqui; o valor fica no registo local do canal e não é copiado para o documento JSON partilhado da conta Google.")
                    with st.form(f"channel_direct_credentials_{channel_id}"):
                        channel_account_id = st.selectbox("Conta Google do documento deste canal", channel_account_ids, index=channel_account_ids.index(current_channel_account_id) if current_channel_account_id in channel_account_ids else 0, format_func=lambda item: youtube_account_labels.get(item, item or "Sem conta Google associada"), key=f"channel_account_{channel_id}")
                        channel_delegated_session_id = st.text_input(
                            "DELEGATED_SESSION_ID deste canal",
                            value=str(channel.get("delegated_session_id") or ""),
                            type="password",
                            key=f"channel_delegated_session_id_{channel_id}",
                            help="Identificador individual usado pelo Upload directo deste canal. Não é partilhado com outros canais nem mostrado nos diagnósticos.",
                        )
                        save_channel_direct_credentials = st.form_submit_button("Guardar conta Google e DELEGATED_SESSION_ID", type="primary", width="stretch")
                    selected_channel_account = youtube_accounts_by_id.get(channel_account_id)
                    if selected_channel_account:
                        selected_account_status = document_status(STORAGE, selected_channel_account, channel, settings, channels)
                        if selected_account_status["ready"]:
                            st.success("Documento da conta completo e DELEGATED_SESSION_ID deste canal encontrado no documento.")
                        elif not selected_account_status["document_exists"]:
                            st.warning("A conta seleccionada ainda não tem documento JSON de credenciais.")
                        else:
                            missing_channel_parts = list(selected_account_status["missing_cookies"])
                            if not selected_account_status["has_session_info"]:
                                missing_channel_parts.append("sessionInfo")
                            if not selected_account_status["has_innertube_api_key"]:
                                missing_channel_parts.append("INNERTUBE_API_KEY")
                            if not selected_account_status["has_delegated_session_id"]:
                                missing_channel_parts.append("DELEGATED_SESSION_ID deste canal")
                            st.warning(f"Documento incompleto: {', '.join(missing_channel_parts)}")
                    else:
                        st.info("Associe este canal a uma conta Google para validar o documento de credenciais.")
                    if save_channel_direct_credentials:
                        update_channel(
                            channel_id,
                            {
                                "google_account_id": channel_account_id.strip(),
                                "google_account_email": str(youtube_accounts_by_id.get(channel_account_id, {}).get("email", "")),
                                "delegated_session_id": channel_delegated_session_id.strip(),
                            },
                        )
                        st.success("Conta Google e DELEGATED_SESSION_ID individual do canal guardados.")
                        st.rerun()

                render_channel_video_defaults(channel)
                render_channel_audio_subtitle_defaults(channel)
                render_channel_videos(channel)


def _saved_video_draft_records() -> list[dict[str, Any]]:
    """Return saved video scripts and local pipeline drafts in one selectable list."""
    records: list[dict[str, Any]] = []
    for source, source_records in (("history", list_script_documents()), ("draft", list_drafts())):
        for raw_record in source_records:
            if not isinstance(raw_record, dict):
                continue
            document_type = str(raw_record.get("document_type") or "video_script").strip()
            draft_kind = str(raw_record.get("draft_kind") or "").strip()
            if document_type not in {"", "video_script"}:
                continue
            if source == "draft" and draft_kind not in {"", "video", "script"}:
                continue
            if source == "draft" and not draft_kind and str(raw_record.get("page") or "") == "Criação de Músicas":
                continue
            if source == "history":
                try:
                    content = read_script_document(raw_record)
                except (OSError, UnicodeError):
                    content = ""
            else:
                content = str(raw_record.get("content") or "")
            record = normalise_saved_script({**raw_record, "source": source, "source_label": "Histórico guardado" if source == "history" else "Rascunho local"}, content)
            record["resume_id"] = f"{source}:{raw_record.get('id') or raw_record.get('filename') or len(records)}"
            records.append(record)
    return records


def _seed_resume_video_settings(record: dict[str, Any], prefix: str = "new_video") -> None:
    """Load one persisted record into the namespaced resume widgets."""
    resume_id = str(record.get("resume_id") or "")
    state_prefix = f"{prefix}_resume"
    if st.session_state.get(f"{state_prefix}_loaded_id") == resume_id:
        return
    generation_settings = record.get("generation_settings") if isinstance(record.get("generation_settings"), dict) else {}
    st.session_state[f"{state_prefix}_sections"] = missing_setting_sections(generation_settings)
    for suffix in setting_widget_suffixes():
        if suffix in generation_settings:
            st.session_state[f"{state_prefix}_{suffix}"] = generation_settings[suffix]
    st.session_state[f"{state_prefix}_loaded_id"] = resume_id


def _create_video_task_from_saved_script(record: dict[str, Any], channel: dict[str, Any], settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Create a normal pipeline task while preserving the saved script as an override."""
    subject = str(record.get("video_subject") or "").strip()
    script = str(record.get("video_script") or "").strip()
    keywords = str(record.get("video_keywords") or "").strip()
    settings = {
        **(record.get("generation_settings") if isinstance(record.get("generation_settings"), dict) else {}),
        **settings,
        "video_subject": subject,
        "video_script": script,
        "video_keywords": keywords,
        "script_language": str(settings.get("script_language") or record.get("language") or channel.get("language") or "pt"),
        "generate_script_with_ai": False,
    }
    style_label = str(settings.get("video_source") or WIDE_STYLE_OPTIONS[0])
    style = channel_video_source_storage(style_label)
    blueprint_id = str(record.get("blueprint_id") or channel.get("default_blueprint_id") or channel.get("blueprint_id") or "")
    blueprint_name = str(record.get("blueprint_name") or blueprint_id or "SEM BLUEPRINT CONFIGURADO")
    payload = {
        "topic": subject,
        "title": str(record.get("title") or subject).strip(),
        "topic_source": "saved_script",
        "language": settings["script_language"],
        "format": settings.get("video_format", "wide"),
        "style_wide": style,
        "style_ia": settings.get("style_ia", ""),
        "material_source": settings.get("material_source", "") if style == "pexels" else "",
        "music_mode": False,
        "background_mode": "none" if style in {"only_music", "music_clips"} else ("ai" if style == "full_ia" else "stock"),
        "voice": str(settings.get("voice") or channel.get("default_voice") or channel.get("voice") or ""),
        "blueprint_id": blueprint_id,
        "blueprint_name": blueprint_name,
        "generation_settings": settings,
    }
    batch = create_batch(
        "single",
        [str(channel.get("id") or "")],
        subject,
        1,
        {
            **payload,
            "topic_source": "saved_script",
            "script_document_id": str(record.get("id") or ""),
            "channel_payloads": {str(channel.get("id") or ""): payload},
        },
    )
    tasks = create_tasks_for_batch(batch)
    for task in tasks:
        task["script_document_id"] = str(record.get("id") or "")
        task["manual_start_required"] = True
        task["created_at"] = str(record.get("created_at") or task.get("created_at") or now())
        task["updated_at"] = now()
    if tasks:
        task_ids = {str(task.get("id") or "") for task in tasks}
        created_by_id = {str(task.get("id") or ""): task for task in tasks}

        def persist_created_metadata(entries: Any) -> None:
            if not isinstance(entries, list):
                return
            for entry in entries:
                if isinstance(entry, dict) and str(entry.get("id") or "") in task_ids:
                    entry.update(created_by_id[str(entry.get("id") or "")])

        update_json("tasks.json", [], persist_created_metadata)
    return tasks


def render_video_from_draft(prefix: str = "new_video") -> None:
    """Render the continuation flow for saved scripts and local pipeline drafts."""
    st.subheader("Roteiros guardados")
    st.caption("Seleccione um roteiro guardado para continuar a criação do vídeo sem perder o conteúdo já preparado.")
    records = _saved_video_draft_records()
    if not records:
        st.info("Ainda não existem roteiros guardados.")
        return

    record_by_id = {str(record["resume_id"]): record for record in records}
    selected_id = st.selectbox(
        "Seleccione um roteiro",
        list(record_by_id),
        format_func=lambda identifier: f"{record_by_id[identifier].get('title') or 'Roteiro sem título'} · {record_by_id[identifier].get('source_label') or 'Rascunho'}",
        key=f"{prefix}_resume_selected",
    )
    record = record_by_id[selected_id]
    _seed_resume_video_settings(record, prefix)
    with st.container(border=True):
        st.markdown(f"**Video Subject:** {record.get('video_subject') or '—'}")
        st.caption(f"{record.get('source_label') or 'Rascunho'} · {record.get('channel_name') or 'Documento independente'} · Blueprint: {record.get('blueprint_name') or '—'}")
        if record.get("video_script"):
            st.text_area("Video Script (Optional)", value=str(record["video_script"]), height=150, disabled=True, key=f"{prefix}_resume_preview_script_{selected_id}")
        if record.get("video_keywords"):
            st.caption(f"**Video Keywords:** {record['video_keywords']}")

    content_missing = missing_content_fields(record)
    if content_missing:
        st.warning(f"Conteúdo em falta: {', '.join(content_missing)}. Volte a Roteiros e guarde tópico, roteiro e palavras-chave antes de continuar.")
        return

    persisted_settings = record.get("generation_settings") if isinstance(record.get("generation_settings"), dict) else {}
    missing_sections = missing_setting_sections(persisted_settings)
    if missing_sections:
        selected_sections = set(
            st.multiselect(
                "Configurações a completar",
                list(DRAFT_SETTING_SECTIONS),
                default=missing_sections,
                key=f"{prefix}_resume_sections",
                help="Seleccione uma ou mais áreas para completar antes de criar a tarefa.",
            )
        )
        st.caption("Seleccione as configurações que pretende completar.")
    else:
        selected_sections = set()
        st.success("Roteiro completo: todas as configurações estão disponíveis.")

    all_channels = [channel for channel in read_json("channels.json", []) if isinstance(channel, dict)]
    selectable_channels = [channel for channel in all_channels if channel.get("active", True)]
    if not selectable_channels:
        st.warning("Cadastre pelo menos um canal antes de continuar.")
        return
    saved_channel_id = str(record.get("channel_id") or "")
    if saved_channel_id and not any(str(channel.get("id")) == saved_channel_id for channel in selectable_channels):
        saved_channel = next((channel for channel in all_channels if str(channel.get("id")) == saved_channel_id), None)
        if saved_channel:
            selectable_channels.insert(0, saved_channel)
    channel_index = next((index for index, channel in enumerate(selectable_channels) if str(channel.get("id")) == saved_channel_id), 0)
    selected_channel = st.selectbox(
        "Canal",
        selectable_channels,
        index=channel_index,
        format_func=lambda channel: str(channel.get("name") or "Canal sem nome"),
        key=f"{prefix}_resume_channel",
    )

    settings_from_form = render_video_generation_settings(
        f"{prefix}_resume",
        current_language=str(record.get("language") or "pt"),
        channel=selected_channel,
        sections=selected_sections,
        include_content=False,
    )
    merged_settings = {**persisted_settings, **settings_from_form}
    still_missing = missing_setting_sections(merged_settings)
    action_label = "Continuar criação" if still_missing else "Gerar apenas o vídeo"
    if still_missing:
        st.caption(f"Faltam: {', '.join(still_missing)}")
    elif not missing_sections:
        st.caption("Este roteiro será usado directamente, sem regenerar o conteúdo editorial guardado.")
    if st.button(action_label, type="primary", width="stretch", key=f"{prefix}_resume_submit", icon=":material/movie:"):
        if still_missing:
            st.error(f"Complete as configurações seleccionadas: {', '.join(still_missing)}.")
        elif not selected_channel.get("id"):
            st.error("Seleccione um canal para continuar.")
        else:
            tasks = _create_video_task_from_saved_script(record, selected_channel, merged_settings)
            st.success(f"Tarefa criada a partir de {record.get('title') or 'Roteiro sem título'}: {tasks[0].get('id') if tasks else '—'}.")


def render_new_video(page_title: str = "Criação de Vídeos", prefix: str = "new_video", *, channel_platform: str = "youtube", fixed_aspect_ratio: str | None = None):
    st.title(page_title)
    tab_labels = ["Criar vídeo"] + (["Gerar de Rascunho"] if page_title in {"Criação de Vídeos", "Criação de Shorts"} else [])
    tabs = render_localized_tabs(tab_labels)
    create_tab = tabs[0]
    draft_tab = tabs[1] if len(tabs) > 1 else None
    with create_tab:
        all_channels = [c for c in read_json("channels.json", []) if classify_channel_platform(c) == channel_platform]
        active_channels = [c for c in all_channels if c.get("active", True)]
        if not all_channels:
            st.warning("Cadastre pelo menos um canal antes de criar vídeos.")
        else:
            if fixed_aspect_ratio:
                mode = "single"
                st.info("Os Shorts são sempre criados para um canal TikTok específico e em formato Portrait 9:16.")
            else:
                mode_label = st.selectbox(
                    "Modo de criação",
                    ["Canal específico", "Lote no mesmo canal", "Lote geral"],
                    key=f"{prefix}_mode",
                )
                mode = {"Canal específico": "single", "Lote no mesmo canal": "same_channel", "Lote geral": "general"}[mode_label]
            selected_one: dict[str, Any] | None = None
            legacy_language = st.session_state.get("video_language") or read_json("settings.json", {}).get("video_language")
            if str(legacy_language or "").strip().casefold() in {"music", "00 – apenas música de fundo (sem falas)", "00 - apenas música de fundo (sem falas)"}:
                st.session_state["video_language"] = "music"
            else:
                st.session_state["video_language"] = language_code(legacy_language or "pt")
            generation_settings: dict[str, Any] = {}
            if mode == "general":
                selected = [str(channel["id"]) for channel in all_channels if channel.get("id")]
                st.info(f"**Lote geral:** será criada exactamente uma tarefa para cada um dos {len(selected)} canais cadastrados. Cada canal receberá um tema, título e thumbnail próprios; não existe selecção parcial.")
                with st.container(border=True):
                    st.subheader("Canais que serão processados")
                    for channel in all_channels:
                        summary = channel_blueprint_summary(channel)
                        status = "Activo" if channel.get("active", True) else "Inactivo"
                        st.caption(f"**{channel.get('name', 'Canal')}** · {status} · Blueprint: **{summary['name']}** · Voz: {summary['voice'] or 'Sem voz padrão'}")
                general_context = st.text_area(
                    "Contexto opcional para todos os canais",
                    value=st.session_state.get(f"{prefix}_general_context", ""),
                    key=f"{prefix}_general_context",
                    placeholder="Opcional: campanha, época, evento ou restrição editorial comum. O tema final será individual por canal.",
                )
                if st.button("Gerar tópicos individuais para todos os canais", key=f"{prefix}_generate_general_topics", width="stretch"):
                    settings = read_json("settings.json", {})
                    generated_topics: dict[str, dict[str, Any]] = {}
                    errors: list[str] = []
                    with st.spinner("A gerar um briefing específico para cada canal…"):
                        for channel in all_channels:
                            try:
                                generated_topics[channel["id"]] = generate_topic_for_ui(settings, channel, general_context)
                            except CreativeGenerationError as exc:
                                errors.append(f"{channel.get('name', 'Canal')}: {exc}")
                    if errors:
                        for error in errors:
                            st.error(error)
                    else:
                        st.session_state[f"{prefix}_general_topics"] = generated_topics
                        st.success(f"Foram gerados {len(generated_topics)} briefings independentes.")
                general_topics = st.session_state.get(f"{prefix}_general_topics", {})
                if general_topics:
                    st.subheader("Briefings por canal")
                    for channel in all_channels:
                        result = general_topics.get(channel["id"])
                        if result:
                            st.write(f"**{channel.get('name', 'Canal')}**")
                            st.caption(f"{result.get('niche', '')} · {result.get('angle', '')}")
                            st.text_area("Briefing gerado", value=result.get("topic", ""), key=f"{prefix}_general_topic_{channel['id']}", height=80)
                generation_settings = render_video_generation_settings(
                    prefix,
                    current_language=str(st.session_state.get("video_language") or ""),
                    default_aspect_ratio=fixed_aspect_ratio or "Landscape 16:9",
                    save_draft_callback=lambda: _save_pipeline_draft_callback(
                        prefix,
                        "music" if page_title == "Criação de Músicas" else "video",
                        page_title,
                        channel=selected_one,
                        blueprint=blueprint_for_channel(selected_one or {}),
                    ),
                )
            else:
                if not active_channels:
                    st.warning("Não existem canais activos disponíveis para os modos de canal específico.")
                    selected = []
                else:
                    selected_one = st.selectbox("Canal", active_channels, format_func=lambda c: c["name"], key=f"{prefix}_channel")
                    selected = [selected_one["id"]]
                    # YouTube uses Blueprints; TikTok Shorts use the channel Prompt Master.
                    if channel_platform == "tiktok":
                        render_tiktok_prompt_master_panel(selected_one)
                    else:
                        render_channel_blueprint_panel(selected_one)
                        render_channel_thumbnail_blueprint_panel(selected_one)
                    generation_settings = render_video_generation_settings(
                        prefix,
                        current_language=str(st.session_state.get("video_language") or ""),
                        channel=selected_one,
                        default_aspect_ratio=fixed_aspect_ratio or "Landscape 16:9",
                        generate_content_callback=lambda: _generate_video_content_callback(
                            prefix,
                            selected_one,
                            str(st.session_state.get("video_language") or "pt"),
                        ),
                        save_draft_callback=lambda: _save_pipeline_draft_callback(
                            prefix,
                            "music" if page_title == "Criação de Músicas" else "video",
                            page_title,
                            channel=selected_one,
                            blueprint=blueprint_for_channel(selected_one or {}),
                        ),
                    )

            if not generation_settings:
                generation_settings = render_video_generation_settings(
                    prefix,
                    current_language=str(st.session_state.get("video_language") or ""),
                    default_aspect_ratio=fixed_aspect_ratio or "Landscape 16:9",
                    save_draft_callback=lambda: _save_pipeline_draft_callback(
                        prefix,
                        "music" if page_title == "Criação de Músicas" else "video",
                        page_title,
                        channel=selected_one,
                        blueprint=blueprint_for_channel(selected_one or {}),
                    ),
                )
            wide_style_label = generation_settings["video_source"]
            if channel_video_source_storage(wide_style_label) == "google_images":
                st.warning(GOOGLE_IMAGES_COPYRIGHT_WARNING)
            style = channel_video_source_storage(wide_style_label)
            if style in UNAVAILABLE_VIDEO_SOURCES:
                if style == "music_clips":
                    st.info("Clipes de Música não está disponível nesta versão porque a pipeline completa não existe no código. Nenhuma tarefa será criada.")
                else:
                    st.info("Esta fonte será implementada na Etapa 2. Nenhuma tarefa será criada.")
                with st.form(f"{prefix}_form"):
                    st.form_submit_button("Criar tarefas", type="primary", disabled=True)
                st.stop()
            material_source = (
                {"Pexels": "pexels", "Pixabay": "pixabay"}.get(str(generation_settings.get("material_source") or ""), "")
                if style == "pexels"
                else ""
            )
            style_ia = generation_settings.get("style_ia", "")
            music_path = ""
            music_source = ""
            if style == "only_music":
                st.caption("Only Music usa uma música existente e gera apenas a thumbnail; não cria vídeo, narração ou música nova.")
                music_source = st.radio("Fonte da música", ["Música existente", "Upload de ficheiro"], horizontal=True, key=f"{prefix}_music_source")
                if music_source == "Música existente":
                    local_music = list_music_files()
                    if local_music:
                        selected_music = st.selectbox("Música local", local_music, format_func=lambda item: item.name, key=f"{prefix}_music_existing")
                        music_path = str(selected_music)
                    else:
                        st.warning("Não existem músicas disponíveis. Vá a Pipeline Música > Criação de Músicas ou faça upload de um ficheiro.")
                elif music_source == "Upload de ficheiro":
                    uploaded_music = st.file_uploader("Carregar música", type=[item.lstrip(".") for item in sorted(MUSIC_UPLOAD_EXTENSIONS)], key=f"{prefix}_music_upload")
                    if uploaded_music and st.button("Guardar música local", key=f"{prefix}_music_store", width="stretch"):
                        try:
                            stored_music = store_music_file(uploaded_music.name, uploaded_music.getvalue())
                            st.session_state[f"{prefix}_music_path"] = str(stored_music)
                            st.success(f"Música guardada em `{stored_music}`")
                        except (OSError, ValueError) as exc:
                            st.error(str(exc))
                    music_path = st.session_state.get(f"{prefix}_music_path", "")
                music_path = music_path or st.session_state.get(f"{prefix}_music_path", "")
            elif style in UNAVAILABLE_VIDEO_SOURCES:
                if style == "music_clips":
                    st.info("Clipes de Música não está disponível nesta versão porque a pipeline completa não existe no código. Nenhuma tarefa será criada.")
                else:
                    st.info("Esta fonte será implementada na Etapa 2.")

            same_channel_quantity = max(1, min(100, int(generation_settings.get("videos_per_run") or 1))) if mode == "same_channel" else 1
            payloads: dict[str, dict[str, Any]] = {}
            if mode == "general":
                existing_topics = st.session_state.get(f"{prefix}_general_topics", {})
                payloads = dict(st.session_state.get(f"{prefix}_general_payloads", {}))
                with st.expander("Gerar Thumbnail com IA", expanded=False):
                    if st.button("Gerar Thumbnail com IA para todos os vídeos", key=f"{prefix}_generate_general_creative", width="stretch"):
                        settings = read_json("settings.json", {})
                        new_payloads: dict[str, dict[str, Any]] = {}
                        errors: list[str] = []
                        with st.spinner("A gerar uma thumbnail independente por vídeo…"):
                            for channel in all_channels:
                                try:
                                    topic_result = existing_topics.get(channel["id"])
                                    topic = str((topic_result or {}).get("topic") or "").strip()
                                    if not topic:
                                        errors.append(f"{channel.get('name', 'Canal')}: gere primeiro o tópico individual do canal.")
                                        continue
                                    generated = generate_thumbnail_for_ui(settings, channel, topic, title=topic, topic_source=str((topic_result or {}).get("topic_source") or "llm"))
                                    generated["ai_generation"]["topic"] = topic_result
                                    new_payloads[channel["id"]] = generated
                                except CreativeGenerationError as exc:
                                    errors.append(f"{channel.get('name', 'Canal')}: {exc}")
                        if errors:
                            for error in errors:
                                st.error(error)
                        else:
                            st.session_state[f"{prefix}_general_payloads"] = new_payloads
                            payloads = new_payloads
                            st.success(f"Thumbnail pronta para {len(new_payloads)} vídeo(s).")
                payloads = st.session_state.get(f"{prefix}_general_payloads", payloads)
                for channel in all_channels:
                    payload = payloads.get(channel["id"])
                    if not payload:
                        continue
                    with st.expander(f"{channel.get('name', 'Canal')} — thumbnail", expanded=False):
                        variants = payload.get("thumbnail_variants", [])
                        if variants:
                            labels = [f"{idx + 1}. {item.get('concept', 'Variante')}" for idx, item in enumerate(variants)]
                            selected_variant_label = st.selectbox("Thumbnail escolhida", labels, key=f"{prefix}_general_thumbnail_{channel['id']}")
                            variant_index = labels.index(selected_variant_label)
                            variant = variants[variant_index]
                            payload["thumbnail_variant"] = variant
                            payload["thumbnail_prompt"] = variant.get("image_prompt", "")
                            payload["thumbnail_text"] = variant.get("overlay_text", "")
                            st.caption(f"{variant.get('composition', '')} · {variant.get('color_palette', '')}")
                            thumbnail_path = str(variant.get("image_path") or payload.get("thumbnail_path") or "").strip()
                            if st.button("Gerar imagem com Nano Banana", key=f"{prefix}_general_generate_thumbnail_{channel['id']}", width="stretch"):
                                try:
                                    thumbnail_path = str(
                                        generate_thumbnail_image(
                                            read_json("settings.json", {}),
                                            variant.get("image_prompt", ""),
                                            topic=str(payload.get("topic") or ""),
                                            variant_index=variant_index,
                                            lettering_text=str(variant.get("overlay_text") or payload.get("thumbnail_text") or ""),
                                            lettering_prompt=str(variant.get("lettering_prompt") or ""),
                                        )
                                    )
                                    variant["image_path"] = thumbnail_path
                                    payload["thumbnail_path"] = thumbnail_path
                                    payload["thumbnail_status"] = "generated"
                                    st.session_state[f"{prefix}_general_payloads"] = payloads
                                    record_notification("thumbnail_generation_completed", f"Thumbnail gerada: {payload.get('title') or payload.get('topic') or 'Vídeo'}", "A thumbnail foi gerada com sucesso pelo Nano Banana.", metadata={"channel_name": channel.get("name") or "", "image_path": Path(thumbnail_path).name}, dedupe_key=f"thumbnail:{thumbnail_path}")
                                    st.success("Thumbnail gerada com Nano Banana.")
                                    st.rerun()
                                except ThumbnailGenerationError as exc:
                                    st.error(str(exc))
                            if thumbnail_path and Path(thumbnail_path).is_file():
                                st.image(thumbnail_path, caption="Thumbnail gerada pelo Nano Banana", width="stretch")
                                payload["thumbnail_path"] = thumbnail_path
                                payload["thumbnail_status"] = "generated"
                            else:
                                st.caption("A imagem ainda não foi gerada. Configure a API key em Configuração API > API Keys.")
                        st.caption(f"Estado da thumbnail: {payload.get('thumbnail_status', 'prompt_ready')} · texto: {payload.get('thumbnail_text') or 'sem texto'}")
            else:
                with st.expander("Gerar Thumbnail com IA", expanded=False):
                    topic_for_thumbnail = str(generation_settings.get("video_subject") or "").strip()
                    if st.button("Gerar Thumbnail com IA", key=f"{prefix}_generate_creative", width="stretch"):
                        if not topic_for_thumbnail:
                            st.error("Preencha o Video Subject antes de gerar a thumbnail.")
                        else:
                            try:
                                existing_payload = dict(st.session_state.get(f"{prefix}_creative_payload") or {})
                                existing_title = str(existing_payload.get("title") or topic_for_thumbnail).strip()
                                generated = generate_thumbnail_variants_for_ui(
                                    read_json("settings.json", {}),
                                    selected_one or {},
                                    topic_for_thumbnail,
                                    same_channel_quantity,
                                    title=existing_title,
                                    topic_source=_video_topic_source(topic_for_thumbnail, prefix),
                                )
                                generated = {**existing_payload, **generated}
                                generated["topic"] = topic_for_thumbnail
                                generated["title"] = existing_title
                                generated["title_candidates"] = existing_payload.get("title_candidates", [])
                                st.session_state[f"{prefix}_creative_payload"] = generated
                                st.success(f"Thumbnail pronta para {same_channel_quantity} vídeo(s); o título existente foi preservado.")
                                st.rerun()
                            except CreativeGenerationError as exc:
                                st.error(str(exc))
                    payload = st.session_state.get(f"{prefix}_creative_payload")
                    if payload:
                        st.subheader("Thumbnail automática")
                        st.caption(f"Título preservado: {payload.get('title') or payload.get('topic') or 'Sem título'}")
                        title_options = [item.get("title", "") for item in payload.get("title_candidates", []) if item.get("title")]
                        if title_options:
                            selected_title = st.selectbox("Título escolhido", title_options, index=max(0, title_options.index(payload.get("title")) if payload.get("title") in title_options else 0), key=f"{prefix}_title_choice")
                            payload["title"] = selected_title
                            with st.expander(f"Ver {len(title_options)} candidatos de título"):
                                st.dataframe(payload.get("title_candidates", []), width="stretch", hide_index=True)
                        variants = payload.get("thumbnail_variants", [])
                        if variants:
                            labels = [f"{idx + 1}. {item.get('concept', 'Variante')}" for idx, item in enumerate(variants)]
                            selected_variant_label = st.selectbox("Thumbnail escolhida", labels, key=f"{prefix}_thumbnail_choice")
                            variant_index = labels.index(selected_variant_label)
                            variant = variants[variant_index]
                            payload["thumbnail_variant"] = variant
                            payload["thumbnail_prompt"] = variant.get("image_prompt", "")
                            payload["thumbnail_text"] = variant.get("overlay_text", "")
                            st.caption(f"Composição: {variant.get('composition', '')} · Cores: {variant.get('color_palette', '')}")
                            st.code(variant.get("image_prompt", ""), language="text")
                            thumbnail_path = str(variant.get("image_path") or payload.get("thumbnail_path") or "").strip()
                            if st.button("Gerar imagem da thumbnail com Nano Banana", key=f"{prefix}_generate_thumbnail_image", width="stretch"):
                                try:
                                    thumbnail_path = str(
                                        generate_thumbnail_image(
                                            read_json("settings.json", {}),
                                            variant.get("image_prompt", ""),
                                            topic=str(payload.get("topic") or ""),
                                            variant_index=variant_index,
                                            lettering_text=str(variant.get("overlay_text") or payload.get("thumbnail_text") or ""),
                                            lettering_prompt=str(variant.get("lettering_prompt") or ""),
                                        )
                                    )
                                    variant["image_path"] = thumbnail_path
                                    payload["thumbnail_path"] = thumbnail_path
                                    payload["thumbnail_status"] = "generated"
                                    st.session_state[f"{prefix}_creative_payload"] = payload
                                    record_notification("thumbnail_generation_completed", f"Thumbnail gerada: {payload.get('title') or payload.get('topic') or 'Vídeo'}", "A thumbnail foi gerada com sucesso pelo Nano Banana.", metadata={"channel_name": selected_one.get("name") if selected_one else "", "image_path": Path(thumbnail_path).name}, dedupe_key=f"thumbnail:{thumbnail_path}")
                                    st.success("Thumbnail gerada com Nano Banana.")
                                    st.rerun()
                                except ThumbnailGenerationError as exc:
                                    st.error(str(exc))
                            if thumbnail_path and Path(thumbnail_path).is_file():
                                st.image(thumbnail_path, caption="Thumbnail gerada pelo Nano Banana", width="stretch")
                                payload["thumbnail_path"] = thumbnail_path
                                payload["thumbnail_status"] = "generated"
                            else:
                                st.info("Escolha a variante e clique em **Gerar imagem da thumbnail com Nano Banana**. A API key é configurada em Configuração API > API Keys.")
                        st.session_state[f"{prefix}_creative_payload"] = payload

            st.session_state[f"{prefix}_generation_settings"] = dict(generation_settings)
            with st.form(f"{prefix}_form"):
                language = generation_settings["script_language"]
                fmt = generation_settings["video_format"]
                submitted = st.form_submit_button("Criar tarefas", type="primary", disabled=style in UNAVAILABLE_VIDEO_SOURCES)
            if style in UNAVAILABLE_VIDEO_SOURCES:
                st.stop()
            if submitted:
                save_video_language(language)
                if style == "only_music" and not music_path:
                    st.error("Escolha uma música existente ou faça upload de um ficheiro antes de criar Only Music. Se a biblioteca estiver vazia, use Pipeline Música > Criação de Músicas.")
                    st.stop()
                if str(generation_settings.get("voiceover_mode") or "").strip().casefold() == "upload":
                    voiceover_file = Path(str(generation_settings.get("voiceover_file") or "").strip()).expanduser()
                    if not str(voiceover_file) or not voiceover_file.is_file() or voiceover_file.stat().st_size <= 0:
                        st.error("Carregue e guarde um ficheiro de narração em Configurações de áudio antes de criar o vídeo.")
                        st.stop()
                if mode == "general":
                    payloads = dict(st.session_state.get(f"{prefix}_general_payloads", {}))
                    topics = dict(st.session_state.get(f"{prefix}_general_topics", {}))
                    channels_by_id = {str(channel["id"]): channel for channel in all_channels}
                    payloads_need_refresh = len(payloads) != len(selected) or any(
                        str(st.session_state.get(f"{prefix}_general_topic_{channel_id}", "") or "").strip()
                        and str(st.session_state.get(f"{prefix}_general_topic_{channel_id}", "") or "").strip() != str((payloads.get(channel_id) or {}).get("topic") or "").strip()
                        for channel_id in selected
                    )
                    if payloads_need_refresh:
                        settings = read_json("settings.json", {})
                        generated_payloads: dict[str, dict[str, Any]] = {}
                        errors: list[str] = []
                        with st.spinner("A gerar automaticamente um pacote criativo independente para cada canal…"):
                            for channel_id in selected:
                                channel = channels_by_id[channel_id]
                                edited_topic = str(st.session_state.get(f"{prefix}_general_topic_{channel_id}", "") or "").strip()
                                topic_result = topics.get(channel_id) or {}
                                try:
                                    if not edited_topic:
                                        topic_result = generate_topic_for_ui(settings, channel, general_context)
                                        edited_topic = topic_result["topic"]
                                    else:
                                        topic_result = {**topic_result, "topic": edited_topic, "topic_source": topic_result.get("topic_source", "manual")}
                                    generated = generate_editorial_for_ui(settings, channel, edited_topic, topic_source=topic_result.get("topic_source", "llm"))
                                    generated["ai_generation"]["topic"] = topic_result
                                    generated_payloads[channel_id] = generated
                                except CreativeGenerationError as exc:
                                    errors.append(f"{channel.get('name', 'Canal')}: {exc}")
                        if errors:
                            for error in errors:
                                st.error(error)
                            st.error("O Lote geral não foi criado porque faltou gerar o conteúdo específico de pelo menos um canal.")
                        else:
                            payloads = generated_payloads
                            st.session_state[f"{prefix}_general_payloads"] = payloads
                            st.session_state[f"{prefix}_general_topics"] = {cid: {"topic": payload["topic"], "topic_source": payload.get("topic_source", "llm")} for cid, payload in payloads.items()}
                    if len(payloads) == len(selected):
                        batch_topic = "Lote geral — um vídeo independente por canal"
                        channel_payloads = {cid: {**payload, "language": language, "format": fmt, "style_wide": style, "style_ia": style_ia, "material_source": material_source, "music_mode": False, "background_mode": "none" if style in {"only_music", "music_clips"} else ("ai" if style == "full_ia" else "stock"), "music_path": music_path, "music_source": music_source, "generation_settings": generation_settings} for cid, payload in payloads.items()}
                        batch = create_batch("general", selected, batch_topic, 1, {"language": language, "format": fmt, "style_wide": style, "style_ia": style_ia, "material_source": material_source, "music_mode": False, "background_mode": "none" if style in {"only_music", "music_clips"} else ("ai" if style == "full_ia" else "stock"), "music_path": music_path, "music_source": music_source, "generation_settings": generation_settings, "topic_source": "llm", "channel_payloads": channel_payloads})
                        tasks = create_tasks_for_batch(batch)
                        st.success(f"Lote geral {batch['id']} criado com {len(tasks)} tarefas independentes, uma por canal.")
                else:
                    topic_value = str(generation_settings.get("video_subject") or "").strip()
                    if not selected:
                        st.error("Seleccione um canal.")
                    else:
                        if not topic_value:
                            st.error("Preencha o campo Video Subject ou use o botão de geração automática abaixo das keywords.")
                            st.stop()
                        quantity_value = same_channel_quantity
                        payload = dict(st.session_state.get(f"{prefix}_creative_payload") or {})
                        if not payload.get("title") or not payload.get("thumbnail_variants"):
                            try:
                                payload = generate_editorial_for_ui(
                                    read_json("settings.json", {}),
                                    selected_one or {},
                                    topic_value,
                                    topic_source=_video_topic_source(topic_value, prefix),
                                )
                            except CreativeGenerationError as exc:
                                st.warning(f"Título/keywords automáticos pendentes: {exc} A tarefa será criada com o tópico como título; o prompt e a imagem da thumbnail serão gerados depois do vídeo.")
                                payload = {"topic": topic_value, "title": topic_value, "topic_source": "manual", "thumbnail_status": "pending_provider", "thumbnail_variants": [], "thumbnail_variant": {}, "thumbnail_prompt": "", "thumbnail_text": ""}
                        payload.update({"topic": topic_value, "topic_source": payload.get("topic_source") or _video_topic_source(topic_value), "language": language, "format": fmt, "style_wide": style, "style_ia": style_ia, "material_source": material_source, "music_mode": False, "background_mode": "none" if style in {"only_music", "music_clips"} else ("ai" if style == "full_ia" else "stock"), "music_path": music_path, "music_source": music_source, "generation_settings": generation_settings})
                        batch = create_batch(mode, selected, topic_value, quantity_value, {"language": language, "format": fmt, "style_wide": style, "style_ia": style_ia, "material_source": material_source, "music_mode": False, "background_mode": "none" if style in {"only_music", "music_clips"} else ("ai" if style == "full_ia" else "stock"), "music_path": music_path, "music_source": music_source, "generation_settings": generation_settings, "topic_source": payload.get("topic_source", "manual"), "channel_payloads": {selected[0]: payload}})
                        tasks = create_tasks_for_batch(batch)
                        st.success(f"Lote {batch['id']} criado com {len(tasks)} tarefa(s). Abra {ui_text('Backlog Vídeos', current_ui_language())} para acompanhar.")

    _render_pipeline_progress_panel()
    if draft_tab is not None:
        with draft_tab:
            render_video_from_draft(prefix)


def render_music_creation():
    """Create audio-only items for the independent Suno/Lyria Music Backlog."""
    st.title("Criação de Músicas")
    st.caption("Crie apenas áudio. Os pedidos desta página não criam vídeo, não usam o MoneyPrinterTurbo e não entram no Backlog Vídeos.")
    settings = read_json("settings.json", {})
    generated_fields = st.session_state.pop("music_task_generated_fields", None)
    if isinstance(generated_fields, dict):
        for state_key, generated_key in (
            ("music_task_title", "title"),
            ("music_task_language", "language"),
            ("music_task_genre", "genre"),
            ("music_task_vocal", "vocal"),
            ("music_task_references", "references"),
            ("music_task_prompt", "prompt"),
        ):
            st.session_state[state_key] = str(generated_fields.get(generated_key) or "")
    provider_label = st.selectbox("Provider de geração musical", ["Suno AI", "Google Lyria", "Eleven Music"], key="music_task_provider")
    theme = st.text_input("Tema / assunto principal", key="music_task_theme", placeholder="Ex.: uma viagem nocturna pela costa portuguesa")
    title = st.text_input("Título da música", key="music_task_title")
    language = st.selectbox(
        "Idioma da letra/música",
        list(LANGUAGE_CODES),
        index=list(LANGUAGE_CODES).index(str(st.session_state.get("music_task_language") or "pt")) if str(st.session_state.get("music_task_language") or "pt") in LANGUAGE_CODES else list(LANGUAGE_CODES).index("pt"),
        format_func=language_label,
        key="music_task_language",
    )
    genre = st.selectbox("Género musical", list(MUSIC_GENRES), key="music_task_genre")
    vocal = st.selectbox("Vocal", list(MUSIC_VOCAL_OPTIONS), key="music_task_vocal")
    eleven_voice_id = ""
    eleven_voice_gender = ""
    if provider_label == "Eleven Music":
        cached_voices = cached_personal_voices()
        if not cached_voices:
            st.info("Sincronize primeiro as vozes pessoais em Vozes Personalizadas. O Eleven Music não disponibiliza voz de coral para este selector.")
        else:
            voice_options = {str(item.get("voice_id")): item for item in cached_voices if item.get("voice_id")}
            selected_voice_id = st.selectbox(
                "Voz personalizada (Eleven Music)",
                [""] + list(voice_options),
                format_func=lambda item: "Sem voz personalizada" if not item else str(voice_options[item].get("name") or item),
                key="music_task_eleven_voice",
            )
            eleven_voice_id = selected_voice_id
            selected_voice = voice_options.get(selected_voice_id, {})
            labels = selected_voice.get("labels") if isinstance(selected_voice.get("labels"), dict) else {}
            raw_gender = str(labels.get("gender") or labels.get("sex") or "").strip().casefold()
            eleven_voice_gender = "female" if raw_gender in {"female", "feminino", "woman", "mulher"} else ("male" if raw_gender in {"male", "masculino", "man", "homem"} else "")
            st.caption(f"Tipo de voz detectado automaticamente: {eleven_voice_gender or 'não identificado'}. Vozes de coral não estão disponíveis no Eleven Music.")
    references = st.text_area(
        "Referências culturais, paisagens, clima ou artistas similares (opcional)",
        key="music_task_references",
        placeholder="Ex.: pôr do sol mediterrânico, estrada molhada, nostalgia suave e arranjos acústicos contemporâneos",
        height=90,
    )
    prompt = st.text_area(
        "Prompt musical",
        placeholder="Use Gerar campos musicais com IA para criar letra e estilo completos, ou escreva um prompt próprio.",
        key="music_task_prompt",
        height=300,
    )
    if st.button("Gerar campos musicais com IA", key="music_task_generate_fields", width="stretch", icon=":material/auto_awesome:"):
        try:
            with st.spinner("A criar título, letra e prompt musical originais…"):
                generated = generate_music_fields(
                    settings,
                    theme=theme,
                    language=language,
                    genre=genre,
                    vocal=vocal,
                    references=references,
                )
            st.session_state["music_task_generated_fields"] = generated
            st.rerun()
        except CreativeGenerationError as exc:
            st.error(str(exc))
    lyria_model = ""
    if provider_label == "Google Lyria":
        models = ["lyria-3-clip-preview", "lyria-3-pro-preview"]
        configured = str(settings.get("lyria_model") or models[0])
        lyria_model = st.selectbox("Modelo Lyria", models, index=models.index(configured) if configured in models else 0, key="music_task_lyria_model")
    if st.button("Gerar Música", key="music_task_submit", type="primary", width="stretch", icon=":material/music_note:"):
        try:
            task = create_music_task(
                provider_label,
                prompt,
                title,
                lyria_model,
                language=language,
                genre=genre,
                vocal=vocal,
                references=references,
                theme=theme,
                voice_id=eleven_voice_id,
                voice_gender=eleven_voice_gender,
            )
            st.success(f"Música criada no Music Backlog: {task['title']}")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


def render_custom_music_voices() -> None:
    """List and test personal ElevenLabs voices without exposing credentials."""
    st.title("Vozes Personalizadas")
    st.caption("Vozes pessoais do ElevenLabs Voice Lab disponíveis para narração no Thunderbolt.")
    settings = read_json("settings.json", {})
    refresh_col, cache_col = st.columns([1, 2])
    with refresh_col:
        refresh = st.button("Actualizar vozes", type="primary", width="stretch", key="elevenlabs_refresh_voices")
    try:
        voices, metadata = fetch_personal_voices(settings, force=refresh)
        if metadata.get("source") == "cache":
            label = "cache local"
            if metadata.get("stale"):
                st.warning("A API não respondeu; a mostrar a última lista guardada localmente.")
        else:
            label = "API ElevenLabs"
        with cache_col:
            st.caption(f"Fonte: {label} · última actualização: {metadata.get('updated_at') or '—'}")
    except ElevenLabsVoicesError as exc:
        st.warning(str(exc))
        st.info("As vozes padrão continuam disponíveis na criação de vídeos.")
        return

    if not voices:
        st.info("Nenhuma voz pessoal foi encontrada nesta conta ElevenLabs.")
        return
    test_text = st.text_input("Texto curto para testar uma voz", value=DEFAULT_SAMPLE, key="elevenlabs_voice_test_text")
    for voice in voices:
        with st.container(border=True):
            voice_cols = st.columns([2.2, 1.8, 1])
            with voice_cols[0]:
                st.markdown(f"**{voice.get('name', 'Sem nome')}**")
                st.caption(f"ID: `{voice.get('voice_id', '')}`")
            with voice_cols[1]:
                labels = voice.get("labels") or {}
                st.caption("Categoria: personal")
                st.caption("Labels: " + (", ".join(f"{key}: {value}" for key, value in labels.items()) if labels else "não disponíveis"))
            with voice_cols[2]:
                if st.button("Testar voz", key=f"elevenlabs_test_voice_{voice['voice_id']}", width="stretch"):
                    try:
                        preview = synthesize_preview(test_text, "elevenlabs", voice["voice_id"], settings)
                        st.audio(str(preview), format="audio/mpeg")
                    except (OSError, RuntimeError, ValueError) as exc:
                        st.error(f"Não foi possível testar esta voz: {exc}")


def render_scripts():
    st.title("Roteiros")
    st.caption("Produza e guarde roteiros de vídeos ou letras de músicas a partir dos Blueprints do Thunderbolt.")
    script_dir = script_storage_path()
    st.info(f"**Ficheiros guardados em:** `{script_dir}` · o conteúdo fica no storage local do Thunderbolt e não é enviado automaticamente para plataformas.")

    create_tab, history_tab = render_localized_tabs(["Novo roteiro/letra", "Histórico guardado"])
    with create_tab:
        all_channels = [channel for channel in read_json("channels.json", []) if isinstance(channel, dict)]
        active_channels = [channel for channel in all_channels if channel.get("active", True)]
        channel_options: list[dict[str, Any] | None] = [None] + active_channels
        selected_channel = st.selectbox(
            "Canal (opcional)",
            channel_options,
            format_func=lambda channel: "Documento independente" if channel is None else str(channel.get("name") or "Canal sem nome"),
            key="script_channel",
        )
        blueprint_options = blueprint_catalog()
        blueprint_ids = [identifier for identifier, _label in blueprint_options]
        blueprint_labels = {identifier: label for identifier, label in blueprint_options}
        selected_blueprint_id = st.selectbox(
            "Blueprint",
            blueprint_ids,
            format_func=lambda identifier: blueprint_labels.get(identifier, "Sem Blueprint padrão"),
            key="script_blueprint",
        )
        selected_blueprint: dict[str, Any] = {}
        if selected_blueprint_id:
            for path in list_blueprint_files():
                try:
                    blueprint = load_blueprint_file(path)
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                identifiers = {str(blueprint.get("id") or ""), path.stem, str(blueprint.get("name") or "")}
                if selected_blueprint_id in identifiers:
                    selected_blueprint = dict(blueprint)
                    selected_blueprint.setdefault("id", selected_blueprint_id)
                    selected_blueprint.setdefault("name", blueprint_labels.get(selected_blueprint_id, selected_blueprint_id))
                    break
        if selected_blueprint:
            st.caption(f"Blueprint aplicado ao contexto: **{selected_blueprint.get('name', selected_blueprint_id)}**")
        else:
            st.warning("Sem Blueprint seleccionado: o documento pode ser criado, mas não terá contexto editorial de Blueprint.")

        document_type = st.selectbox("Tipo de documento", ["Roteiro de vídeo", "Letra de música"], key="script_document_type")
        script_settings = render_video_generation_settings(
            "pipeline_scripts",
            current_language=str(st.session_state.get("script_language") or read_json("settings.json", {}).get("video_language") or "pt"),
            channel=selected_channel,
            generate_content_callback=lambda: _generate_video_content_callback(
                "pipeline_scripts",
                selected_channel or {},
                str(st.session_state.get("pipeline_scripts_script_language") or language_code(legacy_script_language or "pt")),
                selected_blueprint,
            ),
            save_draft_callback=lambda: _save_pipeline_draft_callback(
                "pipeline_scripts",
                "script",
                "Roteiros",
                channel=selected_channel,
                blueprint=selected_blueprint,
                document_type="video_script" if document_type == "Roteiro de vídeo" else "music_lyrics",
                title=title,
                brief=brief,
            ),
        )
        language = script_settings["script_language"]
        structure_notes = script_settings["script_structure_notes"]
        st.session_state["pipeline_scripts_generation_settings"] = dict(script_settings)
        title = str(script_settings.get("video_subject") or "").strip()
        brief = str(script_settings.get("video_script") or "").strip() or title
        generate_col, clear_col = st.columns([1.4, 1])
        with generate_col:
            generate_clicked = st.button("Gerar com IA a partir do Blueprint", type="primary", width="stretch", key="generate_script_document")
        with clear_col:
            clear_clicked = st.button("Limpar rascunho", width="stretch", key="clear_script_document")
        if clear_clicked:
            for key in ("script_draft", "script_draft_title", "script_draft_content", "script_draft_summary", "script_draft_keywords"):
                st.session_state.pop(key, None)
            st.rerun()
        if generate_clicked:
            try:
                with st.spinner("A gerar o documento com o provider LLM configurado…"):
                    generated = generate_script_document(
                        read_json("settings.json", {}),
                        document_type=document_type,
                        title=title,
                        brief=brief,
                        language=language,
                        channel=selected_channel or {},
                        blueprint=selected_blueprint,
                        structure_notes=structure_notes,
                        generation_settings=script_settings,
                    )
                generation_key = hashlib.sha1(f"{document_type}|{generated.get('title', '')}|{generated.get('content', '')}".encode("utf-8")).hexdigest()
                generated["notification_dedupe_key"] = f"script-generation:{generation_key}"
                script_event_type = "music_lyrics_generated" if document_type == "Letra de música" else "standalone_script_generated"
                record_notification(
                    script_event_type,
                    f"{'Letra de música' if document_type == 'Letra de música' else 'Roteiro autónomo'} gerado: {generated.get('title') or title or 'Documento'}",
                    "A geração do documento terminou com sucesso e o rascunho está disponível para revisão.",
                    metadata={"document_type": "music_lyrics" if document_type == "Letra de música" else "video_script", "title": generated.get("title") or title or "Documento"},
                    dedupe_key=generated["notification_dedupe_key"],
                )
                st.session_state["script_draft"] = generated
                st.session_state["script_draft_title"] = generated["title"]
                st.session_state["script_draft_summary"] = generated.get("summary", "")
                st.session_state["script_draft_content"] = generated["content"]
                st.success("Rascunho gerado. Reveja e edite o texto antes de guardar.")
            except CreativeGenerationError as exc:
                st.error(str(exc))

        draft = st.session_state.get("script_draft")
        if draft:
            st.divider()
            st.subheader("Rascunho editável")
            if "script_draft_title" not in st.session_state:
                st.session_state["script_draft_title"] = str(draft.get("title") or title or "Documento")
            if "script_draft_summary" not in st.session_state:
                st.session_state["script_draft_summary"] = str(draft.get("summary") or "")
            if "script_draft_content" not in st.session_state:
                st.session_state["script_draft_content"] = str(draft.get("content") or "")
            if "script_draft_keywords" not in st.session_state:
                st.session_state["script_draft_keywords"] = str(draft.get("keywords") or "")
            draft_title = st.text_input("Título do rascunho", key="script_draft_title")
            draft_summary = st.text_input("Resumo", key="script_draft_summary")
            draft_keywords = st.text_area("Palavras-chave", height=90, key="script_draft_keywords")
            draft_content = st.text_area("Conteúdo guardado", height=460, key="script_draft_content")
            if st.button("Guardar documento no storage", type="primary", width="stretch", key="save_script_document"):
                try:
                    record = save_script_document(
                        {
                            **draft,
                            "title": draft_title,
                            "summary": draft_summary,
                            "keywords": draft_keywords,
                            "content": draft_content,
                            "document_type": "video_script" if document_type == "Roteiro de vídeo" else "music_lyrics",
                            "language": language,
                            "generation_settings": script_settings,
                            "channel_id": str((selected_channel or {}).get("id") or ""),
                            "channel_name": str((selected_channel or {}).get("name") or "Documento independente"),
                            "blueprint_id": str(selected_blueprint.get("id") or selected_blueprint_id or ""),
                            "blueprint_name": str(selected_blueprint.get("name") or blueprint_labels.get(selected_blueprint_id, "SEM BLUEPRINT CONFIGURADO")),
                        }
                    )
                    st.success(f"Documento guardado em `{record['path']}`.")
                except (OSError, ValueError) as exc:
                    st.error(f"Não foi possível guardar o documento: {exc}")
        else:
            st.caption("Gere um rascunho com IA para o editar aqui, ou seleccione um Blueprint e preencha as configurações do tema para começar.")

    with history_tab:
        st.caption(f"Histórico persistente: `{script_dir}` · índice em `{STORAGE / 'state' / 'scripts.json'}`")
        records = _backfill_saved_script_blueprints(list_script_documents())
        if not records:
            st.info("Ainda não existem roteiros ou letras guardados.")
        for record in records[:50]:
            label = f"{record.get('title', 'Documento')} · {record.get('document_type', 'documento')}"
            with st.expander(label, expanded=False):
                st.caption(
                    f"{record.get('created_at', '—')} · {record.get('channel_name', 'Documento independente')} · "
                    f"Blueprint: {record.get('blueprint_name', '—')} · ID: {record.get('blueprint_id', '—')}"
                )
                stored_path = Path(str(record.get("path") or ""))
                content = read_script_document(record)
                if content:
                    document_id = str(record.get("id") or "")
                    edit_key = f"editing_script_{document_id}"
                    if st.session_state.get(edit_key):
                        edited_content = st.text_area("Markdown editável", value=content, height=320, key=f"stored_script_edit_{document_id}")
                        edit_save_col, edit_cancel_col = st.columns(2, gap="small")
                        with edit_save_col:
                            if st.button("Guardar edição", type="primary", width="stretch", key=f"save_script_edit_{document_id}"):
                                try:
                                    update_script_document(document_id, edited_content)
                                    st.session_state.pop(edit_key, None)
                                    st.success("Roteiro actualizado.")
                                    st.rerun()
                                except (FileNotFoundError, OSError, ValueError) as exc:
                                    st.error(f"Não foi possível actualizar o roteiro: {exc}")
                        with edit_cancel_col:
                            if st.button("Cancelar edição", width="stretch", key=f"cancel_script_edit_{document_id}"):
                                st.session_state.pop(edit_key, None)
                                st.rerun()
                    else:
                        st.text_area("Conteúdo", value=content, height=220, key=f"stored_script_{document_id}")
                    if stored_path.is_file():
                        download_col, edit_col, delete_col = st.columns([1.25, 0.75, 0.75], gap="small")
                        with download_col:
                            st.download_button("Descarregar Markdown", data=stored_path.read_bytes(), file_name=stored_path.name, mime="text/markdown", key=f"download_script_{document_id}", width="stretch")
                        with edit_col:
                            if st.button("Editar", key=f"edit_script_{document_id}", width="stretch"):
                                st.session_state[edit_key] = True
                                st.rerun()
                        with delete_col:
                            confirm_delete_key = f"confirm_delete_script_{document_id}"
                            if st.button("Apagar", key=f"delete_script_{document_id}", type="primary", width="stretch"):
                                st.session_state[confirm_delete_key] = True
                                st.rerun()
                        if st.session_state.get(confirm_delete_key):
                            st.warning("Apagar este roteiro do histórico e do storage?")
                            confirm_col, cancel_col = st.columns(2, gap="small")
                            with confirm_col:
                                if st.button("Confirmar apagar", key=f"confirm_delete_script_button_{document_id}", type="primary", width="stretch"):
                                    try:
                                        delete_script_document(document_id)
                                        st.session_state.pop(confirm_delete_key, None)
                                        st.rerun()
                                    except (OSError, ValueError) as exc:
                                        st.error(f"Não foi possível apagar o roteiro: {exc}")
                            with cancel_col:
                                if st.button("Cancelar", key=f"cancel_delete_script_{document_id}", width="stretch"):
                                    st.session_state.pop(confirm_delete_key, None)
                                    st.rerun()
                else:
                    st.warning("O ficheiro deste registo já não está disponível no storage.")


def render_niche_finder():
    st.title("Niche Finder Kaggle")
    st.caption("Analisa o dataset no Kaggle e descarrega apenas os três CSVs de resultados para o Thunderbolt.")
    st.info("A kernel é publicada e executada remotamente. O Thunderbolt não usa CLI, não grava kaggle.json e só valida as credenciais quando solicita uma acção.")
    settings = read_json("settings.json", {})
    username = str(settings.get("kaggle_username") or "").strip()
    api_key = str(settings.get("kaggle_api_key") or "").strip()
    kernel_slug = str(settings.get("kaggle_kernel_slug") or "thunderbolt-niche-finder").strip()
    with st.container(border=True):
        st.subheader("Parâmetros da análise remota")
        with st.form("niche_finder_parameters", clear_on_submit=False):
            parameter_cols = st.columns(2)
            with parameter_cols[0]:
                n_clusters = st.slider("Número de Clusters", 2, 10, 5, key="niche_n_clusters")
            with parameter_cols[1]:
                min_support = st.slider("Suporte Mínimo", 0.01, 0.5, 0.05, 0.01, format="%.2f", key="niche_min_support")
            force_rerun = st.checkbox("Forçar nova execução remota", value=False, key="niche_force_remote")
            analyse = st.form_submit_button("Analisar Nichos", type="primary", width="stretch")
    current_parameters = {
        "n_clusters": n_clusters,
        "min_support": min_support,
        "username": username,
        "kernel_slug": kernel_slug,
    }
    results = st.session_state.get("niche_results")
    if analyse:
        try:
            with st.spinner("A publicar e executar a kernel Kaggle…"):
                results = load_analysis_data(
                    use_remote=True,
                    username=username,
                    api_key=api_key,
                    kernel_slug=kernel_slug,
                    force_rerun=force_rerun,
                    n_clusters=n_clusters,
                    min_support=min_support,
                )
            st.session_state["niche_results"] = results
            st.session_state["niche_last_parameters"] = current_parameters
            niche_key = hashlib.sha1(json.dumps(current_parameters, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
            summary = results.get("summary", {}) if isinstance(results, dict) else {}
            record_notification("niche_analysis_completed", "Análise de nicho concluída", "A análise Kaggle remota terminou com resultados prontos para consulta.", metadata={"source": "Kaggle remote", "rows_filtered": summary.get("rows_filtered", 0)}, dedupe_key=f"niche:kaggle:{niche_key}")
            st.success("Análise remota concluída.")
        except (KaggleNicheError, DatasetError, OSError, ValueError) as exc:
            st.error("Não foi possível concluir a análise Kaggle com a configuração actual.")
            with st.expander("Detalhes técnicos"):
                st.caption(str(exc))
            return
    if results is None:
        st.caption("Ainda não existe uma análise nesta sessão. Configure os três campos Kaggle em Configurações e clique em **Analisar Nichos**.")
        return
    if st.session_state.get("niche_last_parameters") != current_parameters:
        st.warning("Os resultados apresentados pertencem à última análise executada. Clique em **Analisar Nichos** para aplicar os parâmetros actuais.")
    summary = results.get("summary", {})
    metric_cols = st.columns(4)
    for col, (label, value) in zip(metric_cols, [("Registos analisados", summary.get("rows_filtered", 0)), ("Clusters", summary.get("cluster_count", 0)), ("Itemsets frequentes", summary.get("frequent_item_count", 0)), ("Regras de associação", summary.get("association_rule_count", 0))]):
        with col:
            card(label, value)
    cluster_table = results["clusters"]
    rules_table = results["association_rules"]
    items_table = results["frequent_items"]
    tab_clusters, tab_rules, tab_data = render_localized_tabs(["Clusters encontrados", "Regras de associação", "Dados analisados"])
    with tab_clusters:
        st.dataframe(cluster_table, width="stretch", hide_index=True)
    with tab_rules:
        if rules_table.empty:
            st.info("Não foram encontradas regras com os parâmetros actuais.")
        else:
            st.dataframe(rules_table, width="stretch", hide_index=True)
        if not items_table.empty:
            st.subheader("Itemsets frequentes")
            st.dataframe(items_table, width="stretch", hide_index=True)
    with tab_data:
        st.info("A kernel remota devolve apenas clusters, itemsets frequentes e regras de associação; o dataset permanece no Kaggle.")

def render_niche_finder_apify():
    st.title("Niche Finder Apify")
    st.caption("Alternativa independente ao Niche Finder Kaggle: pesquisa vídeos outlier no YouTube através do actor Apify e organiza dados, legendas e estrutura dos vídeos.")
    st.info("Esta página não usa o dataset, os filtros, a execução ou os resultados do Kaggle. A instalação das dependências é automática, mas a operação é manual: defina os parâmetros nesta aba e clique em **Pesquisar no Apify** para iniciar.")
    settings = read_json("settings.json", {})

    active_run = st.session_state.get("niche_apify_active_run")
    if active_run:
        st.warning(f"Existe uma execução Apify pendente: `{active_run.get('run_id', 'sem ID')}`.")
        if st.button("Cancelar execução actual", key="niche_apify_cancel"):
            try:
                abort_actor_run(settings.get("apify_api_token", ""), active_run.get("run_id", ""))
                st.session_state.pop("niche_apify_active_run", None)
                st.success("Execução Apify cancelada.")
                st.rerun()
            except ApifyError as exc:
                st.error(str(exc))

    with st.container(border=True):
        st.subheader("Parâmetros da pesquisa")
        with st.form("niche_apify_parameters", clear_on_submit=False):
            keyword_cols = st.columns(3)
            with keyword_cols[0]:
                keyword1 = st.text_input("Palavra-chave 1", key="niche_apify_keyword1", placeholder="Ex.: healthy food")
            with keyword_cols[1]:
                keyword2 = st.text_input("Palavra-chave 2", key="niche_apify_keyword2", placeholder="Ex.: meal prep healthy")
            with keyword_cols[2]:
                keyword3 = st.text_input("Palavra-chave 3", key="niche_apify_keyword3", placeholder="Ex.: high protein snack")
            search_cols = st.columns(4)
            with search_cols[0]:
                date_filter = st.selectbox("Período", ["week", "month", "3months", "year", "all"], index=0, key="niche_apify_date_filter")
            with search_cols[1]:
                max_results = st.number_input("Máximo por pesquisa", min_value=1, max_value=100, value=3, step=1, key="niche_apify_max_results")
            with search_cols[2]:
                max_results_shorts = st.number_input("Máximo de Shorts", min_value=0, max_value=100, value=0, step=1, key="niche_apify_max_results_shorts")
            with search_cols[3]:
                length_filter = st.selectbox("Duração", ["between420", "any", "short", "long"], index=0, key="niche_apify_length_filter")
            filter_cols = st.columns(4)
            with filter_cols[0]:
                subtitles_language = st.selectbox("Idioma das legendas", ["en", "pt", "es", "fr", "de"], index=0, key="niche_apify_subtitles_language")
            with filter_cols[1]:
                sorting_order = st.selectbox("Ordenação", ["relevance", "date", "viewCount", "rating"], index=0, key="niche_apify_sorting_order")
            with filter_cols[2]:
                download_subtitles = st.checkbox("Descarregar legendas", value=True, key="niche_apify_download_subtitles")
            with filter_cols[3]:
                has_cc = st.checkbox("Apenas vídeos com CC", value=False, key="niche_apify_has_cc")
            analyse_apify = st.form_submit_button("Pesquisar no Apify", type="primary", width="stretch")

    if analyse_apify:
        try:
            actor_input = build_actor_input(
                [keyword1, keyword2, keyword3],
                date_filter=date_filter,
                max_results=int(max_results),
                max_results_shorts=int(max_results_shorts),
                length_filter=length_filter,
                subtitles_language=subtitles_language,
                download_subtitles=download_subtitles,
                sorting_order=sorting_order,
                has_cc=has_cc,
            )
            token = str(settings.get("apify_api_token", "") or "").strip()
            actor_id = str(settings.get("apify_actor_id", DEFAULT_ACTOR_ID) or DEFAULT_ACTOR_ID).strip()
            st.session_state["niche_apify_active_run"] = {"run_id": "a iniciar", "started_at": now()}
            progress = st.progress(0, text="A iniciar o actor Apify…")
            run = start_actor_run(token, actor_id, actor_input)
            st.session_state["niche_apify_active_run"] = {"run_id": run.run_id, "started_at": now(), "status": run.status}
            progress.progress(15, text=f"Actor iniciado: {run.run_id}. A aguardar dataset…")

            def update_progress(current_run):
                st.session_state["niche_apify_active_run"] = {"run_id": current_run.run_id, "started_at": st.session_state["niche_apify_active_run"].get("started_at", now()), "status": current_run.status}
                progress.progress(35 if current_run.status not in {"SUCCEEDED"} else 55, text=f"Estado Apify: {current_run.status}")

            finished = wait_for_actor_run(
                token,
                run,
                poll_interval=int(settings.get("apify_poll_interval_seconds", 10)),
                timeout_seconds=int(settings.get("apify_run_timeout_seconds", 900)),
                on_status=update_progress,
            )
            progress.progress(60, text="Dataset recebido. A carregar vídeos…")
            raw_items = get_dataset_items(token, finished.dataset_id, limit=int(max_results) * max(1, len([value for value in [keyword1, keyword2, keyword3] if value.strip()])))
            items = normalize_video_items(raw_items)
            progress.progress(70, text=f"{len(items)} vídeo(s) carregado(s). A preparar transcrições…")
            items = summarize_items(items, settings, on_item=lambda current, total, item: progress.progress(70 + int((current / max(total, 1)) * 25), text=f"A resumir vídeo {current}/{total}…"))
            st.session_state["niche_apify_results"] = items
            st.session_state["niche_apify_last_run"] = {"run_id": finished.run_id, "status": finished.status, "dataset_id": finished.dataset_id, "created_at": now(), "item_count": len(items), "parameters": actor_input}
            history = read_json("niche_apify_runs.json", [])
            if not isinstance(history, list):
                history = []
            history.insert(0, st.session_state["niche_apify_last_run"])
            write_json("niche_apify_runs.json", history[:20])
            record_notification("niche_analysis_completed", "Análise de nicho concluída", f"A pesquisa Apify terminou com {len(items)} vídeo(s) recebido(s).", metadata={"run_id": finished.run_id, "item_count": len(items)}, dedupe_key=f"niche:apify:{finished.run_id}")
            st.session_state.pop("niche_apify_active_run", None)
            progress.progress(100, text="Pesquisa Apify concluída.")
            st.success(f"Pesquisa concluída: {len(items)} vídeo(s) recebido(s).")
        except ApifyError as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"A pesquisa Apify terminou com um erro inesperado: {exc}")

    results = st.session_state.get("niche_apify_results", [])
    if not results:
        st.caption("Ainda não existe uma pesquisa nesta sessão. Ajuste os parâmetros e clique em **Pesquisar no Apify**.")
        return

    st.subheader("Vídeos encontrados")
    result_filter = st.text_input("Filtrar resultados", placeholder="Título, canal ou palavra no resumo", key="niche_apify_result_filter")
    status_filter = st.selectbox("Estado da sumarização", ["Todos", "concluído", "sem transcrição", "não aplicável", "erro"], key="niche_apify_status_filter")
    visible_results = results
    if result_filter.strip():
        term = result_filter.strip().casefold()
        visible_results = [item for item in visible_results if term in str(item.get("title", "")).casefold() or term in str(item.get("channel_name", "")).casefold() or term in str(item.get("summary", "")).casefold()]
    if status_filter != "Todos":
        visible_results = [item for item in visible_results if str(item.get("summary_status", "")).startswith(status_filter)]
    try:
        import pandas as pd
        result_frame = pd.DataFrame(visible_results)
        display_columns = ["title", "channel_name", "duration", "view_count", "subscriber_count", "comments_count", "vsc_ratio", "url", "transcript_status", "summary_status", "summary"]
        display_columns = [column for column in display_columns if column in result_frame.columns]
        st.dataframe(result_frame[display_columns], width="stretch", hide_index=True)
        export_frame = result_frame.drop(columns=["transcript"], errors="ignore")
        export_json = export_frame.to_json(orient="records", force_ascii=False, indent=2)
        export_csv = export_frame.to_csv(index=False).encode("utf-8")
        export_cols = st.columns(2)
        with export_cols[0]:
            st.download_button("Exportar JSON", data=export_json, file_name="niche-finder-apify-results.json", mime="application/json", width="stretch", key="niche_apify_export_json")
        with export_cols[1]:
            st.download_button("Exportar CSV", data=export_csv, file_name="niche-finder-apify-results.csv", mime="text/csv", width="stretch", key="niche_apify_export_csv")
    except ImportError:
        st.dataframe(visible_results, width="stretch", hide_index=True)

    last_run = st.session_state.get("niche_apify_last_run", {})
    if last_run:
        with st.expander("Detalhes da última execução"):
            st.json({key: value for key, value in last_run.items() if key != "parameters"})


def render_edit_placeholder(page_title: str, description: str):
    st.title(page_title)
    st.caption(description)
    st.info("Esta aba está reservada para desenvolvimento futuro e ainda não executa nenhuma operação.")


def render_media_download():
    st.title("Download Mídia")
    st.caption("Baixe vídeos e áudio de URLs públicas através da API oficial do yt-dlp. Use esta ferramenta apenas com conteúdo que tem autorização para descarregar e utilizar.")
    st.markdown("Baseado em [yt-dlp](https://github.com/yt-dlp/yt-dlp), um downloader open source para vídeo e áudio.")
    dependency = dependency_status()
    if not dependency["yt_dlp"]:
        st.warning("yt-dlp não está instalado neste ambiente. Execute a instalação das dependências do Thunderbolt antes de iniciar um download.")
    st.info("A combinação de streams, conversão de áudio e incorporação de metadados pode exigir FFmpeg. Downloads longos permanecem nesta página até terminarem.")

    with st.form("media_download_form", enter_to_submit=False):
        urls_text = st.text_area("URLs para descarregar", placeholder="Uma URL http(s) por linha", height=120, key="media_download_urls")
        mode_label = st.selectbox("Tipo de mídia", ["Vídeo", "Áudio", "Imagem"], key="media_download_mode")
        option_cols = st.columns(3)
        allow_playlist = False
        download_subtitles = False
        embed_metadata = False
        with option_cols[0]:
            if mode_label == "Vídeo":
                quality_label = st.selectbox("Qualidade", list(VIDEO_QUALITY_OPTIONS), key="media_download_quality")
                video_container = st.selectbox("Contentor", list(VIDEO_CONTAINERS), key="media_download_container")
                audio_format = "mp3"
            elif mode_label == "Áudio":
                quality_label = "Melhor qualidade"
                video_container = "mp4"
                audio_format = st.selectbox("Formato de áudio", list(AUDIO_FORMATS), key="media_download_audio_format")
            else:
                quality_label = st.selectbox("Qualidade", list(IMAGE_QUALITY_OPTIONS), key="media_download_image_quality")
                video_container = st.selectbox("Contentor", list(IMAGE_CONTAINERS), key="media_download_image_container")
                audio_format = "mp3"
        if mode_label == "Vídeo":
            with option_cols[1]:
                allow_playlist = st.checkbox("Permitir playlist", value=False, key="media_download_allow_playlist")
                download_subtitles = st.checkbox("Descarregar legendas", value=False, key="media_download_subtitles")
            with option_cols[2]:
                embed_metadata = st.checkbox("Incorporar metadados", value=False, key="media_download_embed_metadata")
                st.caption("Playlist desactivada por padrão para evitar downloads acidentais em massa.")
        elif mode_label == "Áudio":
            with option_cols[1]:
                allow_playlist = st.checkbox("Permitir playlist", value=False, key="media_download_allow_playlist")
            with option_cols[2]:
                embed_metadata = st.checkbox("Incorporar metadados", value=False, key="media_download_embed_metadata")
        else:
            st.caption("Imagens: apenas qualidade e contentor de imagem são aplicáveis.")
        start_download = st.form_submit_button("Iniciar Download", type="primary", width="stretch")

    if start_download:
        progress = st.progress(0, text="A preparar o download…")
        progress_status = st.empty()

        def on_progress(payload: dict[str, Any]) -> None:
            value = float(payload.get("progress") or 0)
            progress.progress(int(max(0, min(100, value))), text=f"{payload.get('status', 'processing').capitalize()} · {payload.get('current_file') or payload.get('display_url') or 'a processar'}")
            progress_status.caption(str(payload.get("hook_status") or payload.get("status") or "processing"))

        try:
            results = download_media(
                urls_text,
                mode={"Vídeo": "video", "Áudio": "audio", "Imagem": "image"}[mode_label],
                quality=quality_label,
                container=video_container,
                audio_format=audio_format,
                allow_playlist=allow_playlist,
                download_subtitles=download_subtitles,
                embed_metadata=embed_metadata,
                progress_callback=on_progress,
            )
            st.session_state["media_download_last_results"] = results
            completed = sum(1 for item in results if item.get("status") == "completed")
            failed = len(results) - completed
            if completed:
                st.success(f"{completed} download(s) concluído(s) e guardado(s) em `{MEDIA_DOWNLOADS}`.")
            if failed:
                st.warning(f"{failed} download(s) terminou/terminaram com erro. Consulte o histórico abaixo.")
        except (MediaDownloadError, ValueError, OSError) as exc:
            progress.empty()
            st.error(str(exc))

    latest_results = st.session_state.get("media_download_last_results", [])
    if latest_results:
        st.subheader("Resultado da última execução")
        for record in latest_results:
            with st.container(border=True):
                status_label = "Concluído" if record.get("status") == "completed" else "Falhou"
                st.write(f"**{record.get('title') or record.get('display_url') or 'Download'}** — {status_label}")
                st.caption(f"{record.get('display_url', 'URL não disponível')} · {record.get('mode', 'video')} · {record.get('completed_at') or record.get('created_at', '—')}")
                if record.get("error"):
                    st.error(record["error"])
                for filename in record.get("files", []):
                    output = media_download_file(record, str(filename))
                    if output:
                        mime = "audio/*" if record.get("mode") == "audio" else ("image/*" if record.get("mode") == "image" else "video/*")
                        st.download_button("Descarregar ficheiro", data=output.read_bytes(), file_name=output.name, mime=mime, key=f"media_result_{record.get('operation_id')}_{filename}")

    st.divider()
    if st.button("Abrir pasta de downloads", key="media_download_open_folder", width="stretch"):
        try:
            if os.name == "nt":
                os.startfile(str(MEDIA_DOWNLOADS))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(MEDIA_DOWNLOADS)])
            else:
                subprocess.Popen(["xdg-open", str(MEDIA_DOWNLOADS)])
        except OSError as exc:
            st.error(f"Não foi possível abrir a pasta de downloads: {exc}")
        else:
            st.success(f"Pasta de downloads aberta: `{MEDIA_DOWNLOADS}`")
    st.subheader("Histórico de downloads")
    history = list_media_downloads()
    action_cols = st.columns([1, 1, 3])
    with action_cols[0]:
        if st.button("Actualizar histórico", key="media_download_refresh"):
            st.rerun()
    with action_cols[1]:
        clear_requested = st.button("Limpar histórico", key="media_download_clear")
    if clear_requested:
        st.session_state["media_download_confirm_clear"] = True
    if st.session_state.get("media_download_confirm_clear"):
        st.warning("Isto remove apenas o histórico, não os ficheiros guardados em storage/downloads.")
        confirm_cols = st.columns(2)
        with confirm_cols[0]:
            if st.button("Confirmar limpeza", type="primary", key="media_download_confirm_clear_button"):
                clear_media_download_history()
                st.session_state.pop("media_download_confirm_clear", None)
                st.rerun()
        with confirm_cols[1]:
            if st.button("Cancelar", key="media_download_cancel_clear_button"):
                st.session_state.pop("media_download_confirm_clear", None)
                st.rerun()
    if not history:
        st.caption("Ainda não existem downloads registados.")
    for record in history:
        status_label = {"completed": "Concluído", "failed": "Falhou", "processing": "Em processamento"}.get(str(record.get("status")), str(record.get("status") or "—"))
        with st.expander(f"{record.get('title') or record.get('display_url') or 'Download'} — {status_label}", expanded=False):
            st.caption(f"{record.get('display_url', 'URL não disponível')} · {record.get('mode', 'video')} · {record.get('created_at', '—')}")
            if record.get("error"):
                st.error(record["error"])
            for filename in record.get("files", []):
                output = media_download_file(record, str(filename))
                if output:
                    mime = "audio/*" if record.get("mode") == "audio" else ("image/*" if record.get("mode") == "image" else "video/*")
                    st.download_button("Descarregar", data=output.read_bytes(), file_name=output.name, mime=mime, key=f"media_history_{record.get('operation_id')}_{filename}")


def render_cuts():
    st.title("Cortes")
    st.caption("Crie clips verticais, quadrados ou horizontais a partir de vídeos longos, sem sobrescrever a fonte.")

    source_path = None
    source_tab, url_tab, generated_tab, folder_tab = render_localized_tabs(["Upload ficheiro", "URL de vídeo", "Vídeos gerados", "Pasta local"])
    with source_tab:
        uploaded_video = st.file_uploader(
            "Clique para carregar ou arraste um vídeo",
            type=sorted(extension.lstrip(".") for extension in VIDEO_EXTENSIONS),
            key="cuts_video_upload",
            help="MP4, MOV, MKV, WEBM e formatos suportados pelo FFmpeg. O original fica preservado.",
        )
        if uploaded_video is not None:
            try:
                source_path = store_uploaded_video(uploaded_video.name, uploaded_video.getvalue())
                st.session_state["cuts_source_path"] = str(source_path)
                st.session_state["cuts_source_label"] = f"Upload · {uploaded_video.name}"
            except CutsError as exc:
                st.error(str(exc))
    with url_tab:
        url_value = st.text_input("URL directa do vídeo", placeholder="https://exemplo.com/video.mp4", key="cuts_video_url")
        st.caption("A URL deve apontar directamente para um ficheiro de vídeo HTTP/HTTPS. O download só ocorre depois de clicar no botão.")
        if st.button("Descarregar vídeo", key="cuts_download_url", width="stretch"):
            try:
                source_path = download_direct_video_url(url_value)
                st.session_state["cuts_source_path"] = str(source_path)
                st.session_state["cuts_source_label"] = f"URL · {url_value}"
                st.success("Vídeo descarregado e pronto para análise.")
            except CutsError as exc:
                st.error(str(exc))
    with generated_tab:
        generated_paths = list_cut_generated_videos(read_json("tasks.json", []))
        if not generated_paths:
            st.info("Ainda não existem vídeos prontos na pipeline.")
        else:
            st.caption(f"{len(generated_paths)} vídeo(s) pronto(s) disponível(is).")
            for index, generated_path in enumerate(generated_paths):
                with st.expander(generated_path.stem, expanded=False):
                    card_cols = st.columns([1.35, 2.4, 1.1])
                    with card_cols[0]:
                        thumbnail = _video_thumbnail(generated_path)
                        if thumbnail:
                            st.image(thumbnail, width="stretch")
                        else:
                            st.video(str(generated_path))
                    with card_cols[1]:
                        st.markdown(f"**{generated_path.stem}**")
                        st.caption(f"Vídeo pronto · {generated_path.suffix.lstrip('.').upper()}")
                        st.caption(f"{generated_path.stat().st_size / (1024 * 1024):.2f} MB")
                    with card_cols[2]:
                        if st.button("Usar vídeo", key=f"cuts_use_generated_{index}_{_library_card_key('cuts', generated_path)}", type="primary", width="stretch"):
                            st.session_state["cuts_source_path"] = str(generated_path)
                            st.session_state["cuts_source_label"] = f"Pipeline · {generated_path.stem}"
                            st.rerun()
    with folder_tab:
        folder_value = st.text_input("Pasta de vídeos", value=str(STORAGE / "videos"), key="cuts_video_folder")
        folder_paths = list_cut_video_files(folder_value)
        if not folder_paths:
            st.info("Não foram encontrados vídeos nessa pasta.")
        else:
            folder_labels = [f"{path.name} — {path}" for path in folder_paths]
            selected_folder = st.selectbox("Vídeo da pasta", range(len(folder_paths)), format_func=lambda index: folder_labels[index], key="cuts_folder_index")
            if st.button("Usar vídeo da pasta", key="cuts_use_folder", width="stretch"):
                source_path = folder_paths[selected_folder]
                st.session_state["cuts_source_path"] = str(source_path)
                st.session_state["cuts_source_label"] = f"Pasta local · {source_path.name}"

    stored_source = st.session_state.get("cuts_source_path", "")
    if not source_path and stored_source:
        candidate = Path(stored_source)
        if candidate.is_file():
            source_path = candidate
    if source_path and source_path.is_file():
        st.markdown(f"**Fonte seleccionada:** `{st.session_state.get('cuts_source_label', source_path.name)}`")
        source_cols = st.columns([1.4, 1])
        with source_cols[0]:
            st.video(str(source_path))
        with source_cols[1]:
            st.caption(f"{source_path.name}")
            st.caption(f"{source_path.stat().st_size / (1024 * 1024):.2f} MB")
            st.caption("A fonte original não é alterada.")
    else:
        st.info("Escolha um ficheiro, descarregue uma URL, seleccione um vídeo gerado ou indique uma pasta local.")

    with st.container(border=True):
        st.markdown("**Output format**")
        format_options = ["9:16", "1:1", "16:9"]
        output_format = st.radio(
            "Formato de saída",
            format_options,
            format_func=lambda value: {"9:16": "9:16\\nShorts · Reels · TikTok", "1:1": "1:1\\nFeed posts", "16:9": "16:9\\nYouTube · landscape"}[value],
            horizontal=True,
            key="cuts_output_format",
            label_visibility="collapsed",
        )
        with st.expander("advanced options", expanded=False):
            strategy_label = st.selectbox("Estratégia", ["Automático · segmentos locais", "Manual · um intervalo"], key="cuts_strategy")
            strategy = "manual" if strategy_label.startswith("Manual") else "automatic"
            options_cols = st.columns(3)
            with options_cols[0]:
                max_clips = st.number_input("Número máximo de clips", min_value=1, max_value=20, value=3, step=1, key="cuts_max_clips")
            with options_cols[1]:
                min_duration = st.number_input("Duração mínima (s)", min_value=1.0, max_value=600.0, value=15.0, step=1.0, key="cuts_min_duration")
            with options_cols[2]:
                max_duration = st.number_input("Duração máxima (s)", min_value=1.0, max_value=600.0, value=60.0, step=1.0, key="cuts_max_duration")
            manual_start = manual_end = 0.0
            if strategy == "manual":
                manual_cols = st.columns(2)
                with manual_cols[0]:
                    manual_start = st.number_input("Início do intervalo (s)", min_value=0.0, value=0.0, step=0.5, key="cuts_manual_start")
                with manual_cols[1]:
                    manual_end = st.number_input("Fim do intervalo (s)", min_value=0.5, value=30.0, step=0.5, key="cuts_manual_end")
            st.caption("O modo automático cria segmentos locais distribuídos pelo vídeo. A selecção viral por IA fica disponível como extensão quando houver transcrição/provider configurado.")

        rights_confirmed = st.checkbox(
            "Confirmo que possuo os direitos ou autorização para processar este conteúdo.",
            key="cuts_rights_confirmed",
        )
        generate_button = st.button(
            "Gerar Clips",
            type="primary",
            width="stretch",
            disabled=not (source_path and source_path.is_file() and rights_confirmed),
            key="cuts_generate_button",
        )

    if generate_button and source_path and source_path.is_file():
        settings = read_json("settings.json", {})
        with st.status("A analisar e a gerar clips…", expanded=True) as status:
            st.write("A validar fonte e parâmetros…")
            try:
                record = generate_clips(
                    source_path,
                    output_format=output_format,
                    strategy=strategy,
                    max_clips=int(max_clips),
                    min_duration=float(min_duration),
                    max_duration=float(max_duration),
                    rights_confirmed=rights_confirmed,
                    ffmpeg_path=settings.get("ffmpeg_path", ""),
                    manual_start=float(manual_start),
                    manual_end=float(manual_end) if strategy == "manual" else None,
                )
                st.session_state["cuts_last_run"] = record
                status.update(label="Clips gerados", state="complete", expanded=False)
            except CutsError as exc:
                status.update(label="A geração falhou", state="error", expanded=True)
                st.error(str(exc))

    last_run = st.session_state.get("cuts_last_run")
    if last_run:
        st.divider()
        status_label = {"complete": "CONCLUÍDO", "processing": "A PROCESSAR", "error": "ERRO"}.get(last_run.get("status"), str(last_run.get("status", "—")).upper())
        st.markdown(f"### Live Analysis · `{status_label}`")
        if last_run.get("status") == "complete":
            clips = [clip for clip in last_run.get("clips", []) if Path(str(clip.get("path", ""))).is_file()]
            result_cols = st.columns([3, 1, 1])
            with result_cols[0]:
                st.subheader("Generated Shorts")
            with result_cols[1]:
                st.metric("Clips", len(clips))
            with result_cols[2]:
                st.metric("Formato", last_run.get("output_format", "—"))
            for index in range(0, len(clips), 3):
                clip_cols = st.columns(3)
                for col, clip in zip(clip_cols, clips[index:index + 3]):
                    with col:
                        with st.container(border=True):
                            st.caption(f"Clip {clip.get('index', '—')} · {float(clip.get('duration', 0)):.1f}s")
                            st.video(str(clip["path"]))
                            st.download_button("Descarregar clip", data=Path(clip["path"]).read_bytes(), file_name=clip["name"], mime="video/mp4", key=f"cuts_download_{last_run['id']}_{clip['index']}", width="stretch")
            try:
                _, archive_bytes = zip_cut_run(last_run)
                st.download_button("Descarregar todos os clips (ZIP)", data=archive_bytes, file_name=f"{last_run['id']}.zip", mime="application/zip", key=f"cuts_download_zip_{last_run['id']}", width="stretch")
            except CutsError as exc:
                st.warning(str(exc))
            st.download_button("Descarregar manifesto JSON", data=cut_manifest_bytes(last_run), file_name=f"{last_run['id']}.json", mime="application/json", key=f"cuts_download_manifest_{last_run['id']}", width="stretch")
        elif last_run.get("error"):
            st.error(last_run["error"])

    runs = list_cut_runs()
    if runs:
        with st.expander("Histórico do Clip Generator"):
            st.dataframe(
                [{"Data": run.get("created_at", "—"), "Fonte": run.get("source_name", "—"), "Formato": run.get("output_format", "—"), "Clips": len(run.get("clips", [])), "Estado": run.get("status", "—")} for run in runs[:20]],
                width="stretch",
                hide_index=True,
            )


def render_python_editor():
    st.title("Editor Python")
    st.caption("Editor local inspirado no PYEdit para scripts Python e edição manual de vídeos do Thunderbolt.")
    st.info("Escolha um vídeo gerado, indique uma pasta local ou faça upload de um vídeo. Nenhum código Python é executado nesta aba; as operações de vídeo só começam depois de clicar no botão da operação.")

    video_tab, code_tab = render_localized_tabs(["Vídeos", "Código Python"])
    with video_tab:
        st.subheader("Escolher vídeo")
        source_mode = st.radio("Origem", ["Vídeos gerados", "Pasta local", "Upload manual"], horizontal=True, key="python_editor_source_mode")
        source_path = None
        if source_mode == "Vídeos gerados":
            tasks = read_json("tasks.json", [])
            generated_paths = list_generated_videos(tasks)
            if not generated_paths:
                st.info("Ainda não existem vídeos prontos nos artefactos da pipeline.")
            else:
                st.caption("Seleccione um vídeo pronto na pipeline.")
                for index, generated_path in enumerate(generated_paths):
                    with st.expander(generated_path.stem, expanded=False):
                        card_cols = st.columns([1.35, 2.4, 1.1])
                        with card_cols[0]:
                            thumbnail = _video_thumbnail(generated_path)
                            if thumbnail:
                                st.image(thumbnail, width="stretch")
                            else:
                                st.video(str(generated_path))
                        with card_cols[1]:
                            st.markdown(f"**{generated_path.stem}**")
                            st.caption(f"Vídeo pronto · {generated_path.suffix.lstrip('.').upper()}")
                        with card_cols[2]:
                            if st.button("Editar vídeo", key=f"python_use_generated_{index}_{_library_card_key('python', generated_path)}", type="primary", width="stretch"):
                                st.session_state["python_editor_source_path"] = str(generated_path)
                                st.rerun()
                stored_generated = Path(str(st.session_state.get("python_editor_source_path") or ""))
                if stored_generated.is_file() and stored_generated in generated_paths:
                    source_path = stored_generated
        elif source_mode == "Pasta local":
            default_folder = str(STORAGE / "videos")
            folder_value = st.text_input("Pasta de vídeos", value=st.session_state.get("python_editor_folder", default_folder), key="python_editor_folder")
            folder_paths = list_video_files(folder_value)
            if not folder_paths:
                st.info("Não foram encontrados vídeos nessa pasta. Pode indicar a pasta de vídeos gerados ou qualquer outra pasta local.")
            else:
                labels = [f"{path.name} — {path}" for path in folder_paths]
                selected_index = st.selectbox("Vídeo da pasta", range(len(folder_paths)), format_func=lambda index: labels[index], key="python_editor_folder_index")
                source_path = folder_paths[selected_index]
        else:
            uploaded_video = st.file_uploader("Subir vídeo para editar", type=sorted(extension.lstrip(".") for extension in VIDEO_EXTENSIONS), key="python_editor_video_upload")
            if uploaded_video is not None:
                try:
                    source_path = store_uploaded_asset(uploaded_video.name, uploaded_video.getvalue())
                except PythonEditorError as exc:
                    st.error(str(exc))

        if source_path and source_path.is_file():
            st.session_state["python_editor_source_path"] = str(source_path)
            st.caption(f"Fonte seleccionada: `{source_path}` · {source_path.stat().st_size / (1024 * 1024):.2f} MB")
            st.video(str(source_path))
            st.divider()
            st.subheader("Operação PYEdit")
            operation_options = ["Cortar trecho", "Remover áudio", "Extrair áudio", "Substituir áudio", "Alterar velocidade", "Redimensionar vídeo"]
            operation = st.selectbox("Operação", operation_options, key="python_editor_operation")
            with st.form("python_editor_video_form", clear_on_submit=False):
                start_seconds = end_seconds = speed = None
                width = height = None
                replacement_audio = None
                if operation == "Cortar trecho":
                    op_cols = st.columns(2)
                    with op_cols[0]:
                        start_seconds = st.number_input("Início (segundos)", min_value=0.0, value=0.0, step=0.5, key="python_editor_trim_start")
                    with op_cols[1]:
                        end_seconds = st.number_input("Fim (segundos)", min_value=0.5, value=10.0, step=0.5, key="python_editor_trim_end")
                elif operation == "Substituir áudio":
                    replacement_audio = st.file_uploader("Novo áudio", type=sorted(extension.lstrip(".") for extension in AUDIO_EXTENSIONS), key="python_editor_audio_upload")
                    st.caption("O áudio substitui a faixa original e a duração final fica limitada ao menor fluxo.")
                elif operation == "Alterar velocidade":
                    speed = st.number_input("Velocidade", min_value=0.25, max_value=4.0, value=1.0, step=0.25, key="python_editor_speed")
                elif operation == "Redimensionar vídeo":
                    resize_cols = st.columns(2)
                    with resize_cols[0]:
                        width = st.number_input("Largura", min_value=16, max_value=7680, value=1280, step=2, key="python_editor_width")
                    with resize_cols[1]:
                        height = st.number_input("Altura", min_value=16, max_value=7680, value=720, step=2, key="python_editor_height")
                apply_operation = st.form_submit_button(f"Aplicar: {operation}", type="primary", width="stretch")
            if apply_operation:
                try:
                    ffmpeg_path = read_json("settings.json", {}).get("ffmpeg_path", "")
                    if operation == "Cortar trecho":
                        output, run_info = trim_video(source_path, float(start_seconds), float(end_seconds), ffmpeg_path=ffmpeg_path)
                    elif operation == "Remover áudio":
                        output, run_info = remove_audio(source_path, ffmpeg_path=ffmpeg_path)
                    elif operation == "Extrair áudio":
                        output, run_info = extract_audio(source_path, ffmpeg_path=ffmpeg_path)
                    elif operation == "Substituir áudio":
                        if replacement_audio is None:
                            raise PythonEditorError("Seleccione o novo áudio antes de aplicar a operação.")
                        audio_path = store_uploaded_asset(replacement_audio.name, replacement_audio.getvalue(), audio=True)
                        output, run_info = replace_audio(source_path, audio_path, ffmpeg_path=ffmpeg_path)
                    elif operation == "Alterar velocidade":
                        output, run_info = change_speed(source_path, float(speed), ffmpeg_path=ffmpeg_path)
                    else:
                        output, run_info = resize_video(source_path, int(width), int(height), ffmpeg_path=ffmpeg_path)
                    record = save_python_editor_record(source_path, output, run_info)
                    st.session_state["python_editor_last_record"] = record
                    st.success(f"Operação concluída: {output.name}")
                    if output.suffix.lower() in AUDIO_EXTENSIONS:
                        st.audio(output.read_bytes(), format="audio/mpeg")
                    else:
                        st.video(str(output))
                    st.download_button("Descarregar resultado", data=output.read_bytes(), file_name=output.name, mime="video/mp4" if output.suffix.lower() in VIDEO_EXTENSIONS else "audio/mpeg", key=f"python_editor_download_{record['id']}")
                    st.download_button("Descarregar manifesto JSON", data=editor_manifest(record), file_name=f"{output.stem}.json", mime="application/json", key=f"python_editor_manifest_{record['id']}")
                except (PythonEditorError, OSError, ValueError) as exc:
                    st.error(str(exc))
        else:
            st.caption("Seleccione uma fonte de vídeo para activar as operações inspiradas no PYEdit.")

        records = list_python_editor_records()
        if records:
            with st.expander("Histórico do Editor Python"):
                st.dataframe([{key: record.get(key, "") for key in ("created_at", "operation", "source_name", "output_name")} for record in records[:20]], width="stretch", hide_index=True)

    with code_tab:
        st.subheader("Scripts Python locais")
        st.warning("Por segurança, o Editor Python guarda e edita scripts, mas não oferece execução de código dentro da UI.")
        scripts = list_scripts()
        script_options = ["Novo script"] + [str(path.name) for path in scripts]
        selected_script = st.selectbox("Script", script_options, key="python_editor_script_name")
        if selected_script != "Novo script":
            selected_path = next((path for path in scripts if path.name == selected_script), None)
            if selected_path and st.button("Carregar script", key="python_editor_load_script"):
                st.session_state["python_editor_code"] = read_script(selected_path)
                st.rerun()
        with st.form("python_editor_code_form", clear_on_submit=False):
            script_name = st.text_input("Nome do script", value="script.py" if selected_script == "Novo script" else selected_script, key="python_editor_code_name")
            script_content = st.text_area("Código Python", value=st.session_state.get("python_editor_code", ""), height=420, key="python_editor_code_text")
            save_code = st.form_submit_button("Guardar script localmente", type="primary")
        if save_code:
            try:
                path = save_script(script_name, script_content)
                st.session_state["python_editor_code"] = script_content
                st.success(f"Script guardado em `{path}`.")
            except PythonEditorError as exc:
                st.error(str(exc))


_PIPELINE_STAGE_LABELS = {
    "niche": "Tema",
    "blueprint": "Blueprint",
    "brand": "Branding",
    "topic": "Tema",
    "script": "Roteiro",
    "title": "Título",
    "keywords": "Keywords",
    "thumbnail_prompt": "Prompt da thumbnail",
    "thumbnail": "Thumbnail",
    "video": "Vídeo",
    "edit": "Edição",
    "upload": "Upload",
    "idle": "A aguardar",
}


def _pipeline_progress_value(task: dict[str, Any]) -> int:
    try:
        return max(0, min(100, int(task.get("progress") or 0)))
    except (TypeError, ValueError):
        return 0


def _pipeline_stage_label(task: dict[str, Any]) -> str:
    stage = str(task.get("stage") or "pipeline")
    return _PIPELINE_STAGE_LABELS.get(stage, stage.replace("_", " ").title())


def _pipeline_time_age(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "sem actualização registada"
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        seconds = max(0, int((datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()))
    except ValueError:
        return f"última actualização: {text}"
    if seconds < 60:
        return f"actualizado há {seconds}s"
    if seconds < 3600:
        return f"actualizado há {seconds // 60}min"
    return f"actualizado há {seconds // 3600}h"


def _render_pipeline_worker_banner(worker_status: dict[str, Any], active_count: int) -> None:
    if worker_status.get("alive"):
        stage = _PIPELINE_STAGE_LABELS.get(str(worker_status.get("stage") or "idle"), str(worker_status.get("stage") or "idle"))
        progress = max(0, min(100, int(worker_status.get("progress") or 0)))
        st.success(f"Worker de vídeo activo · {active_count} tarefa(s) em execução · {stage} · {progress}%")
    else:
        st.warning("Worker de vídeo sem heartbeat recente. O launcher deve estar aberto para processar as tarefas.")
    heartbeat = worker_status.get("last_heartbeat_at") or worker_status.get("updated_at")
    if heartbeat:
        st.caption(f"{_pipeline_time_age(heartbeat)} · vídeo: até 90 min com watchdog de inactividade de 10 min")
    if worker_status.get("last_error"):
        st.error(f"Último erro do worker: {worker_status['last_error']}")


@st.fragment
def _render_pipeline_progress_panel() -> None:
    """Actualizar apenas o painel da pipeline enquanto existirem tarefas activas."""
    worker_status = load_pipeline_worker_status()
    tasks = read_json("tasks.json", [])
    active = [task for task in tasks if isinstance(task, dict) and str(task.get("state") or "") == "doing"]
    if not worker_status.get("alive") and active:
        recovered = recover_stale_tasks()
        if recovered:
            tasks = read_json("tasks.json", [])
            active = [task for task in tasks if isinstance(task, dict) and str(task.get("state") or "") == "doing"]
            worker_status = load_pipeline_worker_status()
    if not active:
        # O fragmento pode executar mais uma vez após o worker terminar.
        # Retornar mantém a actualização local e não reconstrói a página inteira.
        return
    _render_pipeline_worker_banner(worker_status, len(active))
    for task in active:
        progress = _pipeline_progress_value(task)
        label = str(task.get("title") or task.get("topic") or task.get("id") or "Vídeo")
        st.progress(progress, text=f"{label} · {_pipeline_stage_label(task)} · {progress}%")
        st.caption(f"{task.get('channel_name') or 'Canal'} · {_pipeline_time_age(task.get('updated_at'))}")
        if task.get("error"):
            st.error(str(task.get("error")))
VIDEO_TASK_STATE_LABELS = {
    "to_do": "Pendente",
    "doing": "Em execução",
    "blocked": "Bloqueado",
    "done": "Concluído",
    "failed": "Falha",
    "cancelled": "Cancelado",
}


def load_video_tasks_for_catalog() -> list[dict[str, Any]]:
    """Return the complete persisted task catalog shared by Backlog and Automation, including legacy storage locations and fields."""
    current = read_json("tasks.json", [])
    saved = current if isinstance(current, list) else []
    legacy_path = STORAGE / "tasks.json"
    if legacy_path.is_file():
        try:
            legacy_value = json.loads(legacy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            legacy_value = []
        if isinstance(legacy_value, list):
            saved = [*saved, *legacy_value]
    catalog: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_task in enumerate(saved):
        if not isinstance(raw_task, dict):
            continue
        task = dict(raw_task)
        artifacts = dict(task.get("artifacts") or {}) if isinstance(task.get("artifacts"), dict) else {}
        if not artifacts.get("video"):
            for name in ("video_path", "output_video", "video_file", "video"):
                if task.get(name):
                    artifacts["video"] = task.get(name)
                    break
        task["artifacts"] = artifacts
        task_id = str(task.get("id") or task.get("task_id") or "").strip()
        if not task_id:
            identity = str(artifacts.get("video") or task.get("title") or task.get("topic") or f"legacy-{index}")
            task_id = f"legacy-{hashlib.sha1(identity.encode('utf-8')).hexdigest()[:16]}"
        if task_id in seen_ids:
            continue
        seen_ids.add(task_id)
        task["id"] = task_id
        catalog.append(task)
    return catalog


def task_platform(task: dict[str, Any], channels_by_id: dict[str, dict[str, Any]] | None = None) -> str:
    """Resolve a plataforma da tarefa, incluindo tarefas legadas sem platform."""
    explicit = str(task.get("platform") or "").strip().casefold()
    if explicit in {"youtube", "yt"}:
        return "youtube"
    if explicit in {"tiktok", "tik-tok", "tt"}:
        return "tiktok"
    channel_id = str(task.get("channel_id") or "")
    if channel_id:
        channel = (channels_by_id or {}).get(channel_id)
        if channel is None:
            channel = next((item for item in read_json("channels.json", []) if isinstance(item, dict) and str(item.get("id")) == channel_id), None)
        if channel:
            return classify_channel_platform(channel)
    format_value = str(task.get("format") or "").strip().casefold()
    return "tiktok" if format_value in {"portrait", "portrait 9:16", "9:16"} else "youtube"


def _saved_script_task_matches(task: dict[str, Any], record: dict[str, Any], channel: dict[str, Any], content: str) -> bool:
    document_id = str(record.get("id") or "").strip()
    if document_id and str(task.get("script_document_id") or "").strip() == document_id:
        return True
    if str(task.get("topic_source") or "").strip() != "saved_script":
        return False
    if str(task.get("channel_id") or "").strip() != str(channel.get("id") or "").strip():
        return False
    generation_settings = task.get("generation_settings") if isinstance(task.get("generation_settings"), dict) else {}
    saved_content = str(generation_settings.get("video_script") or task.get("video_script") or "").strip()
    if saved_content and saved_content == content.strip():
        return True
    title = str(record.get("title") or "").strip()
    return bool(title and str(task.get("title") or task.get("topic") or "").strip() == title)


def _sync_saved_scripts_to_youtube_automation() -> None:
    """Expose every saved video script as one manual YouTube task, without duplicates."""
    source_records = list_script_documents()
    sync_signature = "|".join(
        f"{record.get('id', '')}:{record.get('created_at', '')}:{record.get('blueprint_id', '')}:{record.get('blueprint_name', '')}"
        for record in source_records
        if str(record.get("document_type") or "video_script").strip() == "video_script"
    )
    if st.session_state.get("youtube_script_sync_signature") == sync_signature:
        return
    records = _backfill_saved_script_blueprints(source_records)
    channels = [item for item in read_json("channels.json", []) if isinstance(item, dict)]
    existing_tasks = load_video_tasks_for_catalog()
    for raw_record in records:
        if str(raw_record.get("document_type") or "video_script").strip() != "video_script":
            continue
        content = read_script_document(raw_record)
        if not content:
            continue
        channel = _script_channel(raw_record, channels)
        if not channel or task_platform({"platform": channel.get("platform", "youtube"), "channel_id": channel.get("id")}) != "youtube":
            continue
        record = normalise_saved_script({**raw_record, "channel_id": str(channel.get("id") or "")}, content)
        matched_task = next((task for task in existing_tasks if _saved_script_task_matches(task, record, channel, content)), None)
        if matched_task:
            if str(matched_task.get("script_document_id") or "") != str(record.get("id") or "") or (
                str(matched_task.get("state") or "") == "to_do" and not bool(matched_task.get("manual_start_required", False))
            ):
                matched_id = str(matched_task.get("id") or "")

                def mark_existing_script(entries: Any) -> None:
                    if not isinstance(entries, list):
                        return
                    for entry in entries:
                        if isinstance(entry, dict) and str(entry.get("id") or "") == matched_id:
                            entry["script_document_id"] = str(record.get("id") or "")
                            if str(entry.get("state") or "") == "to_do":
                                entry["manual_start_required"] = True

                update_json("tasks.json", [], mark_existing_script)
            continue
        created = _create_video_task_from_saved_script(record, channel, {})
        existing_tasks.extend(created)
    st.session_state["youtube_script_sync_signature"] = sync_signature


def _automation_created_at(task: dict[str, Any]) -> tuple[datetime, str]:
    value = str(task.get("created_at") or "").strip()
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        parsed = datetime.min.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc), str(task.get("id") or "")


def load_automation_tasks_for_platform(platform_name: str) -> list[dict[str, Any]]:
    """Return only automation/catalog tasks belonging to one publishing platform."""
    target = str(platform_name or "").strip().casefold()
    channels_by_id = {
        str(channel.get("id")): channel
        for channel in read_json("channels.json", [])
        if isinstance(channel, dict) and str(channel.get("id") or "").strip()
    }
    return sorted(
        [task for task in load_video_tasks_for_catalog() if task_platform(task, channels_by_id) == target],
        key=_automation_created_at,
    )


def _task_thumbnail_path(task: dict[str, Any]) -> Path | None:
    """Resolve a generated thumbnail from current and legacy task fields."""
    artifacts = task.get("artifacts") if isinstance(task.get("artifacts"), dict) else {}
    candidates = [
        artifacts.get("thumbnail"),
        artifacts.get("thumbnail_path"),
        artifacts.get("thumbnail_file"),
        artifacts.get("cover"),
        artifacts.get("cover_path"),
        task.get("thumbnail_path"),
        task.get("thumbnail_file"),
        task.get("thumbnail"),
        task.get("thumbnail_url"),
    ]
    for candidate in candidates:
        raw = str(candidate or "").strip()
        if not raw or raw.startswith(("http://", "https://")):
            continue
        paths = [Path(raw)]
        if not Path(raw).is_absolute():
            paths.extend([STORAGE / raw, STORAGE / "videos" / raw])
        for path in paths:
            if path.is_file():
                return path
    return None


def _task_artifact_path(task: dict[str, Any], *names: str) -> Path | None:
    """Resolve um artefacto local, incluindo caminhos relativos e legados."""
    artifacts = task.get("artifacts") if isinstance(task.get("artifacts"), dict) else {}
    for name in names:
        raw = str(artifacts.get(name) or "").strip()
        if not raw or raw.startswith(("http://", "https://")):
            continue
        candidates = [Path(raw)]
        if not Path(raw).is_absolute():
            candidates.extend([STORAGE / raw, STORAGE / "videos" / raw])
        for candidate in candidates:
            if candidate.is_file():
                return candidate
    return None


def _download_title(task: dict[str, Any]) -> str:
    """Return the original video name, preserving its spaces in downloaded files."""
    raw_title = str(task.get("topic") or task.get("title") or task.get("name") or "Vídeo").strip()
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", raw_title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or "Vídeo"


def _automation_download_name(prefix: str, task: dict[str, Any], path: Path | None, fallback_suffix: str) -> str:
    suffix = path.suffix if path and path.suffix else fallback_suffix
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    return f"{prefix}_{_download_title(task)}{suffix}"


def _is_music_task(task: dict[str, Any]) -> bool:
    """Identify music pipeline tasks without conflating them with ordinary video tasks."""
    return bool(task.get("music_mode")) or str(task.get("style_wide") or task.get("style") or "").strip().casefold() in {"music", "música"}


def load_music_tasks_for_catalog() -> list[dict[str, Any]]:
    """Return persisted tasks that were explicitly created through a music route."""
    return [task for task in load_video_tasks_for_catalog() if _is_music_task(task)]


def load_standard_video_tasks_for_catalog() -> list[dict[str, Any]]:
    """Keep video backlog free of tasks that belong to the dedicated music queue."""
    return [task for task in load_video_tasks_for_catalog() if not _is_music_task(task)]


def _video_task_format(task: dict[str, Any]) -> str:
    value = task.get("format") or task.get("style_wide") or task.get("style") or "wide"
    return str(value).strip() or "wide"


def _video_task_progress(task: dict[str, Any]) -> int:
    try:
        return max(0, min(100, int(task.get("progress") or 0)))
    except (TypeError, ValueError):
        return 0


def _render_video_task_state(task: dict[str, Any], state_override: str | None = None) -> None:
    """Show the raw state, readable label and progress consistently in both views."""
    state = str(state_override or task.get("state") or "unknown").strip().lower()
    progress = _video_task_progress(task)
    st.caption("Estado")
    if state == "blocked" and task.get("stop_reason") == "user":
        st.write("Stoped by User")
        st.caption("Parado manualmente pelo utilizador.")
    else:
        st.write(state or "—")
        st.caption(VIDEO_TASK_STATE_LABELS.get(state, state.replace("_", " ").capitalize() or "Desconhecido"))
    st.progress(progress, text=f"{progress}%")
    helper_status = str(task.get("video_helper_status") or "").strip()
    if state == "doing" and helper_status:
        st.caption(f"Actividade: {helper_status[-240:]}")
    if state == "doing" and task.get("video_elapsed_seconds") is not None:
        try:
            elapsed_seconds = max(0, int(task.get("video_elapsed_seconds") or 0))
            st.caption(f"Tempo da etapa Vídeo: {elapsed_seconds // 60}m {elapsed_seconds % 60:02d}s")
        except (TypeError, ValueError):
            pass
    if task.get("error") and state != "done":
        error_text = str(task.get("error") or "").strip()
        st.error(error_text[:700])
        if len(error_text) > 700 or task.get("video_log") or task.get("video_result"):
            with st.expander("Ver diagnóstico completo", expanded=False):
                st.code(error_text[:6000])
                if task.get("video_log"):
                    st.caption(f"Log completo: {task.get('video_log')}")
                if task.get("video_result"):
                    st.caption(f"Manifesto: {task.get('video_result')}")


def _create_video_now_from_channel(channel: dict[str, Any]) -> bool:
    """Create a single task that the active pipeline can execute immediately."""
    try:
        result = create_video_now_for_channel(channel)
    except Exception as exc:
        st.error(f"Não foi possível criar o vídeo: {exc}")
        return False
    tasks = result.get("tasks") or []
    st.success(f"Vídeo criado para {channel.get('name') or 'este canal'} e adicionado à lista de Vídeos cadastrados para execução imediata.")
    if not tasks:
        st.warning("A tarefa foi criada, mas ainda não foi possível confirmar o card na fila.")
    return True


def _start_pipeline_task(task_id: str, state: str) -> bool:
    """Start or retry a video task from any platform automation card."""
    if state in {"blocked", "failed"}:
        updated = retry_task_with_current_settings(task_id)
        if updated and bool(updated.get("manual_start_required", False)):
            updated = transition_task(task_id, "doing")
    else:
        updated = transition_task(task_id, "doing")
    if not updated:
        st.error("Não foi possível iniciar este vídeo: a tarefa já não existe na fila.")
        return False
    return True


def _remake_video_from_card(task: dict[str, Any]) -> bool:
    """Queue a new render while keeping the script and all creative artefacts."""
    task_id = str(task.get("id") or "")
    try:
        updated = remake_video_task(task_id)
    except ValueError as exc:
        st.error(str(exc))
        return False
    if not updated:
        st.error("Não foi possível refazer este vídeo: a tarefa já não existe na fila.")
        return False
    st.success("Vídeo colocado na fila para remontagem. Roteiro, tags, voz, thumbnail e artefactos existentes foram preservados.")
    return True


def _catalog_task_state(task: dict[str, Any]) -> str:
    raw_state = str(task.get("state") or task.get("status") or task.get("task_status") or "").strip().casefold()
    video_path = _task_artifact_path(task, "video")
    if video_path is not None and (bool(task.get("video_ready")) or (raw_state == "failed" and str(task.get("stage") or "").strip().casefold() == "upload")):
        return "done"
    if raw_state in {"completed", "complete", "published", "success", "finished"}:
        return "done"
    if raw_state:
        return raw_state
    return "done" if bool(task.get("video_ready")) and _task_artifact_path(task, "video") else "unknown"


def render_videos():
    st.subheader("Backlog Videos")
    st.caption("Acompanhamento dos vídeos criados, estados da pipeline e controlos de execução.")
    st.caption(f"Os vídeos são guardados em `{STORAGE / 'videos'}`.")
    _render_pipeline_progress_panel()
    tasks = load_video_tasks_for_catalog()
    if not tasks:
        st.info("Nenhum vídeo criado.")
        return
    known_states = ["to_do", "doing", "blocked", "done", "failed", "cancelled"]
    extra_states = sorted({str(task.get("state") or "unknown") for task in tasks if str(task.get("state") or "unknown") not in known_states})
    if "videos_state_filter" not in st.session_state:
        st.session_state["videos_state_filter"] = "Todos"
    state_filter = st.selectbox("Filtrar por estado", ["Todos", *known_states, *extra_states], key="videos_state_filter")
    for task in tasks:
        task_state = _catalog_task_state(task)
        if state_filter != "Todos" and task_state != str(state_filter).strip().casefold():
            continue
        with st.container(border=True):
            cols = st.columns([2.2, 1, 1, 1.2, 1.8])
            with cols[0]:
                artifacts = task.get('artifacts') or {}
                thumbnail_file = _task_thumbnail_path(task)
                video_path = str(artifacts.get('video') or '').strip()
                video_file = _task_artifact_path(task, "video")
                media_cols = st.columns(2, gap="small")
                with media_cols[0]:
                    if thumbnail_file is not None:
                        st.image(str(thumbnail_file), width=180, caption="Thumbnail")
                    else:
                        status = task.get('thumbnail_status', 'not_generated')
                        prompt_note = ' · prompt pronto' if task.get('thumbnail_prompt') else ''
                        st.caption(f"Thumbnail: {status}{prompt_note}")
                with media_cols[1]:
                    if video_file is not None and task_state == "done":
                        _render_local_video_player(video_file, width="stretch")
                        with video_file.open("rb") as video_stream:
                            st.download_button(
                                'Descarregar vídeo pronto',
                                data=video_stream,
                                file_name=video_file.name,
                                mime='video/mp4',
                                key=f"pipeline_video_download_{task['id']}",
                                width="stretch",
                            )
                    elif video_path:
                        st.caption(f'Vídeo registado: {video_path}')
                st.write(f"**{task.get('title') or task.get('topic', 'Sem título')}**")
                st.caption(f"Tópico: {task.get('topic', 'Sem tópico')}")
                st.caption(f"{task.get('channel_name')} · {task.get('id')}")
            with cols[1]:
                st.caption("Formato")
                st.write(_video_task_format(task))
            with cols[2]:
                stage_task = {**task, "stage": "video"} if task_state == "done" and str(task.get("stage") or "").strip().casefold() == "upload" else task
                st.write(_pipeline_stage_label(stage_task))
            with cols[3]:
                _render_video_task_state(task, state_override=task_state)

            with cols[4]:
                state = task_state
                start_col, stop_col = st.columns(2)
                with start_col:
                    if st.button("Start", key=f"automation_start_{task['id']}", width="stretch", disabled=state not in {"to_do", "blocked", "failed"}):
                        _start_pipeline_task(str(task["id"]), state)
                        st.rerun()
                with stop_col:
                    if st.button("Stop", key=f"automation_stop_{task['id']}", width="stretch", disabled=state != "doing"):
                        transition_task(task["id"], "blocked")
                        st.rerun()


def _music_backlog_records() -> list[dict[str, Any]]:
    """Combine generated music tasks with audio files imported into storage/music."""
    tasks = list_music_tasks()
    records: list[dict[str, Any]] = []
    registered_paths: set[str] = set()
    for task in tasks:
        record = dict(task)
        record["source_type"] = "created"
        audio_path = Path(str(record.get("audio_path") or "")) if record.get("audio_path") else None
        if audio_path:
            registered_paths.add(str(audio_path.resolve()))
        records.append(record)
    for music_file in list_music_files():
        if str(music_file.resolve()) in registered_paths:
            continue
        records.append({
            "id": f"imported_{hashlib.sha1(str(music_file.resolve()).encode('utf-8')).hexdigest()[:12]}",
            "title": get_display_name("music", music_file, music_file.stem),
            "provider": "imported",
            "stage": "imported",
            "state": "done",
            "progress": 100,
            "audio_path": str(music_file),
            "source_type": "imported",
            "created_at": datetime.fromtimestamp(music_file.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
        })
    return records


def _music_lyrics_records() -> list[dict[str, Any]]:
    """Return persisted music-lyrics documents that still exist on disk."""
    records: list[dict[str, Any]] = []
    for document in list_script_documents():
        if str(document.get("document_type") or "").strip() != "music_lyrics":
            continue
        path = Path(str(document.get("path") or ""))
        if path.is_file():
            records.append({**document, "path": str(path), "title": get_display_name("music_lyrics", path, str(document.get("title") or path.stem))})
    return records


def _render_music_file_card(record: dict[str, Any]) -> None:
    music_path = Path(str(record.get("audio_path") or ""))
    record_id = str(record.get("id") or music_path.name)
    title = get_display_name("music", music_path, str(record.get("title") or music_path.stem)) if music_path else str(record.get("title") or "Música sem título")
    with st.container(border=True):
        cols = st.columns([2.2, 1, 1, 1.2, 1.8])
        with cols[0]:
            st.write(f"**{title}**")
            source_type = "Música criada" if str(record.get("source_type") or "") == "created" else "Música importada"
            st.caption(source_type)
            if str(record.get("provider") or "").casefold() not in {"", "imported"}:
                provider = "Google Lyria" if str(record.get("provider") or "").casefold() == "lyria" else "Suno AI"
                st.caption(f"Provider: {provider}")
            st.caption(record_id)
            if music_path.is_file():
                st.download_button(
                    "Descarregar música",
                    data=music_path.read_bytes(),
                    file_name=music_path.name,
                    mime=mimetypes.guess_type(music_path.name)[0] or "audio/mpeg",
                    key=f"music_backlog_download_{record_id}",
                    width="stretch",
                )
                edit_key = _render_library_name_editor("music", music_path, title)
                with st.columns([0.2, 0.8])[0]:
                    _render_card_pencil(edit_key)
            else:
                st.caption(f"Música registada: {music_path}")
        with cols[1]:
            st.caption("Tipo")
            st.write("Áudio")
        with cols[2]:
            stage = str(record.get("stage") or "")
            st.write({"music_generation": "Geração musical", "completed": "Concluída", "failed": "Falha", "imported": "Importada"}.get(stage, "Na fila"))
        with cols[3]:
            state = str(record.get("state") or "unknown").strip().lower()
            progress = _video_task_progress(record)
            st.caption("Estado")
            st.write(state or "—")
            st.caption(VIDEO_TASK_STATE_LABELS.get(state, state.replace("_", " ").capitalize() or "Desconhecido"))
            st.progress(progress, text=f"{progress}%")
            if record.get("error"):
                st.error(str(record.get("error") or "")[:500])
        with cols[4]:
            if str(record.get("source_type") or "") == "created":
                state = str(record.get("state") or "")
                start_col, stop_col = st.columns(2)
                with start_col:
                    if st.button("Start", key=f"music_backlog_start_{record_id}", width="stretch", disabled=state not in {"to_do", "blocked", "failed"}):
                        run_music_task(record_id, read_json("settings.json", {}))
                        st.rerun()
                with stop_col:
                    if st.button("Stop", key=f"music_backlog_stop_{record_id}", width="stretch", disabled=state != "doing"):
                        transition_music_task(record_id, "blocked")
                        st.rerun()


def _render_lyrics_card(record: dict[str, Any]) -> None:
    path = Path(str(record.get("path") or ""))
    if not path.is_file():
        return
    record_id = str(record.get("id") or hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:12])
    title = str(record.get("title") or path.stem)
    content = read_script_document(record)
    with st.container(border=True):
        title_col, download_col, edit_col = st.columns([3.2, 1.3, 0.6])
        with title_col:
            st.write(f"**{title}**")
            st.caption("Lyrics")
        with download_col:
            st.download_button("Descarregar lyrics", data=path.read_bytes(), file_name=path.name, mime="text/markdown", key=f"music_lyrics_download_{record_id}", width="stretch")
        with edit_col:
            edit_key = _render_library_name_editor("music_lyrics", path, title)
            _render_card_pencil(edit_key)
        with st.expander("Ver lyrics", expanded=False):
            st.code(content or path.read_text(encoding="utf-8"), language="markdown")


def render_music_backlog() -> None:
    """List generated and imported music, plus locally stored lyrics."""
    st.subheader("Music Backlog")
    st.caption("Fila independente de geração e importação de áudio por Suno AI ou Google Lyria. Não inclui tarefas, worker ou progresso de vídeo.")
    st.caption(f"As músicas são guardadas em `{STORAGE / 'music'}`.")
    music_tab, lyrics_tab = st.tabs(["Músicas", "Lyrics"])
    with music_tab:
        with st.form("music_backlog_upload_form", clear_on_submit=True):
            uploaded_music = st.file_uploader("Adicionar músicas à pasta acima", type=["mp3", "mpeg", "wav", "m4a", "aac", "flac", "ogg"], accept_multiple_files=True, key="music_backlog_upload")
            upload_music = st.form_submit_button("Guardar músicas", type="primary", width="stretch")
        if upload_music and uploaded_music:
            for uploaded in uploaded_music:
                store_music_file(uploaded.name, uploaded.getvalue())
            st.success(f"{len(uploaded_music)} música(s) guardada(s) em `{STORAGE / 'music'}`.")
            st.rerun()
        records = _music_backlog_records()
        active = [record for record in records if str(record.get("state") or "") == "doing"]
        if active:
            st.info(f"Geração musical em execução · {len(active)} tarefa(s) de áudio.")
        if not records:
            st.info("Nenhuma música criada ou importada.")
        else:
            known_states = ["to_do", "doing", "blocked", "done", "failed", "cancelled"]
            extra_states = sorted({str(record.get("state") or "unknown") for record in records if str(record.get("state") or "unknown") not in known_states})
            state_filter = st.selectbox("Filtrar por estado", ["Todos", *known_states, *extra_states], key="music_backlog_state_filter")
            for record in records:
                if state_filter != "Todos" and record.get("state") != state_filter:
                    continue
                _render_music_file_card(record)
    with lyrics_tab:
        st.caption(f"As lyrics são guardadas em `{script_storage_path()}` no formato Markdown local do Thunderbolt.")
        with st.form("music_backlog_lyrics_upload_form", clear_on_submit=True):
            uploaded_lyrics = st.file_uploader("Adicionar lyrics", type=["md", "txt"], key="music_backlog_lyrics_upload")
            upload_lyrics = st.form_submit_button("Guardar lyrics", width="stretch")
        if upload_lyrics and uploaded_lyrics:
            content = uploaded_lyrics.getvalue().decode("utf-8", errors="replace").strip()
            if content:
                save_script_document({"title": Path(uploaded_lyrics.name).stem, "document_type": "music_lyrics", "content": content})
                st.success("Lyrics guardadas.")
                st.rerun()
            else:
                st.warning("O ficheiro de lyrics está vazio.")
        lyrics = _music_lyrics_records()
        if not lyrics:
            st.info("Nenhuma lyrics guardada.")
        for record in lyrics:
            _render_lyrics_card(record)


def _thumbnail_editor_context(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve the persisted task channel/Blueprint without requiring either one to remain registered."""
    channel_id = str(record.get("channel_id") or "").strip()
    channels = read_json("channels.json", [])
    channel = next(
        (item for item in channels if isinstance(item, dict) and str(item.get("id") or "") == channel_id),
        None,
    ) if isinstance(channels, list) else None
    if not channel:
        channel = {
            "id": channel_id,
            "name": record.get("channel_name") or "Canal sem nome",
            "language": record.get("language") or "Português",
            "default_blueprint_id": record.get("blueprint_id") or "",
            "blueprint_id": record.get("blueprint_id") or "",
        }
    blueprint = blueprint_for_channel(channel)
    if not blueprint and record.get("blueprint_id"):
        blueprint = {"id": record.get("blueprint_id"), "name": record.get("blueprint_name") or record.get("blueprint_id")}
    thumbnail_blueprint = thumbnail_blueprint_for_channel({**channel, "thumbnail_blueprint_id": record.get("thumbnail_blueprint_id") or channel.get("thumbnail_blueprint_id", "")})
    if thumbnail_blueprint.get("content"):
        blueprint = {**blueprint, "thumbnail_blueprint_rules": thumbnail_blueprint["content"]}
    return channel, blueprint


def render_thumbnails():
    st.title("Thumbnails")
    st.caption("Biblioteca de thumbnails associadas às tarefas da pipeline. Cada acção preserva a imagem anterior no histórico local.")
    records = list_thumbnail_tasks()
    if not records:
        st.info("Ainda não existem tarefas com thumbnail gerada ou prompt de imagem disponível.")
        return

    settings = read_json("settings.json", {})
    page_size = 24
    page_count = max(1, (len(records) + page_size - 1) // page_size)
    current_page = st.session_state.get("thumbnail_gallery_page", 1)
    try:
        current_page = min(max(int(current_page), 1), page_count)
    except (TypeError, ValueError):
        current_page = 1
    if page_count > 1:
        current_page = st.selectbox(
            "Página de thumbnails",
            options=list(range(1, page_count + 1)),
            index=current_page - 1,
            format_func=lambda value: f"Página {value} de {page_count}",
            key="thumbnail_gallery_page",
        )
        start = (current_page - 1) * page_size
        visible_records = records[start : start + page_size]
        st.caption(f"A mostrar {start + 1}–{min(start + page_size, len(records))} de {len(records)} thumbnails.")
    else:
        visible_records = records
    for record in visible_records:
        task_id = record["task_id"]
        with st.container(border=True):
            image_col, details_col, action_col = st.columns([1.25, 2.35, 1.7])
            with image_col:
                image_path = record.get("image_path")
                if image_path and image_path.is_file():
                    # Pass bytes to Streamlit and avoid the deprecated
                    # legacy full-width argument.  On Windows the
                    # deprecation warning can be emitted after the bootstrap
                    # stream has been closed, which masks the real page with
                    # ``ValueError: I/O operation on closed file``.
                    image_bytes = _file_bytes(image_path)
                    st.image(image_bytes)
                    st.download_button(
                        "Descarregar thumbnail",
                        data=image_bytes,
                        file_name=image_path.name,
                        mime="image/jpeg" if image_path.suffix.lower() in {".jpg", ".jpeg"} else "image/png",
                        key=f"thumbnail_download_{task_id}_{record['variant_index']}",
                        width="stretch",
                    )
                else:
                    st.markdown("### Sem imagem")
                    st.caption("Imagem ainda não gerada")
            with details_col:
                st.write(f"**{record['title']}**")
                st.caption(f"Canal: {record['channel_name']} · Tarefa: {task_id}")
                st.caption(f"Estado: {record['status']} · Variante: {record['variant_index'] + 1}")
                if record["prompt"]:
                    with st.expander("Ver prompt da thumbnail", expanded=False):
                        st.code(record["prompt"], language="text")
                else:
                    st.warning("A thumbnail não tem um prompt de imagem para gerar.")

            with action_col:
                if st.button(
                    "Refazer Prompt Thumb",
                    key=f"regenerate_thumbnail_{task_id}",
                    icon=":material/refresh:",
                    width="stretch",
                    disabled=not bool(record["title"] or record["topic"]),
                ):
                    try:
                        with st.spinner("A refazer apenas o prompt da thumbnail…"):
                            channel, blueprint = _thumbnail_editor_context(record)
                            _task, prompt_variant = regenerate_thumbnail_prompt(
                                task_id,
                                settings,
                                channel,
                                blueprint=blueprint,
                                language=str(record.get("language") or current_ui_language()),
                            )
                        record_notification(
                            "thumbnail_generation_completed",
                            "Prompt da thumbnail refeito",
                            "Prompt da thumbnail actualizado; a imagem existente foi preservada.",
                            metadata={
                                "task_id": task_id,
                                "channel_name": record["channel_name"],
                                "prompt_regenerated": True,
                                "prompt_only": True,
                                "image_path": str(record.get("image_path") or ""),
                            },
                            dedupe_key=f"thumbnail:prompt-only:{task_id}:{prompt_variant.get('image_prompt', '')}",
                        )
                        st.success("Prompt da thumbnail actualizado; a imagem existente foi preservada.")
                        st.rerun()
                    except (CreativeGenerationError, ThumbnailGenerationError) as exc:
                        st.error(str(exc))

                if st.button(
                    "Gerar Imagem",
                    key=f"generate_thumbnail_image_{task_id}",
                    icon=":material/image:",
                    width="stretch",
                    disabled=not bool(record["prompt"]),
                ):
                    try:
                        with st.spinner("A gerar a imagem com Nano Banana…"):
                            channel, _blueprint = _thumbnail_editor_context(record)
                            thumbnail_blueprint = thumbnail_blueprint_for_channel({**channel, "thumbnail_blueprint_id": record.get("thumbnail_blueprint_id") or channel.get("thumbnail_blueprint_id", "")})
                            _task, generated_path = generate_thumbnail_for_task(task_id, settings, thumbnail_blueprint=thumbnail_blueprint)
                        record_notification(
                            "thumbnail_generation_completed",
                            f"Thumbnail gerada: {record['title']}",
                            "Thumbnail gerada com sucesso.",
                            metadata={"task_id": task_id, "channel_name": record["channel_name"], "image_path": str(generated_path)},
                            dedupe_key=f"thumbnail:generated:{task_id}:{generated_path}",
                        )
                        st.success("Thumbnail gerada com sucesso.")
                        st.rerun()
                    except MediaGenerationError as exc:
                        st.error(format_media_generation_error(exc, operation="gerar a imagem da thumbnail"))
                    except ThumbnailGenerationError as exc:
                        st.error(str(exc))

                if st.button(
                    "Refazer Prompt e Gerar Imagem",
                    key=f"regenerate_thumbnail_prompt_{task_id}",
                    icon=":material/auto_awesome:",
                    width="stretch",
                    disabled=not bool(record["title"] or record["topic"]),
                ):
                    try:
                        with st.spinner("A refazer o prompt e a imagem…"):
                            channel, blueprint = _thumbnail_editor_context(record)
                            variant = generate_thumbnail_prompt(
                                settings,
                                channel,
                                record["title"] or record["topic"],
                                current_prompt=record["prompt"],
                                blueprint=blueprint,
                                language=str(record.get("language") or current_ui_language()),
                            )
                            _task, generated_path = regenerate_thumbnail_prompt_and_image(task_id, settings, variant)
                        record_notification(
                            "thumbnail_generation_completed",
                            f"Thumbnail renovada: {record['title']}",
                            "Prompt da thumbnail e imagem actualizados.",
                            metadata={"task_id": task_id, "channel_name": record["channel_name"], "image_path": str(generated_path), "prompt_regenerated": True},
                            dedupe_key=f"thumbnail:prompt-regenerated:{task_id}:{generated_path}",
                        )
                        st.success("Prompt da thumbnail e imagem actualizados.")
                        st.rerun()
                    except MediaGenerationError as exc:
                        st.error(format_media_generation_error(exc, operation="refazer o prompt e gerar a imagem da thumbnail"))
                    except (CreativeGenerationError, ThumbnailGenerationError) as exc:
                        st.error(str(exc))

                if st.button(
                    "Refazer Lettering",
                    key=f"regenerate_thumbnail_lettering_{task_id}",
                    icon=":material/title:",
                    width="stretch",
                    disabled=not bool(record.get("image_path") and record["image_path"].is_file()),
                ):
                    try:
                        with st.spinner("A refazer apenas o lettering…"):
                            channel, _blueprint = _thumbnail_editor_context(record)
                            _task, generated_path = regenerate_thumbnail_lettering(
                                task_id,
                                settings,
                                lettering_prompt=record.get("lettering_prompt") or "",
                                language=str(record.get("language") or channel.get("language") or current_ui_language()),
                                channel=channel,
                            )
                        record_notification(
                            "thumbnail_generation_completed",
                            f"Lettering refeito: {record['title']}",
                            "Lettering refeito; a imagem original foi usada como base.",
                            metadata={"task_id": task_id, "channel_name": record["channel_name"], "image_path": str(generated_path), "lettering_only": True},
                            dedupe_key=f"thumbnail:lettering:{task_id}:{generated_path}",
                        )
                        st.success("Lettering refeito; a imagem original foi usada como base.")
                        st.rerun()
                    except MediaGenerationError as exc:
                        st.error(format_media_generation_error(exc, operation="refazer o lettering da thumbnail"))
                    except ThumbnailGenerationError as exc:
                        st.error(str(exc))

            uploaded = st.file_uploader(
                "Upload Image",
                type=["png", "jpg", "jpeg", "webp"],
                key=f"thumbnail_upload_{task_id}",
                help="Suba uma imagem para a associar a esta tarefa e à pipeline.",
            )
            if uploaded is not None:
                uploaded_bytes = uploaded.getvalue()
                uploaded_digest = hashlib.sha256(uploaded_bytes).hexdigest()
                digest_key = f"thumbnail_upload_digest_{task_id}"
                if st.session_state.get(digest_key) != uploaded_digest:
                    try:
                        with st.spinner("A guardar a imagem carregada…"):
                            _task, uploaded_path = upload_thumbnail_image(
                                task_id,
                                uploaded_bytes,
                                uploaded.name,
                                uploaded.type,
                            )
                        st.session_state[digest_key] = uploaded_digest
                        record_notification(
                            "thumbnail_generation_completed",
                            f"Thumbnail carregada: {record['title']}",
                            "Imagem carregada e vinculada à tarefa.",
                            metadata={"task_id": task_id, "channel_name": record["channel_name"], "image_path": str(uploaded_path), "source": "upload"},
                            dedupe_key=f"thumbnail:uploaded:{task_id}:{uploaded_digest}",
                        )
                        st.success("Imagem carregada e vinculada à tarefa.")
                        st.rerun()
                    except ThumbnailGenerationError as exc:
                        st.error(str(exc))


@st.fragment
def _render_tiktok_automation_cards():
        if not _has_script_context():
            return
        st.divider()
        st.subheader("Vídeos cadastrados TikTok")
        st.caption("Esta fila mostra exclusivamente tarefas associadas a canais TikTok.")
        tiktok_tasks = load_automation_tasks_for_platform("tiktok")
        tiktok_channels_by_id = {
            str(channel.get("id")): channel
            for channel in read_json("channels.json", [])
            if isinstance(channel, dict) and classify_channel_platform(channel) == "tiktok"
        }
        if not tiktok_tasks:
            st.info("Ainda não existem vídeos TikTok cadastrados.")
        for task in tiktok_tasks:
            task_id = str(task["id"])
            with st.container(border=True):
                task_cols = st.columns([2.25, 1.55, 1.05, 2.15], gap="small")
                thumbnail_path = _task_thumbnail_path(task)
                script_path = _task_artifact_path(task, "script")
                video_path = _task_artifact_path(task, "video")
                thumbnail_prompt_path = _task_artifact_path(task, "thumbnail_prompt_json")
                thumbnail_prompt = str(task.get("thumbnail_prompt") or "").strip()
                with task_cols[0]:
                    if thumbnail_path:
                        st.image(str(thumbnail_path), width=180, caption="Thumbnail")
                    else:
                        st.caption("Thumbnail ainda não pronta")
                    st.write(f"**{task.get('title') or task.get('topic') or 'Vídeo TikTok'}**")
                    st.caption(f"{task.get('channel_name') or 'Canal TikTok'} · {task_id}")
                    task_channel = tiktok_channels_by_id.get(str(task.get("channel_id") or ""))
                    if task_channel is None:
                        task_channel = next(
                            (channel for channel in tiktok_channels_by_id.values() if str(channel.get("name") or "").strip() == str(task.get("channel_name") or "").strip()),
                            None,
                        )
                    task_channel_url = _tiktok_channel_url(task_channel or {})
                    if task_channel_url:
                        st.link_button("Abrir canal", task_channel_url, type="primary", width="content")
                    thumbnail_download_col, prompt_download_col = st.columns(2, gap="small")
                    with thumbnail_download_col:
                        st.download_button(
                            "Baixar Thumbnail 9:16",
                            data=_file_bytes(thumbnail_path),
                            file_name=_automation_download_name("Thumbnail9:16", task, thumbnail_path, ".png"),
                            mime="image/png",
                            key=f"tiktok_automation_download_thumbnail_{task_id}",
                            width="stretch",
                            disabled=thumbnail_path is None,
                        )
                    with prompt_download_col:
                        prompt_data = thumbnail_prompt_path.read_bytes() if thumbnail_prompt_path else thumbnail_prompt.encode("utf-8")
                        st.download_button(
                            "Baixar Thumbnail Prompt",
                            data=prompt_data,
                            file_name=_automation_download_name("Thumbnail-Prompt", task, thumbnail_prompt_path, ".txt"),
                            mime="application/json" if thumbnail_prompt_path else "text/plain",
                            key=f"tiktok_automation_download_thumbnail_prompt_{task_id}",
                            width="stretch",
                            disabled=thumbnail_prompt_path is None and not thumbnail_prompt,
                        )
                with task_cols[1]:
                    _render_video_task_state(task)
                with task_cols[2]:
                    st.caption("Plataforma")
                    st.write("TikTok")
                    st.caption("Portrait 9:16")
                with task_cols[3]:
                    state = str(task.get("state") or "")
                    start_col, stop_col, delete_col = st.columns(3)
                    with start_col:
                        if st.button("Start", key=f"tiktok_automation_start_{task_id}", width="stretch", disabled=state not in {"to_do", "blocked", "failed"}):
                            if _start_pipeline_task(task_id, state):
                                st.rerun()
                    with stop_col:
                        if st.button("Stop", key=f"tiktok_automation_stop_{task_id}", width="stretch", disabled=state != "doing"):
                            stop_task_by_user(task_id)
                            st.rerun()
                    script_download_col, video_download_col = st.columns(2, gap="small")
                    with script_download_col:
                        st.download_button(
                            "Baixar Roteiro",
                            data=_file_bytes(script_path),
                            file_name=_automation_download_name("Script", task, script_path, ".md"),
                            mime="text/markdown",
                            key=f"tiktok_automation_download_script_{task_id}",
                            width="stretch",
                            disabled=script_path is None,
                        )
                    with video_download_col:
                        st.download_button(
                            "Baixar Vídeo9:16",
                            data=_file_bytes(video_path),
                            file_name=_automation_download_name("Vídeo9:16", task, video_path, ".mp4"),
                            mime="video/mp4",
                            key=f"tiktok_automation_download_video_{task_id}",
                            width="stretch",
                            disabled=video_path is None,
                        )
                    if st.button(
                        "Refazer Vídeo",
                        key=f"tiktok_automation_remake_video_{task_id}",
                        icon=":material/refresh:",
                        type="primary",
                        width="stretch",
                        disabled=state == "doing",
                        help="Remonta apenas o vídeo, mantendo o mesmo roteiro, Blueprint/Prompt Master, tags, thumbnail, voz e artefactos já baixados.",
                    ):
                        if _remake_video_from_card(task):
                            st.rerun()
                    with delete_col:
                        confirm_delete_key = f"tiktok_automation_confirm_delete_{task_id}"
                        if st.button("Apagar", key=f"tiktok_automation_delete_{task_id}", width="stretch", disabled=state == "doing"):
                            st.session_state[confirm_delete_key] = True
                            st.rerun()
                        if st.session_state.get(confirm_delete_key):
                            st.warning("Remover este vídeo da fila? Os ficheiros de artefactos serão preservados.")
                            confirm_col, cancel_col = st.columns(2)
                            with confirm_col:
                                if st.button("Confirmar", key=f"tiktok_automation_confirm_delete_button_{task_id}", width="stretch", type="primary"):
                                    try:
                                        delete_task(task["id"])
                                        st.session_state.pop(confirm_delete_key, None)
                                        st.rerun()
                                    except ValueError as exc:
                                        st.error(str(exc))
                            with cancel_col:
                                if st.button("Cancelar", key=f"tiktok_automation_cancel_delete_{task_id}", width="stretch"):
                                    st.session_state.pop(confirm_delete_key, None)
                                    st.rerun()


def render_tiktok_automation():
    st.title("Automação Tiktok")
    st.caption("Agendamento diário da geração por canal. A fila TikTok usa Prompt Master e mantém exclusivamente o formato Portrait 9:16.")
    worker_status = load_worker_status()
    local_now = datetime.now().astimezone()
    if worker_status.get("alive"):
        st.success(f"Worker activo · relógio local: {local_now.strftime('%d/%m/%Y %H:%M:%S %Z')}")
    else:
        st.warning("Worker de automação não está activo. Inicie o Thunderbolt pelo launcher (`npx.cmd --yes @danhachuel/thunderbolt`) para activar as verificações horárias.")
    channels = _tiktok_channel_records()
    prompt_ids, prompt_labels = _tiktok_prompt_options()
    if not channels:
        st.info("Nenhum canal TikTok seleccionado. A lista de automação permanece vazia até existir um destino.")
    with st.expander("Canais cadastrados", expanded=False):
        for channel in channels:
            channel_id = str(channel["id"])
            with st.container(border=True):
                header_cols = st.columns([0.55, 2.35, 1.25, 0.82, 0.92, 1.2])
                with header_cols[0]:
                    profile_image = _tiktok_avatar_url(channel)
                    if profile_image:
                        st.image(profile_image, width=48)
                    else:
                        st.markdown("### TT")
                with header_cols[1]:
                    st.write(f"**{channel.get('name', 'Sem nome')}**")
                    st.caption(channel.get("handle") or channel.get("url") or "sem URL")
                    channel_url = _tiktok_channel_url(channel)
                    if channel_url:
                        open_create_cols = st.columns(2, gap="small")
                        with open_create_cols[0]:
                            st.link_button("Abrir canal", channel_url, type="primary", width="stretch")
                        with open_create_cols[1]:
                            if st.button("Criar Vídeo", key=f"tiktok_automation_create_video_{channel_id}", width="stretch"):
                                if _create_video_now_from_channel(channel):
                                    st.rerun(scope="fragment")
                    else:
                        if st.button("Criar Vídeo", key=f"tiktok_automation_create_video_{channel_id}", width="stretch"):
                            if _create_video_now_from_channel(channel):
                                st.rerun(scope="fragment")
                with header_cols[2]:
                    enabled = st.toggle("Automação ligada", value=bool(channel.get("automation_on", False)), key=f"tiktok_automation_on_{channel_id}")
                with header_cols[3]:
                    schedule_time = st.text_input("Horário (HH:MM)", value=channel.get("automation_time", "00:00"), key=f"tiktok_automation_time_{channel_id}")
                with header_cols[4]:
                    prompt_file = TIKTOK_PROMPT_MASTERS / str(channel.get("default_prompt_master") or channel.get("prompt_master") or "")
                    prompt_content = load_prompt_master_file(prompt_file) if prompt_file.is_file() else ""
                    calculated_time, calculated_source, calculated_words = _channel_average_video_time(channel, prompt_master=prompt_content)
                    average_video_time = st.text_input("Tempo Medio de Video", value=channel_video_time_value(channel), key=f"tiktok_average_video_time_{channel_id}", help=f"Referência média: {calculated_words or 0} palavras · fonte: {calculated_source}.")
                default_cols = st.columns([1.0, 1.0, 1.35, 1.45, 1.55, 1.0], gap="small")
                with default_cols[0]:
                    st.markdown("**Idioma do roteiro**")
                    st.caption(video_language_label(normalize_video_language(channel.get("language") or "pt")))
                with default_cols[1]:
                    st.markdown("**Nicho Padrão**")
                    st.caption(channel_niche_label(channel))
                with default_cols[2]:
                    st.markdown("**Fonte do vídeo**")
                    st.caption(channel_video_source_value(channel.get("style_wide")))
                    st.markdown("**Proporção do vídeo**")
                    st.caption(str(channel.get("video_aspect_ratio") or "Portrait 9:16"))
                    st.markdown("**Formato**")
                    st.caption(str(channel.get("format") or "Shorts"))
                with default_cols[3]:
                    prompt = st.selectbox("Prompt Master Padrão", prompt_ids, index=prompt_ids.index(channel.get("default_prompt_master", "")) if channel.get("default_prompt_master", "") in prompt_ids else 0, format_func=lambda item: prompt_labels.get(item, item), key=f"tiktok_automation_prompt_{channel_id}")
                with default_cols[4]:
                    automation_format = st.selectbox("Formato", CHANNEL_FORMAT_OPTIONS, index=CHANNEL_FORMAT_OPTIONS.index(str(channel.get("format") or "Shorts")) if str(channel.get("format") or "Shorts") in CHANNEL_FORMAT_OPTIONS else 1, key=f"tiktok_automation_format_{channel_id}")
                with default_cols[5]:
                    if st.button("Guardar", key=f"tiktok_automation_save_{channel_id}", width="stretch", type="primary"):
                        if not valid_hhmm(schedule_time):
                            st.error("Use o formato HH:MM, por exemplo 08:30.")
                        elif not valid_hhmm(average_video_time):
                            st.error("O Tempo Medio de Video deve estar no formato MM:SS, por exemplo 12:00.")
                        else:
                            avatar_url = _tiktok_avatar_url(channel)
                            update_channel(channel_id, {"automation_on": bool(enabled), "automation_time": schedule_time.strip(), "average_video_time": average_video_time.strip() or default_average_video_time(channel), "average_video_word_count": words_from_channel_time(average_video_time), "default_prompt_master": prompt, "prompt_master": prompt, "platform": "tiktok", "format": automation_format, "video_aspect_ratio": "Portrait 9:16", "style_wide": "portrait", "avatar_url": avatar_url, "thumbnail_url": avatar_url})
                            st.success("Automação TikTok guardada.")
                            st.rerun()
    _render_tiktok_automation_cards()

@st.fragment
def _render_youtube_automation_cards():
        if not _has_script_context():
            return
        st.divider()
        st.subheader("Vídeos cadastrados")
        st.caption("Start retoma as etapas já concluídas e só gera novamente o que ainda não estiver pronto. Em tarefas falhadas ou bloqueadas, a nova tentativa lê as chaves, prioridades e configurações actualmente guardadas. Apagar remove o card da fila e elimina todos os artefactos locais do vídeo, incluindo áudio/voz, roteiro, vídeo, thumbnail, legendas, música, prompts e logs.")
        tasks = load_automation_tasks_for_platform("youtube")
        if not tasks:
            st.info("Ainda não existem vídeos cadastrados.")
        page_size = 12
        page_count = max(1, (len(tasks) + page_size - 1) // page_size)
        current_page = st.session_state.get("youtube_automation_page", 1)
        try:
            current_page = min(max(int(current_page), 1), page_count)
        except (TypeError, ValueError):
            current_page = 1
        if page_count > 1:
            current_page = st.selectbox(
                "Página de vídeos cadastrados",
                options=list(range(1, page_count + 1)),
                index=current_page - 1,
                format_func=lambda value: f"Página {value} de {page_count}",
                key="youtube_automation_page",
            )
            start = (current_page - 1) * page_size
            visible_tasks = tasks[start : start + page_size]
            st.caption(f"A mostrar {start + 1}–{min(start + page_size, len(tasks))} de {len(tasks)} vídeos.")
        else:
            visible_tasks = tasks
        for task in visible_tasks:
            with st.container(border=True):
                task_cols = st.columns([2.25, 1.55, 1.05, 2.15], gap="small")
                script_path = _task_artifact_path(task, "script")
                video_path = _task_artifact_path(task, "video")
                thumbnail_path = _task_thumbnail_path(task)
                thumbnail_prompt_path = _task_artifact_path(task, "thumbnail_prompt_json")
                thumbnail_prompt = str(task.get("thumbnail_prompt") or "").strip()
                with task_cols[0]:
                    media_cols = st.columns(2, gap="small")
                    with media_cols[0]:
                        if thumbnail_path is not None:
                            st.image(str(thumbnail_path), width=180, caption="Thumbnail")
                        else:
                            st.caption("Thumbnail ainda não pronta")
                    with media_cols[1]:
                        if video_path is not None and _catalog_task_state(task) == "done":
                            _render_local_video_player(video_path, width="stretch")
                    st.write(f"**{task.get('topic', 'Sem tópico')}**")
                    st.caption(f"{task.get('channel_name', 'Canal')} · {task.get('id', '')}")
                    thumbnail_download_col, prompt_download_col = st.columns(2, gap="small")
                    with thumbnail_download_col:
                        st.download_button(
                            "Baixar Thumbnail",
                            data=_file_bytes(thumbnail_path),
                            file_name=_automation_download_name("Thumbnail", task, thumbnail_path, ".png"),
                            mime="image/png",
                            key=f"automation_download_thumbnail_{task['id']}",
                            width="stretch",
                            disabled=thumbnail_path is None,
                        )
                    with prompt_download_col:
                        prompt_data = thumbnail_prompt_path.read_bytes() if thumbnail_prompt_path else thumbnail_prompt.encode("utf-8")
                        st.download_button(
                            "Baixar Thumbnail Prompt",
                            data=prompt_data,
                            file_name=_automation_download_name("Thumbnail-Prompt", task, thumbnail_prompt_path, ".txt"),
                            mime="application/json" if thumbnail_prompt_path else "text/plain",
                            key=f"automation_download_thumbnail_prompt_{task['id']}",
                            width="stretch",
                            disabled=thumbnail_prompt_path is None and not thumbnail_prompt,
                        )
                with task_cols[1]:
                    _render_video_task_state(task)
                with task_cols[2]:
                    st.caption("Formato")
                    st.write(_video_task_format(task))
                with task_cols[3]:
                    state = str(task.get("state") or "")
                    start_col, stop_col, delete_col = st.columns(3)
                    with start_col:
                        if st.button("Start", key=f"automation_start_{task['id']}", width="stretch", disabled=state not in {"to_do", "blocked", "failed"}):
                            if _start_pipeline_task(str(task["id"]), state):
                                st.rerun(scope="fragment")
                    with stop_col:
                        if st.button("Stop", key=f"automation_stop_{task['id']}", width="stretch", disabled=state != "doing"):
                            stop_task_by_user(task["id"])
                            st.rerun(scope="fragment")
                    script_download_col, video_download_col = st.columns(2, gap="small")
                    with script_download_col:
                        st.download_button(
                            "Baixar Roteiro",
                            data=_file_bytes(script_path),
                            file_name=_automation_download_name("Script", task, script_path, ".md"),
                            mime="text/markdown",
                            key=f"automation_download_script_{task['id']}",
                            width="stretch",
                            disabled=script_path is None,
                        )
                    with video_download_col:
                        if video_path is not None:
                            with video_path.open("rb") as video_stream:
                                st.download_button(
                                    "Baixar Vídeo",
                                    data=video_stream,
                                    file_name=_automation_download_name("Vídeo", task, video_path, ".mp4"),
                                    mime="video/mp4",
                                    key=f"automation_download_video_{task['id']}",
                                    width="stretch",
                                )
                        else:
                            st.download_button(
                                "Baixar Vídeo",
                                data=b"",
                                file_name="video.mp4",
                                mime="video/mp4",
                                key=f"automation_download_video_{task['id']}",
                                width="stretch",
                                disabled=True,
                            )
                    if st.button(
                        "Refazer Vídeo",
                        key=f"automation_remake_video_{task['id']}",
                        icon=":material/refresh:",
                        type="primary",
                        width="stretch",
                        disabled=state == "doing",
                        help="Remonta apenas o vídeo, mantendo o mesmo roteiro, Blueprint/Prompt Master, tags, thumbnail, voz e artefactos já baixados.",
                    ):
                        if _remake_video_from_card(task):
                            st.rerun(scope="fragment")
                    with delete_col:
                        confirm_delete_key = f"automation_confirm_delete_{task['id']}"
                        if st.button("Apagar", key=f"automation_delete_{task['id']}", width="stretch", disabled=state == "doing"):
                            st.session_state[confirm_delete_key] = True
                            st.rerun(scope="fragment")
                        if st.session_state.get(confirm_delete_key):
                            st.warning("Remover este vídeo da fila? Os ficheiros de artefactos serão preservados.")
                            confirm_col, cancel_col = st.columns(2)
                            with confirm_col:
                                if st.button("Confirmar", key=f"automation_confirm_delete_button_{task['id']}", width="stretch", type="primary"):
                                    try:
                                        delete_task(task["id"])
                                        st.session_state.pop(confirm_delete_key, None)
                                        st.rerun(scope="fragment")
                                    except ValueError as exc:
                                        st.error(str(exc))
                            with cancel_col:
                                if st.button("Cancelar", key=f"automation_cancel_delete_{task['id']}", width="stretch"):
                                    st.session_state.pop(confirm_delete_key, None)
                                    st.rerun(scope="fragment")


def _facebook_pages_for_automation() -> list[dict[str, Any]]:
    return [channel for channel in read_json("channels.json", []) if isinstance(channel, dict) and classify_channel_platform(channel) == "facebook"]


@st.fragment
def _render_facebook_automation_cards() -> None:
    if not _has_script_context():
        return
    st.divider()
    st.subheader("Posts Facebook em produção")
    posts = list_posts()
    if not posts:
        st.info("Ainda não existem posts Facebook em produção.")
        return
    for post in posts:
        post_id = str(post.get("id") or "")
        with st.container(border=True):
            cols = st.columns([2.5, 1.35, 1.15, 2.0], gap="small")
            with cols[0]:
                st.write(f"**{post.get('title') or post.get('theme') or 'Post sem tema'}**")
                st.caption(f"{post.get('page_name') or 'Facebook Page'} · {post_id}")
                st.caption(f"Etapa: {post.get('status', 'tema_pendente')}")
                if post.get("article_text"):
                    with st.expander("Ver artigo", expanded=False):
                        st.text_area("Artigo", value=str(post["article_text"]), height=220, key=f"facebook_article_{post_id}", disabled=True)
                image_records = post.get("images") if isinstance(post.get("images"), list) else []
                if image_records:
                    image_cols = st.columns(min(5, len(image_records)))
                    for image_col, image in zip(image_cols, image_records):
                        image_path = Path(str(image.get("captioned_path") or image.get("path") or ""))
                        with image_col:
                            if image_path.is_file():
                                st.image(str(image_path), use_container_width=True)
                            st.caption(str(image.get("status") or "pendente"))
            with cols[1]:
                st.caption("Estado")
                st.write(str(post.get("status") or "tema_pendente").replace("_", " ").capitalize())
                st.progress({"tema_pendente": 0, "artigo_pendente": 20, "imagens_pendentes": 45, "legendas_pendentes": 70, "pronto_upload": 90, "publicado": 100}.get(str(post.get("status")), 0), text=f"{len(post.get('images') or [])}/5 imagens")
            with cols[2]:
                st.caption("Imagens")
                st.write(f"{len(post.get('images') or [])} previstas")
                st.caption("Google Imagens ou IA")
            with cols[3]:
                settings = read_json("settings.json", {})
                pages = _facebook_pages_for_automation()
                page = next((item for item in pages if str(item.get("id")) == str(post.get("page_id"))), {})
                if st.button("Gerar tema", key=f"facebook_generate_theme_{post_id}", disabled=str(post.get("status")) not in {"tema_pendente", "erro"}, width="stretch"):
                    try:
                        generate_theme(settings, post, page)
                        st.success("Tema criado pelo LLM.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
                if st.button("Criar artigo", key=f"facebook_generate_article_{post_id}", disabled=str(post.get("status")) != "artigo_pendente", width="stretch"):
                    try:
                        generate_article(settings, post, page)
                        st.success("Artigo e prompts de imagens criados pelo LLM.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
                source = st.selectbox("Fonte das imagens", ["Google Imagens", "Gerar com IA"], key=f"facebook_image_source_{post_id}")
                if st.button("Buscar/Gerar imagens", key=f"facebook_collect_images_{post_id}", disabled=str(post.get("status")) != "imagens_pendentes", width="stretch"):
                    try:
                        collect_images(settings, post, source="google" if source == "Google Imagens" else "ai")
                        st.success("Imagens processadas.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
                if st.button("Legendar imagens", key=f"facebook_caption_images_{post_id}", disabled=str(post.get("status")) != "legendas_pendentes", width="stretch"):
                    try:
                        caption_images(post)
                        st.success("Textos aplicados nas imagens com Pillow.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
                if st.button("Upload para Facebook", key=f"facebook_publish_{post_id}", type="primary", disabled=str(post.get("status")) != "pronto_upload", width="stretch"):
                    try:
                        publish_to_facebook(post, page)
                        st.success("Post publicado na Facebook Page.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))


def render_facebook_automation() -> None:
    st.title("Automação Facebook")
    st.caption("Fluxo local de posts: Ideia/Tema → LLM → Artigo → Google Imagens ou IA → textos e legendas → Upload pela Meta Graph API.")
    pages = _facebook_pages_for_automation()
    settings = read_json("settings.json", {})
    if not pages:
        st.info("Nenhuma Facebook Page seleccionada. A fila pode ser criada e preenchida; o destino poderá ser escolhido mais tarde.")
    with st.expander("Configurar API Facebook da página", expanded=False):
        for page in pages:
            page_id = str(page.get("id") or "")
            with st.form(f"facebook_page_api_{page_id}"):
                st.write(f"**{page.get('name') or 'Facebook Page'}**")
                meta_page_id = st.text_input("Page ID da Meta", value=str(page.get("page_id") or page.get("facebook_page_id") or ""), key=f"facebook_meta_page_id_{page_id}")
                access_token = st.text_input("Access Token da Page", value=str(page.get("access_token") or page.get("facebook_access_token") or ""), type="password", key=f"facebook_meta_token_{page_id}")
                if st.form_submit_button("Guardar credenciais Facebook", type="primary"):
                    update_channel(page_id, {"page_id": meta_page_id.strip(), "facebook_page_id": meta_page_id.strip(), "access_token": access_token.strip(), "facebook_access_token": access_token.strip()})
                    st.success("Credenciais da página guardadas localmente.")
                    st.rerun()
    with st.form("facebook_automation_new_post"):
        page_options = [""] + [str(page.get("id")) for page in pages]
        page_labels = {str(page.get("id")): str(page.get("name") or "Facebook Page") for page in pages}
        selected_page = st.selectbox("Facebook Page", page_options, format_func=lambda value: page_labels.get(value, "Nenhuma página seleccionada"), key="facebook_automation_target_page")
        form_cols = st.columns([2.2, 1, 1.3])
        with form_cols[0]:
            theme = st.text_input("Tema/ideia opcional", placeholder="Deixe vazio para o LLM sugerir um tema")
        with form_cols[1]:
            image_count = st.number_input("Imagens", min_value=1, max_value=5, value=3, step=1)
        with form_cols[2]:
            start_stage = st.selectbox("Iniciar por", ["Ideia / Tema", "Tema já definido"])
        create_clicked = st.form_submit_button("Criar post na fila", type="primary", width="stretch")
    if create_clicked:
        page = next((page for page in pages if str(page.get("id")) == selected_page), {})
        post = create_post(page, image_count=int(image_count), theme=theme)
        if start_stage == "Tema já definido" and theme.strip():
            save_post({**post, "status": "artigo_pendente"})
        st.success("Post criado na fila local. Execute cada etapa pelos botões do card.")
        st.rerun()
    _render_facebook_automation_cards()


@st.fragment
def _render_youtube_automation_channel_cards():
    channels = [channel for channel in read_json("channels.json", []) if is_youtube_channel_record(channel)]
    if not channels:
        st.info("Nenhum canal cadastrado para configurar.")
    with st.expander("Canais cadastrados", expanded=False):
        automation_country_options = [""] + list(COUNTRY_OPTIONS)
        automation_filter_cols = st.columns([1, 1], gap="small")
        with automation_filter_cols[0]:
            automation_country_filter = st.selectbox(
                "Filtrar por País",
                automation_country_options,
                format_func=lambda value: value or "Todos os países",
                key="youtube_automation_country_filter",
            )
        with automation_filter_cols[1]:
            if st.button("Filtrar", type="primary", width="content", key="youtube_automation_country_filter_apply"):
                st.session_state["youtube_automation_country_filter_applied"] = automation_country_filter
        applied_automation_country = str(st.session_state.get("youtube_automation_country_filter_applied") or "").strip()
        filtered_automation_channels = [
            channel for channel in channels
            if not applied_automation_country or str(channel.get("country") or "").strip() == applied_automation_country
        ]
        for channel in filtered_automation_channels:
            channel_id = channel["id"]
            with st.container(border=True):
                blueprint_ids, blueprint_labels, current_blueprint, voice_options, current_voice = channel_default_options(channel)
                automation_blueprint = current_blueprint
                automation_voice = current_voice
                paired_thumbnail = thumbnail_blueprint_for_blueprint(automation_blueprint)
                automation_format = str(channel.get("format") or "wide")
                header_cols = st.columns([0.58, 2.15, 1.4, 1.15, 1.15, 1.25, 0.82, 0.92], gap="small")
                with header_cols[0]:
                    if channel.get("thumbnail_url"):
                        st.image(channel["thumbnail_url"], width=48)
                    else:
                        st.markdown("### YT")
                with header_cols[1]:
                    st.write(f"**{channel.get('name', 'Sem nome')}**")
                    st.caption(channel.get("handle") or channel.get("url") or "sem URL")
                    st.caption(f"País: {channel.get('country') or 'Não definido'}")
                    channel_url = str(channel.get("url") or "").strip()
                    if not channel_url:
                        channel_id_or_handle = str(channel.get("youtube_channel_id") or channel.get("youtube_id") or channel.get("handle") or "").strip()
                        if channel_id_or_handle.startswith("http"):
                            channel_url = channel_id_or_handle
                        elif channel_id_or_handle.startswith("UC"):
                            channel_url = f"https://www.youtube.com/channel/{channel_id_or_handle}"
                        elif channel_id_or_handle.startswith(("@", "channel/")):
                            channel_url = f"https://www.youtube.com/{channel_id_or_handle}"
                        elif channel_id_or_handle:
                            channel_url = f"https://www.youtube.com/@{channel_id_or_handle}"
                    if channel_url:
                        open_create_cols = st.columns(2, gap="small")
                        with open_create_cols[0]:
                            st.link_button("Abrir canal", channel_url, type="primary", width="stretch")
                        with open_create_cols[1]:
                            if st.button("Criar Vídeo", key=f"youtube_automation_create_video_{channel_id}", width="stretch"):
                                if _create_video_now_from_channel(channel):
                                    st.rerun(scope="fragment")
                    else:
                        if st.button("Criar Vídeo", key=f"youtube_automation_create_video_{channel_id}", width="stretch"):
                            if _create_video_now_from_channel(channel):
                                st.rerun(scope="fragment")
                with header_cols[2]:
                    st.markdown("**Thumbnail Blueprint**")
                    st.caption(str(paired_thumbnail.get("name") or "Youtube_Generic_Thumbnail_Blueprint"))
                with header_cols[3]:
                    st.markdown("**Idioma do roteiro**")
                    st.caption(video_language_label(normalize_video_language(channel.get("language") or "pt")))
                with header_cols[4]:
                    st.markdown("**Nicho Padrão**")
                    st.caption(channel_niche_label(channel))
                with header_cols[5]:
                    st.markdown("**Fonte do vídeo**")
                    st.caption(channel_video_source_value(channel.get("style_wide")))
                    st.markdown("**Proporção do vídeo**")
                    st.caption(str(channel.get("video_aspect_ratio") or "Landscape 16:9"))
                with header_cols[6]:
                    schedule_time = st.text_input("Horário (HH:MM)", value=channel.get("automation_time", "00:00"), key=f"automation_time_{channel_id}")
                with header_cols[7]:
                    calculated_time, calculated_source, calculated_words = _channel_average_video_time(channel)
                    average_video_time = st.text_input("Tempo Medio de Video", value=channel_video_time_value(channel), key=f"average_video_time_{channel_id}", help=f"Referência média: {calculated_words or 0} palavras · fonte: {calculated_source}.")

                control_cols = st.columns([1.8, 1.8, 1.35, 1.2], gap="small")
                with control_cols[0]:
                    automation_blueprint = st.selectbox(
                        "Blueprint Padrão",
                        blueprint_ids,
                        index=blueprint_ids.index(current_blueprint) if current_blueprint in blueprint_ids else 0,
                        format_func=lambda item: blueprint_labels.get(item, item or "Sem Blueprint padrão"),
                        key=f"automation_blueprint_{channel_id}",
                    )
                paired_thumbnail = thumbnail_blueprint_for_blueprint(automation_blueprint)
                with control_cols[1]:
                    automation_voice = st.selectbox(
                        "Narrador/Voz Padrão",
                        voice_options,
                        index=voice_options.index(current_voice) if current_voice in voice_options else 0,
                        format_func=lambda item: item or "Sem voz padrão",
                        key=f"automation_voice_{channel_id}",
                    )
                with control_cols[2]:
                    enabled = st.toggle("Automação ligada", value=bool(channel.get("automation_on", False)), key=f"automation_on_{channel_id}")
                with control_cols[3]:
                    if st.button("Guardar", key=f"automation_save_{channel_id}", width="stretch", type="primary"):
                        if not valid_hhmm(schedule_time):
                            st.error("Use o formato HH:MM, por exemplo 08:30.")
                        elif not valid_hhmm(average_video_time):
                            st.error("O Tempo Medio de Video deve estar no formato MM:SS, por exemplo 12:00.")
                        else:
                            paired_id = str(paired_thumbnail.get("id") or "Youtube_Generic_Thumbnail_Blueprint")
                            update_channel(channel_id, {
                                "automation_on": bool(enabled),
                                "automation_time": schedule_time.strip(),
                                "average_video_time": average_video_time.strip() or DEFAULT_AVERAGE_VIDEO_TIME,
                                "average_video_word_count": words_from_channel_time(average_video_time),
                                "format": automation_format,
                                "blueprint_id": automation_blueprint,
                                "default_blueprint_id": automation_blueprint,
                                "voice": automation_voice,
                                "default_voice": automation_voice,
                                "thumbnail_blueprint_id": paired_id,
                                "default_thumbnail_blueprint_id": paired_id,
                            })
                            st.success("Agendamento guardado.")
                            st.rerun(scope="fragment")



def render_automation():
    st.title("Automação Youtube")
    st.caption("Agendamento diário da geração por canal. O worker verifica o relógio local do computador e coloca os lotes agendados na fila.")
    if st.button("Actualizar agora", key="youtube_automation_refresh", width="content"):
        st.rerun()
    _sync_saved_scripts_to_youtube_automation()
    worker_status = load_worker_status()
    local_now = datetime.now().astimezone()
    if worker_status.get("alive"):
        st.success(f"Worker activo · relógio local: {local_now.strftime('%d/%m/%Y %H:%M:%S %Z')}")
    else:
        st.warning("Worker de automação não está activo. Inicie o Thunderbolt pelo launcher (`npx.cmd --yes @danhachuel/thunderbolt`) para activar as verificações horárias.")
    last_tick = worker_status.get("last_tick_local")
    if last_tick:
        st.caption(f"Última verificação do worker: {last_tick}")
    if worker_status.get("last_error"):
        st.error(f"Último erro do worker: {worker_status['last_error']}")
    _render_youtube_automation_channel_cards()
    _render_youtube_automation_cards()

def render_upload_direct():
    st.subheader("Upload directo")
    st.caption("Upload interno baseado no YouTube-Video-Upload-Frontend-Api, sem usar a quota oficial da Data API. Este método requer cookies e tokens fornecidos manualmente pelo utilizador.")
    st.warning("Não cole cookies ou tokens em mensagens, issues ou Git. O Thunderbolt guarda-os apenas no storage local. A integração não extrai sessões automaticamente do navegador.")
    settings = read_json("settings.json", {})
    channels = read_json("channels.json", [])
    tasks = [task for task in read_json("tasks.json", []) if task.get("state") == "done" or task.get("artifacts", {}).get("video")]
    if not channels:
        st.info("Cadastre um canal e configure o DELEGATED_SESSION_ID antes de usar o upload directo.")
    if not tasks:
        st.info("Não há vídeos prontos para upload directo.")
        return
    direct_accounts = {str(account.get("id")): account for account in settings.get("youtube_batch_accounts", []) if isinstance(account, dict) and account.get("id")}
    channel_map = {channel.get("id"): channel for channel in channels}
    for task in tasks:
        channel = channel_map.get(task.get("channel_id"), {})
        video_path = (task.get("artifacts", {}) or {}).get("video", "")
        with st.container(border=True):
            st.write(f"**{task.get('topic', 'Sem tópico')}** — {task.get('channel_name', 'Canal')}")
            st.caption(video_path or "Sem caminho de vídeo registado")
            account = resolve_youtube_account(settings, channel)
            credential_status = document_status(STORAGE, account, channel, settings, channels) if account else None
            if not account:
                st.warning("Este canal não tem uma conta Google associada. Associe a conta no cartão deste canal em Canais cadastrados.")
            elif not credential_status["ready"]:
                missing_direct_parts = list(credential_status["missing_cookies"])
                if not credential_status["has_session_info"]:
                    missing_direct_parts.append("sessionInfo")
                if not credential_status["has_innertube_api_key"]:
                    missing_direct_parts.append("INNERTUBE_API_KEY")
                if not credential_status["has_delegated_session_id"]:
                    missing_direct_parts.append("DELEGATED_SESSION_ID deste canal")
                st.warning(f"Documento de credenciais incompleto: {', '.join(missing_direct_parts)}")
            else:
                st.caption(f"Documento de credenciais pronto: {account.get('email', 'conta Google')} · dados do canal encontrados no documento")
            direct_cols = st.columns([2.2, 1, 1])
            with direct_cols[0]:
                title = st.text_input("Título", value=task.get("title") or task.get("topic", "Vídeo Thunderbolt"), key=f"direct_title_{task['id']}")
            with direct_cols[1]:
                privacy = st.selectbox("Privacidade", ["private", "unlisted", "public"], key=f"direct_privacy_{task['id']}")
            with direct_cols[2]:
                st.caption("Chunk size lido do documento JSON da conta")
            description = st.text_area("Descrição", value=task.get("description", ""), key=f"direct_description_{task['id']}", height=90)
            if st.button("Enviar por Upload directo", type="primary", key=f"direct_upload_{task['id']}"):
                if not account:
                    st.error("Associe primeiro este canal a uma conta Google no cartão Upload directo — credenciais deste canal em Canais cadastrados.")
                elif not document_status(STORAGE, account, channel, settings, channels)["ready"]:
                    st.error("Complete o documento JSON desta conta, incluindo cookies, sessionInfo, INNERTUBE_API_KEY e DELEGATED_SESSION_ID deste canal.")
                else:
                    result = YouTubeDirectUploader(settings, channel, account=account, storage_root=STORAGE).upload(video_path, title=title, description=description, visibility=privacy)
                    record = {"task_id": task.get("id"), "channel_id": channel.get("id"), "google_account_id": account.get("id", ""), "destination": "YouTube direct frontend", "status": "published" if result.ok else "failed", "message": result.message, "data": result.data, "created_at": now()}
                    uploads = read_json("uploads.json", [])
                    uploads.append(record)
                    write_json("uploads.json", uploads)
                    reconcile_persisted_notifications(force=True)
                    (st.success if result.ok else st.error)(result.message)


def _persist_music_upload_settings(updates: dict[str, Any]) -> dict[str, Any]:
    settings = read_json("settings.json", {})
    settings.update(updates)
    write_json("settings.json", settings)
    return settings


def _render_music_source(prefix: str, extensions: set[str]) -> str:
    source_mode = st.radio(
        "Origem da música",
        ["Ficheiro existente", "Carregar ficheiro"],
        horizontal=True,
        key=f"{prefix}_music_source_mode",
    )
    selected_path = str(st.session_state.get(f"{prefix}_music_path") or "")
    if source_mode == "Ficheiro existente":
        existing = [path for path in list_music_files() if path.suffix.lower() in extensions]
        if existing:
            selected = st.selectbox(
                "Música local",
                existing,
                index=next((index for index, item in enumerate(existing) if str(item) == selected_path), 0),
                format_func=lambda item: item.name,
                key=f"{prefix}_music_existing",
            )
            selected_path = str(selected)
            st.session_state[f"{prefix}_music_path"] = selected_path
        else:
            st.info("Ainda não existem ficheiros compatíveis em storage/music. Escolha Carregar ficheiro.")
            selected_path = ""
    else:
        uploaded = st.file_uploader(
            "Carregar ficheiro de música",
            type=sorted(extension.lstrip(".") for extension in extensions),
            key=f"{prefix}_music_file_upload",
        )
        if uploaded is not None and st.button("Guardar música no storage local", key=f"{prefix}_music_store", width="stretch"):
            try:
                stored = store_music_file(uploaded.name, uploaded.getvalue())
                selected_path = str(stored)
                st.session_state[f"{prefix}_music_path"] = selected_path
                st.success(f"Música guardada em `{stored}`.")
            except (OSError, ValueError) as exc:
                st.error(str(exc))
        selected_path = str(st.session_state.get(f"{prefix}_music_path") or selected_path)
    if selected_path and Path(selected_path).is_file():
        st.caption(f"Ficheiro seleccionado: `{selected_path}`")
        return selected_path
    return ""


def _record_music_upload(destination: str, result: IntegrationResult, *, music_path: str = "", target: dict[str, Any] | None = None) -> dict[str, Any]:
    record = {
        "id": uuid.uuid4().hex,
        "destination": destination,
        "music_path": music_path,
        "target": target or {},
        "status": "published" if result.ok else "failed",
        "message": result.message,
        "data": result.data,
        "created_at": now(),
    }
    uploads = read_json("uploads.json", [])
    uploads.append(record)
    write_json("uploads.json", uploads)
    reconcile_persisted_notifications(force=True)
    return record


def _render_music_upload_history() -> None:
    records = [
        record
        for record in read_json("uploads.json", [])
        if isinstance(record, dict)
        and any(name in str(record.get("destination") or "").lower() for name in ("jewelmusic", "pushtunes", "youtube music", "ytmusicapi", "distrokid"))
    ]
    st.divider()
    st.subheader("Histórico de uploads de música")
    if not records:
        st.caption("Ainda não existem uploads de música registados.")
        return
    for record in reversed(records[-20:]):
        status = "Concluído" if record.get("status") == "published" else "Falhou"
        path = Path(str(record.get("music_path") or ""))
        with st.container(border=True):
            st.write(f"**{record.get('destination', 'Upload musical')}** · {status}")
            st.caption(f"{record.get('created_at', '—')} · {path.name if path.name else record.get('target', {})}")
            st.write(record.get("message", ""))
            if path.is_file():
                st.download_button(
                    "Descarregar cópia local",
                    data=path.read_bytes(),
                    file_name=path.name,
                    mime=mimetypes.guess_type(path.name)[0] or "audio/mpeg",
                    key=f"music_history_download_{record.get('id')}",
                )


def _render_jewelmusic_upload_tab() -> None:
    st.subheader("JewelMusic")
    st.caption("Upload de tracks para o JewelMusic através do endpoint documentado do SDK, com distribuição posterior para as plataformas disponíveis na sua conta.")
    st.info("A API Key é guardada apenas no settings.json local. O teste consulta /v1/ping e não cria uma track.")
    settings = read_json("settings.json", {})
    with st.form("jewelmusic_settings_form"):
        enabled = st.checkbox("Activar JewelMusic", value=bool(settings.get("jewelmusic_enabled", False)))
        api_key = st.text_input("JewelMusic API Key", value=str(settings.get("jewelmusic_api_key") or ""), type="password")
        base_url = st.text_input("Base URL", value=str(settings.get("jewelmusic_base_url") or "https://api.jewelmusic.com"))
        proxy_url = st.text_input("Proxy opcional", value=str(settings.get("jewelmusic_proxy_url") or ""), placeholder="http://127.0.0.1:8080")
        timeout_seconds = st.number_input("Timeout (segundos)", min_value=5, max_value=900, value=int(settings.get("jewelmusic_timeout_seconds", 120)), step=5)
        save = st.form_submit_button("Guardar configuração JewelMusic", type="primary", width="stretch")
    if save:
        settings = _persist_music_upload_settings({
            "jewelmusic_enabled": bool(enabled),
            "jewelmusic_api_key": api_key.strip(),
            "jewelmusic_base_url": base_url.strip().rstrip("/"),
            "jewelmusic_proxy_url": proxy_url.strip(),
            "jewelmusic_timeout_seconds": int(timeout_seconds),
        })
        st.success("Configuração JewelMusic guardada no storage local.")
    adapter = JewelMusicAdapter(settings)
    if st.button("Testar conexão JewelMusic", key="jewelmusic_test", width="stretch"):
        test_result = adapter.test_connection()
        (st.success if test_result.ok else st.error)(test_result.message)
    music_path = _render_music_source("jewelmusic", MUSIC_UPLOAD_EXTENSIONS)
    metadata_cols = st.columns(4)
    with metadata_cols[0]:
        title = st.text_input("Título", value=Path(music_path).stem if music_path else "", key="jewelmusic_title")
    with metadata_cols[1]:
        artist = st.text_input("Artista", key="jewelmusic_artist")
    with metadata_cols[2]:
        album = st.text_input("Álbum", key="jewelmusic_album")
    with metadata_cols[3]:
        year = st.text_input("Ano", key="jewelmusic_year")
    genre = st.text_input("Género", key="jewelmusic_genre")
    if st.button("Enviar música para JewelMusic", type="primary", key="jewelmusic_upload", width="stretch", disabled=not bool(music_path)):
        result = JewelMusicAdapter(read_json("settings.json", {})).upload_track(music_path, title=title, artist=artist, album=album, year=year, genre=genre)
        _record_music_upload("JewelMusic", result, music_path=music_path, target={"artist": artist, "title": title})
        (st.success if result.ok else st.error)(result.message)


def _store_pushtunes_csv(uploaded: Any) -> str:
    target = STORAGE / "music" / "pushtunes-source.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(uploaded.getvalue())
    return str(target)


def _render_pushtunes_upload_tab() -> None:
    st.subheader("Pushtunes")
    st.caption("Sincronização de biblioteca a partir de Subsonic, Jellyfin ou CSV para Spotify, YouTube Music ou Tidal. Pushtunes não transforma um MP3 isolado num upload; para isso use JewelMusic ou ytmusicapi.")
    st.warning("O Pushtunes usa as credenciais próprias dos serviços. O Thunderbolt apenas inicia o comando local com parâmetros separados e mascara os segredos na saída.")
    settings = read_json("settings.json", {})
    with st.form("pushtunes_settings_form"):
        enabled = st.checkbox("Activar Pushtunes", value=bool(settings.get("pushtunes_enabled", False)))
        executable = st.text_input("Executável ou módulo", value=str(settings.get("pushtunes_executable") or "pushtunes"), help="Por padrão é usado o comando pushtunes instalado no ambiente Python do Thunderbolt.")
        source = st.selectbox("Fonte", list(PUSHTUNES_SOURCES), index=list(PUSHTUNES_SOURCES).index(str(settings.get("pushtunes_source") or "csv")) if str(settings.get("pushtunes_source") or "csv") in PUSHTUNES_SOURCES else 0, format_func=lambda value: {"csv": "CSV local", "subsonic": "Subsonic/Navidrome", "jellyfin": "Jellyfin", "spotify": "Spotify", "ytm": "YouTube Music"}.get(value, value))
        target = st.selectbox("Destino", list(PUSHTUNES_TARGETS), index=list(PUSHTUNES_TARGETS).index(str(settings.get("pushtunes_target") or "ytm")) if str(settings.get("pushtunes_target") or "ytm") in PUSHTUNES_TARGETS else 0, format_func=lambda value: {"spotify": "Spotify", "ytm": "YouTube Music", "tidal": "Tidal", "csv": "CSV"}.get(value, value))
        operation = st.selectbox("Operação", list(PUSHTUNES_OPERATIONS), index=list(PUSHTUNES_OPERATIONS).index(str(settings.get("pushtunes_operation") or "tracks")) if str(settings.get("pushtunes_operation") or "tracks") in PUSHTUNES_OPERATIONS else 0, format_func=lambda value: {"tracks": "Tracks", "albums": "Álbuns", "playlist": "Playlist"}.get(value, value))
        profile = st.text_input("Perfil Pushtunes (.toml), opcional", value=str(settings.get("pushtunes_profile") or ""))
        csv_file = st.text_input("Caminho CSV", value=str(settings.get("pushtunes_csv_file") or ""))
        ytm_auth_file = st.text_input("Caminho browser.json do YouTube Music", value=str(settings.get("pushtunes_ytm_auth_file") or ""))
        tidal_session_file = st.text_input("Caminho tidal-session.json do Tidal", value=str(settings.get("pushtunes_tidal_session_file") or ""))
        playlist_name = st.text_input("Nome da playlist", value=str(settings.get("pushtunes_playlist_name") or ""))
        similarity = st.slider("Similaridade mínima", min_value=0.0, max_value=1.0, value=float(settings.get("pushtunes_similarity", 0.8)), step=0.05)
        working_directory = st.text_input("Directório de trabalho", value=str(settings.get("pushtunes_working_directory") or ""))
        spotify_client_id = st.text_input("Spotify Client ID", value=str(settings.get("pushtunes_spotify_client_id") or ""))
        spotify_client_secret = st.text_input("Spotify Client Secret", value=str(settings.get("pushtunes_spotify_client_secret") or ""), type="password")
        spotify_redirect_uri = st.text_input("Spotify Redirect URI", value=str(settings.get("pushtunes_spotify_redirect_uri") or ""))
        timeout_seconds = st.number_input("Timeout Pushtunes (segundos)", min_value=30, max_value=3600, value=int(settings.get("pushtunes_timeout_seconds", 1800)), step=30)
        save = st.form_submit_button("Guardar configuração Pushtunes", type="primary", width="stretch")
    if save:
        settings = _persist_music_upload_settings({
            "pushtunes_enabled": bool(enabled),
            "pushtunes_executable": executable.strip() or "pushtunes",
            "pushtunes_source": source,
            "pushtunes_target": target,
            "pushtunes_operation": operation,
            "pushtunes_profile": profile.strip(),
            "pushtunes_csv_file": csv_file.strip(),
            "pushtunes_ytm_auth_file": ytm_auth_file.strip(),
            "pushtunes_tidal_session_file": tidal_session_file.strip(),
            "pushtunes_playlist_name": playlist_name.strip(),
            "pushtunes_similarity": float(similarity),
            "pushtunes_working_directory": working_directory.strip(),
            "pushtunes_spotify_client_id": spotify_client_id.strip(),
            "pushtunes_spotify_client_secret": spotify_client_secret.strip(),
            "pushtunes_spotify_redirect_uri": spotify_redirect_uri.strip(),
            "pushtunes_timeout_seconds": int(timeout_seconds),
        })
        st.success("Configuração Pushtunes guardada no storage local.")
    if source == "csv":
        st.caption("Pode carregar o CSV nesta página e usar o caminho guardado como origem Pushtunes.")
        csv_upload = st.file_uploader("Carregar CSV de origem Pushtunes", type=["csv"], key="pushtunes_csv_upload")
        if csv_upload is not None and st.button("Guardar CSV Pushtunes no storage", key="pushtunes_csv_store", width="stretch"):
            stored_csv = _store_pushtunes_csv(csv_upload)
            settings = _persist_music_upload_settings({"pushtunes_csv_file": stored_csv})
            st.success(f"CSV guardado em `{stored_csv}`.")
    adapter = PushtunesAdapter(read_json("settings.json", {}))
    status = adapter.status()
    (st.success if status.ok else st.warning)(status.message)
    if st.button("Validar instalação e configuração Pushtunes", key="pushtunes_test", width="stretch"):
        check = PushtunesAdapter(read_json("settings.json", {})).status()
        (st.success if check.ok else st.error)(check.message)
    if st.button("Executar sincronização Pushtunes", type="primary", key="pushtunes_sync", width="stretch", disabled=not status.ok):
        result = PushtunesAdapter(read_json("settings.json", {})).sync()
        _record_music_upload(f"Pushtunes ({adapter.source} → {adapter.target})", result, target={"source": adapter.source, "target": adapter.target, "operation": adapter.operation})
        (st.success if result.ok else st.error)(result.message)
        if result.data.get("stdout") or result.data.get("stderr"):
            with st.expander("Saída técnica do Pushtunes"):
                st.text(result.data.get("stdout", ""))
                if result.data.get("stderr"):
                    st.text(result.data["stderr"])


def _store_ytmusicapi_auth(uploaded: Any) -> str:
    target = STORAGE / "ytmusicapi" / "browser.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(uploaded.getvalue())
    return str(target)


def _render_ytmusicapi_upload_tab() -> None:
    st.subheader("ytmusicapi")
    st.caption("Upload de músicas para YouTube Music através da API não oficial ytmusicapi. O serviço exige autenticação de browser e aceita MP3, M4A, WMA, FLAC ou OGG até 300 MB.")
    st.warning("Use um browser.json exportado/configurado pelo ytmusicapi. Não cole cookies ou tokens na conversa, no GitHub ou em issues; o ficheiro fica apenas no storage local.")
    settings = read_json("settings.json", {})
    with st.form("ytmusicapi_settings_form"):
        enabled = st.checkbox("Activar ytmusicapi", value=bool(settings.get("ytmusicapi_enabled", False)))
        auth_file = st.text_input("Caminho do browser.json", value=str(settings.get("ytmusicapi_auth_file") or ""))
        proxy_url = st.text_input("Proxy opcional", value=str(settings.get("ytmusicapi_proxy_url") or ""), placeholder="http://127.0.0.1:8080")
        timeout_seconds = st.number_input("Timeout (segundos)", min_value=30, max_value=900, value=int(settings.get("ytmusicapi_timeout_seconds", 240)), step=10)
        save = st.form_submit_button("Guardar configuração ytmusicapi", type="primary", width="stretch")
    if save:
        settings = _persist_music_upload_settings({
            "ytmusicapi_enabled": bool(enabled),
            "ytmusicapi_auth_file": auth_file.strip(),
            "ytmusicapi_proxy_url": proxy_url.strip(),
            "ytmusicapi_timeout_seconds": int(timeout_seconds),
        })
        st.success("Configuração ytmusicapi guardada no storage local.")
    auth_upload = st.file_uploader("Carregar browser.json", type=["json"], key="ytmusicapi_auth_upload")
    if auth_upload is not None and st.button("Guardar browser.json no storage local", key="ytmusicapi_auth_store", width="stretch"):
        stored_auth = _store_ytmusicapi_auth(auth_upload)
        settings = _persist_music_upload_settings({"ytmusicapi_auth_file": stored_auth, "ytmusicapi_enabled": True})
        st.success(f"Ficheiro de autenticação guardado em `{stored_auth}`.")
    adapter = YTMusicApiAdapter(read_json("settings.json", {}))
    status = adapter.status()
    (st.success if status.ok else st.warning)(status.message)
    if st.button("Testar autenticação ytmusicapi", key="ytmusicapi_test", width="stretch"):
        result = YTMusicApiAdapter(read_json("settings.json", {})).test_connection()
        (st.success if result.ok else st.error)(result.message)
    music_path = _render_music_source("ytmusicapi", YT_MUSIC_UPLOAD_EXTENSIONS)
    if st.button("Enviar música para YouTube Music", type="primary", key="ytmusicapi_upload", width="stretch", disabled=not bool(music_path) or not status.ok):
        result = YTMusicApiAdapter(read_json("settings.json", {})).upload_song(music_path)
        _record_music_upload("ytmusicapi / YouTube Music", result, music_path=music_path, target={"service": "youtube_music"})
        (st.success if result.ok else st.error)(result.message)


def _store_distrokid_cover(uploaded: Any) -> str:
    target_dir = STORAGE / "distrokid"
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(uploaded.name).name).strip("._") or "cover.jpg"
    target = target_dir / f"{uuid.uuid4().hex[:10]}_{safe_name}"
    target.write_bytes(uploaded.getvalue())
    return str(target)

def _render_distrokid_upload_tab() -> None:
    st.subheader("DistroKid")
    st.caption("Upload assistido baseado no fluxo de publish do musikai. O browser preenche o novo lançamento e carrega as faixas; a submissão final fica sempre manual no DistroKid.")
    settings = read_json("settings.json", {})
    with st.form("distrokid_settings_form"):
        enabled = st.checkbox("Activar DistroKid", value=bool(settings.get("distrokid_enabled", False)))
        cookie = st.text_input("Cookie de sessão DistroKid", value=str(settings.get("distrokid_cookie") or ""), type="password", help="Cole o cabeçalho Cookie da sua sessão DistroKid. O valor é guardado apenas no storage local.")
        account = st.text_input("Nome da conta DistroKid", value=str(settings.get("distrokid_account") or ""))
        browser_path = st.text_input("Executável Chrome/Chromium (opcional)", value=str(settings.get("distrokid_browser_path") or ""), help="Deixe vazio para usar Google Chrome; também pode definir THUNDERBOLT_CHROME_PATH.")
        settings_cols = st.columns(2)
        with settings_cols[0]:
            first_name = st.text_input("Primeiro nome", value=str(settings.get("distrokid_first_name") or ""))
            artist = st.text_input("Artista", value=str(settings.get("distrokid_artist") or ""))
            release_title = st.text_input("Título do lançamento", value=str(settings.get("distrokid_release_title") or ""))
        with settings_cols[1]:
            last_name = st.text_input("Apelido", value=str(settings.get("distrokid_last_name") or ""))
            record_label = st.text_input("Record label", value=str(settings.get("distrokid_record_label") or ""))
            genre = st.text_input("Género principal", value=str(settings.get("distrokid_genre") or ""), help="O género deve corresponder a uma opção aceite pelo formulário DistroKid.")
        save = st.form_submit_button("Guardar configuração DistroKid", type="primary", width="stretch")
    if save:
        _persist_music_upload_settings({
            "distrokid_enabled": bool(enabled), "distrokid_cookie": cookie.strip(), "distrokid_account": account.strip(),
            "distrokid_browser_path": browser_path.strip(), "distrokid_first_name": first_name.strip(), "distrokid_last_name": last_name.strip(),
            "distrokid_artist": artist.strip(), "distrokid_release_title": release_title.strip(), "distrokid_record_label": record_label.strip(), "distrokid_genre": genre.strip(),
        })
        st.success("Configuração DistroKid guardada no storage local.")
    settings = read_json("settings.json", {})
    adapter = DistroKidAdapter(settings)
    status = adapter.status()
    (st.success if status.ok else st.warning)(status.message)
    if st.button("Testar sessão DistroKid", key="distrokid_test", width="stretch"):
        result = DistroKidAdapter(read_json("settings.json", {})).test_connection()
        (st.success if result.ok else st.error)(result.message)
    uploaded_tracks = st.file_uploader("Faixas para o lançamento", type=sorted(extension.lstrip(".") for extension in DISTROKID_AUDIO_EXTENSIONS), accept_multiple_files=True, key="distrokid_track_upload")
    if uploaded_tracks and st.button("Guardar faixas no storage local", key="distrokid_store_tracks", width="stretch"):
        stored_paths: list[str] = []
        for uploaded in uploaded_tracks:
            try:
                stored_paths.append(str(store_music_file(f"distrokid_{uuid.uuid4().hex[:8]}_{uploaded.name}", uploaded.getvalue())))
            except (OSError, ValueError) as exc:
                st.error(str(exc))
        if stored_paths:
            st.session_state["distrokid_track_paths"] = stored_paths
            st.success(f"{len(stored_paths)} faixa(s) guardada(s) no storage local.")
    selected_paths = [str(path) for path in st.session_state.get("distrokid_track_paths", []) if Path(str(path)).is_file()]
    track_rows: list[dict[str, Any]] = []
    if selected_paths:
        st.markdown("**Faixas seleccionadas**")
        for index, path in enumerate(selected_paths, start=1):
            track_title = st.text_input(f"Título da faixa {index}", value=Path(path).stem, key=f"distrokid_track_title_{index}")
            instrumental = st.checkbox("Instrumental", value=False, key=f"distrokid_track_instrumental_{index}")
            track_rows.append({"path": path, "title": track_title.strip() or Path(path).stem, "instrumental": instrumental})
    cover_upload = st.file_uploader("Capa do lançamento (opcional)", type=sorted(extension.lstrip(".") for extension in DISTROKID_COVER_EXTENSIONS), key="distrokid_cover_upload")
    if cover_upload and st.button("Guardar capa no storage local", key="distrokid_store_cover", width="stretch"):
        try:
            st.session_state["distrokid_cover_path"] = _store_distrokid_cover(cover_upload)
            st.success("Capa guardada no storage local.")
        except OSError as exc:
            st.error(f"Não foi possível guardar a capa: {exc}")
    cover_path = str(st.session_state.get("distrokid_cover_path") or "")
    if cover_path and Path(cover_path).is_file():
        st.caption(f"Capa seleccionada: `{cover_path}`")
    session_id = str(st.session_state.get("distrokid_session_id") or "")
    if session_id and st.button("Fechar browser DistroKid", key="distrokid_close_browser", width="stretch"):
        result = close_distrokid_session(session_id)
        (st.success if result.ok else st.warning)(result.message)
        st.session_state.pop("distrokid_session_id", None)
    if st.button("Abrir formulário e carregar para DistroKid", type="primary", key="distrokid_prepare_upload", width="stretch", disabled=not status.ok or not track_rows):
        current = read_json("settings.json", {})
        result = DistroKidAdapter(current).prepare_upload(
            track_rows, artist=str(current.get("distrokid_artist") or ""), release_title=str(current.get("distrokid_release_title") or ""),
            record_label=str(current.get("distrokid_record_label") or ""), cover_path=cover_path or None, genre=str(current.get("distrokid_genre") or ""),
        )
        _record_music_upload("DistroKid", result, music_path=selected_paths[0] if selected_paths else "", target={"service": "DistroKid", "account": str(current.get("distrokid_account") or "")})
        (st.success if result.ok else st.error)(result.message)
        if result.ok and result.data.get("session_id"):
            st.session_state["distrokid_session_id"] = result.data["session_id"]

def render_music_upload() -> None:
    st.title("Upload Música")
    st.caption("Carregue músicas por JewelMusic, sincronize bibliotecas com Pushtunes, envie para YouTube Music com ytmusicapi ou prepare um lançamento DistroKid. As credenciais, browser e histórico permanecem locais.")
    jewel_tab, pushtunes_tab, ytmusicapi_tab, distrokid_tab = render_localized_tabs(["JewelMusic", "Pushtunes", "ytmusicapi", "DistroKid"])
    with jewel_tab:
        _render_jewelmusic_upload_tab()
    with pushtunes_tab:
        _render_pushtunes_upload_tab()
    with ytmusicapi_tab:
        _render_ytmusicapi_upload_tab()
    with distrokid_tab:
        _render_distrokid_upload_tab()
    _render_music_upload_history()


def render_upload():
    st.title("Upload")
    upload_tab, direct_tab, postiz_tab, upload_post_tab, composio_tab = render_localized_tabs(["Upload convencional", "Upload directo", "Postiz", "Upload-Post", "Upload via Composio"])
    with direct_tab:
        render_upload_direct()
    with postiz_tab:
        render_upload_postiz()
    with upload_post_tab:
        render_upload_post()
    with upload_tab:
        render_upload_conventional()
    with composio_tab:
        render_upload_composio()


def render_upload_composio():
    st.subheader("Upload via Composio")
    st.caption("Descubra uma ferramenta de upload Composio, ligue a conta do provider quando necessário e envie um vídeo seleccionado. O slug e o campo do ficheiro são sempre escolhidos explicitamente.")
    settings = read_json("settings.json", {})
    api_key = str(settings.get("composio_api_key") or "").strip()
    user_id = str(settings.get("composio_user_id") or "").strip()
    connected_account_id = str(settings.get("composio_connected_account_id") or "").strip()
    if not settings.get("composio_enabled", False) or not api_key:
        st.warning("Composio está desactivado ou sem API key. Configure-o em Configuração API > API Keys Upload > Composio.")
        return
    query = st.text_input("Pesquisar ferramenta Composio", value="upload a video file", key="composio_upload_query")
    toolkit_filter = st.text_input("Toolkit preferido (opcional)", value=str(settings.get("composio_toolkit") or ""), key="composio_upload_toolkit")
    if st.button("Descobrir ferramentas", key="composio_upload_discover", width="stretch"):
        try:
            st.session_state["composio_upload_tools"] = discover_tools(api_key, user_id, query, toolkit_filter)
            if not st.session_state["composio_upload_tools"]:
                st.info("Nenhuma ferramenta encontrada. Tente uma pesquisa mais específica ou deixe o toolkit vazio.")
            else:
                st.success(f"{len(st.session_state['composio_upload_tools'])} ferramenta(s) encontrada(s).")
        except ComposioUploadError as exc:
            st.error(str(exc))
    tools = [item for item in st.session_state.get("composio_upload_tools", []) if isinstance(item, dict) and item.get("slug")]
    if not tools:
        st.info("Clique em Descobrir ferramentas para carregar os destinos disponíveis na sua conta Composio.")
        return
    tool_slugs = [str(item["slug"]) for item in tools]
    selected_slug = st.selectbox("Ferramenta de upload", tool_slugs, format_func=lambda slug: next((f"{item.get('name') or slug} — {item.get('toolkit') or 'toolkit desconhecido'}" for item in tools if item.get("slug") == slug), slug), key="composio_upload_slug")
    selected_tool = next((item for item in tools if item.get("slug") == selected_slug), tools[0])
    if selected_tool.get("description"):
        st.caption(str(selected_tool["description"]))
    schema = selected_tool.get("schema") or {}
    with st.expander("Schema da ferramenta", expanded=False):
        st.json(schema)
    file_field = st.text_input("Campo que recebe o vídeo", value=str(st.session_state.get("composio_upload_file_field") or "file"), key="composio_upload_file_field")
    arguments_json = st.text_area("Argumentos JSON adicionais", value=str(st.session_state.get("composio_upload_arguments") or "{}"), height=150, key="composio_upload_arguments")
    if st.button("Autorizar toolkit no Composio", key="composio_upload_authorize", width="stretch"):
        try:
            auth = authorize_toolkit(api_key, user_id, str(selected_tool.get("toolkit") or ""))
            if auth.get("redirect_url"):
                st.success("Connect Link criado. Abra o link para autorizar a conta e depois repita o envio.")
                st.markdown(f"[Abrir Connect Link do Composio]({auth['redirect_url']})")
            else:
                st.info("O Composio não devolveu um Connect Link; confirme o estado da conta no dashboard.")
        except ComposioUploadError as exc:
            st.error(str(exc))
    tasks = [task for task in read_json("tasks.json", []) if task.get("state") == "done" or task.get("artifacts", {}).get("video")]
    if not tasks:
        st.info("Não há vídeos prontos para enviar via Composio.")
        return
    task_options = {str(task.get("id")): task for task in tasks if task.get("id")}
    selected_task_id = st.selectbox("Vídeo", list(task_options), format_func=lambda task_id: f"{task_options[task_id].get('topic') or 'Vídeo Thunderbolt'} — {task_options[task_id].get('artifacts', {}).get('video') or 'sem ficheiro'}", key="composio_upload_task")
    task = task_options[selected_task_id]
    video_path = str((task.get("artifacts", {}) or {}).get("video") or "")
    st.caption(video_path or "Sem caminho de vídeo registado")
    st.info(f"Resumo: `{selected_slug}` · toolkit `{selected_tool.get('toolkit') or 'não indicado'}` · campo `{file_field or 'não indicado'}`")
    if st.button("Enviar vídeo via Composio", type="primary", key=f"composio_upload_send_{selected_task_id}", width="stretch"):
        try:
            parse_arguments(arguments_json)
            result = execute_upload(api_key, user_id, selected_slug, video_path, file_field, arguments_json, connected_account_id)
            record = {"id": uuid.uuid4().hex, "task_id": task.get("id"), "destination": "Composio", "target": {"toolkit": selected_tool.get("toolkit"), "slug": selected_slug, "file_field": file_field}, "status": "published" if result.get("successful") else "failed", "message": result.get("error") or "Upload Composio concluído.", "data": result.get("data") or {}, "diagnostics": result.get("diagnostics") or {}, "log_id": result.get("log_id") or "", "created_at": now()}
            uploads = read_json("uploads.json", [])
            uploads.append(record)
            write_json("uploads.json", uploads)
            reconcile_persisted_notifications(force=True)
            if result.get("successful"):
                st.success(record["message"])
            else:
                st.error(record["message"])
            if result.get("log_id"):
                st.caption(f"Composio log ID: {result['log_id']}")
            if result.get("diagnostics"):
                with st.expander("Logs de diagnóstico Composio", expanded=True):
                    st.json(result["diagnostics"])
        except ComposioUploadError as exc:
            st.error(str(exc))


def render_upload_postiz():
    st.subheader("Upload para Postiz")
    st.caption("O Thunderbolt envia primeiro o MP4 para o Postiz e cria um post na integração seleccionada. A API key e o servidor são configurados em Configuração API.")
    settings = read_json("settings.json", {})
    postiz = PostizAdapter(settings)
    if not settings.get("postiz_enabled"):
        st.warning("Postiz está desactivado. Active-o em Configuração API > API Keys e guarde a API key antes de enviar.")
    if not postiz.api_key:
        st.info("Nenhuma API key Postiz configurada.")
        return

    integration_catalog = st.session_state.get("postiz_integrations", [])
    integration_ids = [str(item.get("id")) for item in integration_catalog if isinstance(item, dict) and item.get("id")]
    integration_labels = {
        str(item.get("id")): " — ".join(str(value) for value in [item.get("name") or item.get("provider") or item.get("type") or "Integração", item.get("username") or item.get("profile") or item.get("identifier") or ""] if value)
        for item in integration_catalog if isinstance(item, dict) and item.get("id")
    }
    integration_default = str(settings.get("postiz_integration_id", "") or "")
    if st.button("Carregar integrações Postiz", key="postiz_load_integrations"):
        result = postiz.list_integrations()
        if result.ok:
            st.session_state["postiz_integrations"] = result.data.get("integrations", [])
            st.success(result.message)
            st.rerun()
        st.error(result.message)
    if integration_ids:
        selected_integration = st.selectbox(
            "Canal/integração Postiz",
            integration_ids,
            index=integration_ids.index(integration_default) if integration_default in integration_ids else 0,
            format_func=lambda value: integration_labels.get(value, value),
            key="postiz_upload_integration",
        )
        st.caption("Para alterar a integração padrão, guarde o ID seleccionado em Configuração API.")
    else:
        selected_integration = st.text_input("ID da integração Postiz", value=integration_default, key="postiz_upload_integration_manual", help="Carregue as integrações para seleccionar uma conta ou introduza o ID devolvido pela API do Postiz.").strip()
        st.info("Carregue as integrações para descobrir os canais Postiz ligados à sua conta.")

    tasks = [task for task in read_json("tasks.json", []) if task.get("state") == "done" or task.get("artifacts", {}).get("video")]
    if not tasks:
        st.info("Não há vídeos prontos para enviar para o Postiz.")
        return
    for task in tasks:
        artifacts = task.get("artifacts", {}) or {}
        video_path = artifacts.get("video", "")
        thumbnail_path = artifacts.get("thumbnail") or artifacts.get("cover", "")
        with st.container(border=True):
            st.write(f"**{task.get('topic', 'Vídeo Thunderbolt')}** — {task.get('channel_name', 'Canal')}")
            st.caption(video_path or "Sem caminho de vídeo registado")
            title = st.text_input("Título Postiz", value=task.get("title") or task.get("topic", "Vídeo Thunderbolt"), key=f"postiz_title_{task['id']}")
            description = st.text_area("Descrição Postiz", value=task.get("description", ""), key=f"postiz_description_{task['id']}", height=90)
            visibility = st.selectbox("Visibilidade YouTube no Postiz", ["private", "unlisted", "public"], key=f"postiz_visibility_{task['id']}")
            if st.button("Enviar vídeo para Postiz", type="primary", key=f"postiz_upload_{task['id']}"):
                result = postiz.publish_video(
                    video_path,
                    integration_id=selected_integration,
                    title=title,
                    description=description,
                    visibility=visibility,
                    tags=task.get("tags", []) if isinstance(task.get("tags", []), list) else [tag.strip() for tag in str(task.get("tags", "")).split(",") if tag.strip()],
                    thumbnail_path=thumbnail_path,
                )
                record = {
                    "task_id": task.get("id"),
                    "destination": "Postiz",
                    "status": "published" if result.ok else "failed",
                    "message": result.message,
                    "data": result.data,
                    "created_at": now(),
                }
                uploads = read_json("uploads.json", [])
                uploads.append(record)
                write_json("uploads.json", uploads)
                reconcile_persisted_notifications(force=True)
                (st.success if result.ok else st.error)(result.message)


def render_upload_post():
    st.subheader("Upload-Post")
    st.caption("Envie um vídeo para uma ou mais plataformas ligadas ao seu perfil Upload-Post. A API key é lida da Configuração API e nunca é mostrada nesta aba.")
    settings = read_json("settings.json", {})
    uploader = UploadPostAdapter(settings)
    status = uploader.status()
    if not status.ok:
        st.warning(status.message)
        if not uploader.enabled:
            st.info("Active Upload-Post em Configuração API > API Keys > Serviços e modelos e guarde a configuração.")
        elif not uploader.api_key:
            st.info("Introduza a API key do Upload-Post em Configuração API > API Keys > Serviços e modelos.")
        return

    configured_platforms = normalize_upload_post_platforms(uploader.platforms)
    selected_platforms = st.multiselect(
        "Plataformas Upload-Post",
        list(UPLOAD_POST_PLATFORM_OPTIONS),
        default=configured_platforms,
        format_func=lambda value: "Facebook Pages" if value == "facebook" else "X (Twitter)" if value == "x" else value.title(),
        key="upload_post_platforms_selector",
        help="Seleccione uma ou mais plataformas já ligadas ao perfil Upload-Post.",
    )
    async_upload = st.checkbox(
        "Processar em segundo plano",
        value=False,
        key="upload_post_async_upload",
        help="Envia async_upload=true para a API e mostra o request ID devolvido, quando existir.",
    )
    if not selected_platforms:
        st.info("Seleccione pelo menos uma plataforma antes de publicar.")

    tasks = [task for task in read_json("tasks.json", []) if task.get("state") == "done" or task.get("artifacts", {}).get("video")]
    if not tasks:
        st.info("Não há vídeos prontos para enviar pelo Upload-Post.")
        return
    for task in tasks:
        artifacts = task.get("artifacts", {}) or {}
        video_path = artifacts.get("video", "")
        with st.container(border=True):
            st.write(f"**{task.get('topic', 'Vídeo Thunderbolt')}** — {uploader.username}")
            st.caption(video_path or "Sem caminho de vídeo registado")
            title = st.text_input("Título Upload-Post", value=task.get("title") or task.get("topic", "Vídeo Thunderbolt"), key=f"upload_post_title_{task['id']}")
            description = st.text_area("Descrição Upload-Post", value=task.get("description", ""), key=f"upload_post_description_{task['id']}", height=90)
            if st.button("Enviar vídeo pelo Upload-Post", type="primary", key=f"upload_post_send_{task['id']}", disabled=not selected_platforms):
                result = uploader.upload_video(
                    video_path,
                    title=title,
                    description=description,
                    user=uploader.username,
                    platforms=selected_platforms,
                    async_upload=async_upload,
                )
                record = {
                    "id": uuid.uuid4().hex,
                    "task_id": task.get("id"),
                    "destination": "Upload-Post",
                    "target": {"username": uploader.username, "platforms": selected_platforms},
                    "status": "published" if result.ok else "failed",
                    "message": result.message,
                    "data": result.data,
                    "created_at": now(),
                }
                uploads = read_json("uploads.json", [])
                uploads.append(record)
                write_json("uploads.json", uploads)
                reconcile_persisted_notifications(force=True)
                (st.success if result.ok else st.error)(result.message)
                if result.ok and result.data.get("request_id"):
                    st.caption(f"Request ID Upload-Post: {result.data['request_id']}")


UPLOAD_DESTINATION_TARGET_KEYS = {
    "TikTok": "tiktok_accounts",
    "Bilibili": "bilibili_api_cards",
    "Instagram": "instagram_profiles",
    "Facebook Pages": "facebook_pages",
}


def upload_target_label(target: Any) -> str:
    if isinstance(target, dict):
        name = str(target.get("name") or target.get("label") or target.get("title") or target.get("username") or target.get("id") or "Sem nome")
        handle = str(target.get("handle") or target.get("username") or target.get("url") or "")
        return f"{name} — {handle}" if handle and handle not in name else name
    return str(target)


def upload_target_reference(target: Any) -> dict[str, str] | str | None:
    if target is None:
        return None
    if isinstance(target, dict):
        public_fields = ("id", "name", "label", "handle", "username", "url")
        return {field: str(target[field]) for field in public_fields if target.get(field)}
    return str(target)


def upload_targets_for_destination(destination: str, channels: list[dict[str, Any]], settings: dict[str, Any]) -> list[Any]:
    if destination == "YouTube":
        return [channel for channel in channels if isinstance(channel, dict) and channel.get("id") and channel.get("active", True)]
    setting_key = UPLOAD_DESTINATION_TARGET_KEYS.get(destination)
    if not setting_key:
        return []
    configured_targets = settings.get(setting_key, [])
    if destination == "TikTok" and (not isinstance(configured_targets, list) or not configured_targets):
        configured_targets = settings.get("tiktok_profiles", [])
    if destination == "Bilibili" and isinstance(configured_targets, list):
        configured_targets = [item for item in configured_targets if isinstance(item, dict) and bool(item.get("active", True))]
    if not isinstance(configured_targets, list):
        return []
    targets: list[Any] = []
    for target in configured_targets:
        if isinstance(target, dict) and target.get("id"):
            targets.append(target)
        elif isinstance(target, str) and target.strip():
            targets.append(target.strip())
    return targets


def render_upload_destination_target(destination: str, channels: list[dict[str, Any]], settings: dict[str, Any]) -> Any | None:
    options = upload_targets_for_destination(destination, channels, settings)
    destination_key = re.sub(r"[^a-z0-9]+", "_", destination.lower()).strip("_")
    select_label = "Canal" if destination == "YouTube" else ("Conta TikTok" if destination == "TikTok" else ("Conta Bilibili" if destination == "Bilibili" else "Perfil / página"))
    empty_label = "Nenhum canal YouTube cadastrado" if destination == "YouTube" else ("Nenhuma conta TikTok cadastrada" if destination == "TikTok" else ("Nenhuma conta Bilibili activa" if destination == "Bilibili" else f"Nenhum {destination} configurado"))
    if not options:
        st.selectbox(select_label, [""], format_func=lambda _value: empty_label, key=f"upload_target_{destination_key}")
        if destination == "YouTube":
            st.caption("Nenhum canal YouTube disponível; o destino permanece vazio e pode ser escolhido mais tarde.")
        elif destination == "TikTok":
            st.caption("Nenhuma conta TikTok disponível; o destino permanece vazio e pode ser escolhido mais tarde.")
        elif destination == "Bilibili":
            st.caption("Nenhuma conta Bilibili disponível; o destino permanece vazio e pode ser escolhido mais tarde.")
        else:
            st.caption(f"Nenhum destino {destination} disponível; a lista permanece vazia.")
        return None
    return st.selectbox(
        select_label,
        options,
        format_func=upload_target_label,
        key=f"upload_target_{destination_key}",
    )


def render_upload_conventional():
    st.title("Upload")
    settings = read_json("settings.json", {})
    youtube = YouTubeAdapter(settings=settings)
    channels = read_json("channels.json", [])
    channel_map = {str(channel.get("id")): channel for channel in channels if channel.get("id")}
    direct_accounts = {str(account.get("id")): account for account in settings.get("youtube_batch_accounts", []) if isinstance(account, dict) and account.get("id")}
    postiz = PostizAdapter(settings)
    tasks = [t for t in read_json("tasks.json", []) if t.get("state") == "done" or t.get("artifacts", {}).get("video")]
    destination = st.multiselect("Destinos", ["YouTube", "TikTok", "Bilibili", "Instagram", "Facebook Pages"], default=["YouTube"], key="upload_destinations", placeholder="Seleccione os destinos")
    upload_targets: dict[str, Any | None] = {}
    if destination:
        st.markdown("**Onde enviar**")
        for target_destination in destination:
            with st.container(border=True):
                upload_targets[target_destination] = render_upload_destination_target(target_destination, channels, settings)

    if "Instagram" in destination:
        st.info("Instagram está disponível no front end. A publicação real será ligada numa etapa de credenciais/API própria.")
    if "Facebook Pages" in destination:
        st.info("Facebook Pages está disponível no front end. A publicação real será ligada numa etapa de credenciais/API própria.")

    if "YouTube" in destination:
        st.markdown("**YouTube — fluxo recomendado de envio**")
        st.caption("Ordem automática: 1. API Oficial — até 5 envios bem-sucedidos por dia e por conta Gmail; 2. Upload directo — sessão interna YouTube; 3. Postiz — fallback final configurável.")
        status = youtube.upload_status()
        if settings.get("postiz_enabled"):
            postiz_status = postiz.status()
            (st.success if postiz_status.ok else st.warning)(postiz_status.message)
        else:
            st.caption("Postiz está desactivado; active-o em Configuração API para o usar como fallback final.")
        status_cols = st.columns(2)
        with status_cols[0]:
            (st.success if status["agent"].ok else st.warning)(f"Agente: {status['agent'].message}")
            if st.button("Autorizar agente YouTube", key="youtube_authorize_agent", width="stretch"):
                result = youtube.authorize_agent()
                (st.success if result.ok else st.error)(result.message)
                if result.ok:
                    st.rerun()
        with status_cols[1]:
            (st.info if status["fallback"].ok else st.caption)(f"Fallback OAuth: {status['fallback'].message}")
            if st.button("Autorizar fallback OAuth", key="youtube_authorize_fallback", width="stretch"):
                result = youtube.authorize_fallback()
                (st.success if result.ok else st.error)(result.message)
                if result.ok:
                    st.rerun()
    if "TikTok" in destination:
        status = TikTokAdapter(settings).status()
        (st.success if status.ok else st.warning)(status.message)
    if not tasks:
        st.info("Não há vídeos prontos para upload.")
        return
    for task in tasks:
        with st.container(border=True):
            st.write(f"**{task.get('topic')}** — {task.get('channel_name')}")
            artifacts = task.get("artifacts", {}) or {}
            video_path = artifacts.get("video", "")
            thumbnail_path = artifacts.get("thumbnail") or artifacts.get("cover", "")
            captions_path = artifacts.get("captions") or artifacts.get("subtitle", "")
            st.caption(video_path or "Sem caminho de vídeo registado")
            selected_youtube_channel = upload_targets.get("YouTube") if "YouTube" in destination else None
            channel = selected_youtube_channel or channel_map.get(str(task.get("channel_id")), {})
            account = resolve_youtube_account(settings, channel)
            if "YouTube" in destination:
                detected_language = normalize_video_language(task.get("language") or channel.get("language") or "pt")
                language_state_key = f"yt_language_{task['id']}"
                language_source_key = f"yt_language_source_{task['id']}"
                if st.session_state.get(language_source_key) != detected_language:
                    st.session_state[language_state_key] = detected_language
                    st.session_state[language_source_key] = detected_language
                title_state_key = f"yt_title_{task['id']}"
                title = st.text_input("Título", value=task.get("title") or task.get("topic", "Vídeo Thunderbolt"), key=title_state_key)
                description_state_key = f"yt_description_{task['id']}"
                description_error_key = f"yt_description_ai_error_{task['id']}"

                def generate_upload_description_callback() -> None:
                    current_title = str(st.session_state.get(title_state_key) or title).strip()
                    raw_tags = st.session_state.get(f"yt_tags_{task['id']}", task.get("tags", ""))
                    current_tags = raw_tags if isinstance(raw_tags, list) else [item.strip() for item in str(raw_tags or "").split(",") if item.strip()]
                    try:
                        st.session_state[description_state_key] = generate_video_description(
                            settings,
                            channel,
                            str(task.get("topic") or current_title),
                            title=current_title,
                            tags=current_tags,
                            language=detected_language,
                        )
                    except CreativeGenerationError as exc:
                        st.session_state[description_error_key] = str(exc)
                    else:
                        st.session_state.pop(description_error_key, None)

                description = st.text_area("Descrição", value=task.get("description", ""), key=description_state_key, height=100)
                st.button("Gerar descrição com IA", key=f"yt_description_ai_{task['id']}", width="content", on_click=generate_upload_description_callback)
                if description_error := str(st.session_state.get(description_error_key) or "").strip():
                    st.error(f"Não foi possível gerar a descrição: {description_error}")
                tags_raw = st.text_input("Tags separadas por vírgula", value=task.get("tags", "") if isinstance(task.get("tags", ""), str) else ", ".join(task.get("tags", [])), key=f"yt_tags_{task['id']}")
                yt_cols = st.columns(3)
                with yt_cols[0]:
                    privacy_status = st.selectbox("Privacidade", ["private", "unlisted", "public"], index=1, key=f"yt_privacy_{task['id']}")
                    st.caption("Fluxo recomendado: não listado · incorporação activa · permitir remix de áudio e vídeo · publicar no feed de subscritos.")
                with yt_cols[1]:
                    category_id = st.text_input("Category ID", value="22", key=f"yt_category_{task['id']}")
                with yt_cols[2]:
                    language = st.selectbox(
                        "Idioma",
                        VIDEO_LANGUAGE_SELECTION_OPTIONS,
                        index=VIDEO_LANGUAGE_SELECTION_OPTIONS.index(detected_language) if detected_language in VIDEO_LANGUAGE_SELECTION_OPTIONS else 0,
                        format_func=video_language_label,
                        key=language_state_key,
                    )
                quota_count = official_upload_count(channel, account)
                st.caption(f"API Oficial hoje: {quota_count}/{OFFICIAL_DAILY_LIMIT} envios nesta conta Gmail.")
                if not selected_youtube_channel:
                    st.caption("Nenhum canal YouTube seleccionado; o destino permanece vazio e poderá ser escolhido mais tarde.")
                if st.button("Enviar pelo fluxo recomendado", type="primary", key=f"upload_youtube_{task['id']}"):
                    tags = [tag.strip() for tag in tags_raw.split(",") if tag.strip()]
                    result = upload_with_default_route(
                        settings,
                        storage_root=STORAGE,
                        channel=channel,
                        account=account,
                        video_path=video_path,
                        title=title,
                        description=description,
                        tags=tags,
                        category_id=category_id,
                        language=language,
                        privacy_status=privacy_status,
                        thumbnail_path=thumbnail_path,
                        captions_path=captions_path,
                    )
                    record = {
                        "task_id": task.get("id"),
                        "destination": "YouTube",
                        "target": upload_target_reference(channel),
                        "status": "published" if result.ok else "failed",
                        "message": result.message,
                        "data": result.data,
                        "created_at": now(),
                    }
                    uploads = read_json("uploads.json", [])
                    uploads.append(record)
                    write_json("uploads.json", uploads)
                    reconcile_persisted_notifications(force=True)
                    (st.success if result.ok else st.error)(result.message)
                    if result.data.get("attempts"):
                        with st.expander("Detalhes dos mecanismos de upload"):
                            st.json(result.data["attempts"])
            tiktok_target = upload_targets.get("TikTok") if "TikTok" in destination else None
            if "TikTok" in destination and st.button("Enviar para TikTok", key=f"upload_tiktok_{task['id']}", disabled=not tiktok_target, help="Escolha o perfil TikTok no selector acima." if not tiktok_target else None):
                result = TikTokAdapter(settings).upload_video(video_path, task.get("title") or task.get("topic", ""))
                record = {
                    "task_id": task.get("id"),
                    "destination": "TikTok",
                    "target": upload_target_reference(tiktok_target),
                    "status": "published" if result.ok else "failed",
                    "message": result.message,
                    "data": result.data,
                    "created_at": now(),
                }
                uploads = read_json("uploads.json", [])
                uploads.append(record)
                write_json("uploads.json", uploads)
                reconcile_persisted_notifications(force=True)
                (st.success if result.ok else st.warning)(result.message)
            bilibili_target = upload_targets.get("Bilibili") if "Bilibili" in destination else None
            if "Bilibili" in destination:
                bilibili_title = st.text_input("Título Bilibili", value=task.get("title") or task.get("topic", "Vídeo Thunderbolt"), key=f"bilibili_title_{task['id']}")
                bilibili_description = st.text_area("Descrição Bilibili", value=task.get("description", ""), key=f"bilibili_description_{task['id']}", height=90)
                bilibili_tags = st.text_input("Tags Bilibili separadas por vírgulas", value=task.get("tags", "") if isinstance(task.get("tags", ""), str) else ", ".join(task.get("tags", [])), key=f"bilibili_tags_{task['id']}")
                bilibili_tid = st.number_input("ID da secção Bilibili", min_value=1, max_value=9999, value=BILIBILI_DEFAULT_TID, step=1, key=f"bilibili_tid_{task['id']}")
                if st.button("Enviar via bilibili-api (Python)", type="primary", key=f"upload_bilibili_{task['id']}", disabled=not bilibili_target, help="Configure e active uma conta Bilibili em Configuração API > API Bilibili." if not bilibili_target else None):
                    result = BilibiliApiAdapter(bilibili_target, settings).upload_video(
                        video_path, title=bilibili_title, description=bilibili_description, tags=bilibili_tags, tid=int(bilibili_tid),
                        cover_path=thumbnail_path or None,
                    )
                    record = {
                        "task_id": task.get("id"),
                        "destination": "Bilibili",
                        "target": upload_target_reference(bilibili_target),
                        "status": "published" if result.ok else "failed",
                        "message": result.message,
                        "data": result.data,
                        "created_at": now(),
                    }
                    uploads = read_json("uploads.json", [])
                    uploads.append(record)
                    write_json("uploads.json", uploads)
                    reconcile_persisted_notifications(force=True)
                    (st.success if result.ok else st.error)(result.message)
            if "Instagram" in destination:
                st.button("Preparar Instagram", key=f"upload_instagram_{task['id']}", disabled=True, help="UI preparada; publicação Instagram ainda não está activa.")
            if "Facebook Pages" in destination:
                st.button("Preparar Facebook Pages", key=f"upload_facebook_{task['id']}", disabled=True, help="UI preparada; publicação Facebook Pages ainda não está activa.")


def _normalise_tiktok_api_cards(settings: dict[str, Any]) -> tuple[list[dict[str, str]], bool]:
    raw_cards = settings.get("tiktok_api_cards")
    cards: list[dict[str, str]] = []
    changed = not isinstance(raw_cards, list)
    if isinstance(raw_cards, list):
        for index, raw_card in enumerate(raw_cards):
            if not isinstance(raw_card, dict):
                changed = True
                continue
            card_id = str(raw_card.get("id") or f"tiktok-api-{index + 1}").strip()
            client_id = str(raw_card.get("client_id") or raw_card.get("client_key") or "").strip()
            client_secret = str(raw_card.get("client_secret") or "").strip()
            normalised = {"id": card_id, "client_id": client_id, "client_secret": client_secret}
            cards.append(normalised)
            if normalised != {key: str(raw_card.get(key) or "").strip() for key in ("id", "client_id", "client_secret")}:
                changed = True
    if not cards:
        legacy_client_id = str(settings.get("tiktok_client_key") or "").strip()
        legacy_client_secret = str(settings.get("tiktok_client_secret") or "").strip()
        if legacy_client_id or legacy_client_secret:
            cards = [{"id": "tiktok-api-1", "client_id": legacy_client_id, "client_secret": legacy_client_secret}]
            changed = True
    if changed and cards:
        settings["tiktok_api_cards"] = cards
        write_json("settings.json", settings)
    return cards, changed


def _persist_tiktok_api_cards(settings: dict[str, Any], cards: list[dict[str, str]]) -> None:
    clean_cards = [
        {
            "id": str(card.get("id") or f"tiktok-api-{index + 1}").strip(),
            "client_id": str(card.get("client_id") or "").strip(),
            "client_secret": str(card.get("client_secret") or "").strip(),
        }
        for index, card in enumerate(cards)
    ]
    settings["tiktok_api_cards"] = clean_cards
    first = next((card for card in clean_cards if card["client_id"] and card["client_secret"]), clean_cards[0] if clean_cards else {"client_id": "", "client_secret": ""})
    settings["tiktok_client_key"] = first["client_id"]
    settings["tiktok_client_secret"] = first["client_secret"]
    write_json("settings.json", settings)


def render_tiktok_api_cards(settings: dict[str, Any]) -> None:
    st.title("API Tiktok")
    st.caption("Configure várias aplicações TikTok em cards separados. Cada card mantém apenas o TikTok Client ID e o TikTok Client Secret; autorização OAuth, scopes e tokens continuam a ser geridos no TikTok for Developers Playground.")
    cards, _ = _normalise_tiktok_api_cards(settings)
    if not cards:
        st.info("Ainda não existe nenhuma API TikTok configurada. Use o botão abaixo para criar o primeiro card.")
    for index, card in enumerate(cards):
        card_id = str(card["id"])
        with st.container(border=True):
            header_cols = st.columns([3.2, 1.2])
            with header_cols[0]:
                st.subheader(f"API TikTok {index + 1}")
            with header_cols[1]:
                configured = bool(card["client_id"] and card["client_secret"])
                _api_status_badge("Configured" if configured else "Missing configuration", "ready" if configured else "missing")
            with st.form(f"tiktok_api_card_form_{card_id}"):
                client_id = st.text_input("TikTok Client ID", value=card["client_id"], key=f"tiktok_api_{card_id}_client_id")
                client_secret = st.text_input("TikTok Client Secret", value=card["client_secret"], type="password", key=f"tiktok_api_{card_id}_client_secret")
                action_cols = st.columns(3)
                with action_cols[0]:
                    test_clicked = st.form_submit_button("Testar chamada API", width="stretch")
                with action_cols[1]:
                    save_clicked = st.form_submit_button("Guardar card", type="primary", width="stretch")
                with action_cols[2]:
                    delete_clicked = st.form_submit_button("Apagar card", width="stretch")
            edited = {"id": card_id, "client_id": client_id.strip(), "client_secret": client_secret.strip()}
            if test_clicked:
                cards[index] = edited
                _persist_tiktok_api_cards(settings, cards)
                result = test_tiktok_credentials(edited["client_id"], edited["client_secret"], settings.get("tiktok_access_token", ""))
                if result.get("status") == "success":
                    st.success(result.get("message") or "Chamada TikTok concluída.")
                elif result.get("status") == "unsupported":
                    st.warning(result.get("message") or "Conclua a autorização TikTok antes do teste.")
                else:
                    st.error(result.get("message") or "A chamada TikTok falhou.")
            elif save_clicked:
                cards[index] = edited
                _persist_tiktok_api_cards(settings, cards)
                st.success("Card TikTok guardado.")
                st.rerun()
            elif delete_clicked:
                cards = [item for item in cards if str(item.get("id")) != card_id]
                _persist_tiktok_api_cards(settings, cards)
                st.success("Card TikTok apagado.")
                st.rerun()
    if st.button("Adicionar nova API", type="primary", width="stretch", key="add_tiktok_api_card"):
        cards.append({"id": f"tiktok-api-{uuid.uuid4().hex[:10]}", "client_id": "", "client_secret": ""})
        _persist_tiktok_api_cards(settings, cards)
        st.success("Novo card TikTok criado.")
        st.rerun()


def _persist_bilibili_api_cards(settings: dict[str, Any], cards: list[dict[str, Any]]) -> None:
    clean_cards: list[dict[str, Any]] = []
    for item in cards:
        normalised, _ = normalise_bilibili_api_cards({"bilibili_api_cards": [item]})
        if normalised:
            clean_cards.append(normalised[0])
    settings["bilibili_api_cards"] = clean_cards
    first = next((card for card in clean_cards if card.get("active") and card.get("sessdata") and card.get("bili_jct") and card.get("buvid3")), clean_cards[0] if clean_cards else {})
    for field in ("sessdata", "bili_jct", "buvid3", "buvid4", "dedeuserid", "ac_time_value", "proxy"):
        settings[f"bilibili_{field}"] = str(first.get(field) or "")
    write_json("settings.json", settings)

def render_bilibili_api_cards(settings: dict[str, Any]) -> None:
    st.title("API Bilibili")
    st.caption("Configure várias contas Bilibili em cards separados. O upload usa bilibili-api-python; os cookies permanecem locais e nunca são mostrados em logs, históricos ou metadados.")
    st.warning("O pacote bilibili-api-python é uma integração opcional e depende da sessão do browser Bilibili. Use apenas contas e conteúdos que tenha autorização para operar.")
    cards, changed = normalise_bilibili_api_cards(settings)
    if changed and cards:
        _persist_bilibili_api_cards(settings, cards)
    if not cards:
        st.info("Ainda não existe nenhuma conta Bilibili configurada. Use o botão abaixo para criar o primeiro card.")
    for index, card in enumerate(cards):
        card_id = str(card["id"])
        with st.container(border=True):
            header_cols = st.columns([3.2, 1.2])
            with header_cols[0]:
                st.subheader(str(card.get("label") or f"Conta Bilibili {index + 1}"))
            with header_cols[1]:
                configured = bool(card.get("active", True) and card.get("sessdata") and card.get("bili_jct") and card.get("buvid3"))
                _api_status_badge("Configured" if configured else "Missing configuration", "ready" if configured else "missing")
            with st.form(f"bilibili_api_card_form_{card_id}"):
                label = st.text_input("Nome da conta", value=str(card.get("label") or f"Conta Bilibili {index + 1}"), key=f"bilibili_api_{card_id}_label")
                active = st.checkbox("Conta activa no Upload", value=bool(card.get("active", True)), key=f"bilibili_api_{card_id}_active")
                credential_cols = st.columns(2)
                with credential_cols[0]:
                    sessdata = st.text_input("SESSDATA", value=str(card.get("sessdata") or ""), type="password", key=f"bilibili_api_{card_id}_sessdata")
                    bili_jct = st.text_input("bili_jct", value=str(card.get("bili_jct") or ""), type="password", key=f"bilibili_api_{card_id}_bili_jct")
                    buvid3 = st.text_input("BUVID3", value=str(card.get("buvid3") or ""), type="password", key=f"bilibili_api_{card_id}_buvid3")
                    buvid4 = st.text_input("BUVID4 (opcional)", value=str(card.get("buvid4") or ""), type="password", key=f"bilibili_api_{card_id}_buvid4")
                with credential_cols[1]:
                    dedeuserid = st.text_input("DedeUserID (opcional)", value=str(card.get("dedeuserid") or ""), type="password", key=f"bilibili_api_{card_id}_dedeuserid")
                    ac_time_value = st.text_input("ac_time_value (opcional)", value=str(card.get("ac_time_value") or ""), type="password", key=f"bilibili_api_{card_id}_ac_time_value")
                    proxy = st.text_input("Proxy opcional", value=str(card.get("proxy") or ""), key=f"bilibili_api_{card_id}_proxy", placeholder="http://127.0.0.1:8080")
                action_cols = st.columns(3)
                with action_cols[0]:
                    test_clicked = st.form_submit_button("Testar chamada API", width="stretch")
                with action_cols[1]:
                    save_clicked = st.form_submit_button("Guardar card", type="primary", width="stretch")
                with action_cols[2]:
                    delete_clicked = st.form_submit_button("Apagar card", width="stretch")
            edited = {"id": card_id, "label": label.strip() or f"Conta Bilibili {index + 1}", "active": bool(active), "sessdata": sessdata.strip(), "bili_jct": bili_jct.strip(), "buvid3": buvid3.strip(), "buvid4": buvid4.strip(), "dedeuserid": dedeuserid.strip(), "ac_time_value": ac_time_value.strip(), "proxy": proxy.strip()}
            if test_clicked:
                cards[index] = edited
                _persist_bilibili_api_cards(settings, cards)
                result = BilibiliApiAdapter(edited, settings).test_connection()
                (st.success if result.ok else st.error)(result.message)
            elif save_clicked:
                cards[index] = edited
                _persist_bilibili_api_cards(settings, cards)
                st.success("Card Bilibili guardado.")
                st.rerun()
            elif delete_clicked:
                cards = [item for item in cards if str(item.get("id")) != card_id]
                _persist_bilibili_api_cards(settings, cards)
                st.success("Card Bilibili apagado.")
                st.rerun()
    if st.button("Adicionar nova API", type="primary", width="stretch", key="add_bilibili_api_card"):
        cards.append({"id": f"bilibili-api-{uuid.uuid4().hex[:10]}", "label": f"Conta Bilibili {len(cards) + 1}", "active": True, "sessdata": "", "bili_jct": "", "buvid3": "", "buvid4": "", "dedeuserid": "", "ac_time_value": "", "proxy": ""})
        _persist_bilibili_api_cards(settings, cards)
        st.success("Novo card Bilibili criado.")
        st.rerun()

def render_google_accounts(*, include_innertube: bool = True):
    st.title("Contas Google")
    st.caption("Gestão das contas Google/YouTube, documentos de credenciais, canais em lote e credenciais globais do YouTube.")
    settings = read_json("settings.json", {})

    st.subheader("Contas Google/YouTube — canais em lote")
    st.caption("Abra uma conta para ver e editar os detalhes. O e-mail identifica a conta Google; esta área não lê a caixa Gmail.")
    batch_accounts = [account for account in settings.get("youtube_batch_accounts", []) if isinstance(account, dict) and account.get("id")]
    channel_state = read_json("channels.json", [])
    youtube_accounts_missing_document: list[str] = []

    for batch_account in batch_accounts:
        account_id = str(batch_account["id"])
        account_email_snapshot = str(batch_account.get("email") or "sem e-mail")
        account_label_snapshot = str(batch_account.get("label") or "Canais YouTube")
        ensure_credentials_document(STORAGE, batch_account, settings, channel_state)
        direct_status = direct_account_status(STORAGE, batch_account, settings)
        session_health = check_account_session_info_health(STORAGE, batch_account, settings)
        missing_document_parts = list(direct_status.get("missing_cookies", []))
        if not direct_status.get("has_session_info"):
            missing_document_parts.append("sessionInfo")
        google_ready = bool(
            account_email_snapshot != "sem e-mail"
            and str(batch_account.get("client_id") or "").strip()
            and str(batch_account.get("client_secret") or "").strip()
        )
        youtube_upload_ready = bool(direct_status.get("document_exists") and not missing_document_parts)
        google_status_label = "Configured" if google_ready else ("Missing key" if not str(batch_account.get("client_id") or "").strip() or not str(batch_account.get("client_secret") or "").strip() else "Missing configuration")
        youtube_status_label = "Configured" if youtube_upload_ready else ("Missing key" if not direct_status.get("has_session_info") else "Missing configuration")
        if missing_document_parts:
            youtube_accounts_missing_document.append(account_email_snapshot)

        with st.container(border=True):
            account_header_cols = st.columns([2.35, 1.15, 1.35])
            with account_header_cols[0]:
                st.subheader(f"{account_label_snapshot} — {account_email_snapshot}")
            with account_header_cols[1]:
                st.caption("Conta Google")
                _api_status_badge(google_status_label, "ready" if google_ready else "missing")
            with account_header_cols[2]:
                st.caption("YouTube-Video-Upload-Frontend-Api")
                _api_status_badge(youtube_status_label, "ready" if youtube_upload_ready else "missing")
            with st.expander("Detalhes da conta Google", expanded=False):
                with st.form(f"batch_account_form_{account_id}"):
                    account_cols = st.columns(2)
                    with account_cols[0]:
                        account_label = st.text_input("Nome da conta", value=account_label_snapshot, key=f"batch_label_{account_id}")
                        account_email = st.text_input("E-mail/Gmail da conta", value=account_email_snapshot if account_email_snapshot != "sem e-mail" else "", key=f"batch_email_{account_id}")
                        account_client_id = st.text_input("OAuth Client ID", value=str(batch_account.get("client_id", "")), key=f"batch_client_id_{account_id}")
                    with account_cols[1]:
                        account_client_secret = st.text_input("OAuth Client Secret", value=str(batch_account.get("client_secret", "")), type="password", key=f"batch_client_secret_{account_id}")
                    save_account = st.form_submit_button("Guardar dados da conta Google", type="primary", width="stretch")


                account_status = youtube_batch_account_status(batch_account, STORAGE)
                status_cols = st.columns(2)
                with status_cols[0]:
                    (st.success if account_status.ok else st.warning)(account_status.message)
                with status_cols[1]:
                    if st.button("Autorizar/Reautorizar", key=f"batch_authorize_settings_{account_id}", width="stretch"):
                        result = authorize_youtube_batch_account(batch_account, STORAGE)
                        (st.success if result.ok else st.error)(result.message)
                        if result.ok:
                            st.rerun()
                if st.button("Apagar conta", icon=":material/delete:", key=f"batch_remove_settings_{account_id}", width="stretch"):
                    delete_youtube_batch_token(batch_account, STORAGE)
                    delete_credentials_document(STORAGE, batch_account)
                    remaining_accounts = [account for account in batch_accounts if str(account.get("id")) != account_id]
                    settings["youtube_batch_accounts"] = remaining_accounts
                    if settings.get("youtube_batch_selected_account_id") == account_id:
                        settings["youtube_batch_selected_account_id"] = str(remaining_accounts[0].get("id")) if remaining_accounts else ""
                    for channel in channel_state:
                        if str(channel.get("google_account_id") or "") == account_id:
                            channel.update({"google_account_id": "", "google_account_email": ""})
                    write_json("channels.json", channel_state)
                    write_json("settings.json", settings)
                    st.rerun()

                if save_account:
                    if "@" not in account_email.strip():
                        st.error("Informe um e-mail Google válido.")
                    elif not account_client_id.strip() or not account_client_secret.strip():
                        st.error("Informe o Client ID e o Client Secret desta conta.")
                    else:
                        for existing in batch_accounts:
                            if str(existing.get("id")) == account_id:
                                credentials_changed = any(existing.get(field, "") != value for field, value in (("email", account_email.strip()), ("client_id", account_client_id.strip()), ("client_secret", account_client_secret.strip())))
                                if credentials_changed:
                                    delete_youtube_batch_token(existing, STORAGE)
                                existing.update({"label": account_label.strip() or "Canais YouTube", "email": account_email.strip(), "client_id": account_client_id.strip(), "client_secret": account_client_secret.strip()})
                                ensure_credentials_document(STORAGE, existing, settings, channel_state)
                        settings["youtube_batch_accounts"] = batch_accounts
                        write_json("settings.json", settings)
                        st.success("Dados da conta Google guardados.")
                        st.rerun()

            with st.expander("Detalhes YouTube-Video-Upload-Frontend-Api", expanded=False):
                health_message = f"SessionInfo: {session_health.message}"
                if session_health.status == "healthy":
                    st.success(health_message)
                elif session_health.status in {"expiring", "unknown"}:
                    st.warning(health_message, icon="⚠️")
                elif session_health.status in {"expired", "blocked_by_google", "invalid_format"}:
                    st.error(health_message, icon="⚠️")
                account_session_info = st.text_input(
                    "sessionInfo token desta conta Google",
                    value=str(batch_account.get("sessionInfo") or batch_account.get("session_info") or batch_account.get("direct_session_info", "")),
                    type="password",
                    key=f"batch_session_info_{account_id}",
                    help="Token sessionInfo usado pelo Upload directo. É guardado por conta e sincronizado no credentials.json.",
                )
                captured_at_value = str(session_health.captured_at or batch_account.get("sessionInfoCapturedAt") or batch_account.get("session_info_captured_at") or "").strip()
                try:
                    account_session_info_captured_at = datetime.fromisoformat(captured_at_value.replace("Z", "+00:00")).date() if captured_at_value else None
                except ValueError:
                    account_session_info_captured_at = None
                account_session_info_captured_at = st.date_input("Data de Captura", value=account_session_info_captured_at, key=f"batch_session_info_captured_at_{account_id}", help="Data em que o sessionInfo token foi capturado.")
                st.markdown("**Área de Upload dos cookies**")
                st.caption("O documento padrão é criado automaticamente. Suba um JSON completo ou apenas o documento de cookies; os valores preenchidos são incorporados e mantidos em credentials.json.")
                document_upload = st.file_uploader("Subir documento de cookies/credenciais", type=["json"], key=f"direct_credentials_document_{account_id}", help="Aceita o JSON do YouTube-Video-Upload-Frontend-Api. Um documento parcial de cookies também é incorporado sem apagar os restantes campos.")
                if missing_document_parts:
                    st.warning(f"Documento incompleto: {', '.join(missing_document_parts)}")
                else:
                    st.success("Documento completo para a conta Google")
                st.caption(f"Documento guardado em: {direct_status['document_file']}")
                document_save = st.button("Guardar documento nesta conta", key=f"save_direct_account_{account_id}", width="stretch")
                if st.button("Autorizar upload YouTube", key=f"batch_authorize_upload_{account_id}", width="stretch", help="Autoriza esta conta com o escopo de publicação YouTube."):
                    result = authorize_youtube_agent(settings, STORAGE, account=batch_account)
                    (st.success if result.ok else st.error)(result.message)
                    if result.ok:
                        st.rerun()
                st.markdown("**Renovação de sessionInfo e cookies**")
                st.caption("A renovação é manual ou opt-in antes do upload; não há timer residente nem execução ao seleccionar a conta.")
                renewal_cols = st.columns([2, 1, 1])
                auto_renew = renewal_cols[0].checkbox("Renovar automaticamente antes do upload", value=bool(batch_account.get("auto_renew_before_upload", False)), key=f"auto_renew_before_upload_{account_id}")
                if renewal_cols[1].button("Renovar agora", key=f"renew_session_info_{account_id}", type="primary", width="stretch"):
                    result = renew_account_session(STORAGE, batch_account, settings, force=True, wait_seconds=10)
                    (st.success if result.ok else st.error)(result.message)
                    if result.ok:
                        st.rerun()
                with renewal_cols[2]:
                    _api_status_badge("Configured" if session_health.status == "healthy" else ("Missing key" if session_health.status == "missing" else "Missing configuration"), "ready" if session_health.status == "healthy" else "missing")
                if auto_renew != bool(batch_account.get("auto_renew_before_upload", False)):
                    batch_account["auto_renew_before_upload"] = bool(auto_renew)
                    settings["youtube_batch_accounts"] = batch_accounts
                    write_json("settings.json", settings)
                    st.success("Preferência de renovação guardada para esta conta.")
                if document_save:
                    if document_upload is None:
                        st.error("Seleccione um documento JSON de cookies/credenciais antes de guardar.")
                    else:
                        try:
                            merge_credentials_document(STORAGE, batch_account, document_upload.getvalue(), document_upload.name, session_info_override=account_session_info.strip(), channels=channel_state)
                            update_credentials_document_session_info(STORAGE, batch_account, account_session_info.strip(), captured_at=account_session_info_captured_at.isoformat() if isinstance(account_session_info_captured_at, date) else "")
                            st.success("Documento incorporado e guardado nesta conta Google.")
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))
                if st.button("Guardar dados YouTube-Video-Upload-Frontend-Api", key=f"save_upload_api_data_{account_id}", width="stretch"):
                    captured_at_iso = account_session_info_captured_at.isoformat() if isinstance(account_session_info_captured_at, date) else ""
                    update_credentials_document_session_info(STORAGE, batch_account, account_session_info.strip(), captured_at=captured_at_iso)
                    for existing in batch_accounts:
                        if str(existing.get("id")) == account_id:
                            existing.update({"sessionInfo": account_session_info.strip(), "sessionInfoCapturedAt": captured_at_iso})
                    settings["youtube_batch_accounts"] = batch_accounts
                    write_json("settings.json", settings)
                    st.success("Dados YouTube-Video-Upload-Frontend-Api guardados.")
                    st.rerun()

    if youtube_accounts_missing_document:
        st.info("Contas que ainda precisam de dados no documento: " + ", ".join(youtube_accounts_missing_document))

    if include_innertube:
        st.divider()
        st.markdown("### INNERTUBE_API_KEY")
        st.caption("Esta é uma chave API global do YouTube: aplica-se a todas as contas Google/YouTube e a todo o sistema. Não é associada a uma conta específica, não faz parte dos documentos de cookies/credenciais e não é editada no separador API Keys.")
        configured_global_innertube_api_key = str(settings.get("direct_innertube_api_key") or settings.get("INNERTUBE_API_KEY") or "").strip()
        current_innertube_api_key = configured_global_innertube_api_key
        if not current_innertube_api_key:
            # Migrate values created by older releases, which incorrectly stored
            # the key inside a selected Google account. The first legacy value is
            # retained as the single global value and all account copies are removed.
            for legacy_account in batch_accounts:
                current_innertube_api_key = str(legacy_account.get("innertube_api_key") or legacy_account.get("INNERTUBE_API_KEY") or "").strip()
                if current_innertube_api_key:
                    break
            if current_innertube_api_key:
                settings["direct_innertube_api_key"] = current_innertube_api_key
                settings.pop("INNERTUBE_API_KEY", None)
                for legacy_account in batch_accounts:
                    legacy_account.pop("innertube_api_key", None)
                    legacy_account.pop("INNERTUBE_API_KEY", None)
                settings["youtube_batch_accounts"] = batch_accounts
                write_json("settings.json", settings)
        innertube_status_cols = st.columns([3.2, 1.2])
        with innertube_status_cols[0]:
            st.caption("Estado da chave global")
        with innertube_status_cols[1]:
            _render_credential_status(current_innertube_api_key)
        with st.form("innertube_api_key_form"):
            innertube_api_key_value = st.text_input(
                "INNERTUBE_API_KEY",
                value=current_innertube_api_key,
                type="password",
                key="global_innertube_api_key",
                help="Chave global usada pelo Upload directo para todas as contas Google/YouTube. Guarde-a na configuração global, separada dos documentos de cookies.",
            )
            _render_api_test_control(
                settings,
                "innertube",
                lambda: test_innertube_api_key(innertube_api_key_value),
                widget_key="api_test_innertube",
            )
            save_innertube_api_key = st.form_submit_button("Guardar INNERTUBE_API_KEY global", type="primary", width="stretch")
        if save_innertube_api_key:
            settings["direct_innertube_api_key"] = innertube_api_key_value.strip()
            settings.pop("INNERTUBE_API_KEY", None)
            for legacy_account in batch_accounts:
                legacy_account.pop("innertube_api_key", None)
                legacy_account.pop("INNERTUBE_API_KEY", None)
            settings["youtube_batch_accounts"] = batch_accounts
            write_json("settings.json", settings)
            st.success("INNERTUBE_API_KEY global guardada para todas as contas Google/YouTube e para todo o sistema.")
            st.rerun()

    st.divider()
    add_account = False
    add_form_open = bool(st.session_state.get("add_batch_account_form_open", False))
    if not add_form_open and st.button("Adicionar conta Google/YouTube", type="primary", width="stretch", key="open_add_batch_account_form"):
        st.session_state["add_batch_account_form_open"] = True
        st.rerun()
    if add_form_open:
        st.markdown("### Nova conta Gmail")
        st.caption("Este formulário fica fora dos cartões das contas existentes. A associação de canais não depende da completude deste documento; ela apenas ficará pendente para Upload directo até os campos serem preenchidos.")
        with st.form("add_batch_account_form"):
            add_cols = st.columns(2)
            with add_cols[0]:
                new_account_label = st.text_input("Nome da nova conta", value="Canais YouTube", key="new_batch_account_label")
                new_account_email = st.text_input("E-mail/Gmail", key="new_batch_account_email")
                new_account_client_id = st.text_input("OAuth Client ID", key="new_batch_account_client_id")
            with add_cols[1]:
                new_account_client_secret = st.text_input("OAuth Client Secret", type="password", key="new_batch_account_client_secret")
                new_account_session_info = st.text_input("sessionInfo token desta conta Google", type="password", key="new_batch_account_session_info", help="Token sessionInfo desta conta. Os cookies e delegated_session_ids ficam no documento; a INNERTUBE_API_KEY é configurada no bloco próprio acima.")
                new_account_document = st.file_uploader("Documento de cookies/credenciais opcional", type=["json"], key="new_batch_account_credentials_document", help="Pode subir agora um JSON completo ou apenas o documento de cookies. Se não subir, será criado um credentials.json padrão vazio.")
            add_account = st.form_submit_button("Guardar conta Google/YouTube", type="primary", width="stretch")
        if st.button("Cancelar", key="cancel_add_batch_account_form"):
            st.session_state["add_batch_account_form_open"] = False
            st.rerun()
    if add_account:
        document_error = ""
        if "@" not in new_account_email.strip():
            st.error("Informe um e-mail Google válido.")
        elif not new_account_client_id.strip() or not new_account_client_secret.strip():
            st.error("Informe o Client ID e o Client Secret da nova conta.")
        elif new_account_document is not None:
            try:
                raw_document = new_account_document.getvalue()
                json.loads(raw_document.decode("utf-8-sig", errors="replace"))
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
                document_error = f"O documento {new_account_document.name} deve ser JSON válido."
                st.error(document_error)
        if "@" in new_account_email.strip() and new_account_client_id.strip() and new_account_client_secret.strip() and not document_error:
            new_account = {"id": f"google_batch_{uuid.uuid4().hex[:12]}", "label": new_account_label.strip() or "Canais YouTube", "email": new_account_email.strip(), "client_id": new_account_client_id.strip(), "client_secret": new_account_client_secret.strip(), "sessionInfo": new_account_session_info.strip()}
            batch_accounts.append(new_account)
            settings["youtube_batch_accounts"] = batch_accounts
            settings["youtube_batch_selected_account_id"] = new_account["id"]
            write_json("settings.json", settings)
            ensure_credentials_document(STORAGE, new_account, settings, channel_state)
            if new_account_document is not None:
                try:
                    merge_credentials_document(STORAGE, new_account, new_account_document.getvalue(), new_account_document.name, session_info_override=new_account_session_info.strip(), channels=channel_state)
                except ValueError as exc:
                    st.error(str(exc))
                    st.stop()
                st.success(f"Conta {new_account['email']} adicionada e documento incorporado.")
            else:
                st.warning(f"Conta {new_account['email']} adicionada. Foi criado um credentials.json padrão; suba o documento de cookies nesta conta quando estiver pronto.")
            st.session_state["add_batch_account_form_open"] = False
            st.rerun()

    st.divider()
    youtube_global_cols = st.columns([3.2, 1.2])
    with youtube_global_cols[0]:
        st.subheader("Configuração Global: YouTube Data API v3 (API Key)")
    with youtube_global_cols[1]:
        _render_credential_status(settings.get("youtube_api_key"), required=True)
    st.caption("1. YouTube Data API v3: Metadados públicos (títulos, views, likes) Via MCP integrado.\n\n2. YouTube Analytics API: Métricas internas (CTR, retenção, RPM, tráfego, demografia) Via OAuth 2.0 (Directamente via OAuth das Contas Google/YouTube cadastradas)")
    with st.form("google_global_api_settings_form"):
        st.caption("A autorização OAuth 2.0 é gerida por cada Conta Google/YouTube cadastrada e associada ao canal.")
        youtube_api_key = st.text_input(
            "YouTube Data API Key (opcional)",
            value=str(settings.get("youtube_api_key", "") or ""),
            type="password",
            key="google_page_youtube_api_key",
            help="Credencial Google Cloud separada, usada apenas para métricas oficiais da YouTube Data API.",
        )
        save_google_global = st.form_submit_button("Guardar configuração global do YouTube", type="primary", width="stretch")
    if save_google_global:
        settings.update({
            "youtube_api_key": youtube_api_key.strip(),
        })
        settings.pop("youtube_client_id", None)
        settings.pop("youtube_client_secret", None)
        write_json("settings.json", settings)
        st.success("Configuração global do YouTube guardada em Contas Google.")
        st.rerun()

def _persist_material_source_cards(settings: dict[str, Any], cards: list[dict[str, Any]], active_card_id: str = "") -> dict[str, Any]:
    updated = apply_material_source_cards_to_settings(settings, cards, active_card_id)
    write_json("settings.json", updated)
    return updated


def _material_source_card_definition(provider: str) -> dict[str, str]:
    definition = material_source_definition(provider)
    if definition is not None:
        return definition
    return {
        "code": "local",
        "label": "Ficheiros locais",
        "description": "Usar materiais já existentes no storage local; não requer API key.",
        "legacy_key": "",
    }


def _render_material_source_card(settings: dict[str, Any], cards: list[dict[str, Any]], index: int, *, embedded: bool = False) -> None:
    card = normalize_material_card(cards[index], index)
    cards[index] = card
    card_id = str(card["id"])
    provider = str(card.get("provider") or "pexels")
    definition = _material_source_card_definition(provider)
    is_local = provider == "local"
    active_card_id = str(settings.get("material_active_card_id") or "")
    with st.container(border=True):
        header_cols = st.columns([3.2, 1.2])
        with header_cols[0]:
            st.subheader(definition["label"])
            st.caption(definition["description"])
        with header_cols[1]:
            _render_credential_status("" if is_local else card.get("api_key"), local=is_local, required=not is_local)
        card_form = nullcontext() if embedded else st.form(f"material_source_card_form_{card_id}")
        with card_form:
            content_cols = st.columns([1.4, 1.25, 0.85])
            with content_cols[0]:
                if is_local:
                    st.caption("Esta fonte não usa API key.")
                    api_key = ""
                else:
                    api_key = st.text_input("API Key", value=str(card.get("api_key") or ""), type="password", key=f"material_card_{card_id}_api_key")
            with content_cols[1]:
                enabled = st.checkbox("Fonte activa", value=bool(card.get("enabled", True)), key=f"material_card_{card_id}_enabled")
                selected = st.checkbox(
                    "Usar esta fonte na pipeline",
                    value=active_card_id == card_id,
                    key=f"material_card_{card_id}_selected",
                )
            with content_cols[2]:
                priority = st.number_input(
                    "Prioridade",
                    min_value=1,
                    max_value=999,
                    value=max(1, int(card.get("priority", index + 1))),
                    step=1,
                    help="1 é o primeiro provider da fila. Em caso de falha elegível, os providers seguintes são considerados por ordem crescente.",
                    key=f"material_card_{card_id}_priority",
                )
            if not is_local:
                _render_api_test_control(
                    settings,
                    f"material:{card_id}",
                    lambda: test_material_source_credentials(provider, api_key),
                    widget_key=f"api_test_material_{card_id}",
                )
            save_card = st.form_submit_button("Salvar", type="primary", width="stretch", key=f"material_card_{card_id}_save")
        if save_card:
            cards[index] = {
                **card,
                "api_key": str(api_key or "").strip(),
                "enabled": bool(enabled),
                "priority": max(1, int(priority)),
            }
            selected_id = card_id if selected and enabled else active_card_id
            _persist_material_source_cards(settings, cards, selected_id)
            st.success(f"Fonte {definition['label']} guardada.")
            st.rerun()


def render_material_source_api_keys(settings: dict[str, Any], *, embedded: bool = False) -> None:
    with st.expander("Imagem e Video Montagem/MoviePy", expanded=False):
        st.caption("Configure as fontes usadas pela montagem de vídeo com MoviePy/FFmpeg num cartão independente. Pode repetir o mesmo provedor para guardar várias API keys; a fonte seleccionada será usada pela pipeline.")
        migrated, changed = ensure_material_source_cards(settings)
        cards = [dict(item) for item in migrated.get("material_source_cards", [])]
        if changed:
            write_json("settings.json", settings)
        for index in range(len(cards)):
            _render_material_source_card(settings, cards, index, embedded=embedded)

        st.divider()
        st.markdown("**Adicionar fonte de materiais**")
        provider_codes = [item["code"] for item in material_source_catalog()] + ["local"]
        provider_to_add = st.selectbox(
            "Provedor de materiais",
            provider_codes,
            format_func=lambda value: _material_source_card_definition(value)["label"],
            key="material_new_provider_choice",
        )
        add_source_clicked = st.form_submit_button("Configurar Nova Fonte de Materiais", type="primary", width="stretch", key="add_material_source_card") if embedded else st.button("Configurar Nova Fonte de Materiais", type="primary", width="stretch", key="add_material_source_card")
        if add_source_clicked:
            new_card = new_material_card(provider_to_add, card_id=f"material-{provider_to_add}-{uuid.uuid4().hex[:8]}")
            new_card["priority"] = max(
                (int(item.get("priority", index + 1)) for index, item in enumerate(cards)),
                default=0,
            ) + 1
            cards.append(new_card)
            _persist_material_source_cards(settings, cards, str(settings.get("material_active_card_id") or ""))
            st.rerun()


def _api_status_badge(label: str, kind: str = "missing") -> None:
    """Render a compact status chip that remains legible in both native themes."""
    safe_kind = kind if kind in {"missing", "local", "ready", "error"} else "missing"
    marker = "!" if safe_kind == "missing" else "✓" if safe_kind == "ready" else "×" if safe_kind == "error" else "•"
    visible_label = ui_text(label, current_ui_language())
    st.markdown(
        f'<span class="tb-api-status tb-api-status--{safe_kind}"><span class="tb-api-status__dot">{marker}</span>{visible_label}</span>',
        unsafe_allow_html=True,
    )


def _credential_status(value: Any, *, local: bool = False, required: bool = True) -> tuple[str, str]:
    if local:
        return "local", "Local / sem API key"
    if required and not str(value or "").strip():
        return "missing", "Missing key"
    return "ready", "Configured"


def _render_credential_status(value: Any, *, local: bool = False, required: bool = True) -> None:
    kind, label = _credential_status(value, local=local, required=required)
    _api_status_badge(label, kind)


def _persist_api_test_result(settings: dict[str, Any], test_key: str, result: dict[str, Any]) -> dict[str, Any]:
    """Persist only the safe diagnosis fields; never store credentials or endpoint details."""
    safe_result = {
        "status": str(result.get("status") or "error"),
        "message": str(result.get("message") or "A chamada de diagnóstico falhou.")[:240],
        "status_code": result.get("status_code"),
        "checked_at": str(result.get("checked_at") or ""),
    }
    stored = settings.get("api_test_results")
    if not isinstance(stored, dict):
        stored = {}
    stored[str(test_key)] = safe_result
    settings["api_test_results"] = stored
    write_json("settings.json", settings)
    return safe_result


def _render_api_test_feedback(settings: dict[str, Any], test_key: str, result: dict[str, Any] | None = None) -> None:
    """Render the same compact green/red feedback for every non-LLM API card."""
    current = result
    if current is None:
        stored = settings.get("api_test_results")
        current = stored.get(test_key) if isinstance(stored, dict) else None
    if not isinstance(current, dict):
        return
    status = str(current.get("status") or "error")
    language = current_ui_language()
    if status == "success":
        st.success(ui_text("Último teste: API Key OK", language))
        return
    if status == "missing":
        st.error(ui_text("Último teste: falta configuração", language))
        return
    if status == "unsupported":
        st.warning(ui_text("Último teste: requer autorização ou endpoint seguro", language))
        return
    code = current.get("status_code")
    suffix = f" (HTTP {int(code)})" if isinstance(code, int) and code > 0 else ""
    st.error(ui_text("Último teste: chamada falhou", language) + suffix)


def _render_api_test_control(
    settings: dict[str, Any],
    test_key: str,
    callback: Any,
    *,
    widget_key: str,
    persist_callback: Any = None,
) -> None:
    """Render a form-safe diagnostic button and persist its redacted result.

    ``persist_callback`` keeps a card whose fields live in the global form
    consistent: testing it must not appear successful while its values remain
    only in the browser session.
    """
    if st.form_submit_button("Testar chamada API", width="stretch", key=widget_key):
        with st.spinner(ui_text("A testar chamada API…", current_ui_language())):
            try:
                if persist_callback is not None:
                    persist_callback()
                result = callback()
            except Exception:
                result = {"status": "error", "message": "A chamada de diagnóstico falhou."}
        _persist_api_test_result(settings, test_key, result)
        _render_api_test_feedback(settings, test_key, result)
    else:
        _render_api_test_feedback(settings, test_key)


def _llm_card_config_status(card: dict[str, Any]) -> tuple[str, str]:
    definition = provider_definition(card.get("provider"))
    if definition.local:
        return "local", "Local / sem API key"
    if definition.requires_api_key and not str(card.get("api_key") or "").strip():
        return "missing", "Missing key"
    if definition.show_base_url and not str(card.get("base_url") or "").strip():
        return "missing", "Missing configuration"
    if not str(card.get("model") or "").strip():
        return "missing", "Missing configuration"
    return "ready", "Configured"


def _persist_llm_cards(settings: dict[str, Any], cards: list[dict[str, Any]], active_id: str = "") -> dict[str, Any]:
    updated = apply_llm_cards_to_settings(settings, cards, active_id)
    write_json("settings.json", updated)
    return updated


def _render_llm_card(settings: dict[str, Any], cards: list[dict[str, Any]], index: int, *, embedded: bool = False) -> None:
    card = normalize_llm_card(cards[index], index)
    cards[index] = card
    card_id = str(card["id"])
    definition = provider_definition(card.get("provider"))
    with st.container(border=True):
        header_cols = st.columns([3.2, 1.2])
        with header_cols[0]:
            st.subheader(definition.label)
            if definition.description:
                st.caption(definition.description)
        with header_cols[1]:
            status_kind, status_label = _llm_card_config_status(card)
            _api_status_badge(status_label, status_kind)
        card_form = nullcontext() if embedded else st.form(f"llm_card_form_{card_id}")
        with card_form:
            key_col, model_col = st.columns(2)
            with key_col:
                api_key = card.get("api_key", "")
                if definition.requires_api_key:
                    api_key = st.text_input("API key", value=str(api_key or ""), type="password", key=f"llm_card_{card_id}_api_key")
                else:
                    st.caption("Este provider não exige API key.")
                    api_key = ""
            with model_col:
                model_catalog = st.session_state.get(f"llm_model_catalog_{card_id}", [])
                if not isinstance(model_catalog, list):
                    model_catalog = []
                current_model = str(card.get("model") or "").strip()
                discovered_models = [str(item).strip() for item in model_catalog if str(item).strip()]
                default_models = [
                    "gpt-4.1-mini",
                    "gpt-4o-mini",
                    "meta/llama-3.1-8b-instruct",
                    "meta/llama-3.1-70b-instruct",
                    "meta/llama-3.3-70b-instruct",
                    "nvidia/llama-3.1-nemotron-70b-instruct",
                ] if definition.code == "openai" else (["google/paligemma"] if definition.code == "nvidia_nim_paligemma" else [])
                options = ["__select_model__", *list(dict.fromkeys([*discovered_models, *default_models]))]
                # Mantém modelos guardados mesmo quando a descoberta ainda não foi
                # executada ou quando o provider deixou de os devolver temporariamente.
                if current_model and current_model not in options:
                    options.insert(1, current_model)
                selected = st.selectbox(
                    "Modelo",
                    options,
                    index=options.index(current_model) if current_model in options else 0,
                    format_func=lambda value: "Seleccione um modelo" if value == "__select_model__" else value,
                    help="Seleccione um modelo da lista ou actualize o catálogo a partir do endpoint do provider.",
                    key=f"llm_card_{card_id}_model_select",
                )
                model = "" if selected == "__select_model__" else selected
            base_url = str(card.get("base_url") or definition.default_base_url)
            endpoint_col, action_col = st.columns([1.65, 1.05])
            with endpoint_col:
                if definition.show_base_url:
                    base_url = st.text_input(
                        "Base URL",
                        value=base_url,
                        help="Endpoint OpenAI-compatible deste provider; só aparece quando é configurável.",
                        key=f"llm_card_{card_id}_base_url",
                    )
                elif base_url:
                    st.caption(f"Endpoint gerido pelo provider: {base_url}")
            with action_col:
                action_buttons = st.columns(2)
                with action_buttons[0]:
                    refresh_clicked = st.form_submit_button("Consultar modelos", width="stretch", key=f"llm_card_{card_id}_refresh")
                with action_buttons[1]:
                    test_clicked = st.form_submit_button("Testar chamada API", width="stretch", key=f"llm_card_{card_id}_test")

            extra_values: dict[str, str] = {}
            if definition.extra_fields:
                extra_cols = st.columns(len(definition.extra_fields))
                for extra_col, field_name in zip(extra_cols, definition.extra_fields):
                    with extra_col:
                        extra_values[field_name] = st.text_input(
                            field_name.replace("_", " ").title(),
                            value=str(card.get(field_name) or ""),
                            key=f"llm_card_{card_id}_{field_name}",
                        )

            status_cols = st.columns(3)
            with status_cols[0]:
                enabled = st.checkbox("Provider activo", value=bool(card.get("enabled", True)), key=f"llm_card_{card_id}_enabled")
            with status_cols[1]:
                telegram_llm = st.checkbox(
                    "LLM Telegram",
                    value=bool(card.get("telegram_llm", False)),
                    help="Usar este cartão exclusivamente para o roteamento de notificações Telegram. Apenas um cartão pode ficar seleccionado.",
                    key=f"llm_card_{card_id}_telegram",
                )
            with status_cols[2]:
                priority = st.number_input(
                    "Prioridade",
                    min_value=1,
                    max_value=999,
                    value=max(1, int(card.get("priority", index + 1))),
                    step=1,
                    disabled=bool(telegram_llm),
                    help="Não se aplica a cartões LLM Telegram. Nos restantes cartões, 1 é o primeiro; em falha elegível, segue para 2, 3 e assim por diante.",
                    key=f"llm_card_{card_id}_priority",
                )
                if telegram_llm:
                    st.caption("Exclusivo para Notificações de Telegram — prioridade ignorada no pool LLM.")

            save_clicked = st.form_submit_button("Salvar", type="primary", width="stretch", key=f"llm_card_{card_id}_save")
            remove_clicked = False
            if definition.code != "openai":
                remove_clicked = st.form_submit_button("Remover cartão", width="stretch", key=f"llm_card_{card_id}_remove")

        edited = dict(card)
        edited.update({"api_key": str(api_key or "").strip(), "model": str(model or "").strip(), "base_url": str(base_url or "").strip(), "enabled": bool(enabled), "priority": max(1, int(priority)), "telegram_llm": bool(telegram_llm), **extra_values})
        cards[index] = edited
        if test_clicked:
            test_result = test_llm_provider_card(edited)
            edited["test_result"] = stamp_test_result(test_result)
            _persist_llm_cards(settings, cards)
        elif refresh_clicked:
            try:
                from integrations.openai_model_discovery import fetch_openai_compatible_models
                discovered = fetch_openai_compatible_models(edited.get("api_key", ""), edited.get("base_url", ""))
                if definition.code == "nvidia_nim_paligemma" and "google/paligemma" not in discovered:
                    discovered.insert(0, "google/paligemma")
                st.session_state[f"llm_model_catalog_{card_id}"] = discovered
                _persist_llm_cards(settings, cards)
                st.success(f"{len(discovered)} modelo(s) disponíveis neste endpoint.")
            except Exception:
                if definition.code == "nvidia_nim_paligemma" and str(edited.get("api_key") or "").strip():
                    st.session_state[f"llm_model_catalog_{card_id}"] = ["google/paligemma"]
                    st.warning("O catálogo NIM não expôs modelos, mas o modelo Paligemma foi disponibilizado para este provider.")
                else:
                    st.error("Não foi possível consultar os modelos deste endpoint.")
        elif save_clicked:
            _persist_llm_cards(settings, cards)
            st.success("Cartão LLM guardado.")
            st.rerun()
        elif remove_clicked:
            remaining = [item for item in cards if str(item.get("id")) != card_id]
            _persist_llm_cards(settings, remaining)
            st.success("Cartão LLM removido.")
            st.rerun()

        saved_test = edited.get("test_result") or card.get("test_result")
        if isinstance(saved_test, dict) and saved_test.get("message"):
            if saved_test.get("status") == "success":
                st.success("Último teste: API Key OK")
            else:
                st.error(f"Último teste: {saved_test['message']}")


def render_llm_provider_cards(settings: dict[str, Any], *, embedded: bool = False) -> dict[str, Any]:
    """Renderizar cartões LLM e o limitador NIM dentro do mesmo expander."""
    migrated, changed = ensure_llm_provider_cards(settings)
    cards = [dict(item) for item in migrated.get(LLM_CARDS_KEY, [])]
    if changed:
        settings.update(migrated)
        write_json("settings.json", settings)
    with st.expander("LLM — providers e modelos", expanded=False):
        st.caption("Configure cada provider num cartão independente. Pode repetir o mesmo provider para manter várias API keys; a prioridade 1 é tentada primeiro. Cartões marcados como LLM Telegram ficam excluídos do pool textual e são usados apenas pelas notificações Telegram.")
        with st.container(border=True):
            st.markdown("### Limite LLM NVIDIA NIM")
            st.caption("Quando ligado, limita apenas cartões cujo endpoint é integrate.api.nvidia.com a 40 pedidos por janela de 60 segundos, partilhados entre UI, pipeline e automações.")
            rpm_cols = st.columns(3)
            with rpm_cols[0]:
                llm_rpm_limit_enabled = st.checkbox("Activar limitador NVIDIA NIM — 40 RPM", value=bool(settings.get("llm_rpm_limit_enabled", False)), key="settings_llm_rpm_limit_enabled")
            with rpm_cols[1]:
                llm_rpm_limit = st.number_input("Pedidos por janela", min_value=1, max_value=1000, value=int(settings.get("llm_rpm_limit", 40)), step=1, key="settings_llm_rpm_limit")
            with rpm_cols[2]:
                llm_rpm_window_seconds = st.number_input("Janela (segundos)", min_value=1, max_value=3600, value=int(settings.get("llm_rpm_window_seconds", 60)), step=1, key="settings_llm_rpm_window_seconds")
            save_llm_rpm_clicked = (
                st.form_submit_button("Guardar limite LLM NVIDIA NIM", type="primary", width="stretch", key="save_llm_rpm_limit")
                if embedded
                else st.button("Guardar limite LLM NVIDIA NIM", type="primary", width="stretch", key="save_llm_rpm_limit")
            )
            if save_llm_rpm_clicked:
                settings.update({
                    "llm_rpm_limit_enabled": bool(llm_rpm_limit_enabled),
                    "llm_rpm_limit": int(llm_rpm_limit),
                    "llm_rpm_window_seconds": int(llm_rpm_window_seconds),
                })
                write_json("settings.json", settings)
                st.success("Limite LLM NVIDIA NIM guardado.")
        for index in range(len(cards)):
            _render_llm_card(settings, cards, index, embedded=embedded)
        st.divider()
        st.markdown("**Adicionar provider LLM**")
        provider_codes = [item.code for item in LLM_PROVIDER_CATALOG]
        provider_to_add = st.selectbox(
            "Provider LLM",
            provider_codes,
            format_func=lambda value: ui_text(provider_definition(value).label, current_ui_language()),
            key="llm_new_provider_choice",
        )
        add_provider_clicked = (
            st.form_submit_button("Configurar Novo Provedor LLM", type="primary", width="stretch", key="add_llm_provider_card")
            if embedded
            else st.button("Configurar Novo Provedor LLM", type="primary", width="stretch", key="add_llm_provider_card")
        )
        if add_provider_clicked:
            new_card = new_llm_card(provider_to_add, card_id=f"llm-{provider_to_add}-{uuid.uuid4().hex[:8]}")
            new_card["priority"] = max((int(item.get("priority", index + 1)) for index, item in enumerate(cards)), default=0) + 1
            cards.append(new_card)
            _persist_llm_cards(settings, cards)
            st.rerun()
    return {
        "llm_rpm_limit_enabled": bool(llm_rpm_limit_enabled),
        "llm_rpm_limit": int(llm_rpm_limit),
        "llm_rpm_window_seconds": int(llm_rpm_window_seconds),
    }


def _media_card_config_status(card: dict[str, Any]) -> tuple[str, str]:
    definition = media_provider_definition(card.get("provider"))
    if definition.local:
        if not str(card.get("base_url") or "").strip():
            return "missing", "Endpoint local em falta"
        return "local", "Local / sem API key"
    if definition.requires_api_key and not str(card.get("api_key") or "").strip():
        return "missing", "Missing key"
    if definition.code == "cloudflare_workers_ai" and not str(card.get("account_id") or "").strip():
        return "missing", "Missing Account ID"
    if not str(card.get("base_url") or "").strip():
        return "missing", "Missing Base URL"
    if not str(card.get("model") or "").strip() and card.get("supports_image") and card.get("provider") not in {"cloudflare_workers_ai", "canva"}:
        return "missing", "Missing model"
    return "ready", "Configured"


def _persist_media_cards(settings: dict[str, Any], cards: list[dict[str, Any]], image_active_id: str = "", video_active_id: str = "") -> dict[str, Any]:
    updated = apply_media_provider_cards_to_settings(settings, cards, image_active_id, video_active_id)
    write_json("settings.json", updated)
    settings.update(updated)
    return updated


def _fetch_media_models(card: dict[str, Any]) -> list[str]:
    """Consultar modelos do provider, incluindo o catálogo nativo Gemini."""
    provider = str(card.get("provider") or "").strip().lower()
    if provider == "cloudflare_workers_ai":
        account_id = str(card.get("account_id") or "").strip()
        api_key = str(card.get("api_key") or "").strip()
        if not account_id:
            raise ValueError("Introduza o Account ID do Cloudflare Workers AI antes de consultar os modelos.")
        if not api_key:
            raise ValueError("Introduza o Token API Workers AI antes de consultar os modelos.")
        response = requests.get(
            cloudflare_workers_ai_models_url(account_id),
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        entries: Any = payload.get("result") if isinstance(payload, dict) else []
        if isinstance(entries, dict):
            entries = entries.get("models") or entries.get("data") or entries.get("items") or []
        if not isinstance(entries, list):
            entries = []
        models = {
            str(item.get("name") or item.get("id") or item.get("model") or item.get("model_name") or "").strip()
            for item in entries
            if isinstance(item, dict)
        }
        models.discard("")
        if not models:
            raise ValueError("O Cloudflare Workers AI não devolveu modelos disponíveis para este Account ID.")
        return sorted(models, key=str.casefold)
    if provider == "huggingface":
        from integrations.openai_model_discovery import fetch_huggingface_text_to_image_models
        return fetch_huggingface_text_to_image_models(str(card.get("api_key") or ""))
    if provider == "replicate":
        from integrations.openai_model_discovery import fetch_replicate_models
        return fetch_replicate_models(str(card.get("api_key") or ""), str(card.get("base_url") or ""))
    if provider == "kie_ai":
        return list(KIE_MEDIA_MODEL_CATALOG)
    if provider == "fal_ai":
        api_key = str(card.get("api_key") or "").strip()
        if not api_key:
            raise ValueError("Introduza a API key FAL AI antes de consultar os modelos.")
        response = requests.get(
            "https://api.fal.ai/v1/models",
            headers={"Accept": "application/json", "Authorization": f"Key {api_key}"},
            timeout=12,
        )
        response.raise_for_status()
        payload = response.json()
        entries = payload.get("models") if isinstance(payload, dict) else []
        models = {
            str(item.get("endpoint_id") or "").strip()
            for item in entries
            if isinstance(item, dict) and str(item.get("endpoint_id") or "").strip()
        }
        if not models:
            raise ValueError("A FAL AI não devolveu modelos disponíveis.")
        return sorted(models, key=str.casefold)
    if provider == "together_ai":
        from integrations.openai_model_discovery import fetch_together_models
        return fetch_together_models(
            str(card.get("api_key") or ""),
            str(card.get("base_url") or "https://api.together.ai/v1"),
        )
    if provider == "openrouter":
        base_url = str(card.get("base_url") or "https://openrouter.ai/api/v1").rstrip("/")
        headers = {"Accept": "application/json", "Authorization": f"Bearer {str(card.get('api_key') or '').strip()}"}
        discovered: set[str] = set()
        failures: list[str] = []
        for suffix in ("/images/models", "/videos/models"):
            response = requests.get(f"{base_url}{suffix}", headers=headers, timeout=12)
            if response.status_code >= 400:
                failures.append(f"HTTP {response.status_code}")
                continue
            payload = response.json()
            entries = payload.get("data") if isinstance(payload, dict) else []
            if isinstance(entries, list):
                discovered.update(str(item.get("id") or "").strip() for item in entries if isinstance(item, dict) and str(item.get("id") or "").strip())
        if not discovered:
            detail = f" ({', '.join(failures)})" if failures else ""
            raise ValueError(f"O OpenRouter não devolveu modelos de imagem/vídeo{detail}.")
        return sorted(discovered, key=str.casefold)
    if provider == "nano_banana":
        base_url = str(card.get("base_url") or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        response = requests.get(
            f"{base_url}/models",
            params={"key": str(card.get("api_key") or "").strip()},
            headers={"Accept": "application/json"},
            timeout=12,
        )
        response.raise_for_status()
        payload = response.json()
        models = payload.get("models") if isinstance(payload, dict) else []
        return sorted({str(item.get("name", "")).removeprefix("models/") for item in models if isinstance(item, dict) and item.get("name")}, key=str.casefold)
    from integrations.openai_model_discovery import fetch_openai_compatible_models
    return fetch_openai_compatible_models(str(card.get("api_key") or ""), str(card.get("base_url") or ""))


def _render_media_provider_card(settings: dict[str, Any], cards: list[dict[str, Any]], index: int, *, embedded: bool = False) -> None:
    card = normalize_media_card(cards[index], index)
    cards[index] = card
    card_id = str(card["id"])
    definition = media_provider_definition(card.get("provider"))
    if card.get("provider") == "canva":
        callback_code = str(st.query_params.get("code") or "").strip()
        callback_state = str(st.query_params.get("state") or "").strip()
        oauth_pending = card.get("oauth_pending") if isinstance(card.get("oauth_pending"), dict) else {}
        pending_state = str(st.session_state.get(f"canva_state_{card_id}") or oauth_pending.get("state") or "")
        pending_verifier = str(st.session_state.get(f"canva_verifier_{card_id}") or oauth_pending.get("code_verifier") or "")
        if callback_code:
            if not pending_state or callback_state != pending_state:
                st.error("Canva OAuth rejeitado: state inválido. Inicie a autorização novamente.")
            else:
                try:
                    token = exchange_code(str(card.get("client_id") or ""), str(card.get("client_secret") or ""), callback_code, str(card.get("redirect_uri") or ""), pending_verifier)
                    card["oauth_token"] = token
                    card.pop("oauth_pending", None)
                    cards[index] = card
                    _persist_media_cards(settings, cards, str(settings.get(MEDIA_IMAGE_ACTIVE_CARD_KEY) or ""), str(settings.get(MEDIA_VIDEO_ACTIVE_CARD_KEY) or ""))
                    st.session_state.pop(f"canva_state_{card_id}", None)
                    st.session_state.pop(f"canva_verifier_{card_id}", None)
                    st.query_params.clear()
                    st.success("Canva autorizada com sucesso.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Não foi possível autorizar a Canva: {str(exc)[:240]}")
    with st.container(border=True):
        header_cols = st.columns([3.2, 1.2])
        with header_cols[0]:
            st.subheader(definition.label)
            if definition.description:
                st.caption(definition.description)
        with header_cols[1]:
            status_kind, status_label = _media_card_config_status(card)
            _api_status_badge(status_label, status_kind)
        card_form = nullcontext() if embedded else st.form(f"media_card_form_{card_id}")
        with card_form:
            key_col, model_col = st.columns(2)
            refresh_clicked = False
            authorize_clicked = False
            with key_col:
                api_key = str(card.get("api_key") or "")
                if definition.requires_api_key:
                    api_key_label = "Token API Workers AI" if definition.code == "cloudflare_workers_ai" else "API key"
                    api_key = st.text_input(api_key_label, value=api_key, type="password", key=f"media_card_{card_id}_api_key")
                else:
                    st.caption("Este provider não exige API key.")
                    api_key = ""
            with model_col:
                model_catalog = st.session_state.get(f"media_model_catalog_{card_id}", [])
                if not isinstance(model_catalog, list):
                    model_catalog = []
                current_model = str(card.get("model") or "").strip()
                discovered_models = [str(item).strip() for item in model_catalog if str(item).strip()]
                options = ["__select_model__", *list(dict.fromkeys(discovered_models))]
                if current_model and current_model not in options:
                    options.insert(1, current_model)
                selected_model = st.selectbox(
                    "Modelo",
                    options,
                    index=options.index(current_model) if current_model in options else 0,
                    format_func=lambda value: "Seleccione um modelo" if value == "__select_model__" else value,
                    help="Consulte o catálogo do provider e seleccione um modelo disponível.",
                    key=f"media_card_{card_id}_model_select",
                )
                model = "" if selected_model == "__select_model__" else selected_model
                if definition.code == "canva":
                    refresh_clicked = st.form_submit_button("Consultar Modelos", width="stretch", key=f"media_card_{card_id}_refresh")
            extra_values: dict[str, str] = {}
            if definition.code == "cloudflare_workers_ai":
                account_id = st.text_input("Account ID", value=str(card.get("account_id") or ""), key=f"media_card_{card_id}_account_id").strip()
                extra_values["account_id"] = account_id
                base_url = definition.default_base_url
                display_base_url = cloudflare_workers_ai_run_base_url(account_id)
                st.text_input("Base URL", value=display_base_url, placeholder="Será preenchida após indicar o Account ID", disabled=True, key=f"media_card_{card_id}_base_url_display")
                st.caption("A Base URL é interna e é montada automaticamente a partir do Account ID. Não é editável.")
            elif definition.code == "canva":
                base_url = definition.default_base_url
                st.text_input("Base URL", value=base_url, disabled=True, key=f"media_card_{card_id}_base_url_display")
                st.caption("Canva MCP directo: https://mcp.canva.com/mcp — a autenticação MCP é aberta pelo Thunderbolt na primeira utilização.")
            else:
                base_url = st.text_input(
                    "Base URL",
                    value=str(card.get("base_url") or definition.default_base_url),
                    help="Usada nas chamadas de imagem. Para Together AI, o endpoint de vídeo v2 é derivado automaticamente desta Base URL.",
                    key=f"media_card_{card_id}_base_url",
                )
            if definition.extra_fields and definition.code not in {"canva", "cloudflare_workers_ai"}:
                extra_cols = st.columns(len(definition.extra_fields))
                for extra_col, field_name in zip(extra_cols, definition.extra_fields):
                    with extra_col:
                        field_label = "Account ID" if field_name == "account_id" else field_name.replace("_", " ").title()
                        extra_values[field_name] = st.text_input(field_label, value=str(card.get(field_name) or ""), type="password" if field_name == "client_secret" else "default", key=f"media_card_{card_id}_{field_name}")
            if definition.code == "canva":
                supports_image = True
                supports_video = False
                st.caption("Canva Connect é usado exclusivamente para thumbnails no Pool de Imagem. Não é provider de vídeo.")
                credential_cols = st.columns(3)
                with credential_cols[0]:
                    client_id = st.text_input("Client Id", value=str(card.get("client_id") or ""), key=f"media_card_{card_id}_client_id")
                with credential_cols[1]:
                    client_secret = st.text_input("Client Secret", value=str(card.get("client_secret") or ""), type="password", key=f"media_card_{card_id}_client_secret")
                with credential_cols[2]:
                    redirect_uri = st.text_input("Redirect Uri", value=str(card.get("redirect_uri") or ""), key=f"media_card_{card_id}_redirect_uri")
                extra_values.update({"client_id": client_id.strip(), "client_secret": client_secret.strip(), "redirect_uri": redirect_uri.strip()})
                oauth_token = card.get("oauth_token") if isinstance(card.get("oauth_token"), dict) else {}
                has_credentials = bool(client_id.strip() and client_secret.strip() and redirect_uri.strip())
                is_authorized = bool(oauth_token.get("access_token"))
                oauth_state = "Autorizado" if is_authorized else ("Não Autorizado" if has_credentials else "⚠️ Incompleto")
                st.markdown(f"**Estado OAuth:** `{oauth_state}`")
                if not has_credentials:
                    st.info("Preencha Client Id, Client Secret e Redirect Uri para iniciar a autorização.")
                else:
                    authorize_clicked = st.form_submit_button("Iniciar autorização", width="stretch", key=f"media_card_{card_id}_authorize") if embedded else st.button("Iniciar autorização", key=f"media_card_{card_id}_authorize")
                    if authorize_clicked:
                        verifier, challenge = create_pkce_pair()
                        state = create_state()
                        st.session_state[f"canva_verifier_{card_id}"] = verifier
                        st.session_state[f"canva_state_{card_id}"] = state
                        st.session_state[f"canva_authorization_url_{card_id}"] = authorization_url(client_id, redirect_uri, state=state, code_challenge=challenge)
                        extra_values["oauth_pending"] = {"state": state, "code_verifier": verifier}
                    authorization_link = str(st.session_state.get(f"canva_authorization_url_{card_id}") or "")
                    if authorization_link:
                        st.markdown(f"[Abrir autorização Canva]({authorization_link})")
                with st.expander("Opções de exportação e dimensões", expanded=False):
                    export_quality = st.selectbox("Export Quality", ["High", "Medium", "Low"], index=["high", "medium", "low"].index(str(card.get("export_quality") or "medium").lower()), key=f"media_card_{card_id}_export_quality")
                    export_format = st.selectbox("Export Format", ["PNG", "JPG", "PDF"], index=["png", "jpg", "pdf"].index(str(card.get("export_format") or "png").lower()), key=f"media_card_{card_id}_export_format")
                    dimensions = st.selectbox("Thumbnail Width / Height", ["1280 x 720", "1792 x 1024"], index=1 if str(card.get("thumbnail_width")) == "1792" or str(card.get("thumbnail_height")) == "1024" else 0, key=f"media_card_{card_id}_dimensions")
                    selected_width, selected_height = dimensions.replace(" ", "").split("x", 1)
                    extra_values.update({"export_quality": export_quality.lower(), "export_format": export_format.lower(), "thumbnail_width": selected_width, "thumbnail_height": selected_height})
            status_cols = st.columns(4)
            with status_cols[0]:
                enabled = st.checkbox("Provider activo", value=bool(card.get("enabled", True)), key=f"media_card_{card_id}_enabled")
            with status_cols[1]:
                supports_image = st.checkbox("Pool Imagem", value=bool(card.get("supports_image", definition.supports_image)), key=f"media_card_{card_id}_image")
            with status_cols[2]:
                supports_video = False if definition.code == "canva" else st.checkbox("Pool Vídeo", value=bool(card.get("supports_video", definition.supports_video)), key=f"media_card_{card_id}_video")
            with status_cols[3]:
                priority = st.number_input("Prioridade", min_value=0, max_value=999, value=int(card.get("priority", index)), step=1, key=f"media_card_{card_id}_priority")
            action_cols = st.columns(4)
            with action_cols[0]:
                if definition.code != "canva":
                    refresh_clicked = st.form_submit_button("Consultar Modelos", width="stretch", key=f"media_card_{card_id}_refresh")
            with action_cols[1]:
                test_clicked = st.form_submit_button("Testar Chamada API", width="stretch", key=f"media_card_{card_id}_test")
            with action_cols[2]:
                save_clicked = st.form_submit_button("Salvar", type="primary", width="stretch", key=f"media_card_{card_id}_save")
            with action_cols[3]:
                remove_clicked = st.form_submit_button("Remover provider", width="stretch", key=f"media_card_{card_id}_remove")
        edited = dict(card)
        edited.update({"api_key": str(api_key or "").strip(), "model": str(model or "").strip(), "base_url": str(base_url or "").strip(), "enabled": bool(enabled), "supports_image": bool(supports_image), "supports_video": bool(supports_video), "priority": int(priority), **extra_values})
        cards[index] = edited
        if authorize_clicked:
            # Guardar as credenciais antes de o browser sair para a Canva. No
            # callback, o código OAuth é trocado usando este card persistido.
            _persist_media_cards(settings, cards, str(settings.get(MEDIA_IMAGE_ACTIVE_CARD_KEY) or ""), str(settings.get(MEDIA_VIDEO_ACTIVE_CARD_KEY) or ""))
            st.success("Credenciais Canva guardadas. Abra o link para autorizar.")
        elif refresh_clicked:
            try:
                discovered = _fetch_media_models(edited)
                st.session_state[f"media_model_catalog_{card_id}"] = discovered
                st.success(f"{len(discovered)} modelo(s) disponíveis neste endpoint.")
            except Exception:
                st.error("Não foi possível consultar os modelos deste provider. Confirme a API key e a Base URL.")
        elif test_clicked:
            result = test_media_provider_card(edited)
            edited["test_result"] = stamp_test_result(result)
            _persist_media_cards(settings, cards, str(settings.get(MEDIA_IMAGE_ACTIVE_CARD_KEY) or ""), str(settings.get(MEDIA_VIDEO_ACTIVE_CARD_KEY) or ""))
        elif save_clicked:
            _persist_media_cards(settings, cards, str(settings.get(MEDIA_IMAGE_ACTIVE_CARD_KEY) or ""), str(settings.get(MEDIA_VIDEO_ACTIVE_CARD_KEY) or ""))
            st.success("Cartão de imagem/vídeo guardado.")
            st.rerun()
        elif remove_clicked:
            remaining = [item for item in cards if str(item.get("id")) != card_id]
            _persist_media_cards(settings, remaining, str(settings.get(MEDIA_IMAGE_ACTIVE_CARD_KEY) or ""), str(settings.get(MEDIA_VIDEO_ACTIVE_CARD_KEY) or ""))
            st.success("Provider de imagem/vídeo removido.")
            st.rerun()
        saved_test = edited.get("test_result") or card.get("test_result")
        if isinstance(saved_test, dict) and saved_test.get("message"):
            if saved_test.get("status") == "success":
                st.success("Último teste: API Key OK")
            else:
                st.error(f"Último teste: {saved_test['message']}")


def render_media_provider_cards(settings: dict[str, Any], *, embedded: bool = False) -> None:
    migrated, changed = ensure_media_provider_cards(settings)
    cards = [dict(item) for item in migrated.get(MEDIA_CARDS_KEY, [])]
    if changed:
        settings.update(migrated)
        write_json("settings.json", settings)
    with st.expander("Imagem e Video IA", expanded=False):
        full_ia_labels = ", ".join(media_provider_definition(code).label for code in FULL_IA_VIDEO_PROVIDER_CODES)
        st.caption(f"Configure providers de imagem e vídeo em cartões independentes. O router usa apenas o pool correspondente e faz failover entre providers activos. Pool Full IA: {full_ia_labels}.")
        for index in range(len(cards)):
            _render_media_provider_card(settings, cards, index, embedded=embedded)
        st.divider()
        st.markdown("**Adicionar provider de imagem/vídeo**")
        provider_codes = [item["code"] for item in media_provider_catalog()]
        provider_to_add = st.selectbox("Provider de media", provider_codes, format_func=lambda value: media_provider_definition(value).label, key="media_new_provider_choice")
        add_clicked = st.form_submit_button("Adicionar provider de imagem/vídeo", width="stretch", key="add_media_provider_card") if embedded else st.button("Adicionar provider de imagem/vídeo", width="stretch", key="add_media_provider_card")
        if add_clicked:
            cards.append(new_media_card(provider_to_add, card_id=f"media-{provider_to_add}-{uuid.uuid4().hex[:8]}"))
            _persist_media_cards(settings, cards)
            st.success("Novo provider de imagem/vídeo adicionado.")
            st.rerun()


TEST_UPLOAD_VIDEOS = (
    {
        "id": "horizontal",
        "name": "Vídeo de teste horizontal",
        "filename": "test-horizontal.mp4",
        "path": ROOT / "seed" / "test_upload_videos" / "test-horizontal.mp4",
        "duration": "40,1 s",
        "description": "Vídeo horizontal para YouTube e Bilibili (1920×1080).",
        "upload_metadata": {
            "title": "Vídeo de teste horizontal",
            "description": "A simple video for only test Upload configuration",
            "tags": ["#brandnew", "#video", "#test"],
        },
    },
    {
        "id": "vertical",
        "name": "Vídeo de teste vertical",
        "filename": "test-vertical.mp4",
        "path": ROOT / "seed" / "test_upload_videos" / "test-vertical.mp4",
        "duration": "8,8 s",
        "description": "Vídeo vertical para YouTube Shorts, TikTok, Instagram e Facebook Pages (720×1080).",
        "upload_metadata": {
            "title": "Vídeo de teste vertical",
            "description": "A short video for only test Upload configuration",
            "tags": ["#brandnew", "#video", "#test"],
        },
    },
)


def _test_upload_destinations(settings: dict[str, Any], operation: str) -> list[dict[str, Any]]:
    channels = [item for item in read_json("channels.json", []) if isinstance(item, dict) and item.get("active", True)]
    if operation == "Contas Bilibili":
        return [dict(item, _source="bilibili") for item in settings.get("bilibili_api_cards", []) if isinstance(item, dict)]
    platform_by_operation = {
        "Canais YouTube": "youtube",
        "Canais Tiktok": "tiktok",
        "Contas Instagram": "instagram",
        "Facebook Pages": "facebook",
    }
    accepted_platform = platform_by_operation.get(operation)
    if not accepted_platform:
        return []
    return [item for item in channels if classify_channel_platform(item) == accepted_platform]


def _test_video_upload_metadata(video: dict[str, Any]) -> dict[str, Any]:
    """Validate metadata seeded exclusively for the Test Upload Videos flow."""
    video_name = str(video.get("name") or video.get("id") or "vídeo de teste")
    metadata = video.get("upload_metadata")
    if not isinstance(metadata, dict):
        raise ValueError(f"Metadados obrigatórios ausentes para o vídeo de teste {video_name}: upload_metadata.")
    missing = [field for field in ("title", "description", "tags") if not metadata.get(field)]
    if missing:
        raise ValueError(f"Metadados obrigatórios ausentes para o vídeo de teste {video_name}: {', '.join(missing)}.")
    tags = metadata.get("tags")
    if not isinstance(tags, list) or not all(isinstance(tag, str) and tag.strip() for tag in tags):
        raise ValueError(f"Metadados inválidos para o vídeo de teste {video_name}: tags deve ser uma lista de strings não vazias.")
    return {
        "title": str(metadata["title"]).strip(),
        "description": str(metadata["description"]).strip(),
        "tags": [tag.strip() for tag in tags],
    }


def _test_upload_log_markdown(
    *,
    upload_mode: str,
    operation: str,
    selected_video: dict[str, Any],
    destination: dict[str, Any],
    result: Any = None,
    diagnostics: Any = None,
    error: Exception | None = None,
) -> tuple[str, str]:
    """Build the downloadable Markdown report for the latest upload test."""
    timestamp = datetime.now().strftime("%Y%m%de%H%M%S")
    filename = f"Log_Upload_Composio-{timestamp}.md"
    result_data = getattr(result, "data", {}) if result is not None else {}
    if not isinstance(result_data, dict):
        result_data = {"value": str(result_data)}
    successful = getattr(result, "ok", None) if result is not None else False
    message = getattr(result, "message", "") if result is not None else ""
    lines = [
        "# Log Upload Composio",
        "",
        f"- Data e hora: {datetime.now().isoformat(timespec='seconds')}",
        f"- Modo: {upload_mode}",
        f"- Operação: {operation}",
        f"- Vídeo: {selected_video.get('name') or selected_video.get('id') or ''}",
        f"- Ficheiro: {selected_video.get('filename') or ''}",
        f"- Destino: {destination.get('name') or destination.get('label') or destination.get('id') or 'Nenhum destino configurado'}",
        f"- Resultado: {'sucesso' if successful else 'falha'}",
        f"- Mensagem: {message or 'N/A'}",
    ]
    if error is not None:
        lines.extend([f"- Excepção: `{type(error).__name__}: {error}`"])
    if diagnostics:
        lines.extend(["", "## Diagnóstico", "", "```json", json.dumps(diagnostics, ensure_ascii=False, indent=2, default=str), "```"])
    if result_data:
        lines.extend(["", "## Dados do resultado", "", "```json", json.dumps(result_data, ensure_ascii=False, indent=2, default=str), "```"])
    return filename, "\n".join(lines) + "\n"


def _render_test_upload_videos(settings: dict[str, Any]) -> None:
    st.subheader("Test Upload Videos")
    st.caption("Use esta área para testar as ferramentas de upload com ficheiros locais controlados, sem iniciar qualquer envio até clicar no botão.")
    upload_mode = st.selectbox("Modo de Upload", ["Composio", "API Youtube", "YouTube Frontend API", "Postiz", "Upload-Post"], key="test_upload_mode")
    operation = st.selectbox("Canais/Contas", ["Canais YouTube", "Canais Tiktok", "Contas Instagram", "Contas Bilibili", "Facebook Pages"], key="test_upload_operation")
    destinations = _test_upload_destinations(settings, operation)
    destination_labels = [str(item.get("name") or item.get("label") or item.get("title") or item.get("id") or "Destino sem nome") for item in destinations]
    selected_destination = st.selectbox("Canal/conta alvo", ["Nenhum destino configurado"] + destination_labels, key="test_upload_destination")
    destination = destinations[destination_labels.index(selected_destination)] if selected_destination in destination_labels else {}

    st.markdown("#### Vídeos modelo")
    selector_column, status_column = st.columns([1, 1], gap="small")
    with selector_column:
        selected_video_id = st.radio("Vídeo de teste", [item["id"] for item in TEST_UPLOAD_VIDEOS], format_func=lambda value: next(item["name"] for item in TEST_UPLOAD_VIDEOS if item["id"] == value), key="test_upload_video", horizontal=True)
    with status_column:
        with st.container(height=188, border=True):
            st.caption("Resultado do teste de upload")
            status_panel = st.empty()
    selected_video = next(item for item in TEST_UPLOAD_VIDEOS if item["id"] == selected_video_id)
    log_state_key = "test_upload_composio_log"
    action_column, log_column = st.columns([3, 1], gap="small")
    with action_column:
        execute_upload = st.button("Testar Upload", type="primary", width="stretch", key="test_upload_execute")
    with log_column:
        saved_log = st.session_state.get(log_state_key)
        st.download_button(
            "Download Log",
            data=saved_log.get("data", "") if isinstance(saved_log, dict) else "",
            file_name=saved_log.get("filename", "Log_Upload_Composio.md") if isinstance(saved_log, dict) else "Log_Upload_Composio.md",
            mime="text/markdown",
            key="test_upload_download_log",
            width="stretch",
            disabled=not isinstance(saved_log, dict) or not saved_log.get("data"),
        )
    if execute_upload:
        video_path = Path(selected_video["path"]).resolve()
        if not destination:
            status_panel.warning("Não existe um canal/conta configurado para a operação seleccionada. Configure um destino ou escolha outra operação.")
            if upload_mode == "Composio":
                filename, markdown = _test_upload_log_markdown(upload_mode=upload_mode, operation=operation, selected_video=selected_video, destination=destination, error=ValueError("Nenhum destino configurado"))
                st.session_state[log_state_key] = {"filename": filename, "data": markdown}
        elif not video_path.is_file():
            status_panel.error(f"Vídeo de teste não encontrado: {video_path}")
            if upload_mode == "Composio":
                filename, markdown = _test_upload_log_markdown(upload_mode=upload_mode, operation=operation, selected_video=selected_video, destination=destination, error=FileNotFoundError(str(video_path)))
                st.session_state[log_state_key] = {"filename": filename, "data": markdown}
        else:
            channel = destination if operation == "Canais YouTube" else {}
            account = resolve_youtube_account(settings, channel) if channel else None
            try:
                upload_metadata = _test_video_upload_metadata(selected_video)
                title = upload_metadata["title"]
                description = upload_metadata["description"]
                tags = upload_metadata["tags"]
                if upload_mode == "API Youtube":
                    result = YouTubeAdapter(settings).upload_video(str(video_path), title=title, description=description, tags=tags, category_id="22", language="pt-BR", privacy_status="unlisted", account=account)
                elif upload_mode == "YouTube Frontend API":
                    result = YouTubeDirectUploader(settings, channel, account=account, storage_root=STORAGE).upload(str(video_path), title=title, description=description, visibility="unlisted")
                elif upload_mode == "Postiz":
                    result = PostizAdapter(settings).publish_video(str(video_path), integration_id=str(destination.get("id") or settings.get("postiz_integration_id") or ""), title=title, description=description, visibility="unlisted", tags=tags)
                elif upload_mode == "Upload-Post":
                    platform = {"Canais YouTube": "youtube", "Canais Tiktok": "tiktok", "Contas Instagram": "instagram", "Facebook Pages": "facebook", "Contas Bilibili": "bilibili"}.get(operation, "")
                    result = UploadPostAdapter(settings).upload_video(str(video_path), title=title, description="Vídeo de teste Thunderbolt", user=str(destination.get("username") or destination.get("name") or settings.get("upload_post_username") or ""), platforms=[platform] if platform else None)
                else:
                    result = _composio_upload(
                        settings,
                        channel=destination,
                        video_path=str(video_path),
                        category_id="22",
                        language="pt-BR",
                        privacy_status="unlisted",
                        title=title,
                        description=description,
                        tags=tags,
                    )
                if result.ok:
                    status_panel.success(result.message)
                else:
                    status_panel.error(result.message)
                diagnostics = result.data.get("diagnostics") if isinstance(result.data, dict) else None
                if diagnostics:
                    with st.expander("Logs de diagnóstico Composio", expanded=True):
                        st.json(diagnostics)
                if upload_mode == "Composio":
                    filename, markdown = _test_upload_log_markdown(upload_mode=upload_mode, operation=operation, selected_video=selected_video, destination=destination, result=result, diagnostics=diagnostics)
                    st.session_state[log_state_key] = {"filename": filename, "data": markdown}
            except Exception as exc:
                status_panel.error(f"O teste de upload falhou: {type(exc).__name__}: {exc}")
                if upload_mode == "Composio":
                    filename, markdown = _test_upload_log_markdown(upload_mode=upload_mode, operation=operation, selected_video=selected_video, destination=destination, error=exc)
                    st.session_state[log_state_key] = {"filename": filename, "data": markdown}
        if upload_mode == "Composio" and st.session_state.get(log_state_key):
            st.rerun()
    video_columns = st.columns(2, gap="small")
    for index, video in enumerate(TEST_UPLOAD_VIDEOS):
        with video_columns[index]:
            with st.container(border=True):
                st.write(f"**{video['name']}** · duração: {video['duration']}")
                st.caption(video["description"])
                video_path = Path(video["path"]).resolve()
                if video_path.is_file():
                    media_slot = st.columns([1, 2, 1])[1] if video["id"] == "vertical" else st.container()
                    with media_slot:
                        _render_local_video_player(video_path)
                        st.download_button("Download vídeo modelo", video_path.read_bytes(), file_name=video["filename"], mime="video/mp4", key=f"download_test_upload_{video['id']}", width="stretch")
                else:
                    st.error(f"Asset de teste não encontrado: {video_path}")

def render_settings():
    st.title("Configuração API")
    st.caption("Configuração das APIs, providers, serviços e ferramentas técnicas usados pelo Thunderbolt. As credenciais ficam no storage local e não são enviadas para o GitHub.")
    st.caption(f"Ficheiro local de todas as API keys: `{STORAGE / 'state' / 'settings.json'}`")
    settings = read_json("settings.json", {})

    def text_setting(label: str, key: str, *, secret: bool = False, help_text: str | None = None) -> str:
        return st.text_input(
            label,
            settings.get(key, ""),
            type="password" if secret else "default",
            help=help_text,
            key=f"settings_{key}",
        )

    api_keys_tab, upload_api_keys_tab, subtitles_tab, ffmpeg_tab, ai_influencers_tab, test_upload_videos_tab, voice_test_tab = render_localized_tabs(["API Keys", "API Keys Upload", "Legendas", "FFmpeg", "AI Influencers", "Test Upload Videos", "Teste de Voz"])

    with api_keys_tab:
        with st.container(border=True):
            st.subheader("API Keys")
            moneyprinter_path = str(settings.get("moneyprinter_path") or "").strip()
            st.caption(f"Pasta do motor de vídeo: `{moneyprinter_path or 'não configurada'}`")
            with st.expander("Optimização de tokens — jusTokenMax", expanded=False):
                st.caption("Compressão local e reversível de contextos volumosos antes das chamadas LLM. Os originais permanecem guardados no storage local.")
                optimizer_enabled = st.checkbox("Activar optimizador", value=bool(settings.get("token_optimizer_enabled", True)), key="token_optimizer_enabled_ui")
                optimizer_cols = st.columns(4)
                optimizer_values = {}
                for index, (key, label) in enumerate((("json", "JSON/API"), ("log", "Logs"), ("pdf", "PDF"), ("csv", "CSV"), ("diff", "Diffs"), ("code", "Código"))):
                    with optimizer_cols[index % 4]:
                        optimizer_values[f"token_optimizer_{key}_enabled"] = st.checkbox(label, value=bool(settings.get(f"token_optimizer_{key}_enabled", True)), key=f"token_optimizer_{key}_ui")
                if st.button("Guardar optimizador", key="save_token_optimizer", width="stretch"):
                    settings.update({"token_optimizer_enabled": optimizer_enabled, **optimizer_values})
                    write_json("settings.json", settings)
                    st.success("Configuração do jusTokenMax guardada.")
                status = check_installation()
                st.caption(f"Estado: {'instalado' if status.get('installed') else 'não instalado'}{(' · versão ' + str(status.get('version'))) if status.get('version') else ''}")
                stats = get_token_optimizer_stats()
                st.caption(f"Contextos: {stats['calls']} · redução acumulada: {stats['reduction_percent']}% · fallbacks: {stats['fallbacks']}")
                if st.button("Limpar cache derivado", key="clear_token_optimizer_cache"):
                    st.info(f"{clear_derived_cache()} artefacto(s) derivado(s) removido(s). Os originais da aplicação não foram apagados.")
            with st.form("settings_form"):
                @st.fragment
                def render_niche_finder_fragment():
                    niche_kaggle_tab, niche_apify_tab, niche_kalodata_tab = st.tabs(["Kaggle", "Apify", "Kalodata"])
                    with niche_kaggle_tab:
                        st.caption("O dataset permanece no Kaggle. O Thunderbolt usa estas credenciais apenas para publicar/executar a kernel e obter os resultados pequenos da análise.")
                        kaggle_cols = st.columns(3)
                        with kaggle_cols[0]:
                            kaggle_username = text_setting("Kaggle Username", "kaggle_username", help_text="Nome de utilizador da sua conta Kaggle, sem @ e sem URL.")
                        with kaggle_cols[1]:
                            kaggle_api_key = text_setting("Kaggle API Key", "kaggle_api_key", secret=True, help_text="Chave criada em Kaggle > Settings > API. Nunca é incluída no notebook ou no GitHub.")
                        with kaggle_cols[2]:
                            kaggle_kernel_slug = text_setting("Slug da kernel", "kaggle_kernel_slug", help_text="Identificador da kernel remota, por exemplo thunderbolt-niche-finder.")
                        _render_credential_status(kaggle_api_key)
                        kaggle_action_cols = st.columns(2)
                        with kaggle_action_cols[0]:
                            _render_api_test_control(
                                settings,
                                "kaggle",
                                lambda: test_kaggle_credentials(kaggle_username, kaggle_api_key),
                                widget_key="api_test_kaggle",
                            )
                        with kaggle_action_cols[1]:
                            if st.form_submit_button("Salvar", type="primary", width="stretch", key="save_niche_kaggle"):
                                settings.update({
                                    "kaggle_username": kaggle_username.strip(),
                                    "kaggle_api_key": kaggle_api_key.strip(),
                                    "kaggle_kernel_slug": kaggle_kernel_slug.strip(),
                                })
                                write_json("settings.json", settings)
                                st.success("Configuração Kaggle guardada.")

                    with niche_apify_tab:
                        st.caption("O token fica guardado apenas no storage local. A aba Niche Finder Apify só usa este serviço depois de clicar no botão de pesquisa.")
                        apify_cols = st.columns(4)
                        with apify_cols[0]:
                            apify_api_token = text_setting("Apify API Token", "apify_api_token", secret=True, help_text="Token pessoal da Apify. Não é incluído no workflow, logs ou GitHub.")
                        with apify_cols[1]:
                            apify_actor_id = text_setting("Apify Actor ID", "apify_actor_id", help_text="Por padrão: streamers~youtube-scraper.")
                        with apify_cols[2]:
                            apify_poll_interval = st.number_input("Intervalo de consulta (s)", min_value=1, max_value=120, value=int(settings.get("apify_poll_interval_seconds", 10)), step=1)
                        with apify_cols[3]:
                            apify_run_timeout = st.number_input("Limite da execução (s)", min_value=30, max_value=7200, value=int(settings.get("apify_run_timeout_seconds", 900)), step=30)
                        _render_credential_status(apify_api_token)
                        apify_action_cols = st.columns(2)
                        with apify_action_cols[0]:
                            _render_api_test_control(
                                settings,
                                "apify",
                                lambda: test_apify_credentials(apify_api_token),
                                widget_key="api_test_apify",
                            )
                        with apify_action_cols[1]:
                            if st.form_submit_button("Salvar", type="primary", width="stretch", key="save_niche_apify"):
                                settings.update({
                                    "apify_api_token": apify_api_token.strip(),
                                    "apify_actor_id": apify_actor_id.strip(),
                                    "apify_poll_interval_seconds": int(apify_poll_interval),
                                    "apify_run_timeout_seconds": int(apify_run_timeout),
                                })
                                write_json("settings.json", settings)
                                st.success("Configuração Apify guardada.")

                    with niche_kalodata_tab:
                        kalodata_saved_base_url = str(settings.get("kalodata_base_url") or "").strip()
                        if kalodata_saved_base_url in {"", "https://api.kalodata.com/v1"}:
                            kalodata_saved_base_url = "https://www.kalodata.com/openapi/v1"
                        kalodata_api_key = text_setting(
                            "Kalodata API Key",
                            "kalodata_api_key",
                            secret=True,
                            help_text="Chave da API Kalodata. Não é incluída em logs.",
                        )
                        kalodata_base_url = st.text_input(
                            "Kalodata Base URL",
                            value=kalodata_saved_base_url,
                            help="Base URL oficial do Open Center; o teste usa o ranking de vídeos com baixo volume.",
                            key="settings_kalodata_base_url",
                        ).strip() or "https://www.kalodata.com/openapi/v1"
                        _render_credential_status(kalodata_api_key)
                        kalodata_action_cols = st.columns(2)
                        with kalodata_action_cols[0]:
                            _render_api_test_control(
                                settings,
                                "kalodata",
                                lambda: test_kalodata_credentials(kalodata_api_key, kalodata_base_url),
                                widget_key="api_test_kalodata",
                            )
                        with kalodata_action_cols[1]:
                            if st.form_submit_button("Salvar", type="primary", width="stretch", key="save_niche_kalodata"):
                                settings.update({
                                    "kalodata_api_key": kalodata_api_key.strip(),
                                    "kalodata_base_url": kalodata_base_url.strip(),
                                })
                                write_json("settings.json", settings)
                                st.success("Configuração Kalodata guardada.")
                with st.expander("Niche Finder", expanded=False):
                    render_niche_finder_fragment()

                llm_rpm_settings = render_llm_provider_cards(settings, embedded=True)
                llm_rpm_limit_enabled = bool(llm_rpm_settings["llm_rpm_limit_enabled"])
                llm_rpm_limit = int(llm_rpm_settings["llm_rpm_limit"])
                llm_rpm_window_seconds = int(llm_rpm_settings["llm_rpm_window_seconds"])

                render_material_source_api_keys(settings, embedded=True)

                render_media_provider_cards(settings, embedded=True)

                with st.expander("Remotion", expanded=False):
                    st.caption("Integração do Remotion como provedor de vídeo será implementada na Etapa 2.")
                    st.info("Esta seção está reservada para a configuração do Remotion (renderização local com React/@remotion/renderer).")

                with st.expander("Google Imagem API", expanded=False):
                    st.caption("Configure múltiplas API Keys Google Custom Search com fallback por prioridade e quota diária.")
                    st.warning(GOOGLE_IMAGES_COPYRIGHT_WARNING)
                    migrated_google, google_changed = ensure_google_images_cards(settings)
                    google_cards = [dict(item) for item in migrated_google.get("google_images_cards", [])]
                    if google_changed:
                        settings.update(migrated_google)
                        write_json("settings.json", settings)
                    for google_index, google_card in enumerate(google_cards):
                        card_id = str(google_card.get("id") or f"google-images-{google_index + 1}")
                        with st.container(border=True):
                            st.markdown(f"**{google_card.get('label') or card_id}** · prioridade {google_card.get('priority', google_index + 1)}")
                            gcols = st.columns([2, 2, 1, 1])
                            with gcols[0]:
                                name_col, _name_spacer = st.columns([1, 1])
                                with name_col:
                                    google_card["label"] = st.text_input("Nome", value=str(google_card.get("label") or ""), key=f"google_label_{card_id}")
                                google_card["api_key"] = st.text_input("API Key", value=str(google_card.get("api_key") or ""), type="password", key=f"google_key_{card_id}")
                            with gcols[1]:
                                cx_col, cx_link_col = st.columns([1, 1])
                                with cx_col:
                                    google_card["cx"] = st.text_input("Custom Search Engine ID (CX)", value=str(google_card.get("cx") or ""), key=f"google_cx_{card_id}")
                                with cx_link_col:
                                    st.markdown(
                                        '<a href="https://programmablesearchengine.google.com/" target="_blank" rel="noopener noreferrer" style="display:inline-block;margin-top:28px;padding:6px 10px;border:1px solid rgba(128,128,128,.55);border-radius:6px;text-decoration:none;font-size:0.78rem;line-height:1.2;text-align:center;">Programmable Search Engine</a>',
                                        unsafe_allow_html=True,
                                    )
                                daily_col, _daily_spacer = st.columns([1, 1])
                                with daily_col:
                                    google_card["daily_limit"] = st.number_input("Limite diário", min_value=1, max_value=10000, value=int(google_card.get("daily_limit", 100)), key=f"google_limit_{card_id}")
                            with gcols[2]:
                                google_card["enabled"] = st.checkbox("Activo", value=bool(google_card.get("enabled", True)), key=f"google_enabled_{card_id}")
                            with gcols[3]:
                                used = int(google_card.get("queries_used_today", 0))
                                limit = int(google_card.get("daily_limit", 100))
                                st.metric("Consultas hoje", f"{used}/{limit}")
                                if used >= int(limit * 0.8):
                                    st.warning("Quota ≥ 80%")
                            gactions = st.columns(4)
                            with gactions[0]:
                                if st.form_submit_button("↑", key=f"google_up_{card_id}", disabled=google_index == 0):
                                    google_cards[google_index - 1], google_cards[google_index] = google_cards[google_index], google_cards[google_index - 1]
                                    for pos, item in enumerate(google_cards, start=1): item["priority"] = pos
                                    write_json("settings.json", {**settings, "google_images_cards": google_cards}); st.rerun()
                            with gactions[1]:
                                if st.form_submit_button("↓", key=f"google_down_{card_id}", disabled=google_index == len(google_cards) - 1):
                                    google_cards[google_index + 1], google_cards[google_index] = google_cards[google_index], google_cards[google_index + 1]
                                    for pos, item in enumerate(google_cards, start=1): item["priority"] = pos
                                    write_json("settings.json", {**settings, "google_images_cards": google_cards}); st.rerun()
                            with gactions[2]:
                                if st.form_submit_button("Testar chamada API", key=f"google_test_{card_id}"):
                                    result = test_google_images_card(google_card)
                                    (st.success if result["status"] == "success" else st.error)(result["message"])
                            with gactions[3]:
                                if st.form_submit_button("Salvar", key=f"google_save_{card_id}"):
                                    write_json("settings.json", {**settings, "google_images_cards": google_cards}); st.success("Cartão Google Images guardado.")
                            if st.form_submit_button("Remover card", key=f"google_remove_{card_id}"):
                                st.session_state[f"confirm_google_remove_{card_id}"] = True
                            if st.session_state.get(f"confirm_google_remove_{card_id}"):
                                st.warning("Confirma a remoção deste cartão?")
                                if st.form_submit_button("Confirmar remoção", key=f"google_confirm_remove_{card_id}"):
                                    write_json("settings.json", {**settings, "google_images_cards": [item for item in google_cards if str(item.get("id")) != card_id]})
                                    st.rerun()
                    if st.form_submit_button("Adicionar nova API Key do Google Images", key="google_add_card"):
                        google_cards.append(new_google_images_card(priority=len(google_cards) + 1))
                        write_json("settings.json", {**settings, "google_images_cards": google_cards})
                        st.rerun()

                with st.expander("Voz, TTS e música — Azure Speech, restantes serviços e Suno", expanded=False):
                    st.caption("Cada serviço está separado no seu próprio cartão. Os botões de teste ficam dentro do cartão correspondente e fazem apenas diagnóstico, sem gerar áudio ou música.")

                    with st.container(border=True):
                        st.markdown("#### Azure Speech")
                        st.caption("TTS da Microsoft Azure para narração e catálogo de vozes.")
                        azure_speech_key = text_setting("Azure Speech key", "azure_speech_key", secret=True)
                        _render_credential_status(azure_speech_key)
                        azure_speech_region = text_setting("Azure Speech region", "azure_speech_region")

                        def save_azure_speech() -> None:
                            settings.update({
                                "azure_speech_key": azure_speech_key.strip(),
                                "azure_speech_region": azure_speech_region.strip(),
                            })
                            write_json("settings.json", settings)

                        if st.form_submit_button("Guardar Azure Speech", type="primary", width="stretch", key="save_azure_speech"):
                            save_azure_speech()
                            st.success("Azure Speech guardado.")
                        _render_api_test_control(
                            settings,
                            "voice:azure_speech",
                            lambda: test_voice_provider("azure_speech", {"azure_speech_key": azure_speech_key, "azure_speech_region": azure_speech_region}),
                            widget_key="api_test_voice_azure",
                            persist_callback=save_azure_speech,
                        )

                    with st.container(border=True):
                        st.markdown("#### ElevenLabs")
                        st.caption("TTS ElevenLabs para vozes multilíngues.")
                        elevenlabs_api_key = text_setting("ElevenLabs API key", "elevenlabs_api_key", secret=True)
                        _render_credential_status(elevenlabs_api_key)
                        elevenlabs_model_id = text_setting("ElevenLabs model", "elevenlabs_model_id")
                        _render_api_test_control(
                            settings,
                            "voice:elevenlabs",
                            lambda: test_voice_provider("elevenlabs", {"elevenlabs_api_key": elevenlabs_api_key}),
                            widget_key="api_test_voice_elevenlabs",
                        )

                    tts_cols = st.columns(2)
                    with tts_cols[0]:
                        with st.container(border=True):
                            st.markdown("#### SiliconFlow")
                            st.caption("Provider TTS SiliconFlow.")
                            siliconflow_tts_api_key = text_setting("SiliconFlow TTS API key", "siliconflow_tts_api_key", secret=True)
                            _render_credential_status(siliconflow_tts_api_key)
                            _render_api_test_control(
                                settings,
                                "voice:siliconflow",
                                lambda: test_voice_provider("siliconflow", {"siliconflow_tts_api_key": siliconflow_tts_api_key}),
                                widget_key="api_test_voice_siliconflow",
                            )

                        with st.container(border=True):
                            st.markdown("#### MiniMax TTS")
                            st.caption("Provider MiniMax com endpoint, modelo e voz configuráveis.")
                            minimax_tts_api_key = text_setting("MiniMax TTS API key", "minimax_tts_api_key", secret=True)
                            _render_credential_status(minimax_tts_api_key)
                            minimax_tts_base_url = text_setting("MiniMax TTS Base URL", "minimax_tts_base_url")
                            minimax_tts_model_id = text_setting("MiniMax TTS model", "minimax_tts_model_id")
                            minimax_tts_voice_id = text_setting("MiniMax TTS voice ID", "minimax_tts_voice_id")
                            _render_api_test_control(
                                settings,
                                "voice:minimax",
                                lambda: test_voice_provider("minimax", {"minimax_tts_api_key": minimax_tts_api_key, "minimax_tts_base_url": minimax_tts_base_url}),
                                widget_key="api_test_voice_minimax",
                            )

                    with tts_cols[1]:
                        with st.container(border=True):
                            st.markdown("#### Chatterbox")
                            st.caption("Provider compatível com a API OpenAI; pode ser local e sem API key.")
                            chatterbox_base_url = text_setting("Chatterbox Base URL", "chatterbox_base_url")
                            chatterbox_api_key = text_setting("Chatterbox API key", "chatterbox_api_key", secret=True)
                            _render_credential_status(chatterbox_api_key, local=True, required=False)
                            chatterbox_model_id = text_setting("Chatterbox model", "chatterbox_model_id")
                            _render_api_test_control(
                                settings,
                                "voice:chatterbox",
                                lambda: test_voice_provider("chatterbox", {"chatterbox_api_key": chatterbox_api_key, "chatterbox_base_url": chatterbox_base_url}),
                                widget_key="api_test_voice_chatterbox",
                            )

                        with st.container(border=True):
                            st.markdown("#### Sonilo")
                            st.caption("Provider TTS Sonilo com endpoint próprio.")
                            sonilo_api_key = text_setting("Sonilo API key", "sonilo_api_key", secret=True)
                            _render_credential_status(sonilo_api_key)
                            sonilo_base_url = text_setting("Sonilo Base URL", "sonilo_base_url")
                            _render_api_test_control(
                                settings,
                                "voice:sonilo",
                                lambda: test_voice_provider("sonilo", {"sonilo_api_key": sonilo_api_key, "sonilo_base_url": sonilo_base_url}),
                                widget_key="api_test_voice_sonilo",
                            )

                    with st.container(border=True):
                        st.markdown("#### Suno — agente musical opcional")
                        st.caption("Suno é utilizado para criação de música e fica separado dos providers de voz/TTS.")
                        suno_api_key = text_setting("Suno API key", "suno_api_key", secret=True)
                        _render_credential_status(suno_api_key)
                        suno_api_base_url = text_setting("Suno API Base URL", "suno_api_base_url", help_text="Use o endpoint compatível fornecido pelo seu acesso Suno; não é inventado pelo Thunderbolt.")
                        suno_api_endpoint = text_setting("Suno API endpoint", "suno_api_endpoint", help_text="Ex.: /api/generate")
                        _render_api_test_control(
                            settings,
                            "voice:suno",
                            lambda: test_voice_provider("suno", {"suno_api_key": suno_api_key, "suno_api_base_url": suno_api_base_url, "suno_api_endpoint": suno_api_endpoint}),
                            widget_key="api_test_voice_suno",
                        )

                    with st.container(border=True):
                        st.markdown("#### Google Lyria — geração musical")
                        st.caption("Google Lyria gera apenas áudio através da API Gemini Interactions; não usa a pipeline de vídeo.")
                        lyria_api_key = text_setting("Google Lyria API key", "lyria_api_key", secret=True, help_text="Chave da Gemini API com acesso ao modelo Lyria. O valor é guardado apenas localmente.")
                        _render_credential_status(lyria_api_key)
                        lyria_models = ["lyria-3-clip-preview", "lyria-3-pro-preview"]
                        saved_lyria_model = str(settings.get("lyria_model") or lyria_models[0])
                        lyria_model = st.selectbox("Modelo Google Lyria", lyria_models, index=lyria_models.index(saved_lyria_model) if saved_lyria_model in lyria_models else 0, key="settings_lyria_model")

                        def save_google_lyria() -> None:
                            settings.update({"lyria_api_key": lyria_api_key.strip(), "lyria_model": lyria_model})
                            write_json("settings.json", settings)

                        if st.form_submit_button("Guardar Google Lyria", type="primary", width="stretch", key="save_google_lyria"):
                            save_google_lyria()
                            st.success("Google Lyria guardado.")
                        _render_api_test_control(
                            settings,
                            "voice:google_lyria",
                            lambda: test_voice_provider("google_lyria", {"lyria_api_key": lyria_api_key, "lyria_model": lyria_model}),
                            widget_key="api_test_voice_google_lyria",
                            persist_callback=save_google_lyria,
                        )

                upload_post_enabled = bool(settings.get("upload_post_enabled", False))
                upload_post_api_key = str(settings.get("upload_post_api_key") or "")
                upload_post_username = str(settings.get("upload_post_username") or "")
                upload_post_platforms = str(settings.get("upload_post_platforms") or "youtube,tiktok")
                upload_post_auto_upload = bool(settings.get("upload_post_auto_upload", False))
                postiz_enabled = bool(settings.get("postiz_enabled", False))
                postiz_api_key = str(settings.get("postiz_api_key") or "")
                postiz_base_url = str(settings.get("postiz_base_url") or "https://api.postiz.com/public/v1")
                postiz_mcp_url = str(settings.get("postiz_mcp_url") or "https://api.postiz.com/mcp")
                postiz_mode = str(settings.get("postiz_mode") or "api")
                postiz_integration_id = str(settings.get("postiz_integration_id") or "")
                postiz_auto_publish = bool(settings.get("postiz_auto_publish", False))
                save_all_settings = st.form_submit_button("Guardar configurações do Thunderbolt", type="primary")
                if save_all_settings:
                    settings.update({
                        "moneyprinter_path": moneyprinter_path,
                        "kaggle_username": kaggle_username.strip(), "kaggle_api_key": kaggle_api_key.strip(), "kaggle_kernel_slug": kaggle_kernel_slug.strip() or "thunderbolt-niche-finder",
                        "apify_api_token": apify_api_token.strip(), "apify_actor_id": apify_actor_id.strip() or DEFAULT_ACTOR_ID, "apify_poll_interval_seconds": int(apify_poll_interval), "apify_run_timeout_seconds": int(apify_run_timeout),
                        "kalodata_api_key": kalodata_api_key.strip(), "kalodata_base_url": kalodata_base_url.strip() or "https://www.kalodata.com/openapi/v1",
                        "llm_rpm_limit_enabled": bool(llm_rpm_limit_enabled), "llm_rpm_limit": int(llm_rpm_limit), "llm_rpm_window_seconds": int(llm_rpm_window_seconds),
                        "azure_speech_key": azure_speech_key, "azure_speech_region": azure_speech_region,
                        "siliconflow_tts_api_key": siliconflow_tts_api_key, "minimax_tts_api_key": minimax_tts_api_key,
                        "minimax_tts_base_url": minimax_tts_base_url, "minimax_tts_model_id": minimax_tts_model_id, "minimax_tts_voice_id": minimax_tts_voice_id,
                        "elevenlabs_api_key": elevenlabs_api_key, "elevenlabs_model_id": elevenlabs_model_id,
                        "chatterbox_base_url": chatterbox_base_url, "chatterbox_api_key": chatterbox_api_key, "chatterbox_model_id": chatterbox_model_id,
                        "sonilo_api_key": sonilo_api_key, "sonilo_base_url": sonilo_base_url, "suno_api_key": suno_api_key, "suno_api_base_url": suno_api_base_url, "suno_api_endpoint": suno_api_endpoint,
                        "lyria_api_key": lyria_api_key, "lyria_model": lyria_model,
                        "upload_post_enabled": upload_post_enabled, "upload_post_api_key": upload_post_api_key,
                        "upload_post_username": upload_post_username, "upload_post_platforms": upload_post_platforms,
                        "upload_post_auto_upload": upload_post_auto_upload,
                        "postiz_enabled": postiz_enabled, "postiz_api_key": postiz_api_key, "postiz_base_url": postiz_base_url.strip() or "https://api.postiz.com/public/v1",
                        "postiz_mcp_url": postiz_mcp_url.strip() or "https://api.postiz.com/mcp", "postiz_mode": postiz_mode,
                        "postiz_integration_id": postiz_integration_id.strip(), "postiz_auto_publish": bool(postiz_auto_publish),
                    })
                    write_json("settings.json", settings)
                    try:
                        synced = sync_moneyprinter_config(settings, moneyprinter_path)
                        if synced:
                            st.success(f"Configurações guardadas e sincronizadas com {synced}")
                        else:
                            st.success("Configurações guardadas localmente. Indique uma pasta válida do motor de vídeo para sincronizar config.toml.")
                    except Exception as exc:
                        st.warning(f"Configurações locais guardadas, mas não foi possível sincronizar config.toml: {exc}")
    with upload_api_keys_tab:
        st.subheader("API Keys Upload")
        st.caption("Credenciais e integrações utilizadas pelos fluxos de publicação. Cada grupo fica separado para evitar misturar chaves de geração com chaves de upload.")
        with st.expander("Contas Google", expanded=False):
            render_google_accounts(include_innertube=False)
        with st.expander("API Innertube", expanded=False):
            st.markdown("### INNERTUBE_API_KEY")
            st.caption("Esta é uma chave API global do YouTube: aplica-se a todas as contas Google/YouTube e a todo o sistema. Não é associada a uma conta específica, não faz parte dos documentos de cookies/credenciais e não é editada no separador API Keys.")
            upload_batch_accounts = [item for item in settings.get("youtube_batch_accounts", []) if isinstance(item, dict) and item.get("id")]
            current_upload_innertube = str(settings.get("direct_innertube_api_key") or settings.get("INNERTUBE_API_KEY") or "").strip()
            if not current_upload_innertube:
                for legacy_account in upload_batch_accounts:
                    current_upload_innertube = str(legacy_account.get("innertube_api_key") or legacy_account.get("INNERTUBE_API_KEY") or "").strip()
                    if current_upload_innertube:
                        break
                if current_upload_innertube:
                    settings["direct_innertube_api_key"] = current_upload_innertube
                    settings.pop("INNERTUBE_API_KEY", None)
                    for legacy_account in upload_batch_accounts:
                        legacy_account.pop("innertube_api_key", None)
                        legacy_account.pop("INNERTUBE_API_KEY", None)
                    settings["youtube_batch_accounts"] = upload_batch_accounts
                    write_json("settings.json", settings)
            innertube_upload_status = st.columns([3.2, 1.2])
            with innertube_upload_status[0]:
                st.caption("Estado da chave global")
            with innertube_upload_status[1]:
                _render_credential_status(current_upload_innertube)
            with st.form("upload_innertube_api_key_form"):
                upload_innertube = st.text_input("INNERTUBE_API_KEY", value=current_upload_innertube, type="password", key="upload_api_innertube_key", help="Chave global usada pelo Upload directo para todas as contas Google/YouTube. Guarde-a na configuração global, separada dos documentos de cookies.")
                _render_api_test_control(settings, "innertube_upload", lambda: test_innertube_api_key(upload_innertube), widget_key="api_test_innertube_upload")
                save_upload_innertube = st.form_submit_button("Guardar INNERTUBE_API_KEY global", type="primary", width="stretch")
            if save_upload_innertube:
                settings["direct_innertube_api_key"] = upload_innertube.strip()
                settings.pop("INNERTUBE_API_KEY", None)
                for legacy_account in upload_batch_accounts:
                    legacy_account.pop("innertube_api_key", None)
                    legacy_account.pop("INNERTUBE_API_KEY", None)
                settings["youtube_batch_accounts"] = upload_batch_accounts
                write_json("settings.json", settings)
                st.success("INNERTUBE_API_KEY global guardada para todas as contas Google/YouTube e para todo o sistema.")
                st.rerun()
        with st.expander("API Tiktok", expanded=False):
            render_tiktok_api_cards(settings)
        with st.expander("API Instagram", expanded=False):
            render_meta_api_cards(settings, "instagram")
        with st.expander("API Facebook Pages", expanded=False):
            render_meta_api_cards(settings, "facebook_pages")
        with st.expander("API Bilibili", expanded=False):
            bilibili_cards = settings.get("bilibili_api_cards") if isinstance(settings.get("bilibili_api_cards"), list) else []
            bilibili_ready = any(bool(card.get("active", True) and card.get("sessdata") and card.get("bili_jct") and card.get("buvid3")) for card in bilibili_cards if isinstance(card, dict))
            _api_status_badge("Configured" if bilibili_ready else "Missing configuration", "ready" if bilibili_ready else "missing")
            render_bilibili_api_cards(settings)
        with st.expander("Composio", expanded=False):
            st.caption("Os slugs e parâmetros técnicos do Composio são definidos pelo Thunderbolt conforme a operação; a autenticação da conta continua a ser feita pelo Connect Link do Composio.")
            composio_enabled = st.checkbox("Activar Composio", value=bool(settings.get("composio_enabled", False)), key="upload_composio_enabled")
            composio_auto_upload = st.checkbox("Usar Composio por defeito na Automação Youtube", value=bool(settings.get("composio_auto_upload", True)), key="upload_composio_auto_upload", help="Quando estiver configurado, Composio é tentado antes da API Oficial, Upload directo e Postiz.")
            composio_api_key = st.text_input("Composio API key", value=str(settings.get("composio_api_key") or ""), type="password", key="upload_composio_api_key", help="Use a API key de projecto do Composio Platform. Nunca coloque esta chave no GitHub, em URLs ou em mensagens.")
            composio_user_id = st.text_input("Composio user ID", value=str(settings.get("composio_user_id") or "thunderbolt-local"), key="upload_composio_user_id", help="Tem de ser o mesmo user ID usado quando as contas YouTube foram ligadas no Composio.")
            _render_credential_status(composio_api_key)
            composio_action_cols = st.columns(2)
            with composio_action_cols[0]:
                save_composio = st.button("Guardar Composio", type="primary", width="stretch", key="upload_composio_save")
            with composio_action_cols[1]:
                test_composio = st.button("Testar configuração", width="stretch", key="upload_composio_test")
            if save_composio:
                settings.update({"composio_enabled": bool(composio_enabled), "composio_auto_upload": bool(composio_auto_upload), "composio_api_key": composio_api_key.strip(), "composio_user_id": composio_user_id.strip() or "thunderbolt-local"})
                settings.pop("composio_channel_field", None)
                settings.pop("composio_arguments_json", None)
                write_json("settings.json", settings)
                st.success("Configuração Composio guardada.")
                st.rerun()
            if test_composio:
                try:
                    result = test_configuration(composio_api_key, composio_user_id)
                    found = len((result.get("data") or {}).get("tools", []))
                    st.success(f"Configuração Composio válida; {found} ferramenta(s) de upload encontradas.")
                except ComposioUploadError as exc:
                    st.error(str(exc))
        with st.expander("Upload-Post", expanded=False):
            upload_post_enabled_upload = st.checkbox("Activar Upload-Post", bool(settings.get("upload_post_enabled", False)), key="upload_tab_upload_post_enabled")
            upload_post_key_upload = st.text_input("Upload-Post API key", value=str(settings.get("upload_post_api_key") or ""), type="password", key="upload_tab_upload_post_key")
            upload_post_user_upload = st.text_input("Upload-Post username", value=str(settings.get("upload_post_username") or ""), key="upload_tab_upload_post_user")
            upload_post_platforms_upload = st.text_input("Plataformas Upload-Post", value=str(settings.get("upload_post_platforms") or "youtube,tiktok"), key="upload_tab_upload_post_platforms")
            upload_post_auto_upload = st.checkbox("Publicar automaticamente após gerar", bool(settings.get("upload_post_auto_upload", False)), key="upload_tab_upload_post_auto")
            _render_credential_status(upload_post_key_upload, required=True)
            if st.button("Guardar Upload-Post", type="primary", width="stretch", key="upload_tab_save_upload_post"):
                settings.update({"upload_post_enabled": bool(upload_post_enabled_upload), "upload_post_api_key": upload_post_key_upload.strip(), "upload_post_username": upload_post_user_upload.strip(), "upload_post_platforms": upload_post_platforms_upload.strip(), "upload_post_auto_upload": bool(upload_post_auto_upload)})
                write_json("settings.json", settings)
                st.success("Upload-Post guardado.")
                st.rerun()
        with st.expander("Postiz", expanded=False):
            postiz_enabled_upload = st.checkbox("Activar Postiz como fallback final", bool(settings.get("postiz_enabled", False)), key="upload_tab_postiz_enabled")
            postiz_key_upload = st.text_input("Postiz API key", value=str(settings.get("postiz_api_key") or ""), type="password", key="upload_tab_postiz_key")
            postiz_base_upload = st.text_input("Postiz Public API Base URL", value=str(settings.get("postiz_base_url") or "https://api.postiz.com/public/v1"), key="upload_tab_postiz_base")
            postiz_mcp_upload = st.text_input("Postiz MCP URL", value=str(settings.get("postiz_mcp_url") or "https://api.postiz.com/mcp"), key="upload_tab_postiz_mcp")
            postiz_integration_upload = st.text_input("Postiz integração padrão", value=str(settings.get("postiz_integration_id") or ""), key="upload_tab_postiz_integration")
            postiz_auto_upload = st.checkbox("Permitir publicação imediata no Postiz", bool(settings.get("postiz_auto_publish", False)), key="upload_tab_postiz_auto")
            _render_credential_status(postiz_key_upload, required=True)
            if st.button("Guardar Postiz", type="primary", width="stretch", key="upload_tab_save_postiz"):
                settings.update({"postiz_enabled": bool(postiz_enabled_upload), "postiz_api_key": postiz_key_upload.strip(), "postiz_base_url": postiz_base_upload.strip(), "postiz_mcp_url": postiz_mcp_upload.strip(), "postiz_integration_id": postiz_integration_upload.strip(), "postiz_auto_publish": bool(postiz_auto_upload)})
                write_json("settings.json", settings)
                st.success("Postiz guardado.")
                st.rerun()
    with subtitles_tab:
        st.subheader("Legendas")
        st.caption("Escolha como o motor de vídeo gera as legendas. A configuração só é alterada quando clicar em guardar.")
        st.markdown("### Os dois modos de geração")
        st.markdown("O projecto oferece duas abordagens principais para criar as legendas:")
        st.table([
            {"Modo": "edge", "Velocidade": "Rápida", "Requisitos de Hardware": "Nenhum (roda em CPU)", "Qualidade": "Pode ser instável"},
            {"Modo": "whisper", "Velocidade": "Lenta", "Requisitos de Hardware": "Alta (GPU recomendada)", "Qualidade": "Mais confiável"},
        ])
        subtitle_provider_options = ["edge", "whisper"]
        current_subtitle_provider = str(settings.get("subtitle_provider") or "edge").strip().lower()
        if current_subtitle_provider not in subtitle_provider_options:
            current_subtitle_provider = "edge"
        subtitle_provider = st.radio(
            "Modo de geração",
            subtitle_provider_options,
            index=subtitle_provider_options.index(current_subtitle_provider),
            format_func=lambda value: f"{value} — {'Rápida, CPU, pode ser instável' if value == 'edge' else 'Lenta, GPU recomendada, mais confiável'}",
            horizontal=True,
            key="subtitle_provider_ui",
        )
        st.caption("A escolha é feita alterando a propriedade `subtitle_provider` no `config.toml`.")
        whisper_cols = st.columns(3)
        with whisper_cols[0]:
            whisper_model_size = st.selectbox(
                "Modelo Whisper",
                ["tiny", "base", "small", "medium", "large-v3"],
                index=["tiny", "base", "small", "medium", "large-v3"].index(str(settings.get("whisper_model_size") or "large-v3")) if str(settings.get("whisper_model_size") or "large-v3") in ["tiny", "base", "small", "medium", "large-v3"] else 4,
                key="subtitle_whisper_model_size",
            )
        with whisper_cols[1]:
            whisper_device = st.selectbox(
                "Dispositivo Whisper",
                ["cpu", "cuda"],
                index=["cpu", "cuda"].index(str(settings.get("whisper_device") or "cpu")) if str(settings.get("whisper_device") or "cpu") in ["cpu", "cuda"] else 0,
                key="subtitle_whisper_device",
            )
        with whisper_cols[2]:
            whisper_compute_type = st.selectbox(
                "Tipo de cálculo Whisper",
                ["int8", "float16", "float32"],
                index=["int8", "float16", "float32"].index(str(settings.get("whisper_compute_type") or "int8")) if str(settings.get("whisper_compute_type") or "int8") in ["int8", "float16", "float32"] else 0,
                key="subtitle_whisper_compute_type",
            )
        if st.button("Guardar configuração de legendas", type="primary", width="stretch", key="save_subtitle_settings"):
            settings.update({
                "subtitle_provider": subtitle_provider,
                "whisper_model_size": whisper_model_size,
                "whisper_device": whisper_device,
                "whisper_compute_type": whisper_compute_type,
            })
            write_json("settings.json", settings)
            subtitle_moneyprinter_path = str(settings.get("moneyprinter_path") or "").strip()
            if subtitle_moneyprinter_path:
                try:
                    synced = sync_moneyprinter_config(settings, subtitle_moneyprinter_path)
                    st.success(f"Configuração de legendas guardada{f' e sincronizada com {synced}' if synced else ''}.")
                except Exception as exc:
                    st.warning(f"Configuração de legendas guardada localmente, mas não foi possível sincronizar config.toml: {exc}")
            else:
                st.success("Configuração de legendas guardada localmente.")

    with ffmpeg_tab:
        st.subheader("FFmpeg")
        st.caption("Seleccione a versão do FFmpeg usada pelo pipeline. O FFmpeg actual do pacote é o FFmpeg 7.1 Péter incluído fisicamente no seed; o imageio-ffmpeg permanece instalado como a segunda versão alternativa.")
        seeded_ffmpeg_path = str(settings.get("ffmpeg_seed_path") or "").strip()
        current_ffmpeg_path = str(settings.get("ffmpeg_system_path") or "").strip()
        if not current_ffmpeg_path:
            try:
                import imageio_ffmpeg
                current_ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
            except Exception:
                current_ffmpeg_path = "ffmpeg"
        ffmpeg_options = [
            ("7.1-20240930", "FFmpeg actual — 7.1 Péter, binário incluído no pacote / NVENC API 13.0", seeded_ffmpeg_path or "ffmpeg"),
            ("system", "FFmpeg actual do sistema — imageio-ffmpeg, instalado no ambiente Python", current_ffmpeg_path),
        ]
        saved_ffmpeg_version = str(settings.get("ffmpeg_version") or "7.1-20240930").strip()
        ffmpeg_values = [item[0] for item in ffmpeg_options]
        if saved_ffmpeg_version not in ffmpeg_values:
            saved_ffmpeg_version = "7.1-20240930"
        ffmpeg_version = st.radio(
            "Versão a utilizar",
            ffmpeg_values,
            index=ffmpeg_values.index(saved_ffmpeg_version),
            format_func=lambda value: next(item[1] for item in ffmpeg_options if item[0] == value),
            key="ffmpeg_version_ui",
        )
        selected_ffmpeg_path = next(item[2] for item in ffmpeg_options if item[0] == ffmpeg_version)
        ffmpeg_path_status = shutil.which(selected_ffmpeg_path) or (selected_ffmpeg_path if Path(selected_ffmpeg_path).is_file() else "")
        if ffmpeg_path_status:
            st.success(f"FFmpeg seleccionado disponível: `{ffmpeg_path_status}`")
        else:
            st.warning("O executável seleccionado ainda não foi encontrado no PATH. A instalação Windows abaixo pode corrigir isso.")
        with st.expander("Instalação incluída no pacote", expanded=False):
            st.caption("As duas versões são instaladas pelo próprio pacote: o FFmpeg 7.1 é extraído para a pasta isolada do Thunderbolt e o FFmpeg actual é instalado no ambiente Python através de imageio-ffmpeg. Nenhuma versão altera o PATH global ou substitui a outra.")
        if st.button("Guardar configuração de FFmpeg", type="primary", width="stretch", key="save_ffmpeg_settings"):
            settings.update({
                "ffmpeg_version": ffmpeg_version,
                "ffmpeg_path": selected_ffmpeg_path,
            })
            write_json("settings.json", settings)
            ffmpeg_moneyprinter_path = str(settings.get("moneyprinter_path") or "").strip()
            if ffmpeg_moneyprinter_path:
                try:
                    synced = sync_moneyprinter_config(settings, ffmpeg_moneyprinter_path)
                    st.success(f"Configuração de FFmpeg guardada{f' e sincronizada com {synced}' if synced else ''}.")
                except Exception as exc:
                    st.warning(f"Configuração guardada localmente, mas não foi possível sincronizar config.toml: {exc}")
            else:
                st.success("Configuração de FFmpeg guardada localmente.")

    with ai_influencers_tab:
        st.subheader("AI Influencers")
        st.caption("Estado do backend usado por Personagens e Geração de Conteúdo IA. O selector e as credenciais são editados nesta aba, em Banco de Dados Influencers.")
        saved_backend = str(settings.get("influencer_db_backend") or "SQLite").strip()
        backend_index = list(BACKEND_OPTIONS).index(saved_backend) if saved_backend in BACKEND_OPTIONS else list(BACKEND_OPTIONS).index("SQLite")
        influencer_db_backend = st.selectbox(
            "Backend da base de dados de AI Influencers",
            list(BACKEND_OPTIONS),
            index=backend_index,
            key="settings_influencer_db_backend",
            help="Seleccione Supabase para usar a base remota ou SQLite para guardar tudo localmente.",
        )
        with st.container(border=True):
            st.subheader("Supabase")
            st.caption("Configure apenas os dados da ligação Supabase. Se o selector estiver em Supabase mas faltar qualquer credencial, o backend activo permanece SQLite.")
            with st.form("influencer_database_settings_form"):
                db_cols = st.columns(2)
                with db_cols[0]:
                    influencer_supabase_url = text_setting("Supabase Project URL", "influencer_supabase_url", help_text="URL do projecto, por exemplo https://project-id.supabase.co")
                with db_cols[1]:
                    influencer_supabase_key = text_setting("Supabase API key", "influencer_supabase_key", secret=True, help_text="Use uma chave com as permissões RLS adequadas. Nunca é colocada no GitHub ou nos logs.")
                test_backend_clicked = st.form_submit_button("Testar ligação do backend", width="stretch")
                save_backend_clicked = st.form_submit_button("Guardar configuração do backend", type="primary", width="stretch")
        effective_settings = dict(settings)
        effective_settings.update({
            "influencer_db_backend": influencer_db_backend,
            "influencer_supabase_url": influencer_supabase_url,
            "influencer_supabase_key": influencer_supabase_key,
        })
        if test_backend_clicked:
            db_result = test_backend(effective_settings)
            if db_result.get("ok"):
                st.success(db_result.get("message") or "Backend disponível.")
            else:
                st.error(db_result.get("message") or "O backend não está disponível.")
        if save_backend_clicked:
            settings.update({
                "influencer_db_backend": influencer_db_backend,
                "influencer_supabase_url": influencer_supabase_url.strip(),
                "influencer_supabase_key": influencer_supabase_key.strip(),
            })
            write_json("settings.json", settings)
            st.success("Configuração do backend AI Influencers guardada.")
            st.rerun()
        render_ai_influencers_api_status(effective_settings)

    with test_upload_videos_tab:
        _render_test_upload_videos(settings)

    with voice_test_tab:
        st.subheader("Teste de Voz")
        st.caption("Este painel é exclusivamente um preview. O áudio gerado não altera vídeos, tarefas, Blueprints ou a configuração da pipeline.")
        preview_cols = st.columns([1.1, 2.2, 1.2])
        with preview_cols[0]:
            preview_provider = st.selectbox("Provider", ["edge", "azure_speech", "elevenlabs", "minimax", "siliconflow", "gemini", "chatterbox"], index=0, key="voice_preview_provider")
        with preview_cols[1]:
            if preview_provider in {"edge", "azure_speech"}:
                preview_voice_options = voice_catalog(settings.get("voice_preview_voice", "en-US-AriaNeural-Female"))
                preview_voice = st.selectbox("Voz", preview_voice_options, index=preview_voice_options.index(settings.get("voice_preview_voice", "en-US-AriaNeural-Female")) if settings.get("voice_preview_voice", "en-US-AriaNeural-Female") in preview_voice_options else 0, format_func=lambda item: item or "Escolha uma voz", key="voice_preview_voice")
            else:
                preview_voice = st.text_input("Voice ID", value=settings.get("voice_preview_voice", ""), key="voice_preview_voice_text")
        with preview_cols[2]:
            preview_rate = st.selectbox("Velocidade", ["-20%", "-10%", "+0%", "+10%", "+20%"], index=2, key="voice_preview_rate")
        preview_text = st.text_area("Texto de teste", value=DEFAULT_SAMPLE, max_chars=1000, height=110, key="voice_preview_text")
        if st.button("Testar voz", type="primary", key="voice_preview_generate"):
            st.session_state.pop("voice_preview_path", None)
            try:
                preview_path = synthesize_preview(preview_text, preview_provider, preview_voice, settings, preview_rate)
                st.session_state["voice_preview_path"] = str(preview_path)
                st.success("Amostra de voz gerada. Este ficheiro é apenas um preview.")
            except Exception as exc:
                st.error(f"Não foi possível gerar o preview: {exc}")
        preview_value = str(st.session_state.get("voice_preview_path", "") or "").strip()
        loaded_preview = load_preview_file(preview_value)
        if loaded_preview:
            preview_path, preview_data = loaded_preview
            st.audio(preview_data, format="audio/mpeg")
            st.download_button("Descarregar amostra", data=preview_data, file_name=preview_path.name, mime="audio/mpeg", key="voice_preview_download")
        elif preview_value:
            st.session_state.pop("voice_preview_path", None)
            st.warning("A amostra de voz anterior não é um ficheiro de áudio legível e foi removida do estado local. Teste a voz novamente.")


def _render_telegram_notification_settings() -> None:
    """Render Telegram outbound notification settings and a safe diagnostics action."""
    settings = read_json("settings.json", {})
    if not isinstance(settings, dict):
        settings = {}
    st.subheader("Telegram Gateway")
    st.caption("Envie para o Telegram as mesmas notificações que aparecem na subaba Geral. A integração usa a Bot API oficial e não recebe mensagens nem inicia polling.")
    with st.form("telegram_notifications_form"):
        telegram_enabled = st.checkbox(
            "Activar notificações Telegram",
            value=bool(settings.get("telegram_enabled", False)),
            help="Quando activo, cada nova notificação permitida em Geral é enviada para o Chat ID configurado.",
        )
        telegram_cols = st.columns(2)
        with telegram_cols[0]:
            telegram_bot_token = st.text_input(
                "Telegram Bot Token",
                value=str(settings.get("telegram_bot_token") or ""),
                type="password",
                help="Token criado pelo BotFather. Fica guardado apenas no storage local.",
            )
            _render_credential_status(telegram_bot_token)
        with telegram_cols[1]:
            telegram_chat_id = st.text_input(
                "Telegram Chat ID",
                value=str(settings.get("telegram_chat_id") or ""),
                help="ID do utilizador, grupo ou canal que receberá as notificações; também pode ser um username aceite pelo Telegram.",
            )
        telegram_proxy_url = st.text_input(
            "Proxy Telegram (opcional)",
            value=str(settings.get("telegram_proxy_url") or ""),
            help="Proxy HTTP/HTTPS/SOCKS suportado pelo ambiente, quando o acesso directo ao Telegram não estiver disponível.",
        )
        telegram_timeout_seconds = st.number_input(
            "Timeout de envio (segundos)",
            min_value=5,
            max_value=120,
            value=int(settings.get("telegram_timeout_seconds", 15) or 15),
            step=5,
        )
        st.caption("O teste consulta getMe para validar o Bot Token e não envia uma mensagem de teste.")
        _render_api_test_control(
            settings,
            "telegram",
            lambda: test_telegram_credentials(telegram_bot_token, telegram_chat_id),
            widget_key="api_test_telegram",
        )
        if st.form_submit_button("Guardar configuração Telegram", type="primary", width="stretch"):
            settings.update({
                "telegram_enabled": bool(telegram_enabled),
                "telegram_bot_token": telegram_bot_token.strip(),
                "telegram_chat_id": telegram_chat_id.strip(),
                "telegram_proxy_url": telegram_proxy_url.strip(),
                "telegram_timeout_seconds": int(telegram_timeout_seconds),
            })
            write_json("settings.json", settings)
            st.success("Configuração Telegram guardada no storage local.")
            st.rerun()

    if telegram_enabled and telegram_bot_token.strip() and telegram_chat_id.strip():
        st.success("Telegram está preparado para receber novas notificações.")
    elif telegram_enabled:
        st.warning("Telegram está activo, mas ainda falta configurar o Bot Token e o Chat ID.")
    else:
        st.info("Telegram está desactivado. As notificações continuam disponíveis na subaba Geral.")


def render_logs():
    """Render the unified local activity log before the API configuration page."""
    st.title("Logs")
    st.caption("Histórico unificado das operações do Thunderbolt. Os registos são reconstruídos a partir das tarefas e notificações persistidas no storage local.")
    try:
        reconcile_persisted_notifications()
    except Exception:
        pass

    initial_records = list_logs(limit=500)
    catalog_operations = {str(item.get("label") or "Operação") for item in notification_event_catalog()}
    logged_operations = {str(item.get("operation") or "Operação") for item in initial_records}
    operation_options = ["Todas"] + sorted(catalog_operations | logged_operations)
    status_options = ["Todos"] + sorted({str(item.get("status") or "Desconhecido") for item in initial_records})
    filter_cols = st.columns([2.2, 1.25, 1.1])
    with filter_cols[0]:
        query = st.text_input(
            "Filtrar operações",
            placeholder="Pesquisar por operação, registo, canal ou detalhes",
            key="logs_query_filter",
        )
    with filter_cols[1]:
        selected_operation = st.selectbox("Operação", operation_options, key="logs_operation_filter")
    with filter_cols[2]:
        selected_status = st.selectbox("Estado", status_options, key="logs_status_filter")

    action_cols = st.columns([1, 1, 3])
    with action_cols[0]:
        if st.button("Actualizar logs", width="stretch"):
            st.rerun()
    with action_cols[1]:
        st.metric("Registos", len(initial_records))
    with action_cols[2]:
        st.caption("São incluídos estados pendentes, em execução, concluídos, publicados, falhados, cancelados e bloqueados quando existirem.")

    operation_filter = "" if selected_operation == "Todas" else selected_operation
    status_filter = "" if selected_status == "Todos" else selected_status
    records = list_logs(operation=operation_filter, query=query, status=status_filter, limit=500)
    if not records:
        st.info("Ainda não existem logs para os filtros seleccionados.")
        return
    rows = logs_to_rows(records)

    def _log_source() -> Path | None:
        settings = read_json("settings.json", {})
        configured_root = str(settings.get("moneyprinter_path") or os.environ.get("MONEYPRINTER_PATH") or "").strip()
        roots = [
            Path(configured_root).expanduser() if configured_root else None,
            STORAGE.parent / "MoneyPrinterTurbo",
            STORAGE / "MoneyPrinterTurbo",
            Path.cwd() / "MoneyPrinterTurbo",
        ]
        candidates: list[Path] = []
        for root in roots:
            if root:
                candidates.append(root / ".agent-logs" / "moneyprinterturbo-video")
        candidates.extend([Path("run-codigo.log"), STORAGE / "run-codigo.log", STORAGE.parent / "run-codigo.log"])
        directory = next((path for path in candidates if path.is_dir() and any(path.rglob("*"))), None)
        return directory or next((path for path in candidates if path.is_file()), None)

    def _log_download(source: Path | None, requested_filename: str = "") -> tuple[bytes, str, str] | None:
        if source is None:
            return None
        if source.is_file():
            files = [source]
        else:
            run_files = sorted(
                path for path in source.rglob("*")
                if path.is_file() and re.fullmatch(r"run-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?:\.[^.]+)?", path.name, re.IGNORECASE)
            )
            files = [path for path in run_files if not requested_filename or path.name == requested_filename]
            if not files and not run_files and not requested_filename:
                files = sorted(path for path in source.rglob("*") if path.is_file() and path.name != "latest-result.json")
        if not files:
            return None
        sections = ["# Logs do MoneyPrinterTurbo", "", f"Origem: `{source}`", ""]
        for file_path in files:
            relative_name = file_path.name if source.is_file() else file_path.relative_to(source).as_posix()
            content = file_path.read_text(encoding="utf-8", errors="replace")
            sections.extend([f"## {relative_name}", "", "```text", content.rstrip("\n"), "```", ""])
        markdown = "\n".join(sections).encode("utf-8")
        return markdown, f"{files[0].stem}.md", "text/markdown"

    log_source = _log_source()
    log_columns = ["Download", "Operação", "Estado", "Data", "Hora", "Registo", "Ficheiro", "Origem", "Progresso", "API/Provider", "Detalhes"]
    # Keep the log list within the same vertical footprint as the previous table.
    with st.container(height=520):
        header = st.columns([0.8, 1.4, 0.9, 0.8, 0.8, 2.0, 1.8, 1.0, 0.8, 1.5, 4.0], gap="small")
        for column, label in zip(header, log_columns):
            column.markdown(f"**{label}**")
        for index, row in enumerate(rows):
            cells = st.columns([0.8, 1.4, 0.9, 0.8, 0.8, 2.0, 1.8, 1.0, 0.8, 1.5, 4.0], gap="small")
            with cells[0]:
                log_download = _log_download(log_source, str(row.get("Ficheiro") or "").strip() if row.get("Ficheiro") != "—" else "")
                st.download_button(
                    "Baixar",
                    data=log_download[0] if log_download else b"",
                    file_name=log_download[1] if log_download else "run-codigo.md",
                    mime=log_download[2] if log_download else "text/markdown",
                    key=f"logs_download_{index}",
                    width="stretch",
                    disabled=log_download is None,
                )
            for cell, column in zip(cells[1:], log_columns[1:]):
                cell.write(str(row.get(column) or "—"))

    st.caption("A coluna API/Provider identifica a API responsável por cada falha; quando o registo é anterior a esta correcção, o sistema assinala que a API não pôde ser identificada. Quando a tabela exceder a largura disponível, utilize a barra de rolagem horizontal na parte inferior para consultar todo o conteúdo das células.")


def render_notifications():
    st.title("Notificações")
    st.caption("Centro de notificações internas persistentes do Thunderbolt. As conclusões são guardadas no storage local e aparecem quando a aplicação é actualizada.")
    general_tab, telegram_tab = render_localized_tabs(["Geral", "Telegram"])

    with general_tab:
        reconcile_persisted_notifications()
        preferences = notification_preferences()
        catalog = notification_event_catalog()
        notifications = list_notifications(limit=5)
        unread_count = unread_notification_count()
        summary_cols = st.columns(3)
        with summary_cols[0]:
            st.metric("Não lidas", unread_count)
        with summary_cols[1]:
            st.metric("Total guardado", len(notifications))
        with summary_cols[2]:
            st.metric("Operações mapeadas", len(catalog))

        action_cols = st.columns([1.4, 1.4, 2.2])
        with action_cols[0]:
            if st.button("Marcar todas como lidas", width="stretch", disabled=unread_count == 0):
                mark_all_notifications_read()
                st.rerun()
        with action_cols[1]:
            if st.button("Actualizar notificações", width="stretch"):
                reconcile_persisted_notifications()
                st.rerun()
        with action_cols[2]:
            confirm_clear = st.checkbox("Confirmar limpeza do histórico", key="confirm_clear_notifications")
            if st.button("Limpar histórico", width="stretch", disabled=not confirm_clear):
                clear_notifications()
                st.session_state.pop("confirm_clear_notifications", None)
                st.rerun()

        st.divider()
        with st.expander("Operações notificadas", expanded=False):
            st.subheader("Operações notificadas")
            st.caption("Ligue ou desligue cada tipo de notificação. As preferências ficam guardadas no storage local e aplicam-se às próximas conclusões.")
            grouped: dict[str, list[dict[str, str]]] = {}
            for event in catalog:
                grouped.setdefault(event["category"], []).append(event)
            with st.form("notification_preferences_form"):
                pending_preferences: dict[str, bool] = {}
                for category, events in grouped.items():
                    st.markdown(f"**{category}**")
                    for event in events:
                        pending_preferences[event["code"]] = st.checkbox(
                            event["label"],
                            value=bool(preferences.get(event["code"], True)),
                            help=event["description"],
                            key=f"notification_preference_{event['code']}",
                        )
                if st.form_submit_button("Guardar preferências", type="primary", width="stretch"):
                    save_notification_preferences(pending_preferences)
                    st.success("Preferências de notificação guardadas.")
                    st.rerun()

        st.divider()
        st.subheader("Histórico de notificações")
        filter_cols = st.columns([1, 1.4])
        category_options = ["Todas"] + sorted({event["category"] for event in catalog})
        with filter_cols[0]:
            selected_category = st.selectbox("Categoria", category_options, key="notifications_category_filter")
        with filter_cols[1]:
            selected_state = st.selectbox("Estado", ["Todas", "Não lidas", "Lidas"], key="notifications_state_filter")
        category_filter = "" if selected_category == "Todas" else selected_category
        unread_filter = selected_state == "Não lidas"
        filtered = list_notifications(limit=5, category=category_filter, unread_only=unread_filter)
        if selected_state == "Lidas":
            filtered = [item for item in filtered if item.get("read")]
        if not filtered:
            st.info("Ainda não existem notificações para os filtros seleccionados.")
        for item in filtered:
            with st.container(border=True):
                notification_cols = st.columns([3.3, 1.4, 1])
                with notification_cols[0]:
                    st.write(f"**{item.get('title') or item.get('label') or 'Notificação'}**")
                    st.caption(item.get("message") or "")
                    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
                    if metadata:
                        public_details = " · ".join(f"{key}: {value}" for key, value in metadata.items() if value not in (None, ""))
                        if public_details:
                            st.caption(public_details)
                with notification_cols[1]:
                    st.caption(f"{item.get('category', 'Sistema')} · {item.get('created_at', '—')}")
                    st.write("Lida" if item.get("read") else "Não lida")
                with notification_cols[2]:
                    if not item.get("read") and st.button("Marcar como lida", key=f"mark_notification_{item.get('id')}", width="stretch"):
                        mark_notification_read(str(item.get("id")))
                        st.rerun()

    with telegram_tab:
        _render_telegram_notification_settings()


def render_models_ai_tutorial():
    tutorial_path = ROOT / "seed" / "references" / "guide-instagram.md"
    st.title("Meta")
    st.caption("Guia de configuração de uma conta Instagram profissional e das credenciais Meta para automações com n8n.")
    try:
        tutorial_content = tutorial_path.read_text(encoding="utf-8").strip()
    except OSError:
        tutorial_content = ""
    if not tutorial_content:
        st.error("O conteúdo local do tutorial não está disponível.")
        return
    st.markdown(tutorial_content, unsafe_allow_html=True)

def render_niche_tutorial(tutorial_kind: str):
    ui_language = current_ui_language()
    st.title(tutorial_title(tutorial_kind, ui_language))
    st.caption(tutorial_caption(tutorial_kind, ui_language))
    st.markdown(tutorial_body(tutorial_kind, ui_language), unsafe_allow_html=False)


def render_supabase_tutorial():
    tutorial_path = ROOT / "seed" / "references" / "guide-supabase.md"
    ui_language = current_ui_language()
    st.title(ui_text("Supabase", ui_language))
    st.caption(ui_text("Guia de configuração do Supabase para automações com n8n.", ui_language))
    try:
        tutorial_content = tutorial_path.read_text(encoding="utf-8").strip()
    except OSError:
        tutorial_content = ""
    if not tutorial_content:
        st.error("O conteúdo local do tutorial não está disponível.")
        return
    st.markdown(tutorial_content, unsafe_allow_html=True)


def render_google_oauth_tutorial():
    """Render the Google OAuth setup guide supplied for Thunderbolt."""
    tutorial_path = ROOT / "seed" / "references" / "tutorial-oauth-google.md"
    st.title("OAuth do Google")
    st.caption("Guia completo para configurar a autenticação OAuth do Google e o acesso à YouTube Data API v3.")
    try:
        tutorial_content = tutorial_path.read_text(encoding="utf-8").strip()
    except OSError:
        tutorial_content = ""
    if not tutorial_content:
        st.error("O conteúdo local do tutorial não está disponível.")
        return
    st.markdown(tutorial_content, unsafe_allow_html=False)


def render_youtube_frontend_upload_tutorial():
    """Render the safe operational guide for the YouTube direct-upload workflow."""
    tutorial_path = ROOT / "seed" / "references" / "youtube-video-upload-frontend.md"
    st.title("YouTube Video-Upload Frontend")
    st.caption("Guia prático e seguro para rever metadados, sessão e envio directo de vídeos concluídos.")
    try:
        tutorial_content = tutorial_path.read_text(encoding="utf-8").strip()
    except OSError:
        tutorial_content = ""
    if not tutorial_content:
        st.error("O conteúdo local do tutorial não está disponível.")
        return
    st.markdown(tutorial_content, unsafe_allow_html=False)


def render_youtube_data_api_key_tutorial():
    """Render the YouTube Data API key guide for public data workflows."""
    tutorial_path = ROOT / "seed" / "references" / "tutorial-youtube-data-api-key.md"
    st.title("YouTube Data API Key (Public Data)")
    st.caption("Guia para criar e configurar uma YouTube Data API Key para consultas de dados públicos.")
    try:
        tutorial_content = tutorial_path.read_text(encoding="utf-8").strip()
    except OSError:
        tutorial_content = ""
    if not tutorial_content:
        st.error("O conteúdo local do tutorial não está disponível.")
        return
    st.markdown(tutorial_content, unsafe_allow_html=False)


def render_mcp():
    st.title("MCP")
    st.caption("Clientes externos, servidor MCP do Thunderbolt e a skill local ficam separados para evitar confundir funções diferentes.")

    client_tab, server_tab, skill_tab = render_localized_tabs(["Client MCP", "Servidor MCP", "Skill"])

    with client_tab:
        st.subheader("Client MCP")
        st.info("Configure aqui os serviços MCP externos que o Thunderbolt pode detectar passivamente. Activar uma integração guarda apenas a preferência; não instala nem inicia processos externos.")
        integrations = load_integrations()
        for integration in integrations:
            integration_id = integration["id"]
            with st.container(border=True):
                header_cols = st.columns([2.6, 1.15, 1.65, 1.2])
                with header_cols[0]:
                    st.write(f"**{integration['name']}**")
                    st.caption(f"{integration['protocol']} · {integration['description']}")
                    st.markdown(f"[Abrir repositório oficial]({integration['repository']})")
                with header_cols[1]:
                    port = st.number_input(
                        "Porta",
                        min_value=1,
                        max_value=65535,
                        value=int(integration.get("port", 8000)),
                        step=1,
                        key=f"mcp_port_{integration_id}",
                    )
                with header_cols[2]:
                    status = detect_local_service({**integration, "port": port})
                    if status["available"]:
                        st.success("Disponível")
                    else:
                        st.caption("Não detectado")
                    st.caption(status["message"])
                with header_cols[3]:
                    active = st.toggle("Activo", value=bool(integration.get("active", False)), key=f"mcp_active_{integration_id}")
                    if active != bool(integration.get("active", False)):
                        update_integration(integration_id, active=active)
                        st.rerun()

                st.caption(integration.get("endpoint_note", "Porta editável para o serviço local."))
                if st.button("Guardar porta", key=f"mcp_save_port_{integration_id}", width="stretch"):
                    update_integration(integration_id, port=int(port))
                    st.success(f"Porta de {integration['name']} guardada: {int(port)}")
                    st.rerun()

    with server_tab:
        st.subheader("Servidor MCP")
        st.caption("Servidor local do Thunderbolt para ser descoberto por um agente compatível com MCP. O endpoint usa JSON-RPC sobre HTTP POST em `/mcp`.")
        st.warning("Por segurança, o servidor inicia apenas quando o activar explicitamente. Por padrão fica acessível somente neste computador em 127.0.0.1:3031.")
        server_config = load_server_config()
        if server_config.get("enabled") and not server_status().get("running"):
            try:
                start_server(
                    str(server_config.get("host", "127.0.0.1")),
                    int(server_config.get("port", 3031)),
                    str(server_config.get("auth_token", "")),
                    bool(server_config.get("write_enabled", False)),
                )
            except Exception as exc:
                st.error(f"Não foi possível iniciar o Servidor MCP guardado: {exc}")

        server_cols = st.columns([1.3, 1.4, 1.4])
        with server_cols[0]:
            server_enabled = st.checkbox("Servidor MCP ON", value=bool(server_config.get("enabled", False)), key="mcp_server_enabled")
        with server_cols[1]:
            server_host = st.text_input("Host", value=str(server_config.get("host", "127.0.0.1")), key="mcp_server_host", help="Use 127.0.0.1 para acesso local. Um host externo exige token.")
        with server_cols[2]:
            server_port = st.number_input("Porta do servidor", min_value=1, max_value=65535, value=int(server_config.get("port", 3031)), step=1, key="mcp_server_port")
        server_token = st.text_input("Token de acesso MCP (opcional no localhost)", value=str(server_config.get("auth_token", "")), type="password", key="mcp_server_token")
        write_enabled = st.checkbox("Permitir ferramentas de escrita", value=bool(server_config.get("write_enabled", False)), key="mcp_server_write", help="Desactivado por padrão. Quando activo, o agente pode criar lotes de vídeos através de uma ferramenta MCP; leituras continuam disponíveis sem esta opção.")
        if str(server_host).strip() not in {"127.0.0.1", "localhost", "::1"} and not str(server_token).strip():
            st.error("Para expor o servidor fora do computador local, defina um token de acesso MCP.")

        action_label = "Guardar e iniciar Servidor MCP" if server_enabled else "Guardar e parar Servidor MCP"
        if st.button(action_label, type="primary", key="mcp_server_save", width="stretch"):
            try:
                saved = save_server_config(enabled=server_enabled, host=server_host, port=int(server_port), auth_token=server_token, write_enabled=write_enabled)
                if saved["enabled"]:
                    status = start_server(saved["host"], saved["port"], saved["auth_token"], saved["write_enabled"])
                    st.success(f"Servidor MCP activo em `{status['endpoint']}`")
                else:
                    stop_server()
                    st.success("Servidor MCP parado.")
                st.rerun()
            except Exception as exc:
                st.error(f"Não foi possível guardar/iniciar o Servidor MCP: {exc}")

        runtime = server_status()
        if runtime.get("running"):
            st.success(f"Servidor MCP activo: `{runtime['endpoint']}`")
            st.code(
                json.dumps(
                    {
                        "endpoint": runtime["endpoint"],
                        "health": runtime["health_endpoint"],
                        "transport": "Streamable HTTP / JSON-RPC POST",
                        "write_tools": runtime["write_enabled"],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                language="json",
            )
            st.caption("Use o endpoint `/mcp` na configuração do agente. O endpoint `/health` serve apenas para verificar se o servidor está activo. Não partilhe o token.")
        else:
            st.info("Servidor MCP parado. As configurações ficam guardadas localmente e só são usadas depois de clicar em Guardar e iniciar.")
        st.markdown("**Ferramentas disponibilizadas**")
        st.write("Leitura: estado da pipeline, canais, vídeos e Blueprints. Ferramentas de escrita: criação de lotes de vídeos, apenas quando a opção de escrita estiver activada pelo utilizador.")

    with skill_tab:
        st.subheader("Skill")
        st.caption("A skill anexada pode ser guardada na pasta local do Thunderbolt ou descarregada como ficheiro Markdown. Nenhum dos quatro repositórios externos é copiado para o pacote.")
        skill_cols = st.columns(2)
        with skill_cols[0]:
            if st.button("Guardar skill localmente", type="primary", width="stretch", key="mcp_install_mpt_skill"):
                try:
                    destination = install_skill_locally()
                    st.success(f"Skill guardada em `{destination}`")
                except (FileNotFoundError, OSError) as exc:
                    st.error(f"Não foi possível guardar a skill: {exc}")
        with skill_cols[1]:
            try:
                skill_data = read_packaged_skill()
            except FileNotFoundError:
                skill_data = None
            if skill_data is not None:
                st.download_button(
                    "Descarregar skill .md",
                    data=skill_data,
                    file_name="moneyprinterturbo-video.md",
                    mime="text/markdown",
                    width="stretch",
                    key="mcp_download_mpt_skill",
                )
            else:
                st.warning("A skill ainda não está disponível nesta instalação.")


def render_metadata_cleaner():
    st.title("Limpador de Metadados")
    st.caption("Limpeza e edição de metadados para vídeos de terceiros que já estão prontos.")
    st.warning("Esta área aceita exclusivamente vídeos externos. Vídeos criados na aba Novo vídeo não são listados nem processados aqui.")

    uploaded = st.file_uploader(
        "Subir vídeo de terceiro",
        type=["mp4", "mov", "mkv", "webm", "avi", "m4v", "mpeg", "mpg"],
        help="O sistema cria uma cópia separada em storage/metadata_cleaner/originals e nunca altera o ficheiro original enviado.",
        key="metadata_external_video_upload",
    )
    if uploaded and st.button("Carregar vídeo externo", type="primary", key="metadata_store_external_video"):
        try:
            source, digest = store_external_video(uploaded.name, uploaded.getvalue())
            st.session_state["metadata_external_source"] = str(source)
            st.session_state["metadata_external_digest"] = digest
            st.session_state["metadata_external_name"] = uploaded.name
            st.success("Vídeo externo carregado numa área separada do pipeline de vídeos.")
        except ValueError as exc:
            st.error(str(exc))

    source_value = st.session_state.get("metadata_external_source", "")
    source = Path(source_value) if source_value else None
    if not source or not source.exists():
        st.info("Suba um vídeo de terceiro para começar. Nenhum vídeo produzido pelo sistema é usado nesta página.")
    else:
        st.divider()
        cols = st.columns([2, 1, 1])
        with cols[0]:
            st.write(f"**Vídeo externo:** {st.session_state.get('metadata_external_name', source.name)}")
            st.caption(f"Cópia original preservada em `{source}`")
        with cols[1]:
            st.metric("Tamanho", f"{source.stat().st_size / 1024 / 1024:.1f} MB")
        with cols[2]:
            if st.button("Trocar vídeo", key="metadata_clear_external_source"):
                for key in ["metadata_external_source", "metadata_external_digest", "metadata_external_name", "metadata_last_record"]:
                    st.session_state.pop(key, None)
                st.rerun()

        st.subheader("Metadados para a versão limpa")
        st.caption("A descrição segue o formato do workflow YTB Metadata Generator: preview, links e timestamps. As tags são guardadas sem hashtags.")
        with st.form("metadata_cleaner_form"):
            title = st.text_input("Título", value=source.stem.replace("-", " "))
            preview = st.text_area("Preview / descrição curta", height=90, help="O workflow recomenda uma prévia envolvente de 100 a 200 caracteres, sem hashtags.")
            links = st.text_area("Links", height=90, placeholder="Website: https://exemplo.com\nInstagram: https://instagram.com/exemplo")
            timestamps = st.text_area("Timestamps / capítulos", height=120, placeholder="00:00 Introdução\n00:45 Contexto\n02:10 Conclusão")
            tags = st.text_input("Tags SEO", placeholder="palavra-chave, tema do vídeo, canal dark")
            left, right = st.columns(2)
            with left:
                language = st.text_input("Idioma", value="pt-BR")
                creator = st.text_input("Criador / canal", value="")
                genre = st.text_input("Género", value="")
            with right:
                category_options = ["Não definido", "Film & Animation", "Autos & Vehicles", "Education", "Entertainment", "Howto & Style", "People & Blogs", "Science & Technology", "News & Politics"]
                category = st.selectbox("Categoria para o manifesto de upload", category_options)
                copyright_text = st.text_input("Copyright", value="")
                comment = st.text_input("Comentário interno", value="")
            apply = st.form_submit_button("Limpar e guardar nova versão", type="primary")

        if len(preview.strip()) and not 100 <= len(preview.strip()) <= 200:
            st.caption(f"Prévia: {len(preview.strip())} caracteres. O workflow de referência recomenda entre 100 e 200.")
        if apply:
            selected_tags = normalize_tags(tags)
            description = build_description(preview, links, timestamps)
            metadata = {
                "title": title.strip(),
                "description": description,
                "preview": preview.strip(),
                "links": links.strip(),
                "timestamps": timestamps.strip(),
                "tags": selected_tags,
                "language": language.strip(),
                "creator": creator.strip(),
                "genre": genre.strip(),
                "category": "" if category == "Não definido" else category,
                "copyright": copyright_text.strip(),
                "comment": comment.strip(),
            }
            if not metadata["title"]:
                st.error("Informe um título antes de limpar os metadados.")
            else:
                try:
                    output, run_info = clean_video_metadata(source, metadata, ffmpeg_path=read_json("settings.json", {}).get("ffmpeg_path", ""))
                    record = save_edit_record(source, output, metadata, run_info)
                    st.session_state["metadata_last_record"] = record
                    st.success("Metadados removidos e nova cópia criada. O original continua preservado.")
                except (FileNotFoundError, RuntimeError, ValueError) as exc:
                    st.error(str(exc))

        record = st.session_state.get("metadata_last_record")
        if record and Path(record.get("output_path", "")).exists():
            output = Path(record["output_path"])
            st.subheader("Resultado")
            st.write(f"**Ficheiro limpo:** `{output.name}`")
            mime = "video/mp4" if output.suffix.lower() == ".mp4" else "video/*"
            st.download_button("Descarregar vídeo limpo", data=output.read_bytes(), file_name=output.name, mime=mime, width="stretch", key="metadata_download_video")
            st.download_button("Descarregar manifesto de upload (JSON)", data=metadata_manifest(record), file_name=f"{output.stem}-metadata.json", mime="application/json", width="stretch", key="metadata_download_manifest")
            with st.expander("Pré-visualizar metadados"):
                st.json(record["metadata"])

    st.divider()
    st.subheader("Histórico do Limpador de metadado")
    records = list_edit_records()
    if not records:
        st.caption("Ainda não há edições registadas.")
    for record in records[:10]:
        output = Path(record.get("output_path", ""))
        with st.container(border=True):
            st.write(f"**{record.get('metadata', {}).get('title') or record.get('output_name')}**")
            st.caption(f"Terceiro · {record.get('created_at', '—')} · {record.get('output_name', 'sem saída')}")
            if output.exists():
                st.download_button("Descarregar", data=output.read_bytes(), file_name=output.name, mime="video/*", key=f"metadata_history_{record.get('id')}")


def render_update_youtube_videos():
    st.title("Update Youtube Vídeos")
    st.caption("Actualize título, descrição e thumbnail de vídeos publicados sem alterar o ficheiro de vídeo.")
    settings = read_json("settings.json", {})
    channels = [channel for channel in read_json("channels.json", []) if is_youtube_channel_record(channel) and channel.get("active", True)]
    if not channels:
        st.info("Cadastre pelo menos um canal YouTube activo antes de actualizar vídeos.")
        return
    channel = st.selectbox("Canal YouTube", channels, format_func=lambda item: item.get("name") or item.get("url") or "Canal sem nome", key="update_youtube_channel")
    updater = YouTubeVideoUpdater(settings, STORAGE)
    refresh_key = f"update_youtube_loaded_{channel.get('id', '')}"
    if st.button("Carregar vídeos do canal", type="primary", width="stretch", key="update_youtube_load") or refresh_key not in st.session_state:
        with st.spinner("A carregar vídeos publicados…"):
            result = updater.list_videos(channel, max_results=50)
        st.session_state[refresh_key] = result.data if result.ok else {"error": result.message, "videos": []}
    loaded = st.session_state.get(refresh_key, {})
    if loaded.get("error"):
        st.error(loaded["error"])
        return
    videos = loaded.get("videos", [])
    st.caption(f"{len(videos)} vídeo(s) carregado(s). Operação: `{YOUTUBE_UPDATE_VIDEO}`")
    if not videos:
        st.info("Não foram encontrados vídeos publicados para este canal.")
        return
    tasks = load_video_tasks_for_catalog()
    blueprint = blueprint_for_channel(channel)
    for video in videos:
        video_id = str(video.get("id") or "")
        card_key = f"update_youtube_{video_id}"
        with st.container(border=True):
            top = st.columns([1.2, 3.8, 1.2])
            with top[0]:
                if video.get("thumbnail_url"):
                    st.image(video["thumbnail_url"], width="stretch")
            with top[1]:
                st.markdown(f"**{video.get('title') or 'Sem título'}**")
                st.caption(f"{video.get('published_at') or 'Data indisponível'} · {video.get('privacy_status') or 'estado desconhecido'} · `{video_id}`")
                st.markdown(f"[Abrir no YouTube]({video.get('url')})")
            with top[2]:
                st.caption("Alteração")
                st.write("Metadados")
                st.write("Sem alteração do vídeo")
            title_key, desc_key = f"{card_key}_title", f"{card_key}_description"
            title = st.text_input("Título", value=st.session_state.get(title_key, video.get("title", "")), key=title_key, max_chars=100)
            description = st.text_area("Descrição", value=st.session_state.get(desc_key, video.get("description", "")), key=desc_key, height=150)
            ai_cols = st.columns(3)
            script = next((str(task.get("script") or task.get("video_script") or "") for task in tasks if str(task.get("youtube_video_id") or task.get("video_id") or "") == video_id), "")
            with ai_cols[0]:
                if st.button("Gerar título", key=f"{card_key}_ai_title", width="stretch"):
                    try:
                        generated = generate_video_update_metadata(settings, channel, video, script=script, blueprint=blueprint, mode="title")
                        st.session_state[title_key] = generated["title"]
                        st.rerun()
                    except CreativeGenerationError as exc:
                        st.error(str(exc))
            with ai_cols[1]:
                if st.button("Gerar descrição", key=f"{card_key}_ai_description", width="stretch"):
                    try:
                        generated = generate_video_update_metadata(settings, channel, video, script=script, blueprint=blueprint, mode="description")
                        st.session_state[desc_key] = generated["description"]
                        st.rerun()
                    except CreativeGenerationError as exc:
                        st.error(str(exc))
            with ai_cols[2]:
                if st.button("Gerar título e descrição", key=f"{card_key}_ai_both", width="stretch"):
                    try:
                        generated = generate_video_update_metadata(settings, channel, video, script=script, blueprint=blueprint, mode="both")
                        st.session_state[title_key] = generated.get("title", title)
                        st.session_state[desc_key] = generated.get("description", description)
                        st.rerun()
                    except CreativeGenerationError as exc:
                        st.error(str(exc))
            thumbnail = st.file_uploader("Trocar thumbnail (opcional)", type=["jpg", "jpeg", "png"], key=f"{card_key}_thumbnail")
            if st.button("Actualizar no YouTube", type="primary", key=f"{card_key}_save", width="stretch"):
                thumbnail_path = None
                if thumbnail is not None:
                    thumbnail_path = STORAGE / "youtube_update" / f"{video_id}_{thumbnail.name}"
                    thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
                    thumbnail_path.write_bytes(thumbnail.getvalue())
                result = updater.update_video(video, title=title, description=description, thumbnail_path=thumbnail_path)
                if result.ok:
                    st.success(f"{result.message} Campos: {', '.join(result.data.get('changed') or []) or 'nenhum'}.")
                    st.session_state.pop(refresh_key, None)
                    st.rerun()
                else:
                    st.error(result.message)


def render_pipeline():
    st.title("Pipeline Vídeos")
    st.caption("Estado das filas locais e dependências da cascata")
    queues = read_json("queues.json", {})
    blueprint_count = len(list_blueprint_files())
    cols = st.columns(len(STAGES))
    for col, stage in zip(cols, STAGES):
        with col:
            if stage == "blueprint":
                card("Blueprints", blueprint_count, f"na biblioteca · {len(queues.get(stage, []))} tarefa(s) na fila")
            else:
                card(stage.title(), len(queues.get(stage, [])), "fila")


def render_growth_pages() -> None:
    """Render Growth and its requested real sub-tabs in the page content."""
    st.title("Growth")
    analysis_tab, = render_localized_tabs(["Analise Growth"])
    with analysis_tab:
        growth_subtabs = render_localized_tabs([
            "Growth Youtube", "Growth Tiktok", "Growth Instagram", "Facebook Pages", "Growth Bilibili",
        ])
        growth_renderers = [
            render_growth_youtube, render_growth_tiktok, render_growth_instagram,
            render_growth_facebook_pages, render_growth_bilibili,
        ]
        for tab, renderer in zip(growth_subtabs, growth_renderers):
            with tab:
                renderer()


def render_documentation_pages() -> None:
    """Render Documentação and its requested real sub-tabs in the page content."""
    st.title("Documentação")
    tutorials_tab, = render_localized_tabs(["Tutoriais"])
    with tutorials_tab:
        tutorial_subtabs = render_localized_tabs([
            "Meta", "Supabase", "Kaggle", "Apify", "YouTube Video-Upload Frontend",
            "OAuth do Google", "YouTube Data API Key (Public Data)",
        ])
        tutorial_renderers = [
            render_models_ai_tutorial, render_supabase_tutorial, lambda: render_niche_tutorial("kaggle"),
            lambda: render_niche_tutorial("apify"), render_youtube_frontend_upload_tutorial,
            render_google_oauth_tutorial, render_youtube_data_api_key_tutorial,
        ]
        for tab, renderer in zip(tutorial_subtabs, tutorial_renderers):
            with tab:
                renderer()


def main():
    pipeline_video_items = [
        ("Criação de Vídeos", ":material/add_circle:", "Criação de Vídeos"),
        ("Criação de Shorts", ":material/phone_android:", "Criação de Shorts"),
        ("Backlog Vídeos", ":material/video_library:", "Backlog Vídeos"),
        ("Roteiros", ":material/article:", "Roteiros"),
        ("Thumbnails", ":material/image:", "Thumbnails"),
        ("Upload", ":material/cloud_upload:", "Upload"),
        ("Update Youtube Vídeos", ":material/edit_note:", "Update Youtube Vídeos"),
    ]
    channel_profile_items = [
        ("Canais YouTube", ":material/ondemand_video:", "Canais YouTube"),
        ("Canais Tiktok", ":material/music_video:", "Canais Tiktok"),
        ("Contas Instagram", ":material/share:", "Contas Instagram"),
        ("Facebook Pages", ":material/public:", "Facebook Pages"),
    ]
    blueprint_items = [
        ("Blueprints Youtube", ":material/library_books:", "Blueprints Youtube"),
        ("Thumbnail Blueprints", ":material/image:", "Thumbnail Blueprints"),
        ("Brandings Youtube", ":material/brush:", "Brandings Youtube"),
        ("Prompt-Masters Tiktok", ":material/auto_awesome:", "Prompt-Masters Tiktok"),
        ("Facebook Blueprint", ":material/public:", "Facebook Blueprint"),
    ]
    music_items = [
        ("Criação de Músicas", ":material/music_note:", "Criação de Músicas"),
        ("Music Backlog", ":material/queue_music:", "Music Backlog"),
        ("Vozes Personalizadas", ":material/record_voice_over:", "Vozes Personalizadas"),
        ("Upload Música", ":material/library_music:", "Upload Música"),
    ]
    models_ai_items = [
        ("Personagens", ":material/person:", "Personagens"),
        ("Geração de Conteúdo IA", ":material/auto_awesome:", "Geração de Conteúdo IA"),
        ("Motion Control", ":material/motion_photos_on:", "Motion Control"),
        ("UGC Products", ":material/shopping_bag:", "UGC Products"),
    ]
    growth_analysis_items = [
        ("Growth Youtube", ":material/analytics:", "Growth Youtube"),
        ("Growth Tiktok", ":material/analytics:", "Growth Tiktok"),
        ("Growth Instagram", ":material/analytics:", "Growth Instagram"),
        ("Facebook Pages", ":material/analytics:", "Facebook Pages"),
        ("Growth Bilibili", ":material/analytics:", "Growth Bilibili"),
    ]
    growth_items = growth_analysis_items
    tutorial_items = [
        ("Meta", ":material/menu_book:", "Meta"),
        ("Supabase", ":material/storage:", "Supabase"),
        ("Kaggle", ":material/menu_book:", "Kaggle"),
        ("Apify", ":material/menu_book:", "Apify"),
        ("YouTube Video-Upload Frontend", ":material/video_library:", "YouTube Video-Upload Frontend"),
        ("OAuth do Google", ":material/key:", "OAuth do Google"),
        ("YouTube Data API Key (Public Data)", ":material/vpn_key:", "YouTube Data API Key (Public Data)"),
    ]
    documentation_items = tutorial_items
    settings_items = [
        ("MCP", ":material/hub:", "MCP"),
        ("Notificações", ":material/notifications:", "Notificações"),
        ("Logs", ":material/description:", "Logs"),
        ("Configuração API", ":material/settings:", "Configuração API"),
    ]
    niche_finder_items = [
        ("Niche Finder Kaggle", ":material/search:", "Niche Finder Kaggle"),
        ("Niche Finder Apify", ":material/api:", "Niche Finder Apify"),
    ]
    automation_items = [
        ("Automação Youtube", ":material/schedule:", "Automação Youtube"),
        ("Automação Tiktok", ":material/schedule:", "Automação Tiktok"),
        ("Automação Instagram", ":material/schedule:", "Automação Instagram"),
        ("Automação Facebook", ":material/schedule:", "Automação Facebook"),
        ("Automação Musicas", ":material/schedule:", "Automação Musicas"),
        ("Automação UGC", ":material/schedule:", "Automação UGC"),
        ("Automação Influencer Content", ":material/schedule:", "Automação Influencer Content"),
        ("Automação Bilibili", ":material/schedule:", "Automação Bilibili"),
    ]
    edition_items = [
        ("Limpador de Metadados", ":material/edit_note:", "Limpador de Metadados"),
        ("Cortes", ":material/content_cut:", "Cortes"),
        ("Editor Python", ":material/code:", "Editor Python"),
        ("Download Mídia", ":material/download:", "Download Mídia"),
    ]
    top_pages = [
        ("Início", ":material/home:", "Início"),
        ("Automação", ":material/schedule:", "Automação"),
        ("Niche Finder", ":material/search:", "Niche Finder"),
        ("Canais/Perfis (Vídeos)", ":material/video_library:", "Canais/Perfis (Vídeos)"),
        ("Pipeline Vídeos", ":material/account_tree:", "Pipeline Vídeos"),
        ("Pipeline Música", ":material/music_note:", "Pipeline Música"),
        ("AI Influencers", ":material/smart_toy:", "AI Influencers"),
        ("Blueprints", ":material/library_books:", "Blueprints"),
        ("Edição", ":material/edit:", "Edição"),
        ("Growth", ":material/analytics:", "Growth"),
        ("Documentação", ":material/menu_book:", "Documentação"),
        ("Configurações", ":material/settings:", "Configurações"),
    ]
    groups = {
        "Automação": automation_items,
        "Niche Finder": niche_finder_items,
        "Pipeline Vídeos": pipeline_video_items,
        "AI Influencers": models_ai_items,
        "Blueprints": blueprint_items,
        "Canais/Perfis (Vídeos)": channel_profile_items,
        "Pipeline Música": music_items,
        "Edição": edition_items,
        "Growth": growth_items,
        "Analise Growth": growth_analysis_items,
        "Documentação": documentation_items,
        "Tutoriais": tutorial_items,
        "Configurações": settings_items,
    }
    nav_paths = {
        "Início": "/inicio", "Automação": "/automacao", "Automação Youtube": "/automacao/youtube", "Automação Tiktok": "/automacao/tiktok", "Automação Instagram": "/automacao/instagram", "Automação Facebook": "/automacao/facebook", "Automação Musicas": "/automacao/musicas", "Automação UGC": "/automacao/ugc", "Automação Influencer Content": "/automacao/influencer-content", "Automação Bilibili": "/automacao/bilibili",
        "Niche Finder": "/niche-finder", "Niche Finder Kaggle": "/niche-finder/kaggle", "Niche Finder Apify": "/niche-finder/apify",
        "Pipeline Vídeos": "/pipeline-videos", "Criação de Vídeos": "/pipeline-videos/criacao", "Criação de Shorts": "/pipeline-videos/shorts", "Backlog Vídeos": "/pipeline-videos/backlog", "Roteiros": "/pipeline-videos/roteiros", "Thumbnails": "/pipeline-videos/thumbnails", "Upload": "/pipeline-videos/upload", "Update Youtube Vídeos": "/pipeline-videos/update-youtube",
        "Pipeline Música": "/pipeline-musica", "Criação de Músicas": "/pipeline-musica/criacao", "Music Backlog": "/pipeline-musica/backlog", "Vozes Personalizadas": "/pipeline-musica/vozes-personalizadas", "Upload Música": "/pipeline-musica/upload",
        "Canais/Perfis (Vídeos)": "/canais-perfis-videos", "Canais YouTube": "/canais-perfis-videos/canais-youtube", "Canais Tiktok": "/canais-perfis-videos/canais-tiktok", "Contas Instagram": "/canais-perfis-videos/contas-instagram", "Facebook Pages": "/canais-perfis-videos/facebook-pages", "Blueprints Youtube": "/blueprints/youtube", "Thumbnail Blueprints": "/blueprints/thumbnails", "Brandings Youtube": "/blueprints/brandings-youtube", "Prompt-Masters Tiktok": "/blueprints/prompt-masters-tiktok", "Facebook Blueprint": "/blueprints/facebook",
        "AI Influencers": "/ai-influencers", "Personagens": "/ai-influencers/personagens", "Geração de Conteúdo IA": "/ai-influencers/geracao-conteudo", "Motion Control": "/ai-influencers/motion-control", "UGC Products": "/ai-influencers/ugc-products",
        "Edição": "/edicao", "Limpador de Metadados": "/edicao/limpador-metadados", "Cortes": "/edicao/cortes", "Editor Python": "/edicao/editor-python", "Download Mídia": "/edicao/download-midia",
        "Growth": "/growth", "Analise Growth": "/growth/analise", "Growth Youtube": "/growth/analise/youtube", "Growth Tiktok": "/growth/analise/tiktok", "Growth Instagram": "/growth/analise/instagram", "Facebook Pages": "/growth/analise/facebook-pages", "Growth Bilibili": "/growth/analise/bilibili",
        "Documentação": "/documentacao", "Tutoriais": "/documentacao/tutoriais", "Meta": "/documentacao/tutoriais/meta", "Supabase": "/documentacao/tutoriais/supabase", "Kaggle": "/documentacao/tutoriais/kaggle", "Apify": "/documentacao/tutoriais/apify", "YouTube Video-Upload Frontend": "/documentacao/tutoriais/youtube-video-upload-frontend", "OAuth do Google": "/documentacao/tutoriais/oauth-google", "YouTube Data API Key (Public Data)": "/documentacao/tutoriais/youtube-data-api-key",
        "Configurações": "/configuracoes", "MCP": "/configuracoes/mcp", "Notificações": "/configuracoes/notificacoes", "Logs": "/configuracoes/logs", "Configuração API": "/configuracoes/api",
    }

    aliases = {
        "Dashboard": "Início",
        "Novo vídeo": "Criação de Vídeos",
        "Vídeos": "Backlog Vídeos",
        "Limpador de metadado": "Limpador de Metadados",
        "Pipeline": "Pipeline Vídeos",
        "Música": "Pipeline Música",
        "Pipeline TikTok": "Canais/Perfis (Vídeos)",
        "Canais e Perfis de Vídeos": "Canais/Perfis (Vídeos)",
        "Prompts Master": "Prompt-Masters Tiktok",
        "Prompt Masters": "Prompt-Masters Tiktok",
        "Canais": "Canais YouTube",
        "Canais Youtube": "Canais YouTube",
        "Configurações Técnicas": "Configuração API",
        "Models AI": "AI Influencers",
        "Contas Google/YouTube — canais em lote": "Configuração API",
        "Contas Google": "Configuração API",
        "Tutorial Meta": "Meta",
        "Tutorial Supabase": "Supabase",
        "Tutorial Kaggle": "Kaggle",
        "Tutorial Apify": "Apify",
        "Tutorial YouTube Video-Upload Frontend": "YouTube Video-Upload Frontend",
        "Tutorial OAuth do Google": "OAuth do Google",
        "Tutorial YouTube Data API Key (Public Data)": "YouTube Data API Key (Public Data)",
        "Analista Growth Youtube": "Growth Youtube",
        "Analista Growth Tiktok": "Growth Tiktok",
        "Analista Growth Instagram": "Growth Instagram",
        "Analista Facebook Pages": "Facebook Pages",
        "Analista Bilibili": "Growth",
        "Analise Growth": "Growth",
        "Growth Youtube": "Growth",
        "Growth Tiktok": "Growth",
        "Growth Instagram": "Growth",
        "Growth Bilibili": "Growth",
        "Tutoriais": "Documentação",
        "Meta": "Documentação",
        "Supabase": "Documentação",
        "Kaggle": "Documentação",
        "Apify": "Documentação",
        "YouTube Video-Upload Frontend": "Documentação",
        "OAuth do Google": "Documentação",
        "YouTube Data API Key (Public Data)": "Documentação",
    }
    all_children = [item for items in groups.values() for item in items]
    all_children.extend(item for item in tutorial_items if item not in all_children)
    valid_targets = {item[0] for item in top_pages + all_children}
    # Session state is reset by a browser refresh or an application update. Keep
    # the canonical page in the URL so the open section can be restored.
    query_page = str(st.query_params.get("page") or "").strip()
    stored_page = query_page or str(st.session_state.get("page", "Início"))
    current_page = aliases.get(stored_page, stored_page)
    if current_page not in valid_targets:
        current_page = "Início"
    st.session_state["page"] = current_page
    if str(st.query_params.get("page") or "") != current_page:
        st.query_params["page"] = current_page
    ui_language = current_ui_language()
    current_path = nav_paths.get(current_page, "/inicio")

    def is_nav_item_active(target: str) -> bool:
        """Activate one item only when its own path equals the current path."""
        return current_path == nav_paths.get(target)

    if current_page == "Início":
        render_home_update_controls()
    render_ui_language_picker(ui_language)

    def navigate(target: str):
        st.session_state["page"] = target
        st.query_params["page"] = target
        st.rerun()

    def render_nav_button(target: str, icon: str, label: str, scope: str):
        display_label = ui_text(label, ui_language)
        if st.button(display_label, key=f"nav_{scope}_{target}", icon=icon, width="stretch", type="primary" if is_nav_item_active(target) else "secondary"):
            navigate(target)

    with st.sidebar:
        version_markup = f'<span class="tb-brand-version">{APP_VERSION_LABEL}</span>' if APP_VERSION_LABEL else ""
        st.markdown(f'<div class="tb-brand"><span class="tb-brand-name">Thunderbolt</span>{version_markup}</div>', unsafe_allow_html=True)
        def has_active_descendant(target: str) -> bool:
            children = groups.get(target, [])
            for child_target, _child_icon, _child_label in children:
                if current_page == child_target or has_active_descendant(child_target):
                    return True
            return False

        def render_nav_children(parent: str, children: list[tuple[str, str, str]]):
            for child_target, child_icon, child_label in children:
                nested = groups.get(child_target)
                if nested is None:
                    render_nav_button(child_target, child_icon, child_label, parent)
                else:
                    with st.expander(ui_text(child_label, ui_language), expanded=has_active_descendant(child_target), icon=child_icon):
                        render_nav_children(child_target, nested)

        for target, icon, label in top_pages:
            children = groups.get(target)
            if children is None:
                render_nav_button(target, icon, label, "top")
                continue
            with st.expander(ui_text(label, ui_language), expanded=has_active_descendant(target), icon=icon):
                render_nav_children(target, children)

    renderers = {
        "Início": render_dashboard,
        "Pipeline Vídeos": render_pipeline,
        "Criação de Vídeos": render_new_video,
        "Criação de Shorts": lambda: render_new_video("Criação de Shorts", "new_shorts", channel_platform="tiktok", fixed_aspect_ratio="Portrait 9:16"),
        "Backlog Vídeos": render_videos,
        "Criação de Músicas": render_music_creation,
        "Music Backlog": render_music_backlog,
        "Vozes Personalizadas": render_custom_music_voices,
        "Upload Música": render_music_upload,
        "Roteiros": render_scripts,
        "Thumbnails": render_thumbnails,
        "Upload": render_upload,
        "Update Youtube Vídeos": render_update_youtube_videos,
        "Blueprints Youtube": render_blueprints,
        "Thumbnail Blueprints": render_thumbnail_blueprints,
        "Brandings Youtube": render_youtube_brandings,
        "Prompt-Masters Tiktok": render_tiktok_prompt_masters,
        "Facebook Blueprint": render_facebook_blueprints,
        "Canais YouTube": render_channels,
        "Canais Tiktok": render_tiktok_channels,
        "Facebook Pages": render_facebook_pages,
        "Automação Youtube": render_automation,
        "Automação Tiktok": render_tiktok_automation,
        "Automação Instagram": lambda: render_instagram_automation(read_json("settings.json", {})),
        "Automação Facebook": render_facebook_automation,
        "Automação Musicas": lambda: None,
        "Automação UGC": lambda: None,
        "Automação Influencer Content": lambda: None,
        "Automação Bilibili": render_bilibili_automation,
        "Niche Finder Kaggle": render_niche_finder,
        "Kaggle": lambda: render_niche_tutorial("kaggle"),
        "Niche Finder Apify": render_niche_finder_apify,
        "Apify": lambda: render_niche_tutorial("apify"),
        "Edição": lambda: render_edit_placeholder("Edição", "Seleccione uma das abas de edição no menu expansível."),
        "Limpador de Metadados": render_metadata_cleaner,
        "Cortes": render_cuts,
        "Editor Python": render_python_editor,
        "Download Mídia": render_media_download,
        "AI Influencers": lambda: render_edit_placeholder("AI Influencers", "Seleccione uma das abas AI Influencers no menu expansível."),
        "Personagens": lambda: render_ai_influencer_characters(
            read_json("settings.json", {}),
            language_options=VIDEO_LANGUAGE_SELECTION_OPTIONS,
            language_formatter=video_language_label,
            language_normalizer=normalize_video_language,
        ),
        "Geração de Conteúdo IA": lambda: render_ai_influencer_content(read_json("settings.json", {})),
        "Motion Control": lambda: render_motion_control(read_json("settings.json", {})),
        "UGC Products": lambda: render_ugc_products(read_json("settings.json", {})),
        "Contas Instagram": lambda: render_social_networks(read_json("settings.json", {})),
        "Growth": lambda: render_edit_placeholder("Growth", "Seleccione uma subaba de Growth."),
        "Growth Youtube": render_growth_youtube,
        "Growth Tiktok": render_growth_tiktok,
        "Growth Instagram": render_growth_instagram,
        "Facebook Pages": render_growth_facebook_pages,
        "Growth Bilibili": render_growth_bilibili,
        "Documentação": lambda: render_edit_placeholder("Documentação", "Seleccione uma subaba de documentação."),
        "Meta": render_models_ai_tutorial,
        "Supabase": render_supabase_tutorial,
        "Kaggle": lambda: render_niche_tutorial("kaggle"),
        "Apify": lambda: render_niche_tutorial("apify"),
        "YouTube Video-Upload Frontend": render_youtube_frontend_upload_tutorial,
        "OAuth do Google": render_google_oauth_tutorial,
        "YouTube Data API Key (Public Data)": render_youtube_data_api_key_tutorial,
        "Configurações": lambda: render_edit_placeholder("Configurações", "Seleccione uma opção no menu expansível."),
        "MCP": render_mcp,
        "Contas Google": render_google_accounts,
        "Configuração API": render_settings,
        "Notificações": render_notifications,
        "Logs": render_logs,
    }
    renderers.get(current_page, render_dashboard)()

if __name__ == "__main__":
    main()
