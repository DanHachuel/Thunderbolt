from __future__ import annotations

import hashlib
import json
import re
import os
from datetime import date, datetime
import sys
import uuid
from pathlib import Path
from typing import Any

import requests
import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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

from hermes_ui.domain import STAGES, create_batch, create_channel, create_tasks_for_batch, delete_channel, pipeline_summary, set_channel_defaults, transition_task, update_channel, update_channel_video
from hermes_ui.automation_worker import load_worker_status
from hermes_ui.storage import BLUEPRINTS, DEFAULT_LLM_PROVIDER, MEDIA_DOWNLOADS, STORAGE, TIKTOK_PROMPT_MASTERS, ensure_storage, get_display_name, list_blueprint_files, list_prompt_master_files, load_blueprint_file, load_prompt_master_file, now, read_json, set_display_name, write_json
from app.modules.niche_finder.apify import ApifyError, DEFAULT_ACTOR_ID, abort_actor_run, build_actor_input, get_dataset_items, normalize_video_items, start_actor_run, wait_for_actor_run
from app.modules.niche_finder.core import NicheAnalysisError, run_niche_analysis
from app.modules.niche_finder.data_loader import DatasetError, download_kaggle_dataset
from app.modules.niche_finder.summarizer import summarize_items
from hermes_ui.blueprints import create_blueprint_from_link, list_branding_files, save_generated_blueprint
from hermes_ui.metadata_cleaner import build_description, clean_video_metadata, list_edit_records, metadata_manifest, normalize_tags, save_edit_record, store_external_video
from hermes_ui.python_editor import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS, PythonEditorError, change_speed, editor_manifest, extract_audio, list_edit_records as list_python_editor_records, list_generated_videos, list_scripts, list_video_files, read_script, remove_audio, replace_audio, resize_video, save_edit_record as save_python_editor_record, save_script, store_uploaded_asset, trim_video
from hermes_ui.cuts import CutsError, download_direct_video_url, generate_clips, list_generated_videos as list_cut_generated_videos, list_runs as list_cut_runs, list_video_files as list_cut_video_files, manifest_bytes as cut_manifest_bytes, store_uploaded_video, zip_run as zip_cut_run
from hermes_ui.mcp import detect_local_service, install_skill_locally, load_integrations, load_server_config, read_packaged_skill, save_server_config, update_integration
from hermes_ui.mcp_server import server_status, start_server, stop_server
from hermes_ui.material_sources import material_api_keys, material_source_catalog, selected_material_source, update_material_api_keys
from hermes_ui.llm_providers import LLM_CARDS_KEY, LLM_ACTIVE_CARD_KEY, LLM_PROVIDER_CATALOG, apply_llm_cards_to_settings, ensure_llm_provider_cards, new_llm_card, normalize_llm_card, provider_definition, test_llm_provider_card, stamp_test_result
from hermes_ui.music import list_music_files, materialize_suno_audio, request_suno_generation, store_music_file
from hermes_ui.media_downloader import AUDIO_FORMATS, VIDEO_CONTAINERS, VIDEO_QUALITY_OPTIONS, MediaDownloadError, build_download_options, clear_media_download_history, dependency_status, download_media, list_media_downloads, media_download_file
from hermes_ui.notifications import clear_notifications, list_notifications, mark_all_notifications_read, mark_notification_read, notification_event_catalog, notification_preferences, record_notification, reconcile_persisted_notifications, save_notification_preferences, unread_notification_count
from hermes_ui.languages import LANGUAGE_CODES, LANGUAGE_FLAG_DATA_URIS, language_code, language_label, ui_language_menu_label, ui_text, video_language_label, video_language_options

from hermes_ui.script_documents import list_script_documents, read_script_document, save_script_document, script_storage_path
from hermes_ui.script_generation import generate_script_document
from hermes_ui.voice_preview import DEFAULT_SAMPLE, load_preview_file, synthesize_preview
from hermes_ui.thumbnail_generation import ThumbnailGenerationError, generate_thumbnail_image
from hermes_ui.thumbnail_blueprints import thumbnail_aspect_ratio_for_channel_task
from hermes_ui.creative_generation import CreativeGenerationError, generate_creative_package, generate_topic_for_channel, generate_video_keywords
from integrations.platforms import IntegrationResult, TikTokAdapter, YouTubeAdapter, fetch_channel_videos_public
from integrations.tiktok_public import fetch_public_tiktok_profile, normalize_tiktok_reference
from integrations.postiz import PostizAdapter
from integrations.upload_post import UploadPostAdapter, UPLOAD_POST_PLATFORM_OPTIONS, normalize_upload_post_platforms
from integrations.upload_routing import OFFICIAL_DAILY_LIMIT, official_upload_count, upload_with_default_route
from integrations.youtube_direct_upload import YouTubeDirectUploader
from integrations.youtube_direct_credentials import delete_credentials_document, direct_account_status, document_status, ensure_credentials_document, load_credentials_document, merge_credentials_document, parse_credentials_document, save_credentials_document, update_credentials_document_session_info
from integrations.youtube_batch import account_key as youtube_batch_account_key, account_status as youtube_batch_account_status, authorize_account as authorize_youtube_batch_account, delete_account_token as delete_youtube_batch_token, list_my_channels as list_youtube_batch_channels, loopback_redirect_uri
from integrations.local_runtime import MoneyPrinterRuntime
from integrations.moneyprinter_config import sync_moneyprinter_config
from integrations.openai_model_discovery import DEFAULT_NVIDIA_NIM_BASE_URL

DEFAULT_UI_LANGUAGE = "en"

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

WIDE_STYLE_OPTIONS = ["Pexels/Pixabay", "full_ia", "Apenas Música"]

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
# A UI acrescenta os dez códigos canónicos do MoneyPrinterTurbo com bandeiras.
VIDEO_LANGUAGE_SELECTION_OPTIONS = ["music", *LANGUAGE_CODES, *[item for item in VIDEO_LANGUAGE_OPTIONS if item not in {"01 – Inglês", "06 – Alemão", "15 – Italiano", "29 – Turco", "31 – Russo", "36 – Português (Brasil)", "39 – Mandarim", "41 – Espanhol (LatAm)", "42 – Vietnamita", "44 – Indonésio"}]]

VIDEO_FORMAT_OPTIONS = ["wide", "shorts", "music"]
VIDEO_CONCATENATION_OPTIONS = ["Random Concatenation (Recommended)", "Sequential Concatenation"]
VIDEO_TRANSITION_OPTIONS = ["None", "Fade", "Dissolve"]
VIDEO_ENCODER_OPTIONS = ["Default (Recommended)", "H.264", "H.265"]
VOICEOVER_MODE_OPTIONS = ["Auto", "Upload", "None"]
VOICEOVER_SERVICE_OPTIONS = ["Azure TTS V1"]
VOICEOVER_VOLUME_OPTIONS = ["20%", "40%", "60%", "80%", "100%"]
VOICEOVER_SPEED_OPTIONS = ["0.5x", "0.75x", "1.0x", "1.25x", "1.5x", "2.0x"]
BACKGROUND_MUSIC_SOURCE_OPTIONS = ["Ficheiro existente", "Carregar ficheiro", "Criar via Suno API", "Random Background Music", "Sem música"]
BACKGROUND_MUSIC_VOLUME_OPTIONS = ["0%", "10%", "20%", "30%", "50%", "75%", "100%"]
SUBTITLE_FONT_OPTIONS = ["MicrosoftYaHeiBold.ttc", "Arial.ttf", "DejaVuSans.ttf"]
SUBTITLE_POSITION_OPTIONS = ["Bottom (Recommended)", "Top", "Center"]

ensure_storage()
st.set_page_config(page_title="Thunderbolt", page_icon="T", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
/*
   MoneyPrinterTurbo deixa a maior parte das cores a cargo do tema nativo do
   Streamlit. O Thunderbolt segue o mesmo princípio: componentes próprios usam
   currentColor/color-mix e nunca uma paleta escura fixa.
*/
:root { --tb-accent:#35a7ff; --tb-gold:#c59b55; }
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
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] { background:rgba(128,128,128,.14); color:inherit; border-color:rgba(128,128,128,.30); }
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] { background:color-mix(in srgb, currentColor 12%, transparent); color:inherit; border-color:color-mix(in srgb, currentColor 22%, transparent); }
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"]:hover { background:rgba(128,128,128,.20); color:inherit; }
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"]:hover { background:color-mix(in srgb, currentColor 18%, transparent); color:inherit; }
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


def save_video_language(value: str) -> str:
    normalized = "music" if str(value or "").strip().casefold() == "music" else language_code(value)
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
    if summary["name"] == "SEM BLUEPRINT CONFIGURADO":
        st.warning("**SEM BLUEPRINT CONFIGURADO** · configure um Blueprint padrão na aba Canais.")
    elif compact:
        st.caption(f"**Blueprint:** {summary['name']} · **Voz:** {voice}")
    else:
        st.info(f"**Blueprint utilizado pelo canal:** {summary['name']} · `{summary['id']}` · **Voz:** {voice}")


def creative_payload_from_result(channel: dict, topic: str, creative: dict, topic_source: str = "manual") -> dict[str, Any]:
    variant = creative.get("thumbnail_variant") or {}
    return {
        "topic": topic.strip(),
        "topic_source": topic_source,
        "title": str(creative.get("title") or topic).strip(),
        "title_candidates": creative.get("title_candidates") or [],
        "thumbnail_variant": variant,
        "thumbnail_variants": creative.get("thumbnail_variants") or [],
        "thumbnail_prompt": str(variant.get("image_prompt") or ""),
        "thumbnail_text": str(variant.get("overlay_text") or ""),
        "thumbnail_status": str(creative.get("thumbnail_status") or "prompt_ready"),
        "blueprint_id": str(channel.get("default_blueprint_id") or channel.get("blueprint_id") or ""),
        "blueprint_name": str(channel_blueprint_summary(channel).get("name") or "SEM BLUEPRINT CONFIGURADO"),
        "voice": str(channel.get("default_voice") or channel.get("voice") or ""),
        "ai_generation": {"creative": creative},
    }


def generate_topic_for_ui(settings: dict[str, Any], channel: dict, user_context: str = "") -> dict[str, Any]:
    return generate_topic_for_channel(settings, channel, blueprint_for_channel(channel), user_context=user_context)


def generate_video_content_for_ui(
    settings: dict[str, Any],
    channel: dict,
    subject: str,
    language: str,
    generation_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate the subject, script and English keywords in one MoneyPrinter-style action."""
    subject = str(subject or "").strip()
    topic_result: dict[str, Any] | None = None
    if not subject:
        topic_result = generate_topic_for_ui(settings, channel)
        subject = str(topic_result.get("topic") or "").strip()
    if not subject:
        raise CreativeGenerationError("A IA não devolveu um Video Subject válido.")

    blueprint = blueprint_for_channel(channel)
    script_result = generate_script_document(
        settings,
        document_type="Roteiro de vídeo",
        title=subject,
        brief=subject,
        language=str(language or channel.get("language") or "Português"),
        channel=channel,
        blueprint=blueprint,
        structure_notes=str((generation_settings or {}).get("script_structure_notes") or ""),
        generation_settings=generation_settings or {},
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


def _generate_video_content_callback(prefix: str, channel: dict, fallback_language: str) -> None:
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
        )
        st.session_state[f"{prefix}_video_subject"] = result["topic"]
        st.session_state[f"{prefix}_video_script"] = result["script"]
        st.session_state[f"{prefix}_video_keywords"] = ", ".join(result["keywords"])
        st.session_state["new_video_topic"] = result["topic"]
        st.session_state["new_video_topic_meta"] = result.get("topic_result") or {
            "topic": result["topic"],
            "topic_source": result.get("topic_source", "manual"),
        }
        # A subject change invalidates a previously generated title/thumbnail package.
        st.session_state.pop("new_video_creative_payload", None)
        st.session_state[f"{prefix}_generate_content_notice"] = "Tema, roteiro e palavras-chave gerados com IA."
        st.session_state.pop(f"{prefix}_generate_content_error", None)
    except CreativeGenerationError as exc:
        st.session_state[f"{prefix}_generate_content_error"] = str(exc)
        st.session_state.pop(f"{prefix}_generate_content_notice", None)


def _video_topic_source(subject: str) -> str:
    meta = st.session_state.get("new_video_topic_meta") or {}
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


def valid_hhmm(value: str) -> bool:
    return bool(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(value or "").strip()))


def voice_catalog(current: str = "") -> list[str]:
    voices = [""]
    voice_file = ROOT / "integrations" / "data" / "azure_voices.json"
    try:
        voice_data = json.loads(voice_file.read_text(encoding="utf-8"))
        voices.extend(f"{item.get('name', '')}-{item.get('gender', '')}" for item in voice_data if item.get("name"))
    except (OSError, json.JSONDecodeError):
        pass
    for candidate in (current, "en-US-AriaNeural-Female", "pt-BR-FranciscaNeural-Female", "pt-BR-AntonioNeural-Male"):
        if candidate and candidate not in voices:
            voices.append(candidate)
    return voices


def render_video_generation_settings(
    prefix: str,
    *,
    current_language: str = "",
    channel: dict[str, Any] | None = None,
    generate_content_callback: Any | None = None,
) -> dict[str, Any]:
    """Render the shared MoneyPrinter-style settings and return a serializable payload."""
    settings: dict[str, Any] = {}
    st.markdown("### Video Subject Settings")
    subject_cols = st.columns(2)
    with subject_cols[0]:
        settings["video_subject"] = st.text_input(
            "Video Subject",
            value=str(st.session_state.get(f"{prefix}_video_subject", "")),
            key=f"{prefix}_video_subject",
            placeholder="Ex.: How AI is changing everyday life",
        )
        normalized_current_language = "music" if str(current_language or "").strip().casefold() in {"music", "00 – apenas música de fundo (sem falas)", "00 - apenas música de fundo (sem falas)"} else language_code(current_language)
        settings["script_language"] = st.selectbox(
            "Script Language",
            VIDEO_LANGUAGE_SELECTION_OPTIONS,
            index=VIDEO_LANGUAGE_SELECTION_OPTIONS.index(normalized_current_language) if normalized_current_language in VIDEO_LANGUAGE_SELECTION_OPTIONS else 0,
            format_func=video_language_label,
            key=f"{prefix}_script_language",
        )
    with subject_cols[1]:
        with st.expander("Advanced Script Settings", expanded=False):
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

    st.markdown("### Video Settings")
    video_cols = st.columns(2)
    with video_cols[0]:
        settings["video_source"] = st.selectbox("Video Source", WIDE_STYLE_OPTIONS, key=f"{prefix}_video_source")
        if settings["video_source"] == "full_ia":
            settings["style_ia"] = st.selectbox("Estilo IA", AI_STYLE_OPTIONS, key=f"{prefix}_style_ia")
        else:
            settings["style_ia"] = ""
        settings["video_format"] = st.selectbox("Formato", VIDEO_FORMAT_OPTIONS, key=f"{prefix}_video_format")
        settings["video_concatenation_mode"] = st.selectbox("Video Concatenation Mode", VIDEO_CONCATENATION_OPTIONS, key=f"{prefix}_video_concatenation")
        settings["match_visuals_to_script_order"] = st.checkbox("Match Visuals to Script Order", value=False, key=f"{prefix}_match_visuals")
        settings["video_transition_mode"] = st.selectbox("Video Transition Mode", VIDEO_TRANSITION_OPTIONS, key=f"{prefix}_video_transition")
    with video_cols[1]:
        settings["video_aspect_ratio"] = st.selectbox("Video Aspect Ratio", ["Portrait 9:16", "Landscape 16:9", "Square 1:1"], key=f"{prefix}_video_aspect_ratio")
        settings["maximum_clip_duration"] = st.selectbox("Maximum Clip Duration (seconds)", [3, 5, 8, 10, 15], key=f"{prefix}_maximum_clip_duration")
        settings["videos_per_run"] = st.selectbox("Videos per Run", list(range(1, 11)), key=f"{prefix}_videos_per_run")
        settings["video_encoder"] = st.selectbox("Video Encoder", VIDEO_ENCODER_OPTIONS, key=f"{prefix}_video_encoder")

    st.markdown("### Audio Settings")
    audio_cols = st.columns(2)
    with audio_cols[0]:
        settings["voiceover_mode"] = st.radio("Voiceover Mode", VOICEOVER_MODE_OPTIONS, horizontal=True, key=f"{prefix}_voiceover_mode")
        settings["voiceover_service"] = st.selectbox("Voiceover Service", VOICEOVER_SERVICE_OPTIONS, key=f"{prefix}_voiceover_service")
        if channel is not None:
            channel_id = str(channel.get("id") or channel.get("name") or "")
            channel_voice = str(channel.get("default_voice") or channel.get("voice") or "").strip()
            channel_state_key = f"{prefix}_voice_channel_id"
            if st.session_state.get(channel_state_key) != channel_id:
                st.session_state[f"{prefix}_voice"] = channel_voice
                st.session_state[channel_state_key] = channel_id
        current_voice = str(st.session_state.get(f"{prefix}_voice", ""))
        voice_options = voice_catalog(current_voice)
        settings["voice"] = st.selectbox("Voice (match script language)", voice_options, format_func=lambda value: value or "Sem voz seleccionada", key=f"{prefix}_voice")
        volume_speed_cols = st.columns(2)
        with volume_speed_cols[0]:
            settings["voiceover_volume"] = st.selectbox("Voiceover Volume", VOICEOVER_VOLUME_OPTIONS, index=VOICEOVER_VOLUME_OPTIONS.index("100%"), key=f"{prefix}_voiceover_volume")
        with volume_speed_cols[1]:
            settings["voiceover_speed"] = st.selectbox("Voiceover Speed", VOICEOVER_SPEED_OPTIONS, index=VOICEOVER_SPEED_OPTIONS.index("1.0x"), key=f"{prefix}_voiceover_speed")
        st.button("Preview Voice", key=f"{prefix}_preview_voice", disabled=True, help="A pré-visualização de voz será ligada ao provider configurado.")
    with audio_cols[1]:
        settings["background_music_source"] = st.selectbox("Background Music Source", BACKGROUND_MUSIC_SOURCE_OPTIONS, index=3, key=f"{prefix}_background_music_source")
        settings["background_music_volume"] = st.selectbox("Background Music Volume", BACKGROUND_MUSIC_VOLUME_OPTIONS, index=2, key=f"{prefix}_background_music_volume")

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
    st.markdown("### Últimos 10 vídeos publicados")
    st.caption("A lista usa o feed público do YouTube, sem Data API Key. Pode actualizar manualmente e editar os metadados locais apresentados.")
    refresh_col, view_col = st.columns([1.4, 1])
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
    with view_col:
        view_mode = st.radio("Vista", ["Lista", "Kanban"], horizontal=True, key=f"channel_videos_view_{channel_id}", label_visibility="collapsed")
    videos = st.session_state.get(f"channel_videos_{channel_id}") or channel_videos_for(channel, limit=10)
    if not videos:
        st.info("Ainda não existem vídeos sincronizados. Clique em **Actualizar últimos 10 vídeos**.")
        return
    if view_mode == "Lista":
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
    else:
        columns = st.columns(4)
        groups = [("planejamento", "Planejamento"), ("produção", "Produção"), ("finalizado", "Finalizado"), ("publicado", "Agendado/Publicado")]
        for column, (status_key, label) in zip(columns, groups):
            with column:
                st.markdown(f"**{label}**")
                group = [video for video in videos[:10] if str(video.get("status") or "publicado").lower() in ({status_key} if status_key != "publicado" else {"publicado", "agendado"})]
                if not group:
                    st.caption("Sem vídeos")
                for video in group:
                    with st.container(border=True):
                        st.write(f"**{video.get('title', 'Vídeo sem título')}**")
                        st.caption(video.get("published_at") or "Sem data")
                        render_channel_video_editor(video, channel_id)


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
            edited_language = st.selectbox("Idioma", list(LANGUAGE_CODES), index=list(LANGUAGE_CODES).index(language_code(channel.get("language") or "pt")), format_func=language_label)
            style_options = ["Pexels/Pixabay", "full_ia", "Apenas Música"]
            style_value = {"pexels": "Pexels/Pixabay", "music": "Apenas Música"}.get(str(channel.get("style_wide") or "pexels"), str(channel.get("style_wide") or "Pexels/Pixabay"))
            edited_style = st.selectbox("Estilo wide", style_options, index=style_options.index(style_value) if style_value in style_options else 0)
            edited_niche = st.text_input("Canais de Referência / Nicho", value=str(channel.get("niche") or channel_niche_label(channel) if channel_niche_label(channel) != "SEM NICHO CONFIGURADO" else "") )
            edited_subscribers = st.text_input("Inscritos", value=_channel_count_text(channel.get("subscriber_count")))
            edited_videos = st.text_input("Vídeos", value=_channel_count_text(channel.get("video_count")))
            edited_views = st.text_input("Visualizações", value=_channel_count_text(channel.get("view_count")))
        with edit_cols[1]:
            edited_blueprint = st.selectbox("Prompts do Canal", blueprint_ids, index=blueprint_ids.index(current_blueprint) if current_blueprint in blueprint_ids else 0, format_func=lambda item: blueprint_labels.get(item, item or "Sem Blueprint padrão"))
            edited_voice = st.selectbox("Narrador", voice_options, index=voice_options.index(current_voice) if current_voice in voice_options else 0, format_func=lambda item: item or "Sem voz padrão")
            edited_account = st.selectbox("Conta Google para Upload directo", account_ids, index=account_ids.index(current_account) if current_account in account_ids else 0, format_func=lambda item: youtube_account_labels.get(item, item or "Sem conta Google associada"))
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
                "style_wide": {"Pexels/Pixabay": "pexels", "Apenas Música": "music"}.get(edited_style, edited_style),
                "niche": edited_niche.strip(), "reference_channels": [item.strip() for item in re.split(r"[,|]", edited_niche) if item.strip()],
                "default_blueprint_id": edited_blueprint.strip(), "blueprint_id": edited_blueprint.strip(),
                "default_voice": edited_voice.strip(), "voice": edited_voice.strip(),
                "google_account_id": edited_account.strip(), "google_account_email": str(youtube_accounts_by_id.get(edited_account, {}).get("email", "")),
                "description": edited_description.strip(), "automation_on": bool(edited_automation), "automation_time": edited_time.strip(),
                "subscriber_count": _channel_count_value(edited_subscribers) or None, "video_count": _channel_count_value(edited_videos) or None, "view_count": _channel_count_value(edited_views) or None,
            })
            st.session_state.pop(f"edit_channel_{channel_id}", None)
            st.success("Canal actualizado.")
            st.rerun()


def _channel_count_value(value: Any) -> int:
    """Parse counts entered with Portuguese or English thousand separators."""
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
    parsed = _channel_count_value(value)
    return f"{parsed:,}".replace(",", ".") if value not in (None, "") else "—"


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
    blueprint_tab, branding_tab = render_localized_tabs(["Blueprints", "Brandings"])
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
        if uploaded and st.button("Guardar blueprint JSON", type="secondary"):
            try:
                data = json.loads(uploaded.getvalue().decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("O JSON raiz deve ser um objecto.")
                safe_name = Path(uploaded.name).stem.replace(" ", "-") + ".json"
                destination = BLUEPRINTS / safe_name
                if destination.exists() and not st.checkbox("Confirmar substituição", key="confirm_blueprint_replace"):
                    st.warning("O ficheiro já existe. Confirme a substituição.")
                else:
                    destination.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    with branding_tab:
        st.subheader("Brandings completos")
        st.caption(f"Brandings gerados ou importados da pasta `{BLUEPRINTS / 'brandings'}`")
        branding_upload = st.file_uploader("Subir Branding JSON", type=["json"], key="branding_upload")
        if branding_upload and st.button("Guardar Branding", type="secondary"):
            try:
                data = json.loads(branding_upload.getvalue().decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("O JSON raiz deve ser um objecto.")
                target = BLUEPRINTS / "brandings" / (Path(branding_upload.name).stem.replace(" ", "-") + ".json")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    import_tab, batch_tab, manual_tab = render_localized_tabs(["Importar do YouTube", "Canais em lote gmail", "Cadastro manual"])

    with import_tab:
        st.caption("A pesquisa pública funciona sem API Key. A Data API é opcional e fica disponível numa opção separada para métricas oficiais.")
        source = st.text_input("URL, handle ou ID do canal", placeholder="https://youtube.com/@seucanal", key="youtube_channel_source")
        lookup_mode = st.radio("Método de consulta", ["Página pública — sem API Key", "YouTube Data API — API Key opcional"], horizontal=True, key="youtube_channel_lookup_mode")
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("Buscar no YouTube", type="primary", width="stretch", key="youtube_channel_lookup"):
                if lookup_mode.startswith("Página pública"):
                    result = youtube.fetch_channel_public(source)
                elif not youtube.api_key:
                    result = IntegrationResult(False, "A YouTube Data API Key não está configurada. Escolha a opção Página pública — sem API Key ou configure a chave em Configurações > Contas Google.", {"status": "api_key_not_configured"})
                else:
                    result = youtube.fetch_channel(source)
                st.session_state["yt_import"] = result.data
                st.session_state["yt_message"] = result.message
                st.session_state["yt_ok"] = result.ok
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
                language = st.selectbox("Idioma", list(LANGUAGE_CODES), index=list(LANGUAGE_CODES).index(language_code(imported.get("language") or "pt")), format_func=language_label, key="yt_import_language")
                style = st.selectbox("Estilo wide", ["Pexels/Pixabay", "full_ia", "Apenas Música"], index=0, key="yt_import_style")
                blueprint = st.selectbox("Blueprint padrão do canal", blueprint_ids, index=blueprint_ids.index(imported_blueprint) if imported_blueprint in blueprint_ids else 0, format_func=lambda item: blueprint_labels.get(item, item or "Sem Blueprint padrão"), key="yt_import_blueprint")
                voice_options = voice_catalog(imported.get("default_voice") or imported.get("voice", ""))
                current_voice = imported.get("default_voice") or imported.get("voice", "")
                voice = st.selectbox("Voz padrão do canal", voice_options, index=voice_options.index(current_voice) if current_voice in voice_options else 0, format_func=lambda item: item or "Sem voz padrão", key="yt_import_voice")
                imported_account_id = str(imported.get("google_account_id", ""))
                google_account_id = st.selectbox("Conta Google para Upload directo", youtube_account_ids, index=youtube_account_ids.index(imported_account_id) if imported_account_id in youtube_account_ids else 0, format_func=lambda item: youtube_account_labels.get(item, item), key="yt_import_google_account_id")
                st.caption("O DELEGATED_SESSION_ID é lido exclusivamente do documento JSON da conta Google associada.")
                automation_on = st.toggle("Automação ON", value=bool(imported.get("automation_on", False)), key="yt_import_automation_on")
                automation_time = st.text_input("Horário diário (HH:MM)", value=imported.get("automation_time", "00:00"), key="yt_import_automation_time")
                description = st.text_area("Descrição", value=imported.get("description", ""), key="yt_import_description")
                niche = st.text_input("Canais de Referência / Nicho", value=imported.get("niche", ""), key="yt_import_niche")
                metrics = st.columns(3)
                with metrics[0]: subscriber_count = st.number_input("Inscritos", min_value=0, value=_channel_count_value(imported.get("subscriber_count")), key="yt_import_subscribers")
                with metrics[1]: video_count = st.number_input("Vídeos", min_value=0, value=_channel_count_value(imported.get("video_count")), key="yt_import_videos")
                with metrics[2]: view_count = st.number_input("Visualizações", min_value=0, value=_channel_count_value(imported.get("view_count")), key="yt_import_views")
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
                            "language": language,
                            "style_wide": {"Pexels/Pixabay": "pexels", "full_ia": "full_ia", "Apenas Música": "music"}.get(style, style),
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
                        }
                        channel = create_channel(name, url, metadata)
                        st.success(f"Canal {channel['name']} guardado.")
                        st.rerun()
        else:
            st.info("Introduza um URL, handle ou ID e clique em Buscar no YouTube. Não é necessária API Key na opção pública.")

    with batch_tab:
        st.caption("Esta subaba usa a conta Google/YouTube seleccionada para listar os canais que ela gere. Não lê a caixa Gmail e não usa e-mails como pesquisa pública.")
        accounts = [account for account in settings.get("youtube_batch_accounts", []) if isinstance(account, dict) and account.get("id")]
        if not accounts:
            st.info("Configure primeiro uma conta em Configurações > Configuração API > Contas Google/YouTube para canais em lote.")
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
            niche = st.text_input("Canais de Referência / Nicho", placeholder="Ex.: História militar, mistérios, ciência", key="manual_channel_niche")
            language = st.selectbox("Idioma", list(LANGUAGE_CODES), index=list(LANGUAGE_CODES).index("pt"), format_func=language_label, key="manual_channel_language")
            style = st.selectbox("Estilo wide", ["Pexels/Pixabay", "full_ia", "Apenas Música"], index=0, key="manual_channel_style")
            manual_blueprint_items = blueprint_catalog()
            manual_blueprint_ids = [item[0] for item in manual_blueprint_items]
            manual_blueprint_labels = {item[0]: item[1] for item in manual_blueprint_items}
            blueprint = st.selectbox("Blueprint padrão do canal", manual_blueprint_ids, format_func=lambda item: manual_blueprint_labels.get(item, item or "Sem Blueprint padrão"), key="manual_channel_blueprint")
            voice_options = voice_catalog()
            voice = st.selectbox("Voz padrão do canal", voice_options, format_func=lambda item: item or "Sem voz padrão", key="manual_channel_voice")
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
                        "language": language,
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
                    })
                    st.success(f"Canal {channel['name']} guardado manualmente.")
                    st.rerun()

    st.subheader("Canais cadastrados")
    channels = read_json("channels.json", [])
    if not channels:
        st.info("Nenhum canal cadastrado.")
        return
    for channel in channels:
        channel_id = str(channel["id"])
        edit_key = f"edit_channel_{channel_id}"
        with st.container(border=True):
            header_cols = st.columns([0.7, 3.5, 1.3, 1.3, 1.5])
            with header_cols[0]:
                if channel.get("thumbnail_url"):
                    st.image(channel["thumbnail_url"], width=64)
                else:
                    st.markdown("### YT")
            with header_cols[1]:
                st.write(f"**{channel.get('name', 'Sem nome')}**")
                st.caption(channel_niche_label(channel))
                st.caption(f"{channel.get('handle') or channel.get('url') or 'sem URL'} · {channel.get('metrics_source', 'manual')}")
            with header_cols[2]:
                st.metric("Inscritos", _format_channel_count(channel.get("subscriber_count")))
            with header_cols[3]:
                st.metric("Vídeos", _format_channel_count(channel.get("video_count")))
            with header_cols[4]:
                active = st.toggle("Activo", value=channel.get("active", True), key=f"active_{channel_id}")
                if active != channel.get("active"):
                    update_channel(channel_id, {"active": active})
                    st.rerun()
                action_cols = st.columns(2)
                with action_cols[0]:
                    if st.button("Editar", key=f"edit_channel_button_{channel_id}", width="stretch"):
                        st.session_state[edit_key] = True
                        st.rerun()
                with action_cols[1]:
                    delete_key = f"delete_pending_{channel_id}"
                    if st.button("Apagar", key=f"delete_{channel_id}", width="stretch"):
                        st.session_state[delete_key] = True
                        st.rerun()
            if st.session_state.get(edit_key):
                render_channel_edit_form(channel, youtube_account_ids, youtube_account_labels, youtube_accounts_by_id)
            else:
                summary = channel_blueprint_summary(channel)
                block_cols = st.columns(3)
                with block_cols[0]:
                    st.markdown(f"**Prompts do Canal**\n\n{summary['name']}")
                    if st.button("Editar Prompts", key=f"edit_prompts_{channel_id}", width="stretch"):
                        st.session_state[edit_key] = True
                        st.rerun()
                with block_cols[1]:
                    st.markdown(f"**Canais de Referência**\n\n{channel_niche_label(channel)}")
                    if st.button("Editar Nicho", key=f"edit_niche_{channel_id}", width="stretch"):
                        st.session_state[edit_key] = True
                        st.rerun()
                with block_cols[2]:
                    st.markdown(f"**Narrador**\n\n{summary['voice'] or 'Sem voz padrão'}")
                    if st.button("Configurar Narrador", key=f"edit_voice_{channel_id}", width="stretch"):
                        st.session_state[edit_key] = True
                        st.rerun()

            channel_account_ids = list(youtube_account_ids)
            current_channel_account_id = str(channel.get("google_account_id", ""))
            if current_channel_account_id and current_channel_account_id not in channel_account_ids:
                channel_account_ids.append(current_channel_account_id)
                youtube_account_labels[current_channel_account_id] = "Conta Google não configurada"
            with st.expander("Upload directo — documento da conta deste canal", expanded=False):
                st.caption("O DELEGATED_SESSION_ID deste canal é individual, mas fica apenas no documento JSON da conta Google. A UI não mostra nem edita esse valor; associe apenas o canal à conta que contém o documento.")
                with st.form(f"channel_direct_credentials_{channel_id}"):
                    channel_account_id = st.selectbox("Conta Google do documento deste canal", channel_account_ids, index=channel_account_ids.index(current_channel_account_id) if current_channel_account_id in channel_account_ids else 0, format_func=lambda item: youtube_account_labels.get(item, item or "Sem conta Google associada"), key=f"channel_account_{channel_id}")
                    save_channel_direct_credentials = st.form_submit_button("Associar conta Google ao canal", type="primary", width="stretch")
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
                    update_channel(channel_id, {"google_account_id": channel_account_id.strip(), "google_account_email": str(youtube_accounts_by_id.get(channel_account_id, {}).get("email", ""))})
                    st.success("Conta Google associada ao canal. O DELEGATED_SESSION_ID continua exclusivamente no documento da conta.")
                    st.rerun()

            render_channel_videos(channel)


def render_new_video(page_title: str = "Criação de Vídeos"):
    st.title(page_title)
    create_tab = render_localized_tabs(["Criar vídeo"])[0]
    with create_tab:
        all_channels = [c for c in read_json("channels.json", []) if isinstance(c, dict)]
        active_channels = [c for c in all_channels if c.get("active", True)]
        if not all_channels:
            st.warning("Cadastre pelo menos um canal antes de criar vídeos.")
        else:
            mode_label = st.radio(
                "Modo de criação",
                ["Canal específico", "Lote no mesmo canal", "Lote geral"],
                horizontal=True,
                key="new_video_mode",
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
                    value=st.session_state.get("new_video_general_context", ""),
                    key="new_video_general_context",
                    placeholder="Opcional: campanha, época, evento ou restrição editorial comum. O tema final será individual por canal.",
                )
                if st.button("Gerar tópicos individuais para todos os canais", key="new_video_generate_general_topics", width="stretch"):
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
                        st.session_state["new_video_general_topics"] = generated_topics
                        st.success(f"Foram gerados {len(generated_topics)} briefings independentes.")
                general_topics = st.session_state.get("new_video_general_topics", {})
                if general_topics:
                    st.subheader("Briefings por canal")
                    for channel in all_channels:
                        result = general_topics.get(channel["id"])
                        if result:
                            st.write(f"**{channel.get('name', 'Canal')}**")
                            st.caption(f"{result.get('niche', '')} · {result.get('angle', '')}")
                            st.text_area("Briefing gerado", value=result.get("topic", ""), key=f"new_video_general_topic_{channel['id']}", height=80)
                generation_settings = render_video_generation_settings(
                    "new_video",
                    current_language=str(st.session_state.get("video_language") or ""),
                )
            else:
                if not active_channels:
                    st.warning("Não existem canais activos disponíveis para os modos de canal específico.")
                    selected = []
                else:
                    selected_one = st.selectbox("Canal", active_channels, format_func=lambda c: c["name"], key="new_video_channel")
                    selected = [selected_one["id"]]
                    # Intentionally sits between Canal and the generation settings, as requested.
                    render_channel_blueprint_panel(selected_one)
                    generation_settings = render_video_generation_settings(
                        "new_video",
                        current_language=str(st.session_state.get("video_language") or ""),
                        channel=selected_one,
                        generate_content_callback=lambda: _generate_video_content_callback(
                            "new_video",
                            selected_one,
                            str(st.session_state.get("video_language") or "pt"),
                        ),
                    )

            if not generation_settings:
                generation_settings = render_video_generation_settings(
                    "new_video",
                    current_language=str(st.session_state.get("video_language") or ""),
                )
            wide_style_label = generation_settings["video_source"]
            style_ia = generation_settings.get("style_ia", "")
            music_path = ""
            music_source = ""
            if wide_style_label == "Apenas Música":
                st.caption("Apenas Música não gera Pexels/Pixabay nem fundo IA; o áudio musical será usado como elemento principal.")
                music_source = st.radio("Fonte da música", ["Ficheiro existente", "Carregar ficheiro", "Criar via Suno API"], horizontal=True, key="new_video_music_source")
                if music_source == "Ficheiro existente":
                    local_music = list_music_files()
                    if local_music:
                        selected_music = st.selectbox("Música local", local_music, format_func=lambda item: item.name, key="new_video_music_existing")
                        music_path = str(selected_music)
                    else:
                        st.warning("Ainda não existem músicas em storage/music. Escolha Carregar ficheiro ou Criar via Suno API.")
                elif music_source == "Carregar ficheiro":
                    uploaded_music = st.file_uploader("Carregar música", type=["mp3", "wav", "m4a", "aac", "flac", "ogg"], key="new_video_music_upload")
                    if uploaded_music and st.button("Guardar música local", key="new_video_music_store", width="stretch"):
                        try:
                            stored_music = store_music_file(uploaded_music.name, uploaded_music.getvalue())
                            st.session_state["new_video_music_path"] = str(stored_music)
                            st.success(f"Música guardada em `{stored_music}`")
                        except (OSError, ValueError) as exc:
                            st.error(str(exc))
                    music_path = st.session_state.get("new_video_music_path", "")
                else:
                    suno_prompt = st.text_area("Prompt musical Suno", placeholder="Instrumental cinematográfico, calmo, sem voz...", key="new_video_suno_prompt")
                    suno_title = st.text_input("Título da música", value=st.session_state.get("new_video_topic") or "Thunderbolt music", key="new_video_suno_title")
                    if st.button("Solicitar música no Suno", key="new_video_suno_request", width="stretch"):
                        suno_result = request_suno_generation(read_json("settings.json", {}), suno_prompt, suno_title)
                        (st.success if suno_result["ok"] else st.error)(suno_result["message"])
                        if suno_result["ok"]:
                            try:
                                generated = materialize_suno_audio(suno_result.get("data", {}), suno_title or "suno-generated.mp3")
                                if generated:
                                    st.session_state["new_video_music_path"] = str(generated)
                                    st.success(f"Música descarregada para `{generated}`")
                                else:
                                    st.info("O pedido foi aceite, mas o endpoint ainda não devolveu uma URL de áudio. Consulte o estado no serviço Suno e adicione o ficheiro quando estiver pronto.")
                            except (OSError, requests.RequestException, ValueError) as exc:
                                st.warning(f"Pedido criado, mas não foi possível descarregar o áudio: {exc}")
                    music_path = st.session_state.get("new_video_music_path", "")

            payloads: dict[str, dict[str, Any]] = {}
            if mode == "general":
                existing_topics = st.session_state.get("new_video_general_topics", {})
                payloads = dict(st.session_state.get("new_video_general_payloads", {}))
                if st.button("Gerar títulos e thumbnails para todos os canais", key="new_video_generate_general_creative", width="stretch"):
                    settings = read_json("settings.json", {})
                    new_payloads: dict[str, dict[str, Any]] = {}
                    errors: list[str] = []
                    with st.spinner("A gerar títulos e thumbnails independentes por canal…"):
                        for channel in all_channels:
                            try:
                                topic_result = existing_topics.get(channel["id"])
                                if not topic_result:
                                    topic_result = generate_topic_for_ui(settings, channel, general_context)
                                generated = generate_creative_for_ui(settings, channel, topic_result["topic"], topic_source="llm")
                                generated["ai_generation"]["topic"] = topic_result
                                new_payloads[channel["id"]] = generated
                            except CreativeGenerationError as exc:
                                errors.append(f"{channel.get('name', 'Canal')}: {exc}")
                    if errors:
                        for error in errors:
                            st.error(error)
                    else:
                        st.session_state["new_video_general_topics"] = {cid: {"topic": item["topic"], "topic_source": "llm"} for cid, item in new_payloads.items()}
                        st.session_state["new_video_general_payloads"] = new_payloads
                        payloads = new_payloads
                        st.success(f"Pacote criativo pronto para {len(new_payloads)} canais.")
                payloads = st.session_state.get("new_video_general_payloads", payloads)
                for channel in all_channels:
                    payload = payloads.get(channel["id"])
                    if not payload:
                        continue
                    with st.expander(f"{channel.get('name', 'Canal')} — título e thumbnail", expanded=False):
                        title_options = [item.get("title", "") for item in payload.get("title_candidates", []) if item.get("title")]
                        if title_options:
                            selected_title = st.selectbox("Título escolhido", title_options, index=max(0, title_options.index(payload.get("title")) if payload.get("title") in title_options else 0), key=f"new_video_general_title_{channel['id']}")
                            payload["title"] = selected_title
                        variants = payload.get("thumbnail_variants", [])
                        if variants:
                            labels = [f"{idx + 1}. {item.get('concept', 'Variante')}" for idx, item in enumerate(variants)]
                            selected_variant_label = st.selectbox("Thumbnail escolhida", labels, key=f"new_video_general_thumbnail_{channel['id']}")
                            variant_index = labels.index(selected_variant_label)
                            variant = variants[variant_index]
                            payload["thumbnail_variant"] = variant
                            payload["thumbnail_prompt"] = variant.get("image_prompt", "")
                            payload["thumbnail_text"] = variant.get("overlay_text", "")
                            st.caption(f"{variant.get('composition', '')} · {variant.get('color_palette', '')}")
                            thumbnail_path = str(variant.get("image_path") or payload.get("thumbnail_path") or "").strip()
                            if st.button("Gerar imagem com Nano Banana", key=f"new_video_general_generate_thumbnail_{channel['id']}", width="stretch"):
                                try:
                                    thumbnail_path = str(generate_thumbnail_image(read_json("settings.json", {}), variant.get("image_prompt", ""), topic=str(payload.get("topic") or ""), variant_index=variant_index, aspect_ratio=thumbnail_aspect_ratio_for_channel_task(channel)))
                                    variant["image_path"] = thumbnail_path
                                    payload["thumbnail_path"] = thumbnail_path
                                    payload["thumbnail_status"] = "generated"
                                    st.session_state["new_video_general_payloads"] = payloads
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
                topic_for_creative = str(generation_settings.get("video_subject") or "").strip()
                if st.button("Gerar títulos e thumbnails com IA", key="new_video_generate_creative", width="stretch"):
                    if selected_one is None:
                        st.error("Seleccione primeiro um canal.")
                    else:
                        try:
                            if not topic_for_creative:
                                topic_result = generate_topic_for_ui(read_json("settings.json", {}), selected_one)
                                topic_for_creative = str(topic_result["topic"]).strip()
                                st.session_state["new_video_topic"] = topic_for_creative
                                st.session_state["new_video_topic_meta"] = topic_result
                            generated = generate_creative_for_ui(
                                read_json("settings.json", {}),
                                selected_one,
                                topic_for_creative,
                                topic_source=_video_topic_source(topic_for_creative),
                            )

                            st.session_state["new_video_creative_payload"] = generated
                            st.success("Tema, título e thumbnails gerados; escolha a variante antes de criar as tarefas.")
                            st.rerun()
                        except CreativeGenerationError as exc:
                            st.error(str(exc))
                payload = st.session_state.get("new_video_creative_payload")
                if payload:
                    st.subheader("Título e Thumbnail automáticos")
                    title_options = [item.get("title", "") for item in payload.get("title_candidates", []) if item.get("title")]
                    if title_options:
                        selected_title = st.selectbox("Título escolhido", title_options, index=max(0, title_options.index(payload.get("title")) if payload.get("title") in title_options else 0), key="new_video_title_choice")
                        payload["title"] = selected_title
                        with st.expander(f"Ver {len(title_options)} candidatos de título"):
                            st.dataframe(payload.get("title_candidates", []), width="stretch", hide_index=True)
                    variants = payload.get("thumbnail_variants", [])
                    if variants:
                        labels = [f"{idx + 1}. {item.get('concept', 'Variante')}" for idx, item in enumerate(variants)]
                        selected_variant_label = st.selectbox("Thumbnail escolhida", labels, key="new_video_thumbnail_choice")
                        variant_index = labels.index(selected_variant_label)
                        variant = variants[variant_index]
                        payload["thumbnail_variant"] = variant
                        payload["thumbnail_prompt"] = variant.get("image_prompt", "")
                        payload["thumbnail_text"] = variant.get("overlay_text", "")
                        st.caption(f"Composição: {variant.get('composition', '')} · Cores: {variant.get('color_palette', '')}")
                        st.code(variant.get("image_prompt", ""), language="text")
                        thumbnail_path = str(variant.get("image_path") or payload.get("thumbnail_path") or "").strip()
                        if st.button("Gerar imagem da thumbnail com Nano Banana", key="new_video_generate_thumbnail_image", width="stretch"):
                            try:
                                thumbnail_path = str(generate_thumbnail_image(read_json("settings.json", {}), variant.get("image_prompt", ""), topic=str(payload.get("topic") or ""), variant_index=variant_index, aspect_ratio=thumbnail_aspect_ratio_for_channel_task(selected_one)))
                                variant["image_path"] = thumbnail_path
                                payload["thumbnail_path"] = thumbnail_path
                                payload["thumbnail_status"] = "generated"
                                st.session_state["new_video_creative_payload"] = payload
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
                    st.session_state["new_video_creative_payload"] = payload

            with st.form("new_video_form"):
                quantity = st.number_input("Quantidade", min_value=1, max_value=100, value=1, disabled=mode != "same_channel")
                language = generation_settings["script_language"]
                fmt = generation_settings["video_format"]
                submitted = st.form_submit_button("Criar tarefas", type="primary")
            if submitted:
                save_video_language(language)
                style = {"Pexels/Pixabay": "pexels", "full_ia": "full_ia", "Apenas Música": "music"}[wide_style_label]
                if style == "music" and not music_path:
                    st.error("Escolha, carregue ou gere uma música antes de criar o vídeo Apenas Música.")
                    st.stop()
                if mode == "general":
                    payloads = dict(st.session_state.get("new_video_general_payloads", {}))
                    topics = dict(st.session_state.get("new_video_general_topics", {}))
                    channels_by_id = {str(channel["id"]): channel for channel in all_channels}
                    payloads_need_refresh = len(payloads) != len(selected) or any(
                        str(st.session_state.get(f"new_video_general_topic_{channel_id}", "") or "").strip()
                        and str(st.session_state.get(f"new_video_general_topic_{channel_id}", "") or "").strip() != str((payloads.get(channel_id) or {}).get("topic") or "").strip()
                        for channel_id in selected
                    )
                    if payloads_need_refresh:
                        settings = read_json("settings.json", {})
                        generated_payloads: dict[str, dict[str, Any]] = {}
                        errors: list[str] = []
                        with st.spinner("A gerar automaticamente um pacote criativo independente para cada canal…"):
                            for channel_id in selected:
                                channel = channels_by_id[channel_id]
                                edited_topic = str(st.session_state.get(f"new_video_general_topic_{channel_id}", "") or "").strip()
                                topic_result = topics.get(channel_id) or {}
                                try:
                                    if not edited_topic:
                                        topic_result = generate_topic_for_ui(settings, channel, general_context)
                                        edited_topic = topic_result["topic"]
                                    else:
                                        topic_result = {**topic_result, "topic": edited_topic, "topic_source": topic_result.get("topic_source", "manual")}
                                    generated = generate_creative_for_ui(settings, channel, edited_topic, topic_source=topic_result.get("topic_source", "llm"))
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
                            st.session_state["new_video_general_payloads"] = payloads
                            st.session_state["new_video_general_topics"] = {cid: {"topic": payload["topic"], "topic_source": payload.get("topic_source", "llm")} for cid, payload in payloads.items()}
                    if len(payloads) == len(selected):
                        batch_topic = "Lote geral — um vídeo independente por canal"
                        channel_payloads = {cid: {**payload, "language": language, "format": fmt, "style_wide": style, "style_ia": style_ia, "music_mode": style == "music", "background_mode": "none" if style == "music" else ("ai" if style == "full_ia" else "stock"), "music_path": music_path, "music_source": music_source, "generation_settings": generation_settings} for cid, payload in payloads.items()}
                        batch = create_batch("general", selected, batch_topic, 1, {"language": language, "format": fmt, "style_wide": style, "style_ia": style_ia, "music_mode": style == "music", "background_mode": "none" if style == "music" else ("ai" if style == "full_ia" else "stock"), "music_path": music_path, "music_source": music_source, "generation_settings": generation_settings, "topic_source": "llm", "channel_payloads": channel_payloads})
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
                        quantity_value = int(quantity if mode == "same_channel" else 1)
                        payload = dict(st.session_state.get("new_video_creative_payload") or {})
                        if not payload.get("title") or not payload.get("thumbnail_variants"):
                            try:
                                payload = generate_creative_for_ui(
                                    read_json("settings.json", {}),
                                    selected_one or {},
                                    topic_value,
                                    topic_source=_video_topic_source(topic_value),
                                )
                            except CreativeGenerationError as exc:
                                st.warning(f"Título/thumbnail automáticos pendentes: {exc} A tarefa será criada com o tópico como título e sem ficheiro de thumbnail.")
                                payload = {"topic": topic_value, "title": topic_value, "topic_source": "manual", "thumbnail_status": "pending_provider", "thumbnail_variants": [], "thumbnail_variant": {}, "thumbnail_prompt": "", "thumbnail_text": ""}
                        payload.update({"topic": topic_value, "topic_source": payload.get("topic_source") or _video_topic_source(topic_value), "language": language, "format": fmt, "style_wide": style, "style_ia": style_ia, "music_mode": style == "music", "background_mode": "none" if style == "music" else ("ai" if style == "full_ia" else "stock"), "music_path": music_path, "music_source": music_source, "generation_settings": generation_settings})
                        batch = create_batch(mode, selected, topic_value, quantity_value, {"language": language, "format": fmt, "style_wide": style, "style_ia": style_ia, "music_mode": style == "music", "background_mode": "none" if style == "music" else ("ai" if style == "full_ia" else "stock"), "music_path": music_path, "music_source": music_source, "generation_settings": generation_settings, "topic_source": payload.get("topic_source", "manual"), "channel_payloads": {selected[0]: payload}})
                        tasks = create_tasks_for_batch(batch)
                        st.success(f"Lote {batch['id']} criado com {len(tasks)} tarefa(s). Abra {ui_text('Backlog Vídeos', current_ui_language())} para acompanhar.")


def render_music_creation():
    """Expose the complete video-creation UI under the music-oriented navigation entry without changing the original page."""
    render_new_video(page_title="Criação de Músicas")


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

        document_type = st.radio("Tipo de documento", ["Roteiro de vídeo", "Letra de música"], horizontal=True, key="script_document_type")
        title = st.text_input("Título", key="script_title", placeholder="Ex.: A verdade esquecida sobre…")
        brief = st.text_area(
            "Tema ou briefing",
            key="script_brief",
            height=120,
            placeholder="Descreva o tema, a mensagem, o conflito ou a ideia musical que o Blueprint deve orientar.",
        )
        legacy_script_language = str(st.session_state.get("script_language") or "")
        script_settings = render_video_generation_settings(
            "pipeline_scripts",
            current_language=legacy_script_language or str(read_json("settings.json", {}).get("video_language") or "pt"),
        )
        language = script_settings["script_language"]
        structure_notes = script_settings["script_structure_notes"]
        generate_col, clear_col = st.columns([1.4, 1])
        with generate_col:
            generate_clicked = st.button("Gerar com IA a partir do Blueprint", type="primary", width="stretch", key="generate_script_document")
        with clear_col:
            clear_clicked = st.button("Limpar rascunho", width="stretch", key="clear_script_document")
        if clear_clicked:
            for key in ("script_draft", "script_draft_title", "script_draft_content", "script_draft_summary"):
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
            draft_title = st.text_input("Título do rascunho", key="script_draft_title")
            draft_summary = st.text_input("Resumo", key="script_draft_summary")
            draft_content = st.text_area("Conteúdo guardado", height=460, key="script_draft_content")
            if st.button("Guardar documento no storage", type="primary", width="stretch", key="save_script_document"):
                try:
                    record = save_script_document(
                        {
                            **draft,
                            "title": draft_title,
                            "summary": draft_summary,
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
            st.caption("Gere um rascunho com IA para o editar aqui, ou seleccione um Blueprint e preencha o briefing para começar.")

    with history_tab:
        st.caption(f"Histórico persistente: `{script_dir}` · índice em `{STORAGE / 'state' / 'scripts.json'}`")
        records = list_script_documents()
        if not records:
            st.info("Ainda não existem roteiros ou letras guardados.")
        for record in records[:50]:
            label = f"{record.get('title', 'Documento')} · {record.get('document_type', 'documento')}"
            with st.expander(label, expanded=False):
                st.caption(f"{record.get('created_at', '—')} · {record.get('channel_name', 'Documento independente')} · Blueprint: {record.get('blueprint_name', '—')}")
                stored_path = Path(str(record.get("path") or ""))
                content = read_script_document(record)
                if content:
                    st.text_area("Conteúdo", value=content, height=220, key=f"stored_script_{record.get('id')}")
                    if stored_path.is_file():
                        st.download_button("Descarregar Markdown", data=stored_path.read_bytes(), file_name=stored_path.name, mime="text/markdown", key=f"download_script_{record.get('id')}")
                else:
                    st.warning("O ficheiro deste registo já não está disponível no storage.")


@st.cache_data(show_spinner=False)
def _cached_niche_download():
    """Download or reuse the dataset only after the user submits the form."""
    return str(download_kaggle_dataset())


def render_niche_finder():
    st.title("Niche Finder Kaggle")
    st.caption("Busca de padrões, nichos e tags para orientar canais faceless.")
    st.info("A instalação das dependências é automática. A operação não é: defina os parâmetros abaixo e clique em **Analisar Nichos** para iniciar.")

    default_start = date(2023, 9, 20)
    default_end = date.today()
    country_options = [
        "Todos", "US", "BR", "GB", "CA", "AU", "DE", "FR", "ES", "IT", "JP", "KR", "IN", "MX", "AR", "PT",
    ]
    with st.container(border=True):
        st.subheader("Parâmetros da busca")
        st.caption("Estes controlos pertencem a esta aba. Nenhum dataset é descarregado e nenhuma análise é executada enquanto não clicar no botão.")
        with st.form("niche_finder_parameters", clear_on_submit=False):
            parameter_cols = st.columns(3)
            with parameter_cols[0]:
                n_clusters = st.slider("Número de Clusters", 2, 10, 5, key="niche_n_clusters")
                min_support = st.slider("Suporte Mínimo", 0.01, 0.5, 0.05, 0.01, format="%.2f", key="niche_min_support")
            with parameter_cols[1]:
                country = st.selectbox("País", country_options, key="niche_country")
                engagement = st.selectbox("Engagement", ["Todos", "High", "Moderate", "Low"], key="niche_engagement")
            with parameter_cols[2]:
                start_date = st.date_input("Data inicial", value=default_start, min_value=date(2020, 1, 1), max_value=default_end, key="niche_start_date")
                end_date = st.date_input("Data final", value=default_end, min_value=date(2020, 1, 1), max_value=default_end, key="niche_end_date")
            tags_text = st.text_input("Tags opcionais", key="niche_tags_text", placeholder="Ex.: history, facts, documentary")
            analyse = st.form_submit_button("Analisar Nichos", type="primary", width="stretch")

    current_parameters = {
        "n_clusters": n_clusters,
        "min_support": min_support,
        "country": country,
        "engagement": engagement,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "tags": [tag.strip() for tag in re.split(r"[,|]", tags_text) if tag.strip()],
    }
    results = st.session_state.get("niche_results")
    if analyse:
        try:
            if start_date and end_date and start_date > end_date:
                raise NicheAnalysisError("A data inicial não pode ser posterior à data final.")
            with st.spinner("A preparar os dados apenas porque solicitou a análise…"):
                dataset_path = _cached_niche_download()
            with st.spinner("A executar a análise dos nichos…"):
                results = run_niche_analysis(
                    str(dataset_path),
                    n_clusters=n_clusters,
                    min_support=min_support,
                    start_date=start_date.isoformat() if start_date else None,
                    end_date=end_date.isoformat() if end_date else None,
                    country=country,
                    engagement=engagement,
                    tags=current_parameters["tags"],
                )
            st.session_state["niche_results"] = results
            st.session_state["niche_last_parameters"] = current_parameters
            niche_key = hashlib.sha1(json.dumps(current_parameters, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
            summary = results.get("summary", {}) if isinstance(results, dict) else {}
            record_notification("niche_analysis_completed", "Análise de nicho concluída", "A análise Kaggle terminou com resultados prontos para consulta.", metadata={"source": "Kaggle", "rows_filtered": summary.get("rows_filtered", 0)}, dedupe_key=f"niche:kaggle:{niche_key}")
            st.success("Análise concluída.")
        except (NicheAnalysisError, DatasetError, OSError) as exc:
            st.error("Não foi possível concluir a análise solicitada com os parâmetros actuais.")
            with st.expander("Detalhes técnicos"):
                st.caption(str(exc))
            return

    if results is None:
        st.caption("Ainda não existe uma análise nesta sessão. Ajuste os parâmetros e clique em **Analisar Nichos**.")
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
    points = results["cluster_points"].copy()
    keyword = st.text_input("Filtrar palavras-chave nos clusters", key="niche_cluster_keyword", placeholder="Ex.: música, gaming, receitas")
    if keyword.strip():
        cluster_table = cluster_table[cluster_table["palavras"].str.contains(keyword.strip(), case=False, na=False)]
    tab_clusters, tab_rules, tab_data = render_localized_tabs(["Clusters encontrados", "Regras de associação", "Dados analisados"])
    with tab_clusters:
        st.dataframe(cluster_table, width="stretch", hide_index=True)
        if not points.empty:
            try:
                import plotly.express as px
                points["cluster"] = points["cluster_id"].astype(str)
                hover = [column for column in ["title", "channel_name", "country", "view_count", "engagement_rate"] if column in points.columns]
                figure = px.scatter(points, x="x", y="y", color="cluster", hover_data=hover, title="Distribuição dos clusters")
                figure.update_layout(legend_title_text="Cluster")
                st.plotly_chart(figure, width="stretch")
            except ImportError:
                st.error("A visualização da análise não está disponível nesta instalação.")
    with tab_rules:
        if rules_table.empty:
            st.info("Não foram encontradas regras com os filtros actuais. Reduza o suporte mínimo ou escolha outro filtro.")
        else:
            st.dataframe(rules_table, width="stretch", hide_index=True)
        if not items_table.empty:
            st.subheader("Itemsets frequentes")
            st.dataframe(items_table, width="stretch", hide_index=True)
    with tab_data:
        st.dataframe(results["raw_data"], width="stretch", hide_index=True)


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

    with st.form("media_download_form"):
        urls_text = st.text_area("URLs para descarregar", placeholder="Uma URL http(s) por linha", height=120, key="media_download_urls")
        mode_label = st.radio("Tipo de mídia", ["Vídeo", "Áudio"], horizontal=True, key="media_download_mode")
        option_cols = st.columns(3)
        with option_cols[0]:
            if mode_label == "Vídeo":
                quality_label = st.selectbox("Qualidade", list(VIDEO_QUALITY_OPTIONS), key="media_download_quality")
                video_container = st.selectbox("Contentor", list(VIDEO_CONTAINERS), key="media_download_container")
                audio_format = "mp3"
            else:
                quality_label = "Melhor qualidade"
                video_container = "mp4"
                audio_format = st.selectbox("Formato de áudio", list(AUDIO_FORMATS), key="media_download_audio_format")
        with option_cols[1]:
            allow_playlist = st.checkbox("Permitir playlist", value=False, key="media_download_allow_playlist")
            download_subtitles = st.checkbox("Descarregar legendas", value=False, key="media_download_subtitles")
        with option_cols[2]:
            embed_metadata = st.checkbox("Incorporar metadados", value=False, key="media_download_embed_metadata")
            st.caption("Playlist desactivada por padrão para evitar downloads acidentais em massa.")
        start_download = st.form_submit_button("Iniciar download", type="primary", width="stretch")

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
                mode="video" if mode_label == "Vídeo" else "audio",
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
                        st.download_button("Descarregar ficheiro", data=output.read_bytes(), file_name=output.name, mime="audio/*" if record.get("mode") == "audio" else "video/*", key=f"media_result_{record.get('operation_id')}_{filename}")

    st.divider()
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
                    st.download_button("Descarregar", data=output.read_bytes(), file_name=output.name, mime="audio/*" if record.get("mode") == "audio" else "video/*", key=f"media_history_{record.get('operation_id')}_{filename}")


def render_cuts():
    st.title("Cortes")
    st.caption("Crie clips verticais, quadrados ou horizontais a partir de vídeos longos, com um fluxo local inspirado no Clip Generator do OpenShorts.")

    st.markdown(
        "<div class='tb-cuts-hero'><div class='tb-cuts-kicker'>01 · CLIP GENERATOR</div><h2>Create Viral Shorts</h2><p>Escolha um vídeo longo, defina o formato e gere clips locais sem sobrescrever a fonte.</p></div>",
        unsafe_allow_html=True,
    )

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
            st.info("Ainda não existem vídeos gerados com caminho registado na pipeline.")
        else:
            generated_labels = [f"{path.name} — {path}" for path in generated_paths]
            selected_generated = st.selectbox("Vídeo gerado", range(len(generated_paths)), format_func=lambda index: generated_labels[index], key="cuts_generated_index")
            if st.button("Usar vídeo seleccionado", key="cuts_use_generated", width="stretch"):
                source_path = generated_paths[selected_generated]
                st.session_state["cuts_source_path"] = str(source_path)
                st.session_state["cuts_source_label"] = f"Pipeline · {source_path.name}"
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
                st.info("Ainda não existem vídeos gerados com caminho registado nos artefactos da pipeline.")
            else:
                labels = [f"{path.name} — {path}" for path in generated_paths]
                selected_index = st.selectbox("Vídeo gerado", range(len(generated_paths)), format_func=lambda index: labels[index], key="python_editor_generated_index")
                source_path = generated_paths[selected_index]
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


def render_videos():
    st.subheader("Backlog Videos")
    st.caption("Acompanhamento dos vídeos criados, estados da pipeline e controlos de execução.")
    st.caption(f"Os vídeos são guardados em `{STORAGE / 'videos'}`.")
    tasks = read_json("tasks.json", [])
    if not tasks:
        st.info("Nenhum vídeo criado.")
        return
    state_filter = st.selectbox("Filtrar por estado", ["Todos", "to_do", "doing", "blocked", "done", "failed", "cancelled"], key="videos_state_filter")
    for task in tasks:
        if state_filter != "Todos" and task.get("state") != state_filter:
            continue
        with st.container(border=True):
            cols = st.columns([2.2, 1, 1, 1.2, 1.8])
            with cols[0]:
                st.write(f"**{task.get('title') or task.get('topic', 'Sem título')}**")
                st.caption(f"Tópico: {task.get('topic', 'Sem tópico')}")
                st.caption(f"{task.get('channel_name')} · {task.get('id')}")
                thumbnail_path = (task.get('artifacts') or {}).get('thumbnail', '')
                if thumbnail_path and Path(thumbnail_path).is_file():
                    st.image(thumbnail_path, width=180)
                else:
                    status = task.get('thumbnail_status', 'not_generated')
                    prompt_note = ' · prompt pronto' if task.get('thumbnail_prompt') else ''
                    st.caption(f"Thumbnail: {status}{prompt_note}")
            with cols[1]: st.write(task.get("format", "wide"))
            with cols[2]: st.write(task.get("stage", "—"))
            with cols[3]: st.write(task.get("state", "—"))
            with cols[4]:
                state = str(task.get("state") or "")
                start_col, stop_col = st.columns(2)
                with start_col:
                    if st.button("Start", key=f"automation_start_{task['id']}", width="stretch", disabled=state not in {"to_do", "blocked", "failed"}):
                        transition_task(task["id"], "doing")
                        st.rerun()
                with stop_col:
                    if st.button("Stop", key=f"automation_stop_{task['id']}", width="stretch", disabled=state != "doing"):
                        transition_task(task["id"], "blocked")
                        st.rerun()


def render_automation():
    st.title("Automação Youtube")
    st.caption("Agendamento diário da geração por canal. O worker verifica o relógio local do computador e coloca os lotes agendados na fila.")
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
    channels = read_json("channels.json", [])
    if not channels:
        st.info("Nenhum canal cadastrado para configurar.")
    for channel in channels:
        channel_id = channel["id"]
        with st.container(border=True):
            cols = st.columns([0.55, 2.35, 1.35, 1.5, 1.35])
            with cols[0]:
                if channel.get("thumbnail_url"):
                    st.image(channel["thumbnail_url"], width=48)
                else:
                    st.markdown("### YT")
            with cols[1]:
                st.write(f"**{channel.get('name', 'Sem nome')}**")
                st.caption(channel.get("handle") or channel.get("url") or "sem URL")
                st.caption(f"Blueprint actual: {channel.get('default_blueprint_id') or channel.get('blueprint_id') or '—'} · Voz actual: {channel.get('default_voice') or channel.get('voice') or '—'}")
            blueprint_ids, blueprint_labels, current_blueprint, voice_options, current_voice = channel_default_options(channel)
            default_cols = st.columns(2)
            with default_cols[0]:
                automation_blueprint = st.selectbox(
                    "Blueprint padrão",
                    blueprint_ids,
                    index=blueprint_ids.index(current_blueprint) if current_blueprint in blueprint_ids else 0,
                    format_func=lambda item: blueprint_labels.get(item, item or "Sem Blueprint padrão"),
                    key=f"automation_blueprint_{channel_id}",
                )
            with default_cols[1]:
                automation_voice = st.selectbox(
                    "Voz padrão",
                    voice_options,
                    index=voice_options.index(current_voice) if current_voice in voice_options else 0,
                    format_func=lambda item: item or "Sem voz padrão",
                    key=f"automation_voice_{channel_id}",
                )
            with cols[2]:
                enabled = st.toggle("Automação ON", value=bool(channel.get("automation_on", False)), key=f"automation_on_{channel_id}")
            with cols[3]:
                schedule_time = st.text_input("Horário (HH:MM)", value=channel.get("automation_time", "00:00"), key=f"automation_time_{channel_id}")
            with cols[4]:
                if st.button("Guardar", key=f"automation_save_{channel_id}", width="stretch"):
                    if not valid_hhmm(schedule_time):
                        st.error("Use o formato HH:MM, por exemplo 08:30.")
                    else:
                        update_channel(channel_id, {
                            "automation_on": bool(enabled),
                            "automation_time": schedule_time.strip(),
                        })
                        set_channel_defaults(channel_id, automation_blueprint, automation_voice)
                        st.success("Agendamento guardado.")
                        st.rerun()

    st.divider()
    st.subheader("Vídeos cadastrados")
    tasks = read_json("tasks.json", [])
    if not tasks:
        st.info("Ainda não existem vídeos cadastrados.")
    for task in tasks:
        with st.container(border=True):
            task_cols = st.columns([2.45, 1.15, 1.15, 1.85])
            with task_cols[0]:
                st.write(f"**{task.get('topic', 'Sem tópico')}**")
                st.caption(f"{task.get('channel_name', 'Canal')} · {task.get('id', '')}")
            with task_cols[1]:
                st.caption("Estado")
                st.write(task.get("state", "—"))
            with task_cols[2]:
                st.caption("Estilo")
                st.write(task.get("style_wide", "—"))
            with task_cols[3]:
                state = str(task.get("state") or "")
                start_col, stop_col = st.columns(2)
                with start_col:
                    if st.button("Start", key=f"automation_start_{task['id']}", width="stretch", disabled=state not in {"to_do", "blocked", "failed"}):
                        transition_task(task["id"], "doing")
                        st.rerun()
                with stop_col:
                    if st.button("Stop", key=f"automation_stop_{task['id']}", width="stretch", disabled=state != "doing"):
                        transition_task(task["id"], "blocked")
                        st.rerun()


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
            account = direct_accounts.get(str(channel.get("google_account_id", "")))
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
                    reconcile_persisted_notifications()
                    (st.success if result.ok else st.error)(result.message)


def render_upload():
    st.title("Upload")
    upload_tab, direct_tab, postiz_tab, upload_post_tab = render_localized_tabs(["Upload convencional", "Upload directo", "Postiz", "Upload-Post"])
    with direct_tab:
        render_upload_direct()
    with postiz_tab:
        render_upload_postiz()
    with upload_post_tab:
        render_upload_post()
    with upload_tab:
        render_upload_conventional()


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
                reconcile_persisted_notifications()
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
                reconcile_persisted_notifications()
                (st.success if result.ok else st.error)(result.message)
                if result.ok and result.data.get("request_id"):
                    st.caption(f"Request ID Upload-Post: {result.data['request_id']}")


UPLOAD_DESTINATION_TARGET_KEYS = {
    "TikTok": "tiktok_accounts",
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
    select_label = "Canal" if destination == "YouTube" else ("Conta TikTok" if destination == "TikTok" else "Perfil / página")
    empty_label = "Nenhum canal YouTube cadastrado" if destination == "YouTube" else ("Nenhuma conta TikTok cadastrada" if destination == "TikTok" else f"Nenhum {destination} configurado")
    if not options:
        st.selectbox(select_label, [empty_label], disabled=True, key=f"upload_target_{destination_key}")
        if destination == "YouTube":
            st.caption("Cadastre ou liste pelo menos um canal YouTube antes de escolher o destino de envio.")
        elif destination == "TikTok":
            st.caption("Cadastre uma conta em Pipeline TikTok > Contas TikTok antes de escolher o destino de envio.")
        else:
            st.caption(f"A lista de {destination} será ligada numa etapa própria de credenciais/API.")
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
    destination = st.multiselect("Destinos", ["YouTube", "TikTok", "Instagram", "Facebook Pages"], default=["YouTube"], key="upload_destinations", placeholder="Seleccione os destinos")
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
            account = direct_accounts.get(str(channel.get("google_account_id", "")))
            if "YouTube" in destination:
                title = st.text_input("Título", value=task.get("title") or task.get("topic", "Vídeo Thunderbolt"), key=f"yt_title_{task['id']}")
                description = st.text_area("Descrição", value=task.get("description", ""), key=f"yt_description_{task['id']}", height=100)
                tags_raw = st.text_input("Tags separadas por vírgula", value=task.get("tags", "") if isinstance(task.get("tags", ""), str) else ", ".join(task.get("tags", [])), key=f"yt_tags_{task['id']}")
                yt_cols = st.columns(3)
                with yt_cols[0]:
                    privacy_status = st.selectbox("Privacidade", ["private", "unlisted", "public"], index=1, key=f"yt_privacy_{task['id']}")
                    st.caption("Fluxo recomendado: não listado · incorporação activa · permitir remix de áudio e vídeo · publicar no feed de subscritos.")
                with yt_cols[1]:
                    category_id = st.text_input("Category ID", value="22", key=f"yt_category_{task['id']}")
                with yt_cols[2]:
                    language = st.text_input("Idioma", value="pt-BR", key=f"yt_language_{task['id']}")
                quota_count = official_upload_count(channel, account)
                st.caption(f"API Oficial hoje: {quota_count}/{OFFICIAL_DAILY_LIMIT} envios nesta conta Gmail.")
                if not selected_youtube_channel:
                    st.caption("Seleccione primeiro um canal YouTube no selector acima para activar este envio.")
                if st.button("Enviar pelo fluxo recomendado", type="primary", key=f"upload_youtube_{task['id']}", disabled=not selected_youtube_channel, help="Escolha o canal YouTube no selector acima." if not selected_youtube_channel else None):
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
                    reconcile_persisted_notifications()
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
                reconcile_persisted_notifications()
                (st.success if result.ok else st.warning)(result.message)
            if "Instagram" in destination:
                st.button("Preparar Instagram", key=f"upload_instagram_{task['id']}", disabled=True, help="UI preparada; publicação Instagram ainda não está activa.")
            if "Facebook Pages" in destination:
                st.button("Preparar Facebook Pages", key=f"upload_facebook_{task['id']}", disabled=True, help="UI preparada; publicação Facebook Pages ainda não está activa.")


def render_google_accounts():
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
        missing_document_parts = list(direct_status.get("missing_cookies", []))
        if not direct_status.get("has_session_info"):
            missing_document_parts.append("sessionInfo")
        if missing_document_parts:
            youtube_accounts_missing_document.append(account_email_snapshot)

        with st.expander(f"{account_label_snapshot} — {account_email_snapshot}", expanded=False):
            with st.form(f"batch_account_form_{account_id}"):
                account_cols = st.columns(2)
                with account_cols[0]:
                    account_label = st.text_input("Nome da conta", value=account_label_snapshot, key=f"batch_label_{account_id}")
                    account_email = st.text_input("E-mail/Gmail da conta", value=account_email_snapshot if account_email_snapshot != "sem e-mail" else "", key=f"batch_email_{account_id}")
                    account_client_id = st.text_input("OAuth Client ID", value=str(batch_account.get("client_id", "")), key=f"batch_client_id_{account_id}")
                with account_cols[1]:
                    account_client_secret = st.text_input("OAuth Client Secret", value=str(batch_account.get("client_secret", "")), type="password", key=f"batch_client_secret_{account_id}")
                    account_session_info = st.text_input(
                        "sessionInfo token desta conta Google",
                        value=str(batch_account.get("sessionInfo") or batch_account.get("session_info") or batch_account.get("direct_session_info", "")),
                        type="password",
                        key=f"batch_session_info_{account_id}",
                        help="Token sessionInfo usado pelo Upload directo. É guardado por conta e sincronizado no credentials.json; os cookies e restantes valores continuam exclusivamente no documento.",
                    )
                save_account = st.form_submit_button("Guardar dados da conta Google", type="primary", width="stretch")

            st.markdown("**Documento de cookies/credenciais desta conta Google**")
            st.caption("O documento padrão é criado automaticamente. Suba um JSON completo ou apenas o documento de cookies; os valores preenchidos são incorporados e mantidos em credentials.json.")
            document_upload = st.file_uploader(
                "Subir documento de cookies/credenciais",
                type=["json"],
                key=f"direct_credentials_document_{account_id}",
                help="Aceita o JSON do YouTube-Video-Upload-Frontend-Api. Um documento parcial de cookies também é incorporado sem apagar os restantes campos.",
            )
            if missing_document_parts:
                st.warning(f"Documento incompleto: {', '.join(missing_document_parts)}")
            else:
                st.success("Documento completo para a conta Google")
            st.caption(f"Documento guardado em: {direct_status['document_file']}")
            document_save = st.button("Guardar documento nesta conta", key=f"save_direct_account_{account_id}", width="stretch")

            account_status = youtube_batch_account_status(batch_account, STORAGE)
            status_cols = st.columns(3)
            with status_cols[0]:
                (st.success if account_status.ok else st.warning)(account_status.message)
            with status_cols[1]:
                if st.button("Autorizar/Reautorizar", key=f"batch_authorize_settings_{account_id}", width="stretch"):
                    result = authorize_youtube_batch_account(batch_account, STORAGE)
                    (st.success if result.ok else st.error)(result.message)
                    if result.ok:
                        st.rerun()
            with status_cols[2]:
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
                            existing.update({"label": account_label.strip() or "Canais YouTube", "email": account_email.strip(), "client_id": account_client_id.strip(), "client_secret": account_client_secret.strip(), "sessionInfo": account_session_info.strip()})
                            update_credentials_document_session_info(STORAGE, existing, account_session_info.strip())
                            ensure_credentials_document(STORAGE, existing, settings, channel_state)
                    settings["youtube_batch_accounts"] = batch_accounts
                    write_json("settings.json", settings)
                    st.success("Conta Google/YouTube guardada.")
                    st.rerun()

            if document_save:
                if document_upload is None:
                    st.error("Seleccione um documento JSON de cookies/credenciais antes de guardar.")
                else:
                    try:
                        merge_credentials_document(
                            STORAGE,
                            batch_account,
                            document_upload.getvalue(),
                            document_upload.name,
                            session_info_override=str(batch_account.get("sessionInfo") or ""),
                            channels=channel_state,
                        )
                        st.success("Documento incorporado e guardado nesta conta Google.")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

    if youtube_accounts_missing_document:
        st.info("Contas que ainda precisam de dados no documento: " + ", ".join(youtube_accounts_missing_document))

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
    with st.form("innertube_api_key_form"):
        innertube_api_key_value = st.text_input(
            "INNERTUBE_API_KEY",
            value=current_innertube_api_key,
            type="password",
            key="global_innertube_api_key",
            help="Chave global usada pelo Upload directo para todas as contas Google/YouTube. Guarde-a na configuração global, separada dos documentos de cookies.",
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
    st.markdown("### Adicionar outra conta Gmail")
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
        add_account = st.form_submit_button("Adicionar conta Google/YouTube", type="primary", width="stretch")
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
            st.rerun()

    st.divider()
    st.subheader("Configuração Global: YouTube Data API v3 (API Key)")
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

def render_material_source_api_keys(settings: dict[str, Any]) -> None:
    st.subheader("Fontes de materiais")
    st.caption("Seleccione a fonte que será usada na pipeline e guarde uma ou mais API keys. Qualidade, endpoints e parâmetros internos são definidos pelo Thunderbolt.")
    source_catalog = material_source_catalog()
    source_codes = [item["code"] for item in source_catalog] + ["local"]
    source_labels = {item["code"]: item["label"] for item in source_catalog} | {"local": "Ficheiros locais"}
    source_help = {item["code"]: item["description"] for item in source_catalog} | {"local": "Usar materiais já existentes no storage local; não requer API key."}
    selected_source = st.selectbox(
        "Fonte de materiais",
        source_codes,
        index=source_codes.index(selected_material_source(settings)) if selected_material_source(settings) in source_codes else 0,
        format_func=lambda value: source_labels.get(value, value),
        key="material_source_selector",
    )
    st.caption(source_help.get(selected_source, ""))
    current_keys = material_api_keys(settings, selected_source)
    row_key = f"material_source_key_rows_{selected_source}"
    row_count = max(len(current_keys), int(st.session_state.get(row_key, len(current_keys) or 1)))
    if selected_source == "local":
        _render_credential_status("", local=True, required=False)
        st.info("A fonte local não usa API key. Os materiais devem existir na pasta configurada do storage.")
        if st.button("Guardar fonte local", type="primary", key="save_local_material_source"):
            settings["video_source"] = selected_source
            write_json("settings.json", settings)
            st.success("Fonte de materiais guardada: ficheiros locais.")
            st.rerun()
        return
    _render_credential_status(any(str(item or "").strip() for item in current_keys))
    with st.form(f"material_api_keys_form_{selected_source}"):
        key_values: list[str] = []
        for index in range(row_count):
            key_values.append(st.text_input(f"API Key {index + 1}", value=current_keys[index] if index < len(current_keys) else "", type="password", key=f"material_api_key_{selected_source}_{index}"))
        save_keys = st.form_submit_button("Guardar fonte e chaves", type="primary", width="stretch")
        add_key = st.form_submit_button("Adicionar outra chave", width="stretch")
    if add_key:
        st.session_state[row_key] = row_count + 1
        st.rerun()
    if save_keys:
        update_material_api_keys(settings, selected_source, key_values)
        settings["video_source"] = selected_source
        write_json("settings.json", settings)
        st.session_state[row_key] = max(1, len(material_api_keys(settings, selected_source)))
        st.success(f"Fonte {source_labels.get(selected_source, selected_source)} guardada com {len(material_api_keys(settings, selected_source))} chave(s).")
        st.rerun()
    st.caption(f"{len(current_keys)} chave(s) actualmente guardada(s) para {source_labels.get(selected_source, selected_source)}. As chaves são mantidas no storage local e usadas com rotação interna.")


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


def _render_llm_card(settings: dict[str, Any], cards: list[dict[str, Any]], index: int) -> None:
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
        with st.form(f"llm_card_form_{card_id}"):
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
                current_model = str(card.get("model") or "")
                if model_catalog:
                    manual_model = "__manual_model__"
                    options = [manual_model, *[str(item) for item in model_catalog]]
                    selected = st.selectbox(
                        "Modelo",
                        options,
                        index=options.index(current_model) if current_model in options else 0,
                        format_func=lambda value: "Escrever modelo manualmente" if value == manual_model else value,
                        key=f"llm_card_{card_id}_model_select",
                    )
                    model = st.text_input("Modelo manual", value=current_model if selected == manual_model and current_model not in model_catalog else "", key=f"llm_card_{card_id}_model_manual") if selected == manual_model else selected
                else:
                    model = st.text_input("Modelo", value=current_model, help="ID do modelo usado pelo endpoint Chat Completions.", key=f"llm_card_{card_id}_model")
            if definition.show_base_url:
                base_url = st.text_input(
                    "Base URL",
                    value=str(card.get("base_url") or definition.default_base_url),
                    help="Endpoint OpenAI-compatible deste provider; só aparece quando é configurável.",
                    key=f"llm_card_{card_id}_base_url",
                )
            else:
                base_url = str(card.get("base_url") or definition.default_base_url)
                if base_url:
                    st.caption(f"Endpoint gerido pelo provider: {base_url}")
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
            enabled = st.checkbox("Provider activo", value=bool(card.get("enabled", True)), key=f"llm_card_{card_id}_enabled")
            primary_llm = st.checkbox(
                "LLM principal",
                value=str(settings.get(LLM_ACTIVE_CARD_KEY) or "") == card_id,
                help="Usar este cartão como provider principal para geração de temas, roteiros, títulos e keywords.",
                key=f"llm_card_{card_id}_primary",
            )
            telegram_llm = st.checkbox(
                "LLM Telegram",
                value=bool(card.get("telegram_llm", False)),
                help="Usar este cartão exclusivamente para o roteamento de notificações Telegram. Apenas um cartão pode ficar seleccionado.",
                key=f"llm_card_{card_id}_telegram",
            )
            action_cols = st.columns([1.35, 1.35, 1.1])
            with action_cols[0]:
                test_clicked = st.form_submit_button("Testar chamada API", width="stretch")
            with action_cols[1]:
                refresh_clicked = st.form_submit_button("Consultar modelos", width="stretch")
            with action_cols[2]:
                save_clicked = st.form_submit_button("Guardar cartão", type="primary", width="stretch")
            remove_clicked = False
            if definition.code != "openai":
                remove_clicked = st.form_submit_button("Remover cartão", width="stretch")

        edited = dict(card)
        edited.update({"api_key": str(api_key or "").strip(), "model": str(model or "").strip(), "base_url": str(base_url or "").strip(), "enabled": bool(enabled), "telegram_llm": bool(telegram_llm), **extra_values})
        cards[index] = edited
        if test_clicked:
            test_result = test_llm_provider_card(edited)
            edited["test_result"] = stamp_test_result(test_result)
            _persist_llm_cards(settings, cards, str(settings.get(LLM_ACTIVE_CARD_KEY) or card_id))
            if test_result.get("ok"):
                st.success(f"Teste API: {test_result['message']}")
            else:
                st.error(f"Teste API: {test_result['message']}")
        elif refresh_clicked:
            try:
                from integrations.openai_model_discovery import fetch_openai_compatible_models
                discovered = fetch_openai_compatible_models(edited.get("api_key", ""), edited.get("base_url", ""))
                st.session_state[f"llm_model_catalog_{card_id}"] = discovered
                _persist_llm_cards(settings, cards, str(settings.get(LLM_ACTIVE_CARD_KEY) or card_id))
                st.success(f"{len(discovered)} modelo(s) disponíveis neste endpoint.")
            except Exception:
                st.error("Não foi possível consultar os modelos deste endpoint.")
        elif save_clicked:
            active_id = card_id if primary_llm and enabled else str(settings.get(LLM_ACTIVE_CARD_KEY) or "")
            _persist_llm_cards(settings, cards, active_id)
            st.success("Cartão LLM guardado.")
            st.rerun()
        elif remove_clicked:
            remaining = [item for item in cards if str(item.get("id")) != card_id]
            _persist_llm_cards(settings, remaining, str(settings.get(LLM_ACTIVE_CARD_KEY) or ""))
            st.success("Cartão LLM removido.")
            st.rerun()

        saved_test = edited.get("test_result") or card.get("test_result")
        if isinstance(saved_test, dict) and saved_test.get("message"):
            if saved_test.get("status") == "success":
                st.success(f"Último teste: {saved_test['message']}")
            else:
                st.error(f"Último teste: {saved_test['message']}")


def render_llm_provider_cards(settings: dict[str, Any]) -> None:
    """Renderizar cartões LLM fora da form global para permitir acções por cartão."""
    migrated, changed = ensure_llm_provider_cards(settings)
    cards = [dict(item) for item in migrated.get(LLM_CARDS_KEY, [])]
    if changed:
        settings.update(migrated)
        write_json("settings.json", settings)
    with st.expander("LLM — providers e modelos", expanded=False):
        st.caption("Configure cada provider num cartão independente. Pode repetir o mesmo provider para manter várias API keys; o cartão activo é usado pela geração de conteúdo.")
        for index in range(len(cards)):
            _render_llm_card(settings, cards, index)
        st.divider()
        st.markdown("**Adicionar provider LLM**")
        provider_codes = [item.code for item in LLM_PROVIDER_CATALOG]
        provider_to_add = st.selectbox(
            "Provider LLM",
            provider_codes,
            format_func=lambda value: ui_text(provider_definition(value).label, current_ui_language()),
            key="llm_new_provider_choice",
        )
        if st.button("Configurar Novo Provedor LLM", type="primary", width="stretch", key="add_llm_provider_card"):
            new_card = new_llm_card(provider_to_add, card_id=f"llm-{provider_to_add}-{uuid.uuid4().hex[:8]}")
            cards.append(new_card)
            _persist_llm_cards(settings, cards, str(settings.get(LLM_ACTIVE_CARD_KEY) or DEFAULT_LLM_CARD_ID))
            st.rerun()


def render_settings():
    st.title("Configuração API")
    st.caption("Configuração das APIs, providers, serviços e ferramentas técnicas usados pelo Thunderbolt. As credenciais ficam no storage local e não são enviadas para o GitHub.")
    settings = read_json("settings.json", {})

    def text_setting(label: str, key: str, *, secret: bool = False, help_text: str | None = None) -> str:
        return st.text_input(
            label,
            settings.get(key, ""),
            type="password" if secret else "default",
            help=help_text,
            key=f"settings_{key}",
        )

    api_keys_tab, voice_test_tab = render_localized_tabs(["API Keys", "Teste de vozes"])

    with api_keys_tab:
        api_service_tab, material_sources_tab = render_localized_tabs(["Serviços e modelos", "Fontes de materiais"])
        with api_service_tab:
            with st.form("settings_form"):
                st.subheader("API Keys")
                port = st.number_input("Porta Streamlit", 1, 65535, int(settings.get("port", 3030)))
                moneyprinter_path = st.text_input("Pasta do motor de vídeo", settings.get("moneyprinter_path", ""), key="settings_moneyprinter_path")
                with st.expander("Niche Finder — execução remota no Kaggle", expanded=False):
                    st.caption("O dataset permanece no Kaggle. O Thunderbolt usa estas credenciais apenas para publicar/executar a kernel e obter os resultados pequenos da análise.")
                    kaggle_cols = st.columns(3)
                    with kaggle_cols[0]:
                        kaggle_username = text_setting("Kaggle Username", "kaggle_username", help_text="Nome de utilizador da sua conta Kaggle, sem @ e sem URL.")
                    with kaggle_cols[1]:
                        kaggle_api_key = text_setting("Kaggle API Key", "kaggle_api_key", secret=True, help_text="Chave criada em Kaggle > Settings > API. Nunca é incluída no notebook ou no GitHub.")
                    with kaggle_cols[2]:
                        kaggle_kernel_slug = text_setting("Slug da kernel", "kaggle_kernel_slug", help_text="Identificador da kernel remota, por exemplo thunderbolt-niche-finder.")
                    _render_credential_status(kaggle_api_key)

                with st.expander("Niche Finder — execução através da Apify", expanded=False):
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

                with st.expander("Nano Banana — geração de thumbnails", expanded=False):
                    st.caption("A Nano Banana gera a imagem final das thumbnails a partir da variante escolhida. A chave é guardada apenas no storage local e é distinta da chave do Gemini usado como LLM textual.")
                    nano_cols = st.columns(2)
                    with nano_cols[0]:
                        gemini_image_api_key = text_setting("Nano Banana API key", "gemini_image_api_key", secret=True, help_text="Chave criada no Google AI Studio para a API Gemini. Nunca é incluída no código, logs ou pacote.")
                        gemini_image_model = st.selectbox("Modelo Nano Banana", ["gemini-3.1-flash-image", "gemini-3-pro-image", "gemini-2.5-flash-image"], index=["gemini-3.1-flash-image", "gemini-3-pro-image", "gemini-2.5-flash-image"].index(str(settings.get("gemini_image_model") or "gemini-3.1-flash-image")) if str(settings.get("gemini_image_model") or "gemini-3.1-flash-image") in {"gemini-3.1-flash-image", "gemini-3-pro-image", "gemini-2.5-flash-image"} else 0)
                    with nano_cols[1]:
                        gemini_image_aspect_ratio = st.selectbox("Proporção da thumbnail", ["16:9", "9:16", "1:1", "4:5"], index=["16:9", "9:16", "1:1", "4:5"].index(str(settings.get("gemini_image_aspect_ratio") or "16:9")) if str(settings.get("gemini_image_aspect_ratio") or "16:9") in {"16:9", "9:16", "1:1", "4:5"} else 0)
                        gemini_image_size = st.selectbox("Tamanho da imagem", ["1K", "2K", "4K"], index=["1K", "2K", "4K"].index(str(settings.get("gemini_image_size") or "1K")) if str(settings.get("gemini_image_size") or "1K") in {"1K", "2K", "4K"} else 0)
                    _render_credential_status(gemini_image_api_key)


                with st.expander("Voz, TTS e música — Azure Speech, restantes serviços e Suno", expanded=False):
                    cols = st.columns(2)
                    with cols[0]:
                        azure_speech_key = text_setting("Azure Speech key", "azure_speech_key", secret=True)
                        _render_credential_status(azure_speech_key)
                        azure_speech_region = text_setting("Azure Speech region", "azure_speech_region")
                        siliconflow_tts_api_key = text_setting("SiliconFlow TTS API key", "siliconflow_tts_api_key", secret=True)
                        _render_credential_status(siliconflow_tts_api_key)
                        minimax_tts_api_key = text_setting("MiniMax TTS API key", "minimax_tts_api_key", secret=True)
                        _render_credential_status(minimax_tts_api_key)
                        minimax_tts_base_url = text_setting("MiniMax TTS Base URL", "minimax_tts_base_url")
                        minimax_tts_model_id = text_setting("MiniMax TTS model", "minimax_tts_model_id")
                        minimax_tts_voice_id = text_setting("MiniMax TTS voice ID", "minimax_tts_voice_id")
                    with cols[1]:
                        elevenlabs_api_key = text_setting("ElevenLabs API key", "elevenlabs_api_key", secret=True)
                        _render_credential_status(elevenlabs_api_key)
                        elevenlabs_model_id = text_setting("ElevenLabs model", "elevenlabs_model_id")
                        chatterbox_base_url = text_setting("Chatterbox Base URL", "chatterbox_base_url")
                        chatterbox_api_key = text_setting("Chatterbox API key", "chatterbox_api_key", secret=True)
                        _render_credential_status(chatterbox_api_key, local=True, required=False)
                        chatterbox_model_id = text_setting("Chatterbox model", "chatterbox_model_id")
                        sonilo_api_key = text_setting("Sonilo API key", "sonilo_api_key", secret=True)
                        _render_credential_status(sonilo_api_key)
                        sonilo_base_url = text_setting("Sonilo Base URL", "sonilo_base_url")
                        st.markdown("**Suno — agente musical opcional**")
                        suno_api_key = text_setting("Suno API key", "suno_api_key", secret=True)
                        _render_credential_status(suno_api_key)
                        suno_api_base_url = text_setting("Suno API Base URL", "suno_api_base_url", help_text="Use o endpoint compatível fornecido pelo seu acesso Suno; não é inventado pelo Thunderbolt.")
                        suno_api_endpoint = text_setting("Suno API endpoint", "suno_api_endpoint", help_text="Ex.: /api/generate")

                with st.expander("TikTok for Developers — Client ID e Client Secret", expanded=False):
                    st.caption("Apenas as credenciais da aplicação ficam nesta UI. Redirect URI, scopes, autorização e tokens são geridos no TikTok for Developers Playground.")
                    tiktok_client_key = text_setting("TikTok Client ID", "tiktok_client_key", secret=True)
                    _render_credential_status(tiktok_client_key)
                    tiktok_client_secret = text_setting("TikTok Client Secret", "tiktok_client_secret", secret=True)

                with st.expander("Publicação através do Upload-Post", expanded=False):
                    upload_post_enabled = st.checkbox("Activar Upload-Post", bool(settings.get("upload_post_enabled", False)))
                    upload_post_api_key = text_setting("Upload-Post API key", "upload_post_api_key", secret=True)
                    _render_credential_status(upload_post_api_key)
                    upload_post_username = text_setting("Upload-Post username", "upload_post_username")
                    upload_post_platforms = text_setting("Plataformas Upload-Post", "upload_post_platforms")
                    upload_post_auto_upload = st.checkbox("Publicar automaticamente após gerar", bool(settings.get("upload_post_auto_upload", False)))

                with st.expander("Postiz — API key, integração e MCP", expanded=False):
                    st.caption("O Thunderbolt é o cliente. A API key é enviada exclusivamente ao servidor Postiz configurado; não é colocada em URLs, logs ou repositório.")
                    postiz_enabled = st.checkbox("Activar Postiz como fallback final", bool(settings.get("postiz_enabled", False)))
                    postiz_mode = st.selectbox("Modo de ligação", ["api", "mcp"], index=0 if settings.get("postiz_mode", "api") != "mcp" else 1, help="API é o modo determinístico de upload. MCP fica disponível para uma ligação compatível com Streamable HTTP.")
                    postiz_cols = st.columns(2)
                    with postiz_cols[0]:
                        postiz_api_key = text_setting("Postiz API key", "postiz_api_key", secret=True, help_text="API key criada nas definições do Postiz. A API HTTP usa o valor bruto no cabeçalho Authorization.")
                        _render_credential_status(postiz_api_key)
                        postiz_base_url = text_setting("Postiz Public API Base URL", "postiz_base_url", help_text="Cloud: https://api.postiz.com/public/v1 · Self-hosted: https://seu-servidor/api/public/v1")
                        postiz_integration_id = text_setting("Postiz integração padrão", "postiz_integration_id", help_text="ID do canal/integração devolvido por GET /integrations.")
                    with postiz_cols[1]:
                        postiz_mcp_url = text_setting("Postiz MCP URL", "postiz_mcp_url", help_text="Cloud: https://api.postiz.com/mcp · o cliente acrescenta a API key conforme o modo escolhido.")
                        postiz_auto_publish = st.checkbox("Permitir publicação imediata no Postiz", bool(settings.get("postiz_auto_publish", False)))
                    st.caption("No Upload, a aba Postiz permite carregar as integrações e enviar vídeos manualmente. No fluxo recomendado, Postiz só é tentado depois da API Oficial e do Upload directo.")

                save_all_settings = st.form_submit_button("Guardar configurações do Thunderbolt", type="primary")
                if save_all_settings:
                    settings.update({
                        "port": port, "moneyprinter_path": moneyprinter_path,
                        "kaggle_username": kaggle_username.strip(), "kaggle_api_key": kaggle_api_key.strip(), "kaggle_kernel_slug": kaggle_kernel_slug.strip() or "thunderbolt-niche-finder",
                        "apify_api_token": apify_api_token.strip(), "apify_actor_id": apify_actor_id.strip() or DEFAULT_ACTOR_ID, "apify_poll_interval_seconds": int(apify_poll_interval), "apify_run_timeout_seconds": int(apify_run_timeout),
                        "gemini_image_api_key": gemini_image_api_key, "gemini_image_model": gemini_image_model, "gemini_image_aspect_ratio": gemini_image_aspect_ratio, "gemini_image_size": gemini_image_size,
                        "azure_speech_key": azure_speech_key, "azure_speech_region": azure_speech_region,
                        "siliconflow_tts_api_key": siliconflow_tts_api_key, "minimax_tts_api_key": minimax_tts_api_key,
                        "minimax_tts_base_url": minimax_tts_base_url, "minimax_tts_model_id": minimax_tts_model_id, "minimax_tts_voice_id": minimax_tts_voice_id,
                        "elevenlabs_api_key": elevenlabs_api_key, "elevenlabs_model_id": elevenlabs_model_id,
                        "chatterbox_base_url": chatterbox_base_url, "chatterbox_api_key": chatterbox_api_key, "chatterbox_model_id": chatterbox_model_id,
                        "sonilo_api_key": sonilo_api_key, "sonilo_base_url": sonilo_base_url, "suno_api_key": suno_api_key, "suno_api_base_url": suno_api_base_url, "suno_api_endpoint": suno_api_endpoint,
                        "tiktok_client_key": tiktok_client_key, "tiktok_client_secret": tiktok_client_secret,
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
        render_llm_provider_cards(settings)
        with material_sources_tab:
            render_material_source_api_keys(settings)

    with voice_test_tab:
        st.subheader("Teste de vozes")
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


def render_notifications():
    st.title("Notificações")
    st.caption("Centro de notificações internas persistentes do Thunderbolt. As conclusões são guardadas no storage local e aparecem quando a aplicação é actualizada.")
    reconcile_persisted_notifications()
    preferences = notification_preferences()
    catalog = notification_event_catalog()
    notifications = list_notifications(limit=500)
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
    filtered = list_notifications(limit=500, category=category_filter, unread_only=unread_filter)
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


def render_models_ai_tutorial():
    tutorial_url = "https://github.com/gyoridavid/ai_agents_az/blob/main/episode_8/guide-instagram.md"
    tutorial_path = ROOT / "seed" / "references" / "guide-instagram.md"
    st.title("Tutorial Meta")
    st.caption("Guia de configuração de uma conta Instagram profissional e das credenciais Meta para automações com n8n.")
    st.markdown(f"[Abrir fonte original no GitHub]({tutorial_url})")
    try:
        tutorial_content = tutorial_path.read_text(encoding="utf-8").strip()
    except OSError:
        tutorial_content = ""
    if not tutorial_content:
        st.error("O conteúdo local do tutorial não está disponível. Consulte a fonte original no GitHub.")
        return
    st.markdown(tutorial_content, unsafe_allow_html=True)

def render_supabase_tutorial():
    tutorial_url = "https://github.com/gyoridavid/ai_agents_az/blob/main/episode_8/guide-supabase.md"
    tutorial_path = ROOT / "seed" / "references" / "guide-supabase.md"
    ui_language = current_ui_language()
    st.title(ui_text("Tutorial Supabase", ui_language))
    st.caption(ui_text("Guia de configuração do Supabase para automações com n8n.", ui_language))
    st.markdown(f"[Abrir fonte original no GitHub]({tutorial_url})")
    try:
        tutorial_content = tutorial_path.read_text(encoding="utf-8").strip()
    except OSError:
        tutorial_content = ""
    if not tutorial_content:
        st.error("O conteúdo local do tutorial não está disponível. Consulte a fonte original no GitHub.")
        return
    st.markdown(tutorial_content, unsafe_allow_html=True)


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


def main():
    pipeline_video_items = [
        ("Criação de Vídeos", ":material/add_circle:", "Criação de Vídeos"),
        ("Backlog Vídeos", ":material/video_library:", "Backlog Vídeos"),
        ("Roteiros", ":material/article:", "Roteiros"),
        ("Upload", ":material/cloud_upload:", "Upload"),
    ]
    base_files_items = [
        ("Blueprints Youtube", ":material/library_books:", "Blueprints Youtube"),
        ("Prompt Masters", ":material/auto_awesome:", "Prompt Masters"),
    ]
    channel_profile_items = [
        ("Canais YouTube", ":material/ondemand_video:", "Canais YouTube"),
        ("Contas TikTok", ":material/account_circle:", "Contas TikTok"),
        ("Facebook Pages", ":material/public:", "Facebook Pages"),
    ]
    music_items = [
        ("Criação de Músicas", ":material/music_note:", "Criação de Músicas"),
        ("Upload Música", ":material/library_music:", "Upload Música"),
    ]
    models_ai_items = [
        ("Personagens", ":material/person:", "Personagens"),
        ("Geração de Conteúdo IA", ":material/auto_awesome:", "Geração de Conteúdo IA"),
        ("Motion Control", ":material/motion_mode:", "Motion Control"),
        ("UGC Products", ":material/shopping_bag:", "UGC Products"),
        ("Redes Sociais", ":material/share:", "Redes Sociais"),
    ]
    growth_items = [
        ("Analista Growth Youtube", ":material/analytics:", "Analista Growth Youtube"),
        ("Analista Growth Tiktok", ":material/analytics:", "Analista Growth Tiktok"),
        ("Analista Growth Instagram", ":material/analytics:", "Analista Growth Instagram"),
    ]
    documentation_items = [
        ("Tutorial Meta", ":material/menu_book:", "Tutorial Meta"),
        ("Tutorial Supabase", ":material/storage:", "Tutorial Supabase"),
        ("Tutorial Kaggle", ":material/menu_book:", "Tutorial Kaggle"),
        ("Tutorial Apify", ":material/menu_book:", "Tutorial Apify"),
    ]
    settings_items = [
        ("MCP", ":material/hub:", "MCP"),
        ("Contas Google", ":material/account_circle:", "Contas Google"),
        ("Notificações", ":material/notifications:", "Notificações"),
        ("Configuração API", ":material/settings:", "Configuração API"),
    ]
    niche_finder_items = [
        ("Niche Finder Kaggle", ":material/search:", "Niche Finder Kaggle"),
        ("Niche Finder Apify", ":material/api:", "Niche Finder Apify"),
    ]
    automation_items = [
        ("Automação Youtube", ":material/schedule:", "Automação Youtube"),
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
        ("Arquivos Base", ":material/folder:", "Arquivos Base"),
        ("Canais e Perfis de Vídeos", ":material/video_library:", "Canais e Perfis de Vídeos"),
        ("Growth", ":material/analytics:", "Growth"),
        ("Pipeline Vídeos", ":material/account_tree:", "Pipeline Vídeos"),
        ("Pipeline Música", ":material/music_note:", "Pipeline Música"),
        ("AI Influencers", ":material/smart_toy:", "AI Influencers"),
        ("Edição", ":material/edit:", "Edição"),
        ("Documentação", ":material/menu_book:", "Documentação"),
        ("Configurações", ":material/settings:", "Configurações"),
    ]
    groups = {
        "Automação": automation_items,
        "Niche Finder": niche_finder_items,
        "Pipeline Vídeos": pipeline_video_items,
        "AI Influencers": models_ai_items,
        "Arquivos Base": base_files_items,
        "Canais e Perfis de Vídeos": channel_profile_items,
        "Pipeline Música": music_items,
        "Edição": edition_items,
        "Growth": growth_items,
        "Documentação": documentation_items,
        "Configurações": settings_items,
    }
    aliases = {
        "Dashboard": "Início",
        "Novo vídeo": "Criação de Vídeos",
        "Vídeos": "Backlog Vídeos",
        "Limpador de metadado": "Limpador de Metadados",
        "Pipeline": "Pipeline Vídeos",
        "Música": "Pipeline Música",
        "Pipeline TikTok": "Canais e Perfis de Vídeos",
        "Prompts Master": "Prompt Masters",
        "Canais": "Canais YouTube",
        "Canais Youtube": "Canais YouTube",
        "Blueprints": "Blueprints Youtube",
        "Configurações Técnicas": "Configuração API",
        "Models AI": "AI Influencers",
        "Contas Google/YouTube — canais em lote": "Contas Google",
    }
    all_children = [item for items in groups.values() for item in items]
    valid_targets = {item[0] for item in top_pages + all_children}
    current_page = aliases.get(st.session_state.get("page", "Início"), st.session_state.get("page", "Início"))
    if current_page not in valid_targets:
        current_page = "Início"
    st.session_state["page"] = current_page
    ui_language = current_ui_language()
    render_ui_language_picker(ui_language)

    def navigate(target: str):
        st.session_state["page"] = target
        st.rerun()

    def render_nav_button(target: str, icon: str, label: str, scope: str):
        display_label = ui_text(label, ui_language)
        if st.button(display_label, key=f"nav_{scope}_{target}", icon=icon, width="stretch", type="primary" if current_page == target else "secondary"):
            navigate(target)

    with st.sidebar:
        version_markup = f'<span class="tb-brand-version">{APP_VERSION}</span>' if APP_VERSION else ""
        st.markdown(f'<div class="tb-brand"><span class="tb-brand-name">Thunderbolt</span>{version_markup}</div>', unsafe_allow_html=True)
        for target, icon, label in top_pages:
            children = groups.get(target)
            if children is None:
                render_nav_button(target, icon, label, "top")
                continue
            child_targets = {item[0] for item in children}
            with st.expander(ui_text(label, ui_language), expanded=current_page in child_targets, icon=icon):
                for child_target, child_icon, child_label in children:
                    render_nav_button(child_target, child_icon, child_label, target)

    renderers = {
        "Início": render_dashboard,
        "Pipeline Vídeos": render_pipeline,
        "Criação de Vídeos": render_new_video,
        "Backlog Vídeos": render_videos,
        "Criação de Músicas": render_music_creation,
        "Upload Música": lambda: render_edit_placeholder("Upload Música", ""),
        "Roteiros": render_scripts,
        "Upload": render_upload,
        "Blueprints Youtube": render_blueprints,
        "Prompt Masters": render_tiktok_prompt_masters,
        "Canais YouTube": render_channels,
        "Contas TikTok": render_tiktok_accounts,
        "Facebook Pages": lambda: render_edit_placeholder("Facebook Pages", ""),
        "Automação Youtube": render_automation,
        "Niche Finder Kaggle": render_niche_finder,
        "Tutorial Kaggle": lambda: render_edit_placeholder("Tutorial Kaggle", ""),
        "Niche Finder Apify": render_niche_finder_apify,
        "Tutorial Apify": lambda: render_edit_placeholder("Tutorial Apify", ""),
        "Edição": lambda: render_edit_placeholder("Edição", "Seleccione uma das abas de edição no menu expansível."),
        "Limpador de Metadados": render_metadata_cleaner,
        "Cortes": render_cuts,
        "Editor Python": render_python_editor,
        "Download Mídia": render_media_download,
        "AI Influencers": lambda: render_edit_placeholder("AI Influencers", "Seleccione uma das abas AI Influencers no menu expansível."),
        "Personagens": lambda: render_edit_placeholder("Personagens", "Área reservada para a futura funcionalidade de personagens."),
        "Geração de Conteúdo IA": lambda: render_edit_placeholder("Geração de Conteúdo IA", ""),
        "Motion Control": lambda: render_edit_placeholder("Motion Control", ""),
        "UGC Products": lambda: render_edit_placeholder("UGC Products", ""),
        "Redes Sociais": lambda: render_edit_placeholder("Redes Sociais", "Área reservada para a futura funcionalidade de redes sociais."),
        "Analista Growth Youtube": lambda: render_edit_placeholder("Analista Growth Youtube", ""),
        "Analista Growth Tiktok": lambda: render_edit_placeholder("Analista Growth Tiktok", ""),
        "Analista Growth Instagram": lambda: render_edit_placeholder("Analista Growth Instagram", ""),
        "Documentação": lambda: render_edit_placeholder("Documentação", "Seleccione um tutorial no menu expansível."),
        "Tutorial Meta": render_models_ai_tutorial,
        "Tutorial Supabase": render_supabase_tutorial,
        "Configurações": lambda: render_edit_placeholder("Configurações", "Seleccione uma opção no menu expansível."),
        "MCP": render_mcp,
        "Contas Google": render_google_accounts,
        "Configuração API": render_settings,
        "Notificações": render_notifications,
    }
    try:
        reconcile_persisted_notifications()
    except Exception:
        pass
    renderers.get(current_page, render_dashboard)()

if __name__ == "__main__":
    main()
