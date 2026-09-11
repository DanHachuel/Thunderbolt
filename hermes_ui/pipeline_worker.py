import os
import sys
import io

os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"
_original_stdout, _original_stderr = sys.stdout, sys.stderr
if getattr(sys.stdout, "buffer", None) is not None and str(getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "_") != "utf_8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
if getattr(sys.stderr, "buffer", None) is not None and str(getattr(sys.stderr, "encoding", "") or "").lower().replace("-", "_") != "utf_8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

import json
import queue
import re
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from integrations.moneyprinter_config import sync_moneyprinter_config
from integrations.session_info_health import check_all_accounts_session_info_health, emit_session_info_health_alerts
from integrations.upload_routing import resolve_youtube_account, upload_with_default_route
from hermes_ui.creative_generation import CreativeGenerationError, generate_creative_package, generate_title_and_keywords, generate_thumbnail_prompt, generate_topic_for_channel
from hermes_ui.script_documents import save_script_document
from hermes_ui.script_generation import generate_script_document
from hermes_ui.storage import STORAGE, atomic_write, ensure_storage, get_display_name, list_blueprint_files, load_blueprint_file, read_json, write_json
from hermes_ui.llm_providers import active_llm_card, provider_definition
from hermes_ui.media_generation import MediaGenerationError, _append_generation_constraints, generate_image_from_pool, generate_video_from_pool
from hermes_ui.media_providers import FULL_IA_VIDEO_PROVIDER_CODES, media_cards_for_pool, media_provider_definition
from hermes_ui.material_sources import material_api_keys, material_source_cards, selected_material_source
from hermes_ui.thumbnail_generation import ThumbnailGenerationError, generate_thumbnail_image, infer_thumbnail_aspect_ratio
from hermes_ui.thumbnail_blueprints import thumbnail_blueprint_for_channel
from hermes_ui.voice_preview import synthesize_preview

PIPELINE_LOCK_FILENAME = "pipeline_worker.lock"
PIPELINE_LOG_FILENAME = "pipeline_worker.json"
VIDEO_TIMEOUT_SECONDS = 20 * 60
LONG_STOCK_VIDEO_TIMEOUT_SECONDS = 90 * 60
VIDEO_IDLE_TIMEOUT_SECONDS = 10 * 60
# O helper do MoneyPrinterTurbo pode ficar silencioso durante downloads/API.
# Mantemos uma janela de inactividade maior para Pixabay, sem remover o watchdog.
STOCK_VIDEO_IDLE_TIMEOUT_SECONDS = 30 * 60
STALE_TASK_SECONDS = VIDEO_TIMEOUT_SECONDS + 5 * 60
WORKER_HEARTBEAT_TIMEOUT_SECONDS = 15
CASCADE_STAGE_ORDER = ("topic", "script", "title", "keywords", "video", "thumbnail_prompt", "thumbnail", "upload")


class PipelineError(RuntimeError):
    """Raised when a pipeline stage cannot complete with an actionable error."""

    def __init__(
        self,
        message: str,
        *,
        failure_metadata: dict[str, Any] | None = None,
        fallback_eligible: bool = False,
    ):
        super().__init__(message)
        self.failure_metadata = dict(failure_metadata or {})
        self.fallback_eligible = bool(fallback_eligible)


class PipelineStopped(PipelineError):
    """Raised when the user stops a task while the worker is processing it."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _settings() -> dict[str, Any]:
    value = read_json("settings.json", {})
    return value if isinstance(value, dict) else {}


def _generate_pipeline_thumbnail(
    settings: dict[str, Any],
    prompt: str,
    *,
    topic: str,
    variant_index: int = 0,
    lettering_text: str = "",
    lettering_prompt: str = "",
    thumbnail_blueprint: dict[str, Any] | None = None,
) -> Path:
    """Use the image pool while keeping the legacy single-Nano call seam."""
    cards = media_cards_for_pool(settings, "image")
    if len(cards) == 1 and str(cards[0].get("provider") or "") == "nano_banana":
        return generate_thumbnail_image(
            settings,
            prompt,
            topic=topic,
            variant_index=variant_index,
            lettering_text=lettering_text,
            lettering_prompt=lettering_prompt,
            aspect_ratio=infer_thumbnail_aspect_ratio(prompt, thumbnail_blueprint),
            lock_aspect_ratio=True,
        )
    return generate_image_from_pool(
        settings,
        prompt,
        topic=topic,
        variant_index=variant_index,
        lettering_text=lettering_text,
        lettering_prompt=lettering_prompt,
        thumbnail_blueprint=thumbnail_blueprint,
    )


def _lock_path() -> Path:
    ensure_storage()
    return STORAGE / "state" / PIPELINE_LOCK_FILENAME


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _acquire_lock() -> Path | None:
    path = _lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            old_pid = int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            old_pid = 0
        if _pid_alive(old_pid):
            return None
        try:
            path.unlink()
        except OSError:
            return None
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return None
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii"))
    finally:
        os.close(descriptor)
    return path


def _write_worker_state(**updates: Any) -> None:
    state = read_json(PIPELINE_LOG_FILENAME, {})
    if not isinstance(state, dict):
        state = {}
    state.update(updates)
    state["updated_at"] = _now()
    write_json(PIPELINE_LOG_FILENAME, state)


def _worker_heartbeat(**updates: Any) -> None:
    _write_worker_state(
        worker_pid=os.getpid(),
        last_heartbeat_at=_now(),
        **updates,
    )


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def load_pipeline_worker_status() -> dict[str, Any]:
    """Return the persisted worker heartbeat for the Backlog UI."""
    status = read_json(PIPELINE_LOG_FILENAME, {})
    if not isinstance(status, dict):
        status = {}
    heartbeat_at = _parse_timestamp(status.get("last_heartbeat_at"))
    status["alive"] = bool(
        heartbeat_at
        and (datetime.now(timezone.utc) - heartbeat_at.astimezone(timezone.utc)).total_seconds()
        <= WORKER_HEARTBEAT_TIMEOUT_SECONDS
    )
    return status


def _recover_stale_tasks() -> list[str]:
    """Convert abandoned doing tasks to failed after the worker timeout window."""
    from hermes_ui.domain import update_task

    recovered: list[str] = []
    current_time = datetime.now(timezone.utc)
    for task in read_json("tasks.json", []):
        if not isinstance(task, dict) or str(task.get("state") or "") != "doing":
            continue
        updated_at = _parse_timestamp(task.get("updated_at"))
        if not updated_at:
            continue
        age_seconds = (current_time - updated_at.astimezone(timezone.utc)).total_seconds()
        timeout_seconds = _task_stale_timeout_seconds(task)
        if age_seconds <= timeout_seconds:
            continue
        task_id = str(task.get("id") or "")
        if not task_id:
            continue
        message = (
            f"A tarefa ficou sem heartbeat durante mais de {timeout_seconds // 60} minutos. "
            "Foi marcada como falhada para evitar execução eterna; reveja o log do worker."
        )
        failed_stage = str(task.get("stage") or "pipeline")
        metadata = _failure_attribution(task, _settings(), failed_stage, error=message)
        update_task(task_id, {"state": "failed", "error": _failure_message(message, metadata), "failed_stage": failed_stage, **metadata})
        recovered.append(task_id)
    return recovered


def recover_stale_tasks() -> list[str]:
    """Public wrapper used by the UI to recover tasks after an abrupt worker exit."""
    return _recover_stale_tasks()


def _task_by_id(task_id: str) -> dict[str, Any] | None:
    return next((task for task in read_json("tasks.json", []) if isinstance(task, dict) and task.get("id") == task_id), None)


def _cascade_metadata(current: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    """Build resumable orchestration metadata for one stage transition."""
    previous = str(current.get("stage") or "")
    next_stage = str(updates.get("stage") or previous)
    raw = current.get("orchestration") if isinstance(current.get("orchestration"), dict) else {}
    completed = [str(item) for item in raw.get("completed_stages", []) if str(item) in CASCADE_STAGE_ORDER]
    if previous in CASCADE_STAGE_ORDER and next_stage != previous and previous not in completed:
        completed.append(previous)
    if str(updates.get("state") or "") == "done" and next_stage in CASCADE_STAGE_ORDER and next_stage not in completed:
        completed.append(next_stage)
    transition_at = raw.get("last_transition_at") or _now()
    if next_stage != previous:
        transition_at = _now()
    try:
        transition_count = int(raw.get("transition_count") or 0)
    except (TypeError, ValueError):
        transition_count = 0
    return {
        "name": "local-cascade",
        "stage_order": list(CASCADE_STAGE_ORDER),
        "current_stage": next_stage,
        "completed_stages": completed,
        "resumable": True,
        "last_transition_at": transition_at,
        "transition_count": transition_count + (1 if next_stage != previous else 0),
    }

def _update(task_id: str, **updates: Any) -> dict[str, Any]:
    from hermes_ui.domain import update_task
    current = _task_by_id(task_id)
    if not current:
        raise PipelineError(f"Tarefa {task_id} deixou de existir durante a execução.")
    if str(current.get("state") or "") in {"blocked", "cancelled"}:
        raise PipelineStopped("A tarefa foi parada pelo utilizador.")
    updates = dict(updates)
    if "progress" in updates:
        try:
            previous_progress = max(0, min(100, int(current.get("progress") or 0)))
        except (TypeError, ValueError):
            previous_progress = 0
        try:
            requested_progress = max(0, min(100, int(updates.get("progress") or 0)))
        except (TypeError, ValueError):
            requested_progress = previous_progress
        # A geração pode ser retomada a partir de um checkpoint avançado,
        # enquanto o subprocesso expõe uma faixa própria para a etapa actual.
        # Nunca deixar a percentagem persistida recuar evita a oscilação visual
        # e mantém o card fiel ao maior avanço já confirmado.
        updates["progress"] = max(previous_progress, requested_progress)
    updates["orchestration"] = _cascade_metadata(current, updates)
    updated = update_task(task_id, updates)
    if not updated:
        raise PipelineError(f"Tarefa {task_id} deixou de existir durante a execução.")
    _worker_heartbeat(
        task_id=task_id,
        status="running",
        stage=str(updated.get("stage") or "pipeline"),
        progress=int(updated.get("progress") or 0),
        orchestration=updated.get("orchestration") or {},
    )
    return updated


def _next_runnable_task(tasks: Any) -> dict[str, Any] | None:
    """Return the first active task, excluding saved scripts awaiting Start."""
    if not isinstance(tasks, list):
        return None
    return next(
        (
            task
            for task in tasks
            if isinstance(task, dict)
            and (
                task.get("state") == "doing"
                or (task.get("state") == "to_do" and not bool(task.get("manual_start_required", False)))
            )
        ),
        None,
    )


def _channel_for_task(task: dict[str, Any]) -> dict[str, Any]:
    channel_id = str(task.get("channel_id") or "")
    return next((channel for channel in read_json("channels.json", []) if str(channel.get("id")) == channel_id), {})


def _blueprint_for_channel(channel: dict[str, Any]) -> dict[str, Any]:
    """Resolve the Blueprint assigned to a channel from the persisted library files."""
    blueprint_id = str(channel.get("default_blueprint_id") or channel.get("blueprint_id") or "").strip()
    blueprint_name = ""
    if not blueprint_id and not blueprint_name:
        return {}
    for path in list_blueprint_files():
        try:
            data = load_blueprint_file(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        display_name = get_display_name("blueprints", path, str(data.get("name") or data.get("title") or path.stem))
        identifiers = {
            str(data.get("id") or "").strip(),
            path.stem,
            str(data.get("name") or "").strip(),
            display_name,
        }
        if blueprint_id in identifiers or blueprint_name in identifiers:
            resolved = dict(data)
            resolved.setdefault("id", blueprint_id or path.stem)
            resolved["name"] = display_name
            return resolved
    return {"id": blueprint_id, "name": blueprint_name or blueprint_id}


def _keywords(topic: str, title: str, niche: str = "") -> list[str]:
    """Derive deterministic SEO keywords when the LLM does not return a keyword list."""
    source = f"{title} {topic} {niche}".casefold()
    words = re.findall(r"[\wÀ-ÿ]{4,}", source, flags=re.UNICODE)
    blocked = {"para", "como", "sobre", "mais", "esse", "esta", "that", "this", "with", "from", "video"}
    result: list[str] = []
    for word in words:
        if word in blocked or word in result:
            continue
        result.append(word)
    return result[:15]


def _save_json_artifact(task_id: str, name: str, payload: dict[str, Any]) -> str:
    """Persist a resumable pipeline artifact atomically."""
    directory = STORAGE / "artifacts"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{task_id}-{name}.json"
    atomic_write(path, payload)
    return str(path)


def _configured_moneyprinter_root(settings: dict[str, Any]) -> Path | None:
    """Resolve the installed MoneyPrinterTurbo project selected by the user."""
    configured = str(settings.get("moneyprinter_path") or os.environ.get("MONEYPRINTER_PATH") or "").strip()
    if not configured:
        return None
    root = Path(configured).expanduser().resolve()
    if not (root / "cli.py").is_file():
        raise PipelineError(f"A pasta configurada do MoneyPrinterTurbo não contém cli.py: {root}")
    if not ((root / "config.toml").is_file() or (root / "config.example.toml").is_file()):
        raise PipelineError(f"A pasta configurada do MoneyPrinterTurbo não contém config.toml: {root}")
    return root


def _helper_output_value(output: str, key: str) -> str:
    match = re.search(rf"(?m)^{re.escape(key)}=(.+)$", output)
    return match.group(1).strip() if match else ""


def _redact_helper_output(text: str) -> str:
    for key in ("MPT_LLM_API_KEY", "MPT_PEXELS_API_KEY", "MPT_PIXABAY_API_KEY", "AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION"):
        secret = os.environ.get(key, "").strip()
        if secret:
            text = text.replace(secret, "[redacted]")
    return text

def _terminal_helper_detail(output: str) -> str:
    """Return concise actionable failure lines, never startup or path markers."""
    raw_lines = [_redact_helper_output(line).strip() for line in str(output or "").splitlines()]
    lines = [line for line in raw_lines if line]
    metadata_prefixes = ("TASK_DIR=", "LOG_FILE=", "RESULT_FILE=", "VIDEO_FILE=")
    noise_markers = ("using existing project:", "updated configuration fields:", "starting video generation, task id:", "installing or verifying project dependencies with uv", "pexels key validation completed:")
    useful = [line for line in lines if not line.startswith(metadata_prefixes) and not any(marker in line.casefold() for marker in noise_markers)]
    failure_markers = ("mpt_error=", "traceback", "exception", "error", "failed", "falhou", "failure", "missing", "invalid", "timeout", "timed out", "not found", "exceeded", "excedeu")
    failures = [line for line in useful if any(marker in line.casefold() for marker in failure_markers)]
    return "\n".join((failures or useful)[-8:]).strip()


def _helper_failure_markers(output: str) -> dict[str, Any]:
    missing = [item.strip() for item in re.findall(r"(?m)^MISSING=(.+)$", output) if item.strip()]
    invalid = [item.strip() for item in re.findall(r"(?m)^INVALID=(.+)$", output) if item.strip()]
    return {
        "helper_provider": _helper_output_value(output, "LLM_PROVIDER"),
        "missing_fields": list(dict.fromkeys(missing)),
        "invalid_fields": list(dict.fromkeys(invalid)),
    }


def _provider_api_label(provider: str) -> str:
    code = str(provider or "").strip().casefold()
    if code in {"pexels", "pixabay"}:
        return f"{code.capitalize()} API"
    if code in {"local", "local_storage"}:
        return "Ficheiro local"
    return f"{provider_definition(code).label} API"


def _is_azure_long_audio_error(text: str) -> bool:
    combined = str(text or "").casefold()
    duration_marker = any(
        marker in combined
        for marker in (
            "600000ms",
            "600000 ms",
            "maximum media duration",
            "maximum audio length",
        )
    )
    code_marker = any(marker in combined for marker in ("error code: 1007", "error code=1007", "code 1007"))
    speech_marker = any(marker in combined for marker in ("azure", "speech synthesis", "speech sdk", "tts"))
    return speech_marker and (duration_marker or code_marker)


def _failure_attribution(
    task: dict[str, Any],
    settings: dict[str, Any],
    stage: str,
    *,
    error: str = "",
    output: str = "",
) -> dict[str, Any]:
    """Return safe, human-readable API attribution for every pipeline failure."""
    route = _normalise_video_route(task, settings)
    markers = _helper_failure_markers(output)
    missing = list(markers["missing_fields"])
    invalid = list(markers["invalid_fields"])
    provider_code = str(markers["helper_provider"] or "").strip().casefold()
    combined = f"{output} {error}".casefold()

    if stage == "video" and _is_azure_long_audio_error(combined):
        return {
            "failure_api": "Azure Speech SDK V2 API",
            "failure_provider": "azure_speech",
            "failure_service": "Narração TTS — limite de 600000 ms",
            "failure_route": route,
            "failure_config_fields": "",
            "failure_stage": stage,
        }

    if stage == "video" and any(marker in combined for marker in ("azure speech sdk v2", "azure speech v2", "azure_tts_v2")):
        return {
            "failure_api": "Azure Speech SDK V2 API",
            "failure_provider": "azure_speech",
            "failure_service": "Narração TTS — segmentação Azure",
            "failure_route": route,
            "failure_config_fields": "",
            "failure_stage": stage,
        }

    if stage == "video" and any(marker in combined for marker in ("edge_tts", "edge tts", "azure_tts_v1", "azure speech")):
        return {
            "failure_api": "Azure Speech / edge_tts API",
            "failure_provider": "azure_speech, edge_tts",
            "failure_service": "Narração TTS",
            "failure_route": route,
            "failure_config_fields": "",
            "failure_stage": stage,
        }

    if stage == "video" and missing:
        api_labels: list[str] = []
        provider_values: list[str] = []
        for field in [*missing, *invalid]:
            if field.endswith("_api_keys"):
                source = field.removesuffix("_api_keys")
                label = _provider_api_label(source)
                provider_values.append(source)
            elif field.endswith("_api_key"):
                source = field.removesuffix("_api_key")
                label = _provider_api_label(source)
                provider_values.append(source)
            else:
                label = field
            if label not in api_labels:
                api_labels.append(label)
        return {
            "failure_api": " + ".join(api_labels) or _provider_api_label(route),
            "failure_provider": ", ".join(dict.fromkeys(provider_values or ([provider_code] if provider_code else [route]))),
            "failure_service": "MoneyPrinterTurbo",
            "failure_route": route,
            "failure_config_fields": ", ".join(dict.fromkeys([*missing, *invalid])),
            "failure_stage": stage,
        }

    if stage == "video" and route in {"pexels", "pixabay"}:
        return {
            "failure_api": _provider_api_label(route),
            "failure_provider": route,
            "failure_service": "MoneyPrinterTurbo",
            "failure_route": route,
            "failure_config_fields": f"{route}_api_keys",
            "failure_stage": stage,
        }
    if stage == "video" and route == "full_ia":
        providers = [
            (code, media_provider_definition(code).label)
            for code in FULL_IA_VIDEO_PROVIDER_CODES
        ]
        found = [label for code, label in providers if code in combined or label.casefold() in combined]
        labels = found or [label for _, label in providers]
        codes = [code for code, label in providers if label in labels] or [code for code, _ in providers]
        return {
            "failure_api": " / ".join(f"{label} API" for label in labels),
            "failure_provider": ", ".join(codes),
            "failure_service": "Pool de vídeo Full IA",
            "failure_route": route,
            "failure_config_fields": "",
            "failure_stage": stage,
        }
    if stage in {"topic", "script", "title", "keywords", "thumbnail_prompt"}:
        card = active_llm_card(settings)
        provider = str(card.get("provider") or provider_code or "openai").strip()
        return {
            "failure_api": _provider_api_label(provider),
            "failure_provider": provider,
            "failure_service": "LLM textual",
            "failure_route": route,
            "failure_config_fields": "",
            "failure_stage": stage,
        }
    if stage == "thumbnail":
        cards = media_cards_for_pool(settings, "image")
        labels = []
        codes = []
        for card in cards:
            code = str(card.get("provider") or "").strip().casefold()
            if not code:
                continue
            label = _provider_api_label(code)
            if code in combined or label.casefold() in combined or len(cards) == 1:
                labels.append(label)
                codes.append(code)
        if not labels:
            labels = [_provider_api_label(str(card.get("provider") or "imagem")) for card in cards] or ["Pool Imagem API"]
            codes = [str(card.get("provider") or "").strip() for card in cards if card.get("provider")] or ["image_pool"]
        return {
            "failure_api": " / ".join(labels),
            "failure_provider": ", ".join(codes),
            "failure_service": "Pool de imagem",
            "failure_route": route,
            "failure_config_fields": "",
            "failure_stage": stage,
        }
    if stage == "upload":
        return {
            "failure_api": "YouTube Upload API",
            "failure_provider": "youtube_upload",
            "failure_service": "Upload",
            "failure_route": route,
            "failure_config_fields": "",
            "failure_stage": stage,
        }
    return {
        "failure_api": "API não identificada (falha anterior)",
        "failure_provider": provider_code or "unknown",
        "failure_service": "Thunderbolt",
        "failure_route": route,
        "failure_config_fields": ", ".join(dict.fromkeys([*missing, *invalid])),
        "failure_stage": stage or "pipeline",
    }


def _failure_message(message: str, metadata: dict[str, Any]) -> str:
    api = str(metadata.get("failure_api") or "API não identificada").strip()
    provider = str(metadata.get("failure_provider") or "").strip()
    fields = str(metadata.get("failure_config_fields") or "").strip()
    suffix = f" API/provider: {api}"
    if provider and provider.casefold() not in api.casefold():
        suffix += f" (provider: {provider})"
    if fields:
        suffix += f"; configuração: {fields}"
    return f"{message.rstrip('.')} —{suffix}."


def _persist_video_diagnostics(task: dict[str, Any], output: str) -> dict[str, str]:
    """Persist bounded helper diagnostics and a safe terminal summary."""
    task_id = str(task.get("id") or "").strip()
    if not task_id:
        return {}
    log_file = _helper_output_value(output, "LOG_FILE")
    result_file = _helper_output_value(output, "RESULT_FILE")
    terminal_detail = _terminal_helper_detail(output)
    try:
        markers = _helper_failure_markers(output)
        payload: dict[str, Any] = {
            "captured_at": _now(),
            "log_file": log_file,
            "result_file": result_file,
            "output_tail": _redact_helper_output(output[-6000:]),
            "terminal_detail": terminal_detail,
            "helper_provider": markers["helper_provider"],
            "missing_fields": markers["missing_fields"],
            "invalid_fields": markers["invalid_fields"],
        }
        artifact_path = _save_json_artifact(task_id, "video-diagnostics", payload)
        current = _task_by_id(task_id) or task
        artifacts = dict(current.get("artifacts") or {})
        artifacts["video_diagnostics"] = artifact_path
        updates: dict[str, Any] = {
            "artifacts": artifacts,
            "video_diagnostic_summary": terminal_detail,
        }
        if log_file:
            updates["video_log"] = log_file
            artifacts["video_log"] = log_file
        if result_file:
            updates["video_result"] = result_file
            artifacts["video_result"] = result_file
        from hermes_ui.domain import update_task
        update_task(task_id, updates)
        return {"log_file": log_file, "result_file": result_file, "artifact": artifact_path}
    except Exception:
        # Diagnostics must never hide the actual generation error.
        return {"log_file": log_file, "result_file": result_file}


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        try:
            process_id = getattr(process, "pid", None)
            if os.name != "nt" and process_id:
                os.killpg(os.getpgid(process_id), signal.SIGKILL)
            elif os.name == "nt" and process_id:
                subprocess.run(
                    ["taskkill", "/PID", str(process_id), "/T", "/F"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                process.kill()
        except (OSError, ProcessLookupError):
            process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _normalise_video_route(task: dict[str, Any], settings: dict[str, Any]) -> str:
    """Resolve the per-task source without conflating stock, AI and music routes."""
    generation_settings = task.get("generation_settings") if isinstance(task.get("generation_settings"), dict) else {}
    if bool(task.get("music_mode")):
        return "music"
    explicit_source = str(
        task.get("material_source")
        or generation_settings.get("material_source")
        or generation_settings.get("video_material_source")
        or ""
    ).strip().casefold()
    if explicit_source in {"pexels", "pixabay", "local"}:
        return explicit_source
    raw = str(task.get("style_wide") or generation_settings.get("video_source") or "pexels").strip().casefold()
    if raw in {"full_ia", "full ia", "full-ai", "ai", "ia"}:
        return "full_ia"
    if raw in {"music", "apenas música", "apenas musica", "only music"}:
        return "music"
    if raw in {"pixabay", "pixabay only"}:
        return "pixabay"
    if raw in {"pexels", "pexels/pixabay", "stock", "materials", "materiales"}:
        configured = selected_material_source(settings)
        return configured if configured in {"pexels", "pixabay"} else "pexels"
    return raw if raw in {"pexels", "pixabay", "local"} else "pexels"


def _material_video_attempts(task: dict[str, Any], settings: dict[str, Any]) -> list[tuple[str, str]]:
    """Return one stock attempt per configured key in persisted priority order."""
    route = _normalise_video_route(task, settings)
    if route not in {"pexels", "pixabay"}:
        return [(route, "")]

    has_explicit_cards = isinstance(settings.get("material_source_cards"), list) and bool(settings.get("material_source_cards"))
    attempts: list[tuple[str, str]] = []
    for card in material_source_cards(settings, enabled_only=True) if has_explicit_cards else []:
        provider = str(card.get("provider") or "").strip().casefold()
        api_key = str(card.get("api_key") or "").strip()
        if provider not in {"pexels", "pixabay"} or not api_key:
            continue
        attempts.append((provider, api_key))

    # A selected source is an explicit preference for this task. Its individual
    # keys remain in their configured priority order before other providers.
    preferred = [item for item in attempts if item[0] == route]
    fallback = [item for item in attempts if item[0] != route]
    ordered = preferred + fallback
    if ordered:
        # Uma execução do helper já recebe a lista de chaves do provider
        # configurado; não repetir o mesmo provider por cada cartão/key.
        # Repetições anteriores reinstalavam dependências e produziam cascatas
        # como Pexels → Pexels → Pixabay sem acrescentar uma estratégia real.
        unique: list[tuple[str, str]] = []
        seen: set[str] = set()
        for provider, api_key in ordered:
            if provider in seen:
                continue
            seen.add(provider)
            unique.append((provider, api_key))
        return unique
    # Legacy settings keep the complete key list in one config field. Let
    # MoneyPrinterTurbo retain its own list handling when no individual cards
    # are available, preserving backwards compatibility for older installs.
    return [(route, "")]


def _material_video_routes(task: dict[str, Any], settings: dict[str, Any]) -> list[str]:
    """Return provider names for compatibility with diagnostics and callers."""
    return [provider for provider, _api_key in _material_video_attempts(task, settings)]


def _video_timeout_seconds(task: dict[str, Any], settings: dict[str, Any] | None = None) -> int:
    """Reserve extra bounded time for long stock-video downloads and assembly."""
    effective_settings = settings if isinstance(settings, dict) else _settings()
    route = _normalise_video_route(task, effective_settings)
    script = str(task.get("video_script") or "").strip()
    if route == "pixabay" or (route == "pexels" and len(script) >= 1_200):
        return max(VIDEO_TIMEOUT_SECONDS, LONG_STOCK_VIDEO_TIMEOUT_SECONDS)
    return VIDEO_TIMEOUT_SECONDS


def _video_idle_timeout_seconds(task: dict[str, Any], settings: dict[str, Any] | None = None) -> int:
    """Allow Pixabay downloads to stay quiet without treating them as hung."""
    configured = VIDEO_IDLE_TIMEOUT_SECONDS
    if configured <= 0:
        return configured
    effective_settings = settings if isinstance(settings, dict) else _settings()
    route = _normalise_video_route(task, effective_settings)
    if route == "pixabay":
        return max(configured, STOCK_VIDEO_IDLE_TIMEOUT_SECONDS)
    if route == "pexels":
        return max(configured, STOCK_VIDEO_IDLE_TIMEOUT_SECONDS)
    return configured


def _task_stale_timeout_seconds(task: dict[str, Any]) -> int:
    """Keep stale-task recovery aligned with the actual execution budget."""
    if str(task.get("stage") or "").strip().casefold() == "video":
        settings = _settings()
        attempts = max(1, len(_material_video_routes(task, settings)))
        return _video_timeout_seconds(task, settings) * attempts + 5 * 60
    return STALE_TASK_SECONDS


def _latest_helper_log_activity(log_path: Path | None, previous_mtime: float) -> tuple[float, bool]:
    """Return whether the helper's file log advanced without reading its content."""
    if log_path is None:
        return previous_mtime, False
    try:
        current_mtime = log_path.stat().st_mtime
    except OSError:
        return previous_mtime, False
    return (current_mtime, current_mtime > previous_mtime)


def _mpt_aspect_ratio(value: Any, format_value: Any = "") -> str:
    raw = str(value or format_value or "").strip().casefold()
    if raw in {"landscape 16:9", "wide", "16:9", "landscape"}:
        return "16:9"
    if raw in {"square 1:1", "square", "1:1"}:
        return "1:1"
    return "9:16"


def _mpt_concat_mode(value: Any) -> str:
    raw = str(value or "").strip().casefold()
    return "sequential" if raw in {"sequential", "sequential concatenation", "ordem sequencial"} else "random"


def _mpt_transition_mode(value: Any) -> str:
    raw = str(value or "").strip().casefold()
    return {"fade": "fade-in", "dissolve": "fade-out", "fade-in": "fade-in", "fade-out": "fade-out"}.get(raw, "none")


def _mpt_percent(value: Any, fallback: float = 1.0) -> str:
    raw = str(value or "").strip().replace("%", "")
    try:
        return str(max(0.0, min(2.0, float(raw) / 100.0)))
    except ValueError:
        return str(fallback)


def _valid_audio_artifact(value: Any) -> Path | None:
    path = _valid_artifact_path(value)
    if path is None or path.suffix.lower() not in {'.mp3', '.mpeg', '.wav', '.m4a', '.aac', '.flac', '.ogg'}:
        return None
    return path


def _mpt_rate(value: Any, fallback: float = 1.0) -> str:
    raw = str(value or "").strip().casefold().replace("x", "")
    try:
        return str(max(0.1, float(raw)))
    except ValueError:
        return str(fallback)


def _mpt_video_language(value: Any) -> str:
    """Convert common Thunderbolt labels to the language codes accepted by MPT."""
    raw = str(value or "").strip()
    folded = raw.casefold()
    aliases = {
        "português": "pt-BR", "portugues": "pt-BR", "português (brasil)": "pt-BR",
        "portuguese": "pt-BR", "inglês": "en-US", "ingles": "en-US", "english": "en-US",
        "espanhol": "es-ES", "español": "es-ES", "francês": "fr-FR", "frances": "fr-FR",
        "alemão": "de-DE", "alemao": "de-DE", "italiano": "it-IT", "japonês": "ja-JP",
        "japones": "ja-JP", "mandarim": "zh-CN", "chinês": "zh-CN", "chines": "zh-CN",
    }
    if folded in aliases:
        return aliases[folded]
    return raw if re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z]{2,4})?", raw) else ""


def _uses_azure_speech_sdk_v2(
    generation_settings: dict[str, Any],
    settings: dict[str, Any] | None = None,
) -> bool:
    service = str(generation_settings.get("voiceover_service") or "").strip().casefold()
    if service in {"elevenlabs", "eleven labs"}:
        return False
    if service in {
        "azure speech sdk v2",
        "azure speech",
        "azure tts v2",
        "azure speech sdk",
    }:
        return True
    if service in {"azure tts v1", "edge tts", "edge_tts"}:
        configured = settings or {}
        return bool(
            str(configured.get("azure_speech_key") or "").strip()
            and str(configured.get("azure_speech_region") or "").strip()
        )
    configured = settings or {}
    return bool(
        str(configured.get("azure_speech_key") or "").strip()
        and str(configured.get("azure_speech_region") or "").strip()
    )


def _azure_speech_v2_voice_name(value: str) -> str:
    """Mark a normal Azure voice for MPT's Azure Speech SDK V2 branch."""
    voice = str(value or "").strip()
    if not voice or ":" in voice or voice.casefold() == "no-voice":
        return voice
    if re.search(r"-v2(?:-|$)", voice, flags=re.IGNORECASE):
        return voice
    match = re.search(r"-(Female|Male)$", voice, flags=re.IGNORECASE)
    if match:
        return f"{voice[:match.start()]}-V2{voice[match.start():]}"
    return f"{voice}-V2"


def _moneyprinter_cli_args(task: dict[str, Any], route: str, settings: dict[str, Any] | None = None) -> list[str]:
    """Build the explicit MPT CLI contract for the stock Pexels/Pixabay route."""
    generation_settings = task.get("generation_settings") if isinstance(task.get("generation_settings"), dict) else {}
    args: list[str] = ["--video-source", route]
    script = str(task.get("video_script") or generation_settings.get("video_script") or "").strip()
    if script:
        args.extend(["--video-script", script])
    keywords = task.get("video_keywords") or generation_settings.get("video_keywords") or task.get("keywords") or task.get("tags")
    if isinstance(keywords, str):
        keywords = [part.strip() for part in re.split(r"[,;|\n]+", keywords) if part.strip()]
    if isinstance(keywords, list):
        terms = [str(item).strip() for item in keywords if str(item).strip()]
        if terms:
            args.extend(["--video-terms", ",".join(terms[:15])])

    language = _mpt_video_language(task.get("language"))
    if language:
        args.extend(["--video-language", language])
    format_value = str(task.get("format") or generation_settings.get("video_format") or "").strip().casefold()
    if format_value in {"wide", "landscape", "16:9"}:
        aspect_ratio = "16:9"
    elif format_value in {"shorts", "portrait", "9:16"}:
        aspect_ratio = "9:16"
    else:
        aspect_ratio = _mpt_aspect_ratio(generation_settings.get("video_aspect_ratio"), task.get("format"))
    args.extend(["--video-aspect", aspect_ratio])
    args.extend(["--video-concat-mode", _mpt_concat_mode(generation_settings.get("video_concatenation_mode"))])
    args.extend(["--video-transition-mode", _mpt_transition_mode(generation_settings.get("video_transition_mode"))])
    clip_duration = generation_settings.get("maximum_clip_duration")
    if str(clip_duration or "").strip().isdigit() and int(clip_duration) > 0:
        args.extend(["--video-clip-duration", str(int(clip_duration))])
    elif route in {"pexels", "pixabay"} and len(script) >= 1_200:
        # Vídeos longos com o padrão de 5 s podem exigir dezenas de downloads
        # sequenciais. Para manter variedade e terminar de forma previsível,
        # adoptamos 15 s apenas quando não há escolha explícita do utilizador.
        args.extend(["--video-clip-duration", "15"])
    if bool(generation_settings.get("match_visuals_to_script_order")):
        args.append("--match-materials-to-script")

    voice_mode = str(generation_settings.get("voiceover_mode") or "").strip().casefold()
    azure_service = str(generation_settings.get("voiceover_service") or "").strip().casefold()
    voice = str(task.get("voice") or generation_settings.get("voice") or "").strip()
    if voice_mode == "none" or voice_mode == "upload":
        args.extend(["--voice-name", "no-voice"])
    elif voice or azure_service in {"azure speech sdk v2", "azure speech", "azure tts v2", "azure speech sdk"}:
        if not voice:
            voice = "en-US-JennyNeural"
        if _uses_azure_speech_sdk_v2(generation_settings, settings):
            voice = _azure_speech_v2_voice_name(voice)
        args.extend(["--voice-name", voice])
    volume = generation_settings.get("voiceover_volume")
    speed = generation_settings.get("voiceover_speed")
    if volume is not None:
        args.extend(["--voice-volume", _mpt_percent(volume)])
    if speed is not None:
        args.extend(["--voice-rate", _mpt_rate(speed)])

    subtitles = generation_settings.get("enable_subtitles")
    if subtitles is not None:
        args.append("--subtitle-enabled" if bool(subtitles) else "--no-subtitle-enabled")
    subtitle_position = str(generation_settings.get("subtitle_position") or "").strip().casefold()
    if subtitle_position in {"top", "center", "bottom", "custom"}:
        args.extend(["--subtitle-position", subtitle_position])
    font_name = str(generation_settings.get("subtitle_font") or "").strip()
    if font_name:
        args.extend(["--font-name", font_name])
    bgm_source = str(generation_settings.get("background_music_source") or "").strip().casefold()
    bgm_type = {"sem música": "none", "sem musica": "none", "random background music": "random", "ficheiro existente": "custom"}.get(bgm_source)
    if bgm_type:
        args.extend(["--bgm-type", bgm_type])
    bgm_volume = generation_settings.get("background_music_volume")
    if bgm_volume is not None:
        args.extend(["--bgm-volume", _mpt_percent(bgm_volume)])
    return args


def _run_video_helper_once(
    task: dict[str, Any],
    *,
    route_override: str = "",
    api_key_override: str = "",
    settings: dict[str, Any] | None = None,
) -> Path:
    helper_dir = Path(__file__).resolve().parents[1] / "seed" / "skills"
    helper = helper_dir / "mpt_agent.py"
    if not helper.is_file():
        raise PipelineError("O helper de vídeo MoneyPrinterTurbo não está instalado no pacote.")
    subject = str(task.get("topic") or "").strip()
    if not subject:
        raise PipelineError("A etapa Vídeo não recebeu um tema válido.")
    settings = settings if isinstance(settings, dict) else _settings()
    configured_root = _configured_moneyprinter_root(settings)
    task_id = str(task.get("id") or "").strip()
    if not task_id:
        raise PipelineError("A tarefa de vídeo não tem um identificador válido.")
    env = os.environ.copy()
    for key in (
        "MPT_PEXELS_API_KEY",
        "MPT_PEXELS_API_KEYS",
        "MPT_PIXABAY_API_KEY",
        "MPT_PIXABAY_API_KEYS",
    ):
        env.pop(key, None)
    card = active_llm_card(settings)
    provider = str(card.get("provider") or "openai").strip()
    definition = provider_definition(provider)
    route = str(route_override or _normalise_video_route(task, settings)).strip().casefold()
    source_keys = material_api_keys(settings, route) if route in {"pexels", "pixabay"} else []
    if api_key_override and route in {"pexels", "pixabay"}:
        source_keys = [str(api_key_override).strip()]
    if route in {"pexels", "pixabay"} and not source_keys:
        source_label = "Pexels" if route == "pexels" else "Pixabay"
        message = f"Configure pelo menos uma API key de {source_label} em Configurações > Configuração API > Fontes de materiais."
        metadata = _failure_attribution(task, settings, "video", error=message)
        raise PipelineError(_failure_message(message, metadata), failure_metadata=metadata)
    if configured_root:
        try:
            sync_moneyprinter_config(settings, str(configured_root))
        except OSError as exc:
            raise PipelineError(f"Não foi possível sincronizar a configuração do MoneyPrinterTurbo: {exc}") from exc
    generation_settings = task.get("generation_settings") if isinstance(task.get("generation_settings"), dict) else {}
    voiceover_mode = str(generation_settings.get("voiceover_mode") or "").strip().casefold()
    voiceover_service = str(generation_settings.get("voiceover_service") or "").strip().casefold()
    generated_elevenlabs_audio: Path | None = None
    if voiceover_mode not in {"none", "upload"} and voiceover_service == "elevenlabs":
        elevenlabs_voice = str(task.get("voice") or generation_settings.get("voice") or "").strip()
        script_text = str(task.get("video_script") or generation_settings.get("video_script") or "").strip()
        if not elevenlabs_voice:
            raise PipelineError("Seleccione uma voz personalizada ElevenLabs antes de criar o vídeo.")
        if not str(settings.get("elevenlabs_api_key") or "").strip():
            raise PipelineError("ElevenLabs foi seleccionado, mas a API Key não está configurada.")
        if not script_text:
            raise PipelineError("ElevenLabs foi seleccionado, mas o roteiro ainda não está disponível.")
        try:
            generated_elevenlabs_audio = synthesize_preview(script_text, "elevenlabs", elevenlabs_voice, settings)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PipelineError(f"Não foi possível gerar a narração ElevenLabs: {exc}") from exc
    env_values = {
        "MPT_LLM_PROVIDER": provider,
        "MPT_LLM_API_KEY": str(card.get("api_key") or "").strip(),
        "MPT_LLM_BASE_URL": str(card.get("base_url") or definition.default_base_url or "").strip(),
        "MPT_LLM_MODEL_NAME": str(card.get("model") or "").strip(),
        "MPT_PEXELS_API_KEY": source_keys[0] if route == "pexels" and source_keys else "",
        "MPT_PEXELS_API_KEYS": json.dumps(source_keys, ensure_ascii=False) if route == "pexels" and source_keys else "",
        "MPT_PIXABAY_API_KEY": source_keys[0] if route == "pixabay" and source_keys else "",
        "MPT_PIXABAY_API_KEYS": json.dumps(source_keys, ensure_ascii=False) if route == "pixabay" and source_keys else "",
        "MPT_AZURE_SPEECH_KEY": str(settings.get("azure_speech_key") or "").strip(),
        "MPT_AZURE_SPEECH_REGION": str(settings.get("azure_speech_region") or "").strip(),
    }
    for key, value in env_values.items():
        if value:
            env[key] = value
    command = ["uv", "run", "--no-project", "--python", "3.11", "python", "mpt_agent.py"]
    if configured_root:
        command.extend(["--root", str(configured_root)])
    command.extend(["--subject", subject, "--"])
    if _uses_azure_speech_sdk_v2(generation_settings, settings) and str(generation_settings.get("voiceover_mode") or "").strip().casefold() not in {"none", "upload"}:
        missing_voice_config = [
            field for field, value in (
                ("azure_speech_key", settings.get("azure_speech_key")),
                ("azure_speech_region", settings.get("azure_speech_region")),
            ) if not str(value or "").strip()
        ]
        if missing_voice_config:
            message = "Azure Speech SDK V2 foi seleccionado, mas faltam credenciais de voz."
            metadata = _failure_attribution(task, settings, "video", error=message)
            metadata.update({
                "failure_api": "Azure Speech API",
                "failure_provider": "azure_speech",
                "failure_service": "Azure Speech SDK V2",
                "failure_config_fields": ", ".join(missing_voice_config),
            })
            raise PipelineError(_failure_message(message, metadata), failure_metadata=metadata)
    command.extend(_moneyprinter_cli_args(task, route, settings=settings))
    if voiceover_mode == "upload":
        voiceover_file = Path(str(generation_settings.get("voiceover_file") or "").strip()).expanduser()
        if not str(voiceover_file) or not voiceover_file.is_file() or voiceover_file.stat().st_size <= 0:
            message = "O modo Upload foi seleccionado, mas não existe um ficheiro de narração válido. Carregue o áudio em Configurações de áudio."
            metadata = _failure_attribution(task, settings, "video", error=message)
            metadata.update({"failure_api": "Ficheiro local", "failure_provider": "local_storage", "failure_service": "Áudio de narração", "failure_config_fields": "voiceover_file"})
            raise PipelineError(_failure_message(message, metadata), failure_metadata=metadata)
        command.extend(["--custom-audio-file", str(voiceover_file.resolve())])
    elif generated_elevenlabs_audio is not None:
        command.extend(["--custom-audio-file", str(generated_elevenlabs_audio.resolve())])
    output_lines: list[str] = []
    line_queue: queue.Queue[str | None] = queue.Queue()
    started_at = time.monotonic()
    timeout_seconds = _video_timeout_seconds(task, settings)
    idle_timeout_seconds = _video_idle_timeout_seconds(task, settings)
    process: subprocess.Popen[str] | None = None

    def _read_output() -> None:
        if process is None or process.stdout is None:
            line_queue.put(None)
            return
        for line in iter(process.stdout.readline, ""):
            line_queue.put(line.rstrip())
        process.stdout.close()
        line_queue.put(None)

    try:
        process = subprocess.Popen(
            command,
            cwd=helper_dir,
            env=env,
            start_new_session=os.name != "nt",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as exc:
        message = "O comando uv não está instalado; não foi possível iniciar a geração de vídeo."
        metadata = _failure_attribution(task, settings, "video", error=message)
        metadata.update({"failure_service": "Runtime MoneyPrinterTurbo"})
        raise PipelineError(_failure_message(message, metadata), failure_metadata=metadata) from exc

    reader = threading.Thread(target=_read_output, name=f"mpt-output-{task.get('id', 'video')}", daemon=True)
    reader.start()
    output_finished = False
    last_heartbeat = 0.0
    last_output_line = ""
    last_activity_at = started_at
    helper_log_path: Path | None = None
    helper_log_mtime = 0.0
    try:
        while True:
            try:
                line = line_queue.get(timeout=0.5)
                if line is None:
                    output_finished = True
                elif line:
                    last_output_line = _redact_helper_output(line).strip()
                    output_lines.append(line)
                    last_activity_at = time.monotonic()
                    match = re.search(r"full generation log:\s*(.+)$", last_output_line, flags=re.IGNORECASE)
                    if match:
                        candidate = Path(match.group(1).strip()).expanduser()
                        helper_log_path = candidate if candidate.is_file() else None
            except queue.Empty:
                pass
            elapsed = time.monotonic() - started_at
            helper_log_mtime, helper_log_advanced = _latest_helper_log_activity(helper_log_path, helper_log_mtime)
            if helper_log_advanced:
                last_activity_at = time.monotonic()
                if not last_output_line:
                    last_output_line = "[MoneyPrinterTurbo] actividade de geração confirmada"
            if elapsed - last_heartbeat >= 5:
                # O helper expõe o resultado final, mas não uma percentagem estável.
                # Mantemos uma faixa reservada para a etapa de vídeo e avançamos-a
                # lentamente enquanto o processo responde, sem fingir conclusão.
                video_progress = min(79, 52 + int(elapsed // 15))
                current_task = _task_by_id(task_id)
                if current_task and str(current_task.get("state") or "") in {"blocked", "cancelled"}:
                    _stop_process(process)
                    raise PipelineStopped("A tarefa foi parada pelo utilizador.")
                _update(
                    task_id,
                    progress=video_progress,
                    video_helper_status=last_output_line[-500:] if last_output_line else "",
                    video_elapsed_seconds=int(elapsed),
                )
                _worker_heartbeat(
                    task_id=str(task.get("id") or ""),
                    status="running",
                    stage="video",
                    progress=video_progress,
                    video_helper_status=last_output_line[-500:] if last_output_line else "",
                    video_elapsed_seconds=int(elapsed),
                )
                last_heartbeat = elapsed
            if process.poll() is not None and output_finished:
                break
            if elapsed >= timeout_seconds:
                _stop_process(process)
                message = f"A etapa Vídeo excedeu o limite de {timeout_seconds // 60} minutos e foi encerrada."
                metadata = _failure_attribution(task, settings, "video", error=message)
                raise PipelineError(
                    _failure_message(message, metadata),
                    failure_metadata=metadata,
                    fallback_eligible=True,
                )
            if time.monotonic() - last_activity_at >= idle_timeout_seconds:
                _stop_process(process)
                message = (
                    "A etapa Vídeo não apresentou actividade comprovada do motor durante "
                    f"{idle_timeout_seconds // 60} minutos e foi encerrada."
                )
                metadata = _failure_attribution(task, settings, "video", error=message)
                raise PipelineError(
                    _failure_message(message, metadata),
                    failure_metadata=metadata,
                    fallback_eligible=True,
                )
    finally:
        reader.join(timeout=2)
        _persist_video_diagnostics(task, "\n".join(output_lines))
    if process.returncode is None:
        process.wait(timeout=5)
    result_code = process.returncode
    output = "\n".join(output_lines)
    _persist_video_diagnostics(task, output)
    if result_code == 10:
        metadata = _failure_attribution(task, settings, "video", output=output)
        detail = _terminal_helper_detail(output)
        message = "A geração de vídeo precisa de credenciais adicionais do MoneyPrinterTurbo"
        if detail:
            message += f". Detalhe do helper: {detail}"
        raise PipelineError(
            _failure_message(message, metadata),
            failure_metadata=metadata,
            fallback_eligible=True,
        )
    if result_code != 0:
        detail = _terminal_helper_detail(output) or "erro sem detalhes devolvidos pelo helper"
        metadata = _failure_attribution(task, settings, "video", error=detail, output=output)
        message = f"MoneyPrinterTurbo falhou na etapa Vídeo: {detail}"
        raise PipelineError(
            _failure_message(message, metadata),
            failure_metadata=metadata,
            fallback_eligible=True,
        )
    match = re.search(r"(?m)^VIDEO_FILE=(.+)$", output)
    video_path = Path(match.group(1).strip()).expanduser() if match else None
    if not video_path or not video_path.is_file() or video_path.stat().st_size <= 0:
        result_root = configured_root or (Path.home() / "MoneyPrinterTurbo")
        result_file = result_root / ".agent-logs" / "moneyprinterturbo-video" / "latest-result.json"
        if result_file.is_file():
            try:
                payload = json.loads(result_file.read_text(encoding="utf-8"))
                video_path = Path(str(payload.get("video_file") or payload.get("VIDEO_FILE") or "")).expanduser()
            except (OSError, json.JSONDecodeError):
                video_path = None
    if not video_path or not video_path.is_file() or video_path.stat().st_size <= 0:
        message = "MoneyPrinterTurbo terminou sem devolver um MP4 válido."
        metadata = _failure_attribution(task, settings, "video", error=message, output=output)
        raise PipelineError(
            _failure_message(message, metadata),
            failure_metadata=metadata,
            fallback_eligible=True,
        )
    return video_path


def _stock_fallback_is_eligible(route: str, error: PipelineError) -> bool:
    """Allow fallback only when the failed attempt points to its stock source."""
    if route not in {"pexels", "pixabay"} or not getattr(error, "fallback_eligible", False):
        return False
    metadata = dict(getattr(error, "failure_metadata", {}) or {})
    providers = {
        item.strip().casefold()
        for item in str(metadata.get("failure_provider") or "").split(",")
        if item.strip()
    }
    if providers and providers - {route}:
        return False
    fields = {
        item.strip().casefold()
        for item in str(metadata.get("failure_config_fields") or "").split(",")
        if item.strip()
    }
    if fields and fields - {f"{route}_api_key", f"{route}_api_keys"}:
        return False
    return True


def _run_video_helper(task: dict[str, Any]) -> Path:
    """Run the stock helper with provider fallback in the configured priority order."""
    settings = _settings()
    attempts = _material_video_attempts(task, settings)
    if len(attempts) <= 1:
        route, api_key = attempts[0] if attempts else ("", "")
        return _run_video_helper_once(task, route_override=route, api_key_override=api_key, settings=settings)
    for index, (route, api_key) in enumerate(attempts):
        attempt_task = dict(task)
        generation_settings = task.get("generation_settings") if isinstance(task.get("generation_settings"), dict) else {}
        attempt_task["material_source"] = route
        attempt_task["generation_settings"] = {**generation_settings, "material_source": route}
        try:
            return _run_video_helper_once(attempt_task, route_override=route, api_key_override=api_key, settings=settings)
        except PipelineStopped:
            raise
        except PipelineError as exc:
            if not _stock_fallback_is_eligible(route, exc) or index == len(attempts) - 1:
                metadata = dict(getattr(exc, "failure_metadata", {}) or {})
                metadata["failure_route"] = route
                metadata["fallback_attempts"] = " → ".join(_provider_api_label(item[0]) for item in attempts[: index + 1])
                message = (
                    f"Falha no provider {_provider_api_label(route)} após tentar "
                    f"{metadata['fallback_attempts']}. Último erro: {exc}"
                )
                raise PipelineError(message, failure_metadata=metadata) from exc

    raise PipelineError("Nenhuma chave de provider de vídeo stock configurada.")


def _read_persisted_script(task: dict[str, Any], channel: dict[str, Any], blueprint: dict[str, Any], topic: str) -> dict[str, Any] | None:
    """Load a previously saved script so retries do not regenerate it."""
    artifacts = task.get("artifacts") if isinstance(task.get("artifacts"), dict) else {}
    script_path = Path(str(artifacts.get("script") or "")).expanduser()
    if not script_path.is_file() or script_path.stat().st_size <= 0:
        return None
    try:
        raw = script_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    content = raw
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) == 3:
            content = parts[2].strip()
            if content.startswith(">"):
                content = "\n".join(line[1:].lstrip() if line.startswith(">") else line for line in content.splitlines()).strip()
    return {
        "document_type": "video_script",
        "title": str(task.get("title") or topic),
        "summary": topic,
        "content": content,
        "language": str(task.get("language") or channel.get("language") or "Português"),
        "blueprint_id": str(blueprint.get("id") or ""),
        "blueprint_name": str(blueprint.get("name") or "SEM BLUEPRINT CONFIGURADO"),
        "channel_id": str(channel.get("id") or ""),
        "channel_name": str(channel.get("name") or "Canal sem nome"),
        "generated_by": "persisted_pipeline_artifact",
    }


def _valid_artifact_path(value: Any) -> Path | None:
    path = Path(str(value or "")).expanduser()
    try:
        return path if path.is_file() and path.stat().st_size > 0 else None
    except OSError:
        return None


def _existing_thumbnail_path(task: dict[str, Any], artifacts: dict[str, Any], variant: dict[str, Any]) -> Path | None:
    """Find a thumbnail made previously by Pipeline Vídeos or the UI."""
    candidates: list[Any] = [
        artifacts.get("thumbnail"),
        task.get("thumbnail_path"),
        variant.get("image_path"),
    ]
    variants = task.get("thumbnail_variants") if isinstance(task.get("thumbnail_variants"), list) else []
    candidates.extend(item.get("image_path") for item in variants if isinstance(item, dict))
    for value in candidates:
        path = _valid_artifact_path(value)
        if path is not None:
            return path
    return None


def _read_json_artifact(value: Any) -> dict[str, Any] | None:
    path = _valid_artifact_path(value)
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _run_task(task: dict[str, Any]) -> dict[str, Any]:
    """Run one resumable local-cascade task, reusing valid persisted artefacts."""
    task_id = str(task.get("id") or "")
    channel = _channel_for_task(task)
    settings = _settings()
    blueprint = _blueprint_for_channel(channel)
    if not blueprint and (task.get("blueprint_id") or task.get("blueprint_name")):
        blueprint = {"id": str(task.get("blueprint_id") or ""), "name": str(task.get("blueprint_name") or task.get("blueprint_id") or "")}
    channel_visual_context = {**channel}
    if not channel_visual_context.get("platform") and task.get("platform"):
        channel_visual_context["platform"] = task.get("platform")
    visual_blueprint = thumbnail_blueprint_for_channel(channel_visual_context)
    if visual_blueprint.get("content"):
        blueprint = {**blueprint, "thumbnail_blueprint_rules": visual_blueprint["content"]}
    route = _normalise_video_route(task, settings)
    topic = str(task.get("topic") or "").strip()
    if route != "music" and (not topic or str(task.get("topic_source") or "") in {"auto", "llm_pending"}):
        _update(task_id, stage="topic", state="doing", progress=5, error=None)
        topic_result = generate_topic_for_channel(settings, channel, blueprint, user_context=str(task.get("topic_context") or ""))
        topic = str(topic_result.get("topic") or "").strip()
        if not topic:
            raise PipelineError("A IA não devolveu um tema válido.")
        _update(task_id, topic=topic, topic_source="llm", ai_generation={"topic": topic_result}, progress=12)

    generation_settings = task.get("generation_settings") if isinstance(task.get("generation_settings"), dict) else {}
    artifacts = dict(task.get("artifacts") or {})
    if route == "music":
        # Apenas Música não é uma tarefa de vídeo: reutiliza o áudio preparado e
        # termina pronta para a integração de upload musical, sem chamar LLM,
        # Pexels/Pixabay, MoviePy de vídeo, thumbnail ou upload de vídeo.
        music_candidates = [
            task.get("music_path"),
            generation_settings.get("music_path"),
            artifacts.get("music"),
        ]
        music_path = next((path for path in (_valid_audio_artifact(item) for item in music_candidates) if path is not None), None)
        if music_path is None:
            raise PipelineError("A fonte Apenas Música exige um ficheiro de áudio local válido ou uma música Suno já descarregada antes de criar a tarefa.")
        artifacts["music"] = str(music_path)
        _update(
            task_id,
            stage="upload",
            state="done",
            progress=100,
            artifacts=artifacts,
            music_ready=True,
            video_ready=False,
            thumbnail_status="not_applicable",
            error=None,
        )
        return _task_by_id(task_id) or task

    script = _read_persisted_script(task, channel, blueprint, topic)
    if script is None:
        _update(task_id, stage="script", state="doing", progress=18, error=None)
        provided_script = str(generation_settings.get("video_script") or "").strip()
        if provided_script:
            script = {
                "document_type": "video_script",
                "title": str(task.get("title") or topic),
                "summary": topic,
                "content": provided_script,
                "language": str(task.get("language") or channel.get("language") or "Português"),
                "blueprint_id": str(blueprint.get("id") or ""),
                "blueprint_name": str(blueprint.get("name") or "SEM BLUEPRINT CONFIGURADO"),
                "channel_id": str(channel.get("id") or ""),
                "channel_name": str(channel.get("name") or "Canal sem nome"),
                "generation_settings": generation_settings,
                "generated_by": "video_creation_form",
            }
        else:
            script = generate_script_document(
                settings,
                document_type="Roteiro de vídeo",
                title=str(task.get("title") or topic),
                brief=topic,
                language=str(task.get("language") or channel.get("language") or "Português"),
                channel=channel,
                blueprint=blueprint,
                structure_notes=str(generation_settings.get("script_structure_notes") or ""),
                generation_settings=generation_settings,
            )
        script_record = save_script_document(script)
        artifacts["script"] = script_record.get("path", "")
        _update(task_id, artifacts=artifacts, progress=max(30, int(task.get("progress") or 0)))
    else:
        _update(task_id, artifacts=artifacts, error=None, progress=max(30, int(task.get("progress") or 0)))

    title = str(task.get("title") or "").strip()
    provided_keywords = generation_settings.get("video_keywords") or task.get("keywords") or task.get("tags")
    if isinstance(provided_keywords, str):
        provided_keywords = re.split(r"[,\n;|]+", provided_keywords)
    keywords = [str(item).strip() for item in provided_keywords or [] if str(item).strip()][:15]
    title_candidates = task.get("title_candidates") if isinstance(task.get("title_candidates"), list) else []
    if not title or not keywords:
        _update(task_id, stage="title", state="doing", progress=max(35, int(task.get("progress") or 0)), error=None)
        editorial: dict[str, Any] = {
            "title": title or topic,
            "title_candidates": title_candidates,
            "keywords": keywords,
        }
        if not title:
            try:
                editorial = generate_title_and_keywords(
                    settings,
                    channel,
                    topic,
                    blueprint,
                    language=str(task.get("language") or channel.get("language") or "Português"),
                )
            except CreativeGenerationError:
                # A falha editorial não deve impedir a geração do vídeo: usa o tema
                # como título e keywords determinísticas, deixando o erro de imagem
                # para a etapa posterior e independente da criação do MP4.
                editorial = {"title": topic, "title_candidates": [], "keywords": []}
        title = str(editorial.get("title") or title or topic).strip()
        keywords = keywords or (
            editorial.get("keywords") if isinstance(editorial.get("keywords"), list) else []
        )
        keywords = [str(item).strip() for item in keywords if str(item).strip()][:15] or _keywords(
            topic,
            title,
            str(channel.get("niche") or ""),
        )
        title_candidates = editorial.get("title_candidates") if isinstance(editorial.get("title_candidates"), list) else title_candidates
        title_artifact = _save_json_artifact(
            task_id,
            "title-keywords",
            {"topic": topic, "title": title, "keywords": keywords, "title_candidates": title_candidates},
        )
        artifacts["title_keywords"] = title_artifact
        _update(task_id, title=title, tags=keywords, artifacts=artifacts, title_candidates=title_candidates, progress=max(45, int(task.get("progress") or 0)))
    else:
        _update(task_id, title=title, tags=keywords, artifacts=artifacts, title_candidates=title_candidates, error=None, progress=max(50, int(task.get("progress") or 0)))

    _update(task_id, stage="keywords", state="doing", progress=max(50, int(task.get("progress") or 0)), error=None)
    _update(task_id, tags=keywords, progress=max(50, int(task.get("progress") or 0)))

    # O vídeo é deliberadamente concluído antes de qualquer chamada ao provider
    # de imagem. O artefacto fica persistido mesmo que a quota da thumbnail falhe.
    existing_video = _valid_artifact_path(artifacts.get("video"))
    if existing_video is None:
        _update(task_id, stage="video", state="doing", progress=max(52, int(task.get("progress") or 0)), error=None)
        try:
            video_prompt = _append_generation_constraints(
                f"Título: {title}\n\nRoteiro:\n{str(script.get('content') or '')[:12000]}",
                kind="video",
            )
            if route == "full_ia":
                video_path = generate_video_from_pool(
                    settings,
                    video_prompt,
                    allowed_providers=set(FULL_IA_VIDEO_PROVIDER_CODES),
                )
            else:
                video_path = _run_video_helper({
                    **task,
                    "topic": topic,
                    "title": title,
                    "video_script": str(script.get("content") or ""),
                    "video_keywords": keywords,
                    "style_wide": route,
                })
        except MediaGenerationError as exc:
            if route == "full_ia":
                message = f"Pool Full IA (FAL AI/KIE AI/Agnes AI/Nano Banana/Replicate AI/Pollinations.ai/Hugging Face Inference API/InferencePort Proxy/HeyGen): {exc}"
            else:
                message = f"Pipeline MoneyPrinterTurbo ({route}): {exc}"
            metadata = _failure_attribution(task, settings, "video", error=str(exc))
            raise PipelineError(_failure_message(message, metadata), failure_metadata=metadata) from exc
        current_after_video = _task_by_id(task_id) or {}
        artifacts = dict(current_after_video.get("artifacts") or artifacts)
        artifacts["video"] = str(video_path)
        _update(task_id, artifacts=artifacts, video_ready=True, progress=max(80, int(task.get("progress") or 0)))
    else:
        video_path = existing_video
        artifacts["video"] = str(existing_video)
        _update(task_id, stage="video", state="doing", artifacts=artifacts, video_ready=True, error=None, progress=max(80, int(task.get("progress") or 0)))

    persisted_prompt = _read_json_artifact(artifacts.get("thumbnail_prompt_json"))
    persisted_variant = persisted_prompt.get("thumbnail") if isinstance(persisted_prompt, dict) and isinstance(persisted_prompt.get("thumbnail"), dict) else {}
    existing_variant = task.get("thumbnail_variant") if isinstance(task.get("thumbnail_variant"), dict) else {}
    variant = {**persisted_variant, **dict(existing_variant)}
    if not str(variant.get("image_prompt") or "").strip() and str(task.get("thumbnail_prompt") or "").strip():
        variant["image_prompt"] = str(task.get("thumbnail_prompt") or "").strip()
    if not str(variant.get("overlay_text") or "").strip() and str(task.get("thumbnail_text") or "").strip():
        variant["overlay_text"] = str(task.get("thumbnail_text") or "").strip()
    if not str(variant.get("image_prompt") or "").strip():
        _update(task_id, stage="thumbnail_prompt", state="doing", progress=max(82, int(task.get("progress") or 0)), error=None)
        try:
            variant = generate_thumbnail_prompt(
                settings,
                channel,
                topic,
                blueprint=blueprint,
                language=str(task.get("language") or channel.get("language") or "Português"),
            )
        except CreativeGenerationError as exc:
            raise PipelineError(f"Não foi possível gerar o prompt da thumbnail: {exc}") from exc
    prompt_payload = {
        "topic": topic,
        "title": title,
        "keywords": keywords,
        "thumbnail": variant,
        "requirements": {
            "aspect_ratio": "16:9",
            "resolution": "1920x1080",
            "max_elements": 3,
            "max_overlay_words": 4,
            "lettering_required": True,
            "lettering_text": str(variant.get("overlay_text") or ""),
            "lettering_prompt": str(variant.get("lettering_prompt") or ""),
        },
    }
    if _valid_artifact_path(artifacts.get("thumbnail_prompt_json")) is None:
        artifacts["thumbnail_prompt_json"] = _save_json_artifact(task_id, "thumbnail-prompt", prompt_payload)
    _update(
        task_id,
        stage="thumbnail_prompt",
        state="doing",
        progress=max(84, int(task.get("progress") or 0)),
        thumbnail_variant=variant,
        thumbnail_prompt=str(variant.get("image_prompt") or ""),
        thumbnail_text=str(variant.get("overlay_text") or ""),
        thumbnail_status="prompt_ready",
        artifacts=artifacts,
        error=None,
    )

    _update(task_id, stage="thumbnail", state="doing", progress=max(86, int(task.get("progress") or 0)), error=None)
    current_artifacts = dict((_task_by_id(task_id) or {}).get("artifacts") or artifacts)
    current_task = _task_by_id(task_id) or task
    existing_thumbnail = _existing_thumbnail_path(current_task, current_artifacts, variant)
    if existing_thumbnail is not None:
        thumbnail_path = existing_thumbnail
    else:
        try:
            thumbnail_path = _generate_pipeline_thumbnail(
                settings,
                str(variant.get("image_prompt") or ""),
                topic=topic,
                variant_index=0,
                lettering_text=str(variant.get("overlay_text") or ""),
                lettering_prompt=str(variant.get("lettering_prompt") or ""),
                thumbnail_blueprint=blueprint,
            )
        except (MediaGenerationError, ThumbnailGenerationError) as exc:
            raise PipelineError(f"A thumbnail não foi gerada; o vídeo já está disponível em {video_path}: {exc}") from exc
    artifacts = dict((_task_by_id(task_id) or {}).get("artifacts") or current_artifacts)
    artifacts["thumbnail"] = str(thumbnail_path)
    _update(task_id, artifacts=artifacts, thumbnail_status="generated", progress=max(90, int(task.get("progress") or 0)))

    stored_upload = artifacts.get("upload")
    if isinstance(stored_upload, dict) and stored_upload:
        return _update(task_id, stage="upload", state="done", progress=100, artifacts=artifacts, video_ready=True, error=None)

    configured_account_id = str(channel.get("google_account_id") or "").strip()
    configured_composio = bool(settings.get("composio_enabled", False)) and bool(settings.get("composio_auto_upload", True)) and bool(settings.get("composio_api_key")) and bool(settings.get("composio_tool_slug"))
    configured_upload_post = bool(settings.get("upload_post_enabled", False)) and bool(settings.get("upload_post_auto_upload", False))
    configured_postiz = bool(settings.get("postiz_enabled", False)) and bool(settings.get("postiz_auto_publish", False))
    if not (configured_composio or configured_account_id or configured_upload_post or configured_postiz):
        artifacts["upload"] = {
            "route": "local",
            "status": "skipped",
            "reason": "Nenhuma rota de publicação foi configurada para esta tarefa; os artefactos foram concluídos localmente.",
        }
        return _update(task_id, stage="upload", state="done", progress=100, artifacts=artifacts, video_ready=True, error=None)

    _update(task_id, stage="upload", state="doing", progress=max(94, int(task.get("progress") or 0)), error=None)
    result = upload_with_default_route(
        settings,
        storage_root=STORAGE,
        channel=channel,
        account=resolve_youtube_account(settings, channel),
        video_path=str(video_path),
        title=title,
        description=str(script.get("summary") or "") + "\n\n" + str(script.get("content") or "")[:5000],
        tags=keywords,
        language=str(task.get("language") or channel.get("language") or "pt-BR"),
        privacy_status="unlisted",
        thumbnail_path=str(thumbnail_path),
        captions_path=str(artifacts.get("captions") or ""),
    )
    if not result.ok:
        attempts = (result.data or {}).get("attempts") if isinstance(result.data, dict) else None
        detail = ""
        if isinstance(attempts, list):
            failed = [
                f"{item.get('route')}: {item.get('message')}"
                for item in attempts
                if isinstance(item, dict) and item.get("status") in {"failed", "skipped"} and item.get("message")
            ]
            if failed:
                detail = " Detalhes: " + " | ".join(failed[-4:])
        raise PipelineError(f"{result.message}{detail}")
    artifacts["upload"] = result.data
    return _update(task_id, stage="upload", state="done", progress=100, artifacts=artifacts, error=None)


def run_once() -> dict[str, Any]:
    """Execute one worker tick and resume the first pending cascade task."""
    ensure_storage()
    lock = _acquire_lock()
    if lock is None:
        return {"ok": True, "busy": True}
    try:
        try:
            session_health = check_all_accounts_session_info_health(STORAGE, _settings())
            session_alerts = emit_session_info_health_alerts(session_health)
            _worker_heartbeat(
                session_info_health=[item.as_dict() for item in session_health],
                session_info_alerts=len(session_alerts),
                session_info_health_error="",
            )
        except Exception as exc:
            # Monitoring is advisory and must not prevent a resumable task from running.
            _worker_heartbeat(session_info_health_error=type(exc).__name__)
        recovered = _recover_stale_tasks()
        tasks = read_json("tasks.json", [])
        candidate = _next_runnable_task(tasks)
        if not candidate:
            _worker_heartbeat(last_task_id=None, last_error="", status="idle", stage="idle", progress=0, recovered_task_ids=recovered)
            return {"ok": True, "status": "idle", "recovered_task_ids": recovered}
        task_id = str(candidate.get("id") or "")
        _worker_heartbeat(last_task_id=task_id, status="running", stage=str(candidate.get("stage") or "pipeline"), progress=int(candidate.get("progress") or 0), last_error="", recovered_task_ids=recovered)
        try:
            result = _run_task(candidate)
            _worker_heartbeat(status="completed", last_error="", stage=str(result.get("stage") or "upload"), progress=100, task_id=task_id)
            return {"ok": True, "task_id": task_id, "task": result, "recovered_task_ids": recovered}
        except PipelineStopped as exc:
            current_task = _task_by_id(task_id) or candidate
            current_state = str(current_task.get("state") or "")
            if current_state not in {"blocked", "cancelled"}:
                from hermes_ui.domain import update_task
                update_task(task_id, {"state": "blocked", "error": str(exc), "failed_stage": current_task.get("stage") or "pipeline"})
            _worker_heartbeat(status="stopped", last_error=str(exc), stage=str(current_task.get("stage") or "pipeline"), progress=int(current_task.get("progress") or 0), task_id=task_id)
            return {"ok": True, "task_id": task_id, "status": "stopped", "recovered_task_ids": recovered}
        except Exception as exc:
            message = str(exc)[:2000]
            from hermes_ui.domain import update_task
            current_task = _task_by_id(task_id) or candidate
            failed_stage = str(current_task.get("stage") or "pipeline")
            settings = _settings()
            failure_metadata = dict(getattr(exc, "failure_metadata", {}) or {})
            if not failure_metadata:
                failure_metadata = _failure_attribution(current_task, settings, failed_stage, error=message)
            if "API/provider:" not in message:
                message = _failure_message(message, failure_metadata)[:2000]
            failure_updates = {
                "state": "failed",
                "error": message,
                "failed_stage": failed_stage,
                **failure_metadata,
            }
            update_task(task_id, failure_updates)
            _worker_heartbeat(status="failed", last_error=message, stage=failed_stage, progress=int(current_task.get("progress") or 0), task_id=task_id)
            return {"ok": False, "task_id": task_id, "error": message, "failure_metadata": failure_metadata, "recovered_task_ids": recovered}
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def run_worker(interval_seconds: int = 5) -> None:
    ensure_storage()
    _worker_heartbeat(status="starting", stage="idle", progress=0, last_error="")
    while True:
        run_once()
        time.sleep(max(2, int(interval_seconds)))


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Executor do pipeline de criação de vídeos Thunderbolt")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=5)
    args = parser.parse_args()
    if args.once:
        print(json.dumps(run_once(), ensure_ascii=False), flush=True)
    else:
        run_worker(args.interval)


if __name__ == "__main__":
    main()
