from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from integrations.upload_routing import upload_with_default_route
from hermes_ui.creative_generation import CreativeGenerationError, generate_creative_package, generate_topic_for_channel
from hermes_ui.script_documents import save_script_document
from hermes_ui.script_generation import generate_script_document
from hermes_ui.storage import STORAGE, ensure_storage, read_json, write_json
from hermes_ui.llm_providers import active_llm_card, provider_definition
from hermes_ui.thumbnail_generation import generate_thumbnail_image
from hermes_ui.media_generation import MediaGenerationError, google_images_search

PIPELINE_LOCK_FILENAME = "pipeline_worker.lock"
PIPELINE_LOG_FILENAME = "pipeline_worker.json"
VIDEO_TIMEOUT_SECONDS = 20 * 60
STALE_TASK_SECONDS = 2 * 60 * 60


class PipelineError(RuntimeError):
    """Raised when a pipeline stage cannot complete with an actionable error."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _settings() -> dict[str, Any]:
    value = read_json("settings.json", {})
    return value if isinstance(value, dict) else {}


def _lock_path() -> Path:
    ensure_storage()
    return STORAGE / "state" / PIPELINE_LOCK_FILENAME


def _acquire_lock() -> Path | None:
    path = _lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        os.close(descriptor)
        return path
    except FileExistsError:
        return None


def _write_worker_state(**updates: Any) -> None:
    state = read_json(PIPELINE_LOG_FILENAME, {})
    if not isinstance(state, dict):
        state = {}
    state.update(updates)
    state["updated_at"] = _now()
    write_json(PIPELINE_LOG_FILENAME, state)


def _task_by_id(task_id: str) -> dict[str, Any] | None:
    return next((task for task in read_json("tasks.json", []) if isinstance(task, dict) and task.get("id") == task_id), None)


def _update(task_id: str, **updates: Any) -> dict[str, Any]:
    from hermes_ui.domain import update_task

    updated = update_task(task_id, updates)
    if not updated:
        raise PipelineError(f"Tarefa {task_id} deixou de existir durante a execução.")
    return updated


def _channel_for_task(task: dict[str, Any]) -> dict[str, Any]:
    channel_id = str(task.get("channel_id") or "")
    return next((channel for channel in read_json("channels.json", []) if str(channel.get("id")) == channel_id), {})


def _blueprint_for_channel(channel: dict[str, Any]) -> dict[str, Any]:
    blueprint_id = str(channel.get("default_blueprint_id") or channel.get("blueprint_id") or "")
    blueprints = read_json("blueprints.json", [])
    if not isinstance(blueprints, list):
        return {}
    return next((item for item in blueprints if isinstance(item, dict) and str(item.get("id")) == blueprint_id), {})


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
    directory = STORAGE / "artifacts"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{task_id}-{name}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return str(path)


def _run_video_helper(task: dict[str, Any]) -> Path:
    helper_dir = Path(__file__).resolve().parents[1] / "seed" / "skills"
    helper = helper_dir / "mpt_agent.py"
    if not helper.is_file():
        raise PipelineError("O helper de vídeo MoneyPrinterTurbo não está instalado no pacote.")
    subject = str(task.get("topic") or "").strip()
    if not subject:
        raise PipelineError("A etapa Vídeo não recebeu um tema válido.")
    settings = _settings()
    requested_source = str(task.get("style_wide") or task.get("material_source") or "pexels").strip().lower()
    if requested_source == "google_images":
        try:
            results = google_images_search(settings, subject, num_results=3, safe="active")
            artifact = _save_json_artifact(str(task.get("id") or "google-images"), "google-images", {"query": subject, "items": results})
            task["google_images_artifact"] = artifact
        except MediaGenerationError:
            # Google Images is an optional visual source; stock helper remains the final fallback.
            requested_source = "pexels"
    env = os.environ.copy()
    card = active_llm_card(settings)
    provider = str(card.get("provider") or "openai").strip()
    definition = provider_definition(provider)
    env_values = {
        "MPT_LLM_PROVIDER": provider,
        "MPT_LLM_API_KEY": str(card.get("api_key") or "").strip(),
        "MPT_LLM_BASE_URL": str(card.get("base_url") or definition.default_base_url or "").strip(),
        "MPT_LLM_MODEL_NAME": str(card.get("model") or "").strip(),
        "MPT_PEXELS_API_KEY": str(settings.get("pexels_api_key") or "").strip(),
    }
    for key, value in env_values.items():
        if value:
            env[key] = value
    command = ["uv", "run", "--no-project", "--python", "3.11", "python", "mpt_agent.py", "--subject", subject]
    try:
        result = subprocess.run(command, cwd=helper_dir, env=env, capture_output=True, text=True, timeout=VIDEO_TIMEOUT_SECONDS, check=False)
    except FileNotFoundError as exc:
        raise PipelineError("O comando uv não está instalado; não foi possível iniciar a geração de vídeo.") from exc
    except subprocess.TimeoutExpired as exc:
        raise PipelineError(f"A etapa Vídeo excedeu o limite de {VIDEO_TIMEOUT_SECONDS // 60} minutos e foi encerrada.") from exc
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    if result.returncode == 10:
        raise PipelineError("A geração de vídeo precisa de credenciais adicionais do MoneyPrinterTurbo.")
    if result.returncode != 0:
        detail = output[-1200:].strip() or "erro sem detalhes devolvidos pelo helper"
        raise PipelineError(f"MoneyPrinterTurbo falhou na etapa Vídeo: {detail}")
    match = re.search(r"(?m)^VIDEO_FILE=(.+)$", output)
    video_path = Path(match.group(1).strip()).expanduser() if match else None
    if not video_path or not video_path.is_file() or video_path.stat().st_size <= 0:
        result_file = Path.home() / "MoneyPrinterTurbo" / ".agent-logs" / "moneyprinterturbo-video" / "latest-result.json"
        if result_file.is_file():
            try:
                payload = json.loads(result_file.read_text(encoding="utf-8"))
                video_path = Path(str(payload.get("video_file") or payload.get("VIDEO_FILE") or "")).expanduser()
            except (OSError, json.JSONDecodeError):
                video_path = None
    if not video_path or not video_path.is_file() or video_path.stat().st_size <= 0:
        raise PipelineError("MoneyPrinterTurbo terminou sem devolver um MP4 válido.")
    return video_path


def _run_task(task: dict[str, Any]) -> dict[str, Any]:
    task_id = str(task.get("id") or "")
    channel = _channel_for_task(task)
    settings = _settings()
    blueprint = _blueprint_for_channel(channel)
    topic = str(task.get("topic") or "").strip()
    if not topic or str(task.get("topic_source") or "") in {"auto", "llm_pending"}:
        _update(task_id, stage="topic", state="doing", progress=5, error=None)
        topic_result = generate_topic_for_channel(settings, channel, blueprint, user_context=str(task.get("topic_context") or ""))
        topic = str(topic_result.get("topic") or "").strip()
        if not topic:
            raise PipelineError("A IA não devolveu um tema válido.")
        _update(task_id, topic=topic, topic_source="llm", ai_generation={"topic": topic_result}, progress=12)

    _update(task_id, stage="script", state="doing", progress=18, error=None)
    generation_settings = task.get("generation_settings") if isinstance(task.get("generation_settings"), dict) else {}
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
    artifacts = dict(task.get("artifacts") or {})
    artifacts["script"] = script_record.get("path", "")
    _update(task_id, artifacts=artifacts, progress=30)

    _update(task_id, stage="title", state="doing", progress=35)
    creative = generate_creative_package(settings, channel, topic, blueprint, language=str(task.get("language") or channel.get("language") or "Português"))
    title = str(creative.get("title") or topic).strip()
    provided_keywords = generation_settings.get("video_keywords")
    if isinstance(provided_keywords, str):
        provided_keywords = re.split(r"[,\n;|]+", provided_keywords)
    provided_keywords = [str(item).strip() for item in provided_keywords or [] if str(item).strip()]
    keywords = provided_keywords[:15] or (creative.get("keywords") if isinstance(creative.get("keywords"), list) else _keywords(topic, title, str(channel.get("niche") or "")))
    title_artifact = _save_json_artifact(task_id, "title-keywords", {"topic": topic, "title": title, "keywords": keywords, "title_candidates": creative.get("title_candidates", [])})
    _update(task_id, title=title, tags=keywords, artifacts={**artifacts, "title_keywords": title_artifact}, title_candidates=creative.get("title_candidates", []), progress=45)

    _update(task_id, stage="keywords", state="doing", progress=48)
    variant = creative.get("thumbnail_variant") if isinstance(creative.get("thumbnail_variant"), dict) else {}
    prompt_payload = {"topic": topic, "title": title, "keywords": keywords, "thumbnail": variant, "requirements": {"aspect_ratio": "16:9", "resolution": "1920x1080", "max_elements": 3, "max_overlay_words": 4}}
    prompt_artifact = _save_json_artifact(task_id, "thumbnail-prompt", prompt_payload)
    artifacts = {**artifacts, "thumbnail_prompt_json": prompt_artifact}
    _update(task_id, stage="thumbnail_prompt", state="doing", progress=52, thumbnail_prompt=str(variant.get("image_prompt") or ""), thumbnail_text=str(variant.get("overlay_text") or ""), thumbnail_status="prompt_ready", artifacts=artifacts)
    _update(task_id, stage="thumbnail", state="doing", progress=56, thumbnail_prompt=str(variant.get("image_prompt") or ""), thumbnail_text=str(variant.get("overlay_text") or ""), thumbnail_status="prompt_ready", artifacts=artifacts)
    thumbnail_path = generate_thumbnail_image(settings, str(variant.get("image_prompt") or ""), topic=topic, variant_index=0)
    artifacts["thumbnail"] = str(thumbnail_path)
    _update(task_id, artifacts=artifacts, thumbnail_status="generated", progress=62)

    _update(task_id, stage="video", state="doing", progress=68)
    video_path = _run_video_helper({**task, "topic": topic})
    artifacts["video"] = str(video_path)
    _update(task_id, artifacts=artifacts, progress=80)

    _update(task_id, stage="upload", state="doing", progress=86)
    result = upload_with_default_route(
        settings,
        storage_root=STORAGE,
        channel=channel,
        account=next((item for item in settings.get("youtube_batch_accounts", []) if isinstance(item, dict) and str(item.get("id")) == str(channel.get("google_account_id"))), None),
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
        raise PipelineError(result.message)
    artifacts["upload"] = result.data
    return _update(task_id, stage="upload", state="done", progress=100, artifacts=artifacts, error=None)


def run_once() -> dict[str, Any]:
    ensure_storage()
    lock = _acquire_lock()
    if lock is None:
        return {"ok": True, "busy": True}
    try:
        tasks = read_json("tasks.json", [])
        candidate = next((task for task in tasks if isinstance(task, dict) and task.get("state") in {"to_do", "doing"}), None)
        if not candidate:
            _write_worker_state(last_task_id=None, last_error="", status="idle")
            return {"ok": True, "status": "idle"}
        task_id = str(candidate.get("id") or "")
        _write_worker_state(last_task_id=task_id, status="running", last_error="")
        try:
            result = _run_task(candidate)
            _write_worker_state(status="completed", last_error="")
            return {"ok": True, "task_id": task_id, "task": result}
        except Exception as exc:
            message = str(exc)[:2000]
            from hermes_ui.domain import update_task
            update_task(task_id, {"state": "failed", "error": message})
            _write_worker_state(status="failed", last_error=message)
            return {"ok": False, "task_id": task_id, "error": message}
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def run_worker(interval_seconds: int = 5) -> None:
    ensure_storage()
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
