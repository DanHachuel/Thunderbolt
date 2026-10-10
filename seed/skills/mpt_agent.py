#!/usr/bin/env python3
"""Cross-platform installation and video generation for the MoneyPrinterTurbo Skill."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ARCHIVE_URL = (
    "https://github.com/harry0703/MoneyPrinterTurbo/archive/refs/heads/main.zip"
)
DEFAULT_ROOT = Path.home() / "MoneyPrinterTurbo"
MOVIEPY_REQUIREMENT = "moviepy==2.2.1"
CHUNKED_SYNTHESIS_TIMEOUT_SECONDS = 15 * 60
DEPENDENCY_SYNC_TIMEOUT_SECONDS = 15 * 60
DEFAULT_VOICE_NAME = "zh-CN-XiaoxiaoNeural-Female"
NEEDS_INPUT_EXIT_CODE = 10
SUPPORTED_SOURCES = {"pexels", "pixabay", "coverr", "local"}
PEXELS_API_KEY_URL = "https://www.pexels.com/api/"
PEXELS_VALIDATION_URL = "https://api.pexels.com/v1/collections?per_page=1"
PEXELS_API_KEY_HELP_URL = (
    "https://help.pexels.com/hc/en-us/articles/"
    "900004904026-How-do-I-get-an-API-key"
)

# Keep the recommended list focused on commonly used providers. When an LLM
# key is missing, the helper emits all choices at once to avoid extra turns.
RECOMMENDED_LLM_PROVIDERS = {
    "moonshot": (
        "Kimi / Moonshot AI",
        "https://platform.kimi.com?track_id=track-2f5441d6ffd84c509dd079d78e9db5dc&aff=moneyprinterturbo",
    ),
    "openai": ("OpenAI", "https://platform.openai.com/api-keys"),
    "gemini": ("Google Gemini", "https://aistudio.google.com/app/apikey"),
    "deepseek": ("DeepSeek", "https://platform.deepseek.com/api_keys"),
    "volcengine": (
        "ByteDance VolcEngine Ark / Doubao",
        "https://www.volcengine.com/activity/ai618?utm_source=MoneyPrinterTurbo",
    ),
    "minimax": ("MiniMax", "https://platform.minimax.io/"),
    "mimo": (
        "Xiaomi MiMo",
        "https://platform.xiaomimimo.com/docs/zh-CN/quick-start/first-api-call",
    ),
}
KEYLESS_LLM_PROVIDERS = {"ollama", "litellm"}
CUSTOM_OPENAI_PROVIDER = "oneapi"

# Hidden providers such as Qwen, Azure, and Grok remain usable when already
# selected, but are not automatic fallback candidates. A fully configured
# generic OpenAI-compatible endpoint can be reused safely.
ADDITIONAL_REUSABLE_PROVIDERS = (CUSTOM_OPENAI_PROVIDER,)


class SkillError(RuntimeError):
    """An actionable Skill error that can be reported without a traceback."""


def log(message: str) -> None:
    """Flush concise progress so the agent knows the long-running job started."""
    print(f"[MoneyPrinterTurbo] {message}", flush=True)


def _atomic_write_text(path: Path, text: str) -> None:
    """Replace a text file atomically so an interrupted Windows write keeps the old file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except Exception:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install MoneyPrinterTurbo and generate a final video from a topic."
    )
    parser.add_argument("--subject", required=True, help="video topic")
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help=f"MoneyPrinterTurbo installation directory (default: {DEFAULT_ROOT})",
    )
    parser.add_argument(
        "cli_args",
        nargs=argparse.REMAINDER,
        help="additional MoneyPrinterTurbo CLI arguments placed after --",
    )
    args = parser.parse_args(argv)
    args.subject = args.subject.strip()
    if not args.subject:
        parser.error("--subject cannot be empty")
    if args.cli_args and args.cli_args[0] == "--":
        args.cli_args = args.cli_args[1:]
    return args


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    """Reject ZIP entries that would escape the temporary extraction directory."""
    destination = destination.resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        if target != destination and destination not in target.parents:
            raise SkillError(f"project archive contains an unsafe path: {member.filename}")
    archive.extractall(destination)


def ensure_project(root: Path) -> None:
    """Reuse an existing project or install it from the official GitHub archive."""
    root = root.expanduser().resolve()
    if (root / "cli.py").is_file() and (root / "config.example.toml").is_file():
        log(f"using existing project: {root}")
        return
    if root.exists() and any(root.iterdir()):
        raise SkillError(f"installation directory exists but is not a valid project: {root}")

    root.parent.mkdir(parents=True, exist_ok=True)
    log(f"first-time installation: downloading the official project to {root}")
    with tempfile.TemporaryDirectory(prefix="mpt-install-") as temp_dir_value:
        temp_dir = Path(temp_dir_value)
        archive_path = temp_dir / "MoneyPrinterTurbo.zip"
        request = urllib.request.Request(
            PROJECT_ARCHIVE_URL,
            headers={"User-Agent": "MoneyPrinterTurbo-Agent-Skill"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            # Stream the archive to avoid holding a second full copy in memory.
            with archive_path.open("wb") as archive_file:
                shutil.copyfileobj(response, archive_file)
        with zipfile.ZipFile(archive_path) as archive:
            _safe_extract(archive, temp_dir)

        candidates = [
            path
            for path in temp_dir.iterdir()
            if path.is_dir() and (path / "cli.py").is_file()
        ]
        if len(candidates) != 1:
            raise SkillError("download completed but no valid MoneyPrinterTurbo project was found")
        if root.exists():
            root.rmdir()
        shutil.move(str(candidates[0]), str(root))
    log("project download completed")


def ensure_config(root: Path) -> Path:
    """Create the initial configuration without overwriting an existing file."""
    config_path = root / "config.toml"
    if not config_path.exists():
        shutil.copy2(root / "config.example.toml", config_path)
        log(f"created configuration file: {config_path}")
    return config_path


def _plain_config_value(text: str, key: str) -> str:
    """Read a simple top-level TOML value without printing its contents."""
    match = re.search(rf"(?m)^{re.escape(key)}\s*=\s*(.*)$", text)
    if not match:
        return ""
    value = match.group(1).split("#", 1)[0].strip()
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value


def _replace_config_value(text: str, key: str, value: object) -> str:
    """Replace one active field while preserving the configuration layout."""
    pattern = re.compile(rf"(?m)^({re.escape(key)}\s*=\s*).*$")
    if not pattern.search(text):
        raise SkillError(f"configuration field not found in config.toml: {key}")
    encoded = json.dumps(value, ensure_ascii=False)
    return pattern.sub(lambda match: f"{match.group(1)}{encoded}", text, count=1)


def _replace_toml_section_value(text: str, section: str, key: str, value: object) -> str:
    """Replace or append a scalar value inside one TOML section."""
    encoded = json.dumps(value, ensure_ascii=False)
    section_pattern = re.compile(
        rf"(?ms)^\[{re.escape(section)}\][ \t]*(?:\n|$)(.*?)(?=^\[|\Z)"
    )
    section_match = section_pattern.search(text)
    if section_match is None:
        separator = "" if not text.strip() else "\n\n"
        return f"{text.rstrip()}{separator}[{section}]\n{key} = {encoded}\n"
    body = section_match.group(1)
    value_pattern = re.compile(rf"(?m)^({re.escape(key)}\s*=\s*).*$")
    if value_pattern.search(body):
        updated_body = value_pattern.sub(
            lambda match: f"{match.group(1)}{encoded}", body, count=1
        )
    else:
        updated_body = f"{body.rstrip()}\n{key} = {encoded}\n"
    return f"{text[:section_match.start(1)]}{updated_body}{text[section_match.end(1):]}"


def _has_configured_value(value: str) -> bool:
    """Treat empty strings and whitespace-only key arrays as unconfigured."""
    if not value:
        return False
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return bool(value.strip())
    if isinstance(parsed, list):
        return any(str(item).strip() for item in parsed)
    return bool(str(parsed).strip())


def _parse_string_list(value: str) -> list[str]:
    """Parse a configured string list while removing blanks and duplicates."""
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in parsed if str(item).strip()))


def apply_environment_config(config_path: Path) -> None:
    """Write supplied credentials while logging field names only."""
    provider = os.environ.get("MPT_LLM_PROVIDER", "").strip().lower()
    if provider == "openai_compatible":
        provider = CUSTOM_OPENAI_PROVIDER
    llm_key = os.environ.get("MPT_LLM_API_KEY", "").strip()
    base_url = os.environ.get("MPT_LLM_BASE_URL", "").strip()
    model_name = os.environ.get("MPT_LLM_MODEL_NAME", "").strip()
    pexels_key = os.environ.get("MPT_PEXELS_API_KEY", "").strip()
    pixabay_key = os.environ.get("MPT_PIXABAY_API_KEY", "").strip()
    azure_speech_key = os.environ.get("MPT_AZURE_SPEECH_KEY", "").strip()
    azure_speech_region = os.environ.get("MPT_AZURE_SPEECH_REGION", "").strip()
    pexels_keys = _parse_string_list(os.environ.get("MPT_PEXELS_API_KEYS", ""))
    pixabay_keys = _parse_string_list(os.environ.get("MPT_PIXABAY_API_KEYS", ""))
    if not pexels_keys and pexels_key:
        pexels_keys = [pexels_key]
    if not pixabay_keys and pixabay_key:
        pixabay_keys = [pixabay_key]
    if not any((provider, llm_key, base_url, model_name, pexels_keys, pixabay_keys, azure_speech_key, azure_speech_region)):
        return

    text = config_path.read_text(encoding="utf-8")
    current_provider = _plain_config_value(text, "llm_provider") or "moonshot"
    provider = provider or current_provider
    changes: list[str] = []
    if os.environ.get("MPT_LLM_PROVIDER", "").strip():
        text = _replace_config_value(text, "llm_provider", provider)
        changes.append("llm_provider")
    if llm_key:
        text = _replace_config_value(text, f"{provider}_api_key", llm_key)
        changes.append(f"{provider}_api_key")
    if base_url:
        text = _replace_config_value(text, f"{provider}_base_url", base_url)
        changes.append(f"{provider}_base_url")
    if model_name:
        text = _replace_config_value(text, f"{provider}_model_name", model_name)
        changes.append(f"{provider}_model_name")
    if pexels_keys:
        text = _replace_config_value(text, "pexels_api_keys", pexels_keys)
        changes.append("pexels_api_keys")
    if pixabay_keys:
        text = _replace_config_value(text, "pixabay_api_keys", pixabay_keys)
        changes.append("pixabay_api_keys")
    if azure_speech_key:
        text = _replace_toml_section_value(text, "azure", "speech_key", azure_speech_key)
        changes.append("azure.speech_key")
    if azure_speech_region:
        text = _replace_toml_section_value(text, "azure", "speech_region", azure_speech_region)
        changes.append("azure.speech_region")
    _atomic_write_text(config_path, text)
    log("updated configuration fields: " + ", ".join(changes))


def _provider_is_ready(text: str, provider: str) -> bool:
    """Return whether a provider has enough configuration to generate."""
    if provider in KEYLESS_LLM_PROVIDERS:
        return True
    if not _has_configured_value(
        _plain_config_value(text, f"{provider}_api_key")
    ):
        return False
    if provider == CUSTOM_OPENAI_PROVIDER:
        return all(
            _has_configured_value(_plain_config_value(text, f"{provider}_{suffix}"))
            for suffix in ("base_url", "model_name")
        )
    return True


def reuse_existing_llm_provider(config_path: Path) -> str:
    """
    Reuse existing LLM credentials before asking the user for another key.

    Keep the current provider when it is ready. Otherwise, scan configured
    recommended providers in UI order and update ``llm_provider``. Credential
    values are inspected in memory and are never logged.
    """
    text = config_path.read_text(encoding="utf-8")
    current_provider = _plain_config_value(text, "llm_provider") or "moonshot"
    if _provider_is_ready(text, current_provider):
        return current_provider

    reusable_providers = (
        *RECOMMENDED_LLM_PROVIDERS,
        *ADDITIONAL_REUSABLE_PROVIDERS,
    )
    for provider in reusable_providers:
        if _provider_is_ready(text, provider):
            text = _replace_config_value(text, "llm_provider", provider)
            _atomic_write_text(config_path, text)
            log(f"reusing configured LLM provider: {provider}")
            return provider
    return current_provider


def selected_video_source(cli_args: list[str]) -> str:
    """Read the effective material source from forwarded CLI arguments."""
    for index, item in enumerate(cli_args):
        if item == "--video-source" and index + 1 < len(cli_args):
            return cli_args[index + 1].strip().lower()
        if item.startswith("--video-source="):
            return item.split("=", 1)[1].strip().lower()
    return "pexels"


def has_cli_option(cli_args: list[str], option: str) -> bool:
    """Return whether forwarded arguments explicitly set a CLI option."""
    return any(item == option or item.startswith(f"{option}=") for item in cli_args)


def supported_cli_options(root: Path, uv: str) -> dict[str, bool] | None:
    """Map each option of the installed cli.py to whether it consumes a value.

    MoneyPrinterTurbo evolves independently of Thunderbolt: forwarding an
    option that the installed cli.py does not know yet aborts argparse with
    "unrecognized arguments" before any pipeline stage runs. Detection is
    best-effort — on any failure we return None and forward everything,
    preserving the legacy behaviour.
    """
    try:
        result = subprocess.run(
            [uv, "run", "python", "cli.py", "--help"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
            creationflags=_windows_process_group_flags(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = "\n".join(part for part in (result.stdout, result.stderr) if part)
    if result.returncode != 0 or not text.strip():
        return None
    options: dict[str, bool] = {}
    # Only lines that start with an option string belong to the argparse
    # options section; epilog examples and continuation lines are ignored.
    # Genuine definitions are parsed before the epilog, so the OR-merge
    # below can never downgrade a value-taking option to a flag.
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("--"):
            continue
        matches = list(re.finditer(r"--[a-z0-9][a-z0-9-]*", stripped))
        if not matches:
            continue
        tail = stripped[matches[-1].end():].split()
        takes_value = bool(tail) and (
            tail[0].startswith("{") or re.fullmatch(r"[A-Z][A-Z0-9_]*", tail[0].rstrip(",")) is not None
        )
        for match in matches:
            option = match.group(0)
            previous = options.get(option)
            options[option] = takes_value if previous is None else (previous or takes_value)
    return options or None


def filter_forwarded_args(cli_args: list[str], supported: dict[str, bool] | None) -> list[str]:
    """Drop forwarded options the installed cli.py does not support yet.

    Unknown options are skipped together with their value, so an older
    MoneyPrinterTurbo install keeps generating with its own default for that
    option instead of failing the whole video generation.
    """
    if supported is None:
        return list(cli_args)
    filtered: list[str] = []
    index = 0
    while index < len(cli_args):
        token = str(cli_args[index])
        if not token.startswith("--"):
            filtered.append(token)
            index += 1
            continue
        takes_value = supported.get(token)
        if takes_value is None:
            log(f"ignoring option unsupported by this cli.py: {token}")
            index += 1
            if index < len(cli_args) and not str(cli_args[index]).startswith("--"):
                index += 1
            continue
        filtered.append(token)
        index += 1
        if takes_value and index < len(cli_args) and not str(cli_args[index]).startswith("--"):
            filtered.append(str(cli_args[index]))
            index += 1
    return filtered


def _toml_section_value(config_path: Path, section: str, key: str) -> str:
    """Read one nested TOML value without logging the value or its contents."""
    try:
        payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ""
    section_payload = payload.get(section)
    if not isinstance(section_payload, dict):
        return ""
    value = section_payload.get(key, "")
    return str(value or "").strip()


def _forwarded_option_value(cli_args: list[str], option: str) -> str:
    for index, item in enumerate(cli_args):
        if item == option and index + 1 < len(cli_args):
            return str(cli_args[index + 1]).strip()
        if item.startswith(f"{option}="):
            return item.split("=", 1)[1].strip()
    return ""


def _azure_v2_voice(cli_args: list[str]) -> str:
    """Return the unmarked Azure voice when this invocation requests Azure V2."""
    voice = _forwarded_option_value(cli_args, "--voice-name")
    if "-v2" not in voice.casefold():
        return ""
    base_voice = re.sub("-v2", "", voice, count=1, flags=re.IGNORECASE).strip()
    return re.sub(r"-(Female|Male)$", "", base_voice, flags=re.IGNORECASE).strip()
def _voice_rate(cli_args: list[str]) -> float:
    value = _forwarded_option_value(cli_args, "--voice-rate")
    try:
        return float(value) if value else 1.0
    except ValueError:
        return 1.0


def _prepare_azure_v2_chunked_audio(
    root: Path,
    config_path: Path,
    task_dir: Path,
    cli_args: list[str],
    uv: str,
) -> Path | None:
    """Create task-local audio in chunks before MPT starts its normal pipeline."""
    voice = _azure_v2_voice(cli_args)
    text = _forwarded_option_value(cli_args, "--video-script")
    if not voice or not text.strip():
        return None
    speech_key = _toml_section_value(config_path, "azure", "speech_key")
    speech_region = _toml_section_value(config_path, "azure", "speech_region")
    if not speech_key or not speech_region:
        raise SkillError("Azure Speech SDK V2 foi seleccionado, mas as credenciais não estão completas.")
    text_file = task_dir / "azure-v2-script.txt"
    audio_file = task_dir / "azure-v2-audio.mp3"
    text_file.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(text_file, text.strip() + "\n")
    chunk_script = Path(__file__).with_name("azure_tts_chunked.py")
    command = [
        uv,
        "run",
        "--project",
        str(root),
        "python",
        str(chunk_script),
        "--text-file",
        str(text_file),
        "--output",
        str(audio_file),
        "--voice",
        voice,
        "--rate",
        str(_voice_rate(cli_args)),
    ]
    environment = os.environ.copy()
    environment["AZURE_SPEECH_KEY"] = speech_key
    environment["AZURE_SPEECH_REGION"] = speech_region
    ffmpeg_path = _toml_section_value(config_path, "app", "ffmpeg_path")
    if ffmpeg_path:
        environment["IMAGEIO_FFMPEG_EXE"] = ffmpeg_path
    try:
        result = subprocess.run(
            command,
            cwd=root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            check=False,
            timeout=CHUNKED_SYNTHESIS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise SkillError(
            "A síntese segmentada Azure Speech SDK V2 excedeu 15 minutos; "
            "a chamada monolítica não será usada."
        ) from exc
    chunk_match = re.search(r"(?m)^AZURE_CHUNK_COUNT=(\d+)$", result.stdout or "")
    if not chunk_match:
        detail = "\n".join((result.stdout or "").splitlines()[-12:]).strip()
        detail = detail.replace(speech_key, "[redacted]").replace(speech_region, "[redacted]")
        raise SkillError(
            "Azure Speech SDK V2 não confirmou segmentos e áudio customizado. "
            + (detail or "O helper não devolveu detalhes.")
        )
    if result.returncode != 0 or not audio_file.is_file() or audio_file.stat().st_size <= 0:
        detail = "\n".join((result.stdout or "").splitlines()[-12:]).strip()
        detail = detail.replace(speech_key, "[redacted]").replace(speech_region, "[redacted]")
        raise SkillError(
            "Azure Speech SDK V2 falhou na síntese segmentada. "
            + (detail or "O helper não devolveu detalhes.")
        )
    chunk_count = int(chunk_match.group(1))
    if chunk_count <= 0:
        raise SkillError("Azure Speech SDK V2 não confirmou segmentos de áudio válidos.")
    _atomic_write_text(
        audio_file.with_suffix(".json"),
        json.dumps(
            {
                "status": "completed",
                "audio_file": str(audio_file.resolve()),
                "chunk_count": chunk_count,
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
    )
    log(f"Azure Speech V2 segmentado: {chunk_count} segmentos; áudio customizado preparado")
    return audio_file.resolve()


def missing_config(config_path: Path, cli_args: list[str]) -> tuple[str, list[str]]:
    """Return the active provider and only the fields required by this run."""
    text = config_path.read_text(encoding="utf-8")
    provider = _plain_config_value(text, "llm_provider") or "moonshot"
    missing: list[str] = []
    if provider not in KEYLESS_LLM_PROVIDERS and not _has_configured_value(
        _plain_config_value(text, f"{provider}_api_key")
    ):
        missing.append(f"{provider}_api_key")
    if provider == CUSTOM_OPENAI_PROVIDER:
        for suffix in ("base_url", "model_name"):
            field = f"{provider}_{suffix}"
            if not _has_configured_value(_plain_config_value(text, field)):
                missing.append(field)

    source = selected_video_source(cli_args)
    if source not in SUPPORTED_SOURCES:
        raise SkillError(f"unsupported video source: {source}")
    if source != "local":
        value = _plain_config_value(text, f"{source}_api_keys")
        if not _has_configured_value(value):
            missing.append(f"{source}_api_keys")
    return provider, missing


def report_missing_config(provider: str, missing: list[str]) -> int:
    """Tell the agent exactly which credentials must be requested."""
    print("MPT_NEEDS_INPUT")
    print(f"LLM_PROVIDER={provider}")
    for field in missing:
        print(f"MISSING={field}")
    if any(field.endswith("_api_key") for field in missing):
        print("LLM_PROVIDER_OPTIONS_BEGIN")
        for provider_id, (label, url) in RECOMMENDED_LLM_PROVIDERS.items():
            print(f"LLM_PROVIDER_OPTION={provider_id}|{label}|{url}")
        print(
            "LLM_PROVIDER_OPTION=oneapi|Other OpenAI-compatible provider|"
            "requires an API key, API base URL, and model name"
        )
        print("LLM_PROVIDER_OPTIONS_END")
    if any(field.startswith(f"{CUSTOM_OPENAI_PROVIDER}_") for field in missing):
        print(
            "OPENAI_COMPATIBLE_REQUIRED="
            "API key, API base URL, model name"
        )
    if "pexels_api_keys" in missing:
        print(f"PEXELS_API_KEY_URL={PEXELS_API_KEY_URL}")
        print(f"PEXELS_API_KEY_HELP_URL={PEXELS_API_KEY_HELP_URL}")
    print("Request only the listed values, set the environment variables, and rerun the same command.")
    return NEEDS_INPUT_EXIT_CODE


def report_invalid_pexels_config() -> int:
    """Request only a new Pexels key when every configured key is rejected."""
    print("MPT_NEEDS_INPUT")
    print("INVALID=pexels_api_keys")
    print(f"PEXELS_API_KEY_URL={PEXELS_API_KEY_URL}")
    print(f"PEXELS_API_KEY_HELP_URL={PEXELS_API_KEY_HELP_URL}")
    print("All configured Pexels API keys were rejected or are unavailable. Provide a new key.")
    return NEEDS_INPUT_EXIT_CODE


def _validate_pexels_key(api_key: str) -> str:
    """
    Return ``valid``, ``rejected``, or ``unknown`` for a Pexels key.

    HTTP 401, 403, and rate-limited 429 responses make a key unusable for this
    run. Network and server errors return unknown so the configuration is kept.
    """
    # Curated and popular search requests may hit a public cache and return 200
    # without valid authorization. My Collections is account-specific, requires
    # authentication, and still returns 200 for an empty collection list.
    request = urllib.request.Request(
        PEXELS_VALIDATION_URL,
        headers={
            "Authorization": api_key,
            "User-Agent": "MoneyPrinterTurbo-Agent-Skill",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return "valid" if 200 <= response.status < 300 else "unknown"
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403, 429}:
            return "rejected"
        return "unknown"
    except (TimeoutError, urllib.error.URLError, OSError, http.client.HTTPException):
        return "unknown"


def validate_pexels_config(config_path: Path, cli_args: list[str]) -> bool:
    """
    Validate all Pexels keys used by the default material source.

    Downstream code selects configured keys randomly. Keeping rejected keys can
    cause intermittent 401 responses and missing material results. If at least
    one key is verified, retain only verified keys. If validation is impossible
    because of a transient network failure, keep the original configuration.
    """
    if selected_video_source(cli_args) != "pexels":
        return True

    text = config_path.read_text(encoding="utf-8")
    keys = _parse_string_list(_plain_config_value(text, "pexels_api_keys"))
    if not keys:
        return False

    valid_keys: list[str] = []
    rejected_count = 0
    unknown_count = 0
    for api_key in keys:
        status = _validate_pexels_key(api_key)
        if status == "valid":
            valid_keys.append(api_key)
        elif status == "rejected":
            rejected_count += 1
        else:
            unknown_count += 1

    if valid_keys:
        if valid_keys != keys:
            text = _replace_config_value(text, "pexels_api_keys", valid_keys)
            _atomic_write_text(config_path, text)
        log(
            "Pexels key validation completed: "
            f"valid={len(valid_keys)}, rejected={rejected_count}, "
            f"unknown={unknown_count}"
        )
        return True
    if unknown_count:
        log("Pexels keys could not be verified due to a network or service error; keeping the existing configuration")
        return True

    log(f"Pexels key validation failed: all {rejected_count} configured keys are unusable")
    return False


def result_manifest_path(root: Path) -> Path:
    return root / ".agent-logs" / "moneyprinterturbo-video" / "latest-result.json"


def write_result_manifest(root: Path, payload: dict[str, object]) -> Path:
    """
    Atomically write the stable result file for agents that cannot wait.

    The file contains task status and result paths only, never configuration
    contents, credentials, or full logs.
    """
    result_path = result_manifest_path(root)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    unique_suffix = str(uuid.uuid4()).replace("-", "")
    temp_path = result_path.with_name(
        f".{result_path.name}.{os.getpid()}.{unique_suffix}.tmp"
    )
    temp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temp_path.replace(result_path)
    return result_path.resolve()

def _windows_process_group_flags() -> int:
    """Windows: consola SEPARADA para a árvore uv/MPT/ffmpeg (0.9.81).

    Evidência forense: 3 timestamps ao segundo entre o fecho de logs MPT e
    launcher_exiting ctrl+c — subprocessos desta árvore emitem CTRL_C_EVENT
    à consola quando terminam. DETACHED_PROCESS cria uma consola separada:
    qualquer sinal gerado internamente (uv, ffmpeg, Python) fica isolado e
    nunca chega ao launcher. CREATE_NEW_PROCESS_GROUP assegura que Ctrl+C
    do grupo 0 também não interrompa a renderização.
    """
    if os.name != "nt":
        return 0
    return subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP


def _ignore_console_ctrl_c() -> None:
    """Windows: ignora CTRL_C_EVENT (o pipeline termina via TerminateProcess)."""
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleCtrlHandler(None, True)
    except (OSError, AttributeError, ImportError):
        pass


def run_checked(command: list[str], *, cwd: Path) -> None:
    """Run dependency sync with a bounded wait and safe failure output."""
    log("installing or verifying project dependencies with uv")
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            check=False,
            timeout=DEPENDENCY_SYNC_TIMEOUT_SECONDS,
            creationflags=_windows_process_group_flags(),
        )
    except subprocess.TimeoutExpired as exc:
        raise SkillError(
            "A verificação das dependências com uv excedeu 15 minutos; "
            "a execução foi interrompida."
        ) from exc
    output = result.stdout or ""
    for key in ("MPT_LLM_API_KEY", "MPT_PEXELS_API_KEY", "MPT_PIXABAY_API_KEY", "AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION"):
        secret = os.environ.get(key, "").strip()
        if secret:
            output = output.replace(secret, "[redacted]")
    if result.returncode != 0:
        output_tail = "\n".join(output.splitlines()[-30:]).strip()
        raise SkillError(
            f"dependency installation failed with exit code {result.returncode}. "
            + (f"Detalhe do uv: {output_tail}" if output_tail else "O uv não devolveu detalhes.")
        )
    log("project dependencies verified with uv")


def ensure_moviepy(root: Path, uv: str) -> None:
    """Ensure the render engine matches MoneyPrinterTurbo's MoviePy release."""
    run_checked(
        [
            uv,
            "run",
            "--with",
            MOVIEPY_REQUIREMENT,
            "python",
            "-c",
            "import importlib.metadata; print(f\"moviepy {importlib.metadata.version('moviepy')}\")",
        ],
        cwd=root,
    )


def generate_video(
    root: Path,
    subject: str,
    cli_args: list[str],
) -> tuple[list[Path], Path, Path, Path]:
    """Run one traceable CLI task and return only its final video files."""
    uv = shutil.which("uv")
    if not uv:
        raise SkillError("uv was not found; reopen the terminal or add uv to PATH")
    run_checked([uv, "sync", "--frozen"], cwd=root)
    ensure_moviepy(root, uv)
    config_path = ensure_config(root)
    # As opções encaminhadas dependem da versão instalada do cli.py: opções
    # recentes (estilo completo de legendas, transições, …) são ignoradas em
    # instalações mais antigas em vez de abortarem o argparse.
    cli_args = filter_forwarded_args(cli_args, supported_cli_options(root, uv))

    task_id = str(uuid.uuid4())
    task_dir = root / "storage" / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    log_dir = root / ".agent-logs" / "moneyprinterturbo-video"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"run-{task_id}.log"
    write_result_manifest(
        root,
        {
            "status": "running",
            "subject": subject,
            "task_id": task_id,
            "task_dir": str(task_dir.resolve()),
            "log_file": str(log_path.resolve()),
            "video_files": [],
        },
    )
    voice_args = (
        []
        if has_cli_option(cli_args, "--voice-name")
        else ["--voice-name", DEFAULT_VOICE_NAME]
    )
    forwarded_args = list(cli_args)
    azure_v2_requested = bool(_azure_v2_voice(forwarded_args))
    custom_audio_requested = has_cli_option(forwarded_args, "--custom-audio-file")
    if azure_v2_requested and not custom_audio_requested:
        chunked_audio = _prepare_azure_v2_chunked_audio(
            root,
            config_path,
            task_dir,
            forwarded_args,
            uv,
        )
        if chunked_audio is None or not chunked_audio.is_file() or chunked_audio.stat().st_size <= 0:
            raise SkillError(
                "Azure Speech SDK V2 não produziu áudio segmentado; "
                "a geração foi interrompida para não usar a chamada monolítica."
            )
        forwarded_args.extend(["--custom-audio-file", str(chunked_audio.resolve())])
    elif azure_v2_requested and custom_audio_requested:
        custom_audio_value = _forwarded_option_value(forwarded_args, "--custom-audio-file")
        custom_audio_path = Path(custom_audio_value).expanduser()
        if not custom_audio_value or not custom_audio_path.is_file() or custom_audio_path.stat().st_size <= 0:
            raise SkillError(
                "Azure Speech SDK V2 recebeu um áudio customizado inválido; "
                "a geração foi interrompida para não usar a chamada monolítica."
            )
    command = [
        uv,
        "run",
        "--with",
        MOVIEPY_REQUIREMENT,
        "python",
        "cli.py",
        *forwarded_args,
        "--video-subject",
        subject,
        "--task-id",
        task_id,
        # Older CLI versions leave voice_name empty and fail during Edge TTS
        # with ``Invalid voice ''``. Supply a stable Chinese voice unless the
        # user has explicitly selected another voice.
        *voice_args,
        # A Skill request must produce a finished video. Force the final stage
        # so forwarded options cannot stop at script, audio, or materials.
        "--stop-at",
        "video",
    ]
    log(f"starting video generation, task ID: {task_id}")
    log(f"full generation log: {log_path}")
    with log_path.open("w", encoding="utf-8") as log_file:
        result = subprocess.run(
            command,
            cwd=root,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            creationflags=_windows_process_group_flags(),
        )
    if result.returncode != 0:
        tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]
        if tail:
            print("\n".join(tail), file=sys.stderr)
        error = (
            f"video generation failed with exit code {result.returncode}; "
            f"log: {log_path}"
        )
        write_result_manifest(
            root,
            {
                "status": "failed",
                "subject": subject,
                "task_id": task_id,
                "task_dir": str(task_dir.resolve()),
                "log_file": str(log_path.resolve()),
                "video_files": [],
                "error": error,
            },
        )
        raise SkillError(error)

    videos = sorted(
        path.resolve()
        for path in task_dir.glob("final-*.mp4")
        if path.is_file() and path.stat().st_size > 0
    )
    if not videos:
        error = f"generation completed without a valid final MP4; log: {log_path}"
        write_result_manifest(
            root,
            {
                "status": "failed",
                "subject": subject,
                "task_id": task_id,
                "task_dir": str(task_dir.resolve()),
                "log_file": str(log_path.resolve()),
                "video_files": [],
                "error": error,
            },
        )
        raise SkillError(error)
    result_path = write_result_manifest(
        root,
        {
            "status": "completed",
            "subject": subject,
            "task_id": task_id,
            "task_dir": str(task_dir.resolve()),
            "log_file": str(log_path.resolve()),
            "video_files": [str(video) for video in videos],
        },
    )
    return videos, task_dir.resolve(), log_path.resolve(), result_path


def main(argv: list[str] | None = None) -> int:
    _ignore_console_ctrl_c()
    args = parse_args(argv)
    root = args.root.expanduser().resolve()
    try:
        ensure_project(root)
        config_path = ensure_config(root)
        apply_environment_config(config_path)
        reuse_existing_llm_provider(config_path)
        provider, missing = missing_config(config_path, args.cli_args)
        if missing:
            write_result_manifest(
                root,
                {
                    "status": "needs_input",
                    "subject": args.subject,
                    "missing": missing,
                },
            )
            return report_missing_config(provider, missing)
        if not validate_pexels_config(config_path, args.cli_args):
            write_result_manifest(
                root,
                {
                    "status": "needs_input",
                    "subject": args.subject,
                    "invalid": ["pexels_api_keys"],
                },
            )
            return report_invalid_pexels_config()
        videos, task_dir, log_path, result_path = generate_video(
            root, args.subject, args.cli_args
        )
    except (OSError, SkillError, urllib.error.URLError, zipfile.BadZipFile) as exc:
        manifest_path = result_manifest_path(root)
        try:
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
        except (OSError, json.JSONDecodeError):
            manifest_payload = {}
        if manifest_payload.get("status") == "running":
            manifest_payload.update({"status": "failed", "error": str(exc)[:1000]})
            write_result_manifest(root, manifest_payload)
        for output_key, manifest_key in (("TASK_DIR", "task_dir"), ("LOG_FILE", "log_file"), ("RESULT_FILE", "result_file")):
            value = str(manifest_payload.get(manifest_key) or "").strip()
            if value:
                print(f"{output_key}={value}", file=sys.stderr)
        print(f"MPT_ERROR={exc}", file=sys.stderr)
        return 1

    print("MPT_RESULT")
    for video in videos:
        print(f"VIDEO_FILE={video}")
    print(f"TASK_DIR={task_dir}")
    print(f"LOG_FILE={log_path}")
    print(f"RESULT_FILE={result_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
