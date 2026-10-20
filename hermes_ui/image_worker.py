"""Worker da fila de IMAGENS DE PRODUÇÃO (1.0.11) — 3 filas paralelas do Motor.

Fila DISTINTA da de thumbnails (são configurações independentes). Processa
posts estáticos que NÃO geram vídeo:
  1. Imagens de Influencer (Geração de Conteúdo IA → "Gerar imagem",
     destino Instagram/redes) — `state == "image_queued"` no repositório.
  2. Fotos UGC Products (modo "Gerar Foto") — mesmo repositório,
     `metadata.workflow == "ugc_products"`.
  3. Facebook editorial — posts com `status == "imagens_na_fila"` (o botão
     "Buscar/Gerar Imagens" marca e responde instantâneo).
Pool limitado por `motor.max_parallel_images`; Rate Limit (429) reza em
backoff exponencial. O estado do worker fica em `image_worker.json`.
"""
import argparse
import json
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from hermes_ui.queue_worker_runtime import (
    acquire_pid_lock,
    load_queue_worker_status,
    run_with_rate_limit_backoff,
    write_queue_heartbeat,
)
from hermes_ui.storage import read_json

STATE_FILENAME = "image_worker.json"
LOCK_FILENAME = "image_worker.lock"
WORKER_MARKER = "hermes_ui.image_worker"
ACTIVE_INTERVAL_SECONDS = 5
IDLE_INTERVAL_SECONDS = 15

_state_lock = threading.Lock()
_executor: ThreadPoolExecutor | None = None
_executor_workers = 0
_inflight: set[str] = set()


def load_image_worker_status() -> dict[str, Any]:
    return load_queue_worker_status(STATE_FILENAME)


def _heartbeat(**updates: Any) -> None:
    write_queue_heartbeat(STATE_FILENAME, **updates)


def _lock_path() -> Path:
    from hermes_ui.storage import STATE

    return Path(STATE) / LOCK_FILENAME


def _settings() -> dict[str, Any]:
    value = read_json("settings.json", {})
    return value if isinstance(value, dict) else {}


def _repository(settings: dict[str, Any]):
    from hermes_ui.influencers import InfluencerBackendError, get_repository

    try:
        return get_repository(settings)
    except InfluencerBackendError:
        return None


def _queued_image_contents(repository: Any) -> list[dict[str, Any]]:
    """Conteúdos de imagem em fila (Influencer + UGC fotos) de TODOS os personagens."""
    try:
        records = repository.list_content("", limit=200)
    except Exception:
        return []
    return [
        dict(item)
        for item in records
        if isinstance(item, dict)
        and str(item.get("state") or "") == "image_queued"
        and str(item.get("content_type") or "") == "image"
        and str(item.get("id") or "").strip()
    ]


def _queued_facebook_posts() -> list[dict[str, Any]]:
    from hermes_ui.facebook_automation import list_posts

    return [dict(post) for post in list_posts() if str(post.get("status") or "") == "imagens_na_fila"]


def _card_for(settings: dict[str, Any], record: dict[str, Any]) -> dict[str, Any] | None:
    from hermes_ui.media_providers import media_cards_for_pool

    cards = media_cards_for_pool(settings, "image")
    if not cards:
        return None
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    card_id = str(metadata.get("provider_card_id") or "")
    for card in cards:
        if card_id and str(card.get("id") or "") == card_id:
            return dict(card)
    provider = str(record.get("provider") or "").casefold()
    model = str(record.get("model") or "").casefold()
    for card in cards:
        if provider and str(card.get("provider") or "").casefold() == provider and (not model or str(card.get("model") or "").casefold() == model):
            return dict(card)
    return dict(cards[0]) if len(cards) == 1 else None


def _process_image_content(content_id: str) -> dict[str, Any]:
    """Gera UMA imagem de produção (claim 'running' → 'completed'/'failed')."""
    from hermes_ui.media_generation import generate_image_for_card
    from hermes_ui.notifications import record_notification

    settings = _settings()
    repository = _repository(settings)
    if repository is None:
        return {"ok": False, "content_id": content_id, "error": "Backend de influencers indisponível."}
    record = next((item for item in repository.list_content("", limit=200) if str(item.get("id") or "") == content_id), None)
    if record is None:
        return {"ok": False, "content_id": content_id, "error": "Conteúdo não encontrado."}
    try:
        card = _card_for(settings, record)
        if card is None:
            raise ValueError("Nenhum provider de imagem activo corresponde a este conteúdo; configure o pool de imagem.")
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        repository.update_content(content_id, {"state": "running"})
        if metadata.get("workflow") == "ugc_products":
            prompts = [str(item or "").strip() for item in (metadata.get("segment_prompts") or []) if str(item or "").strip()]
            prompt = prompts[0] if prompts else str(record.get("prompt") or "")
            reference = Path(str(metadata.get("product_image_path") or ""))
            output = run_with_rate_limit_backoff(
                lambda: generate_image_for_card(
                    settings, {**card, "aspect_ratio": "9:16"}, prompt,
                    topic=str(metadata.get("product_name") or ""), reference_image=reference if reference.is_file() else None,
                )
            )
        else:
            reference_id = str(metadata.get("reference_asset_id") or "")
            reference_path = None
            if reference_id:
                assets = repository.list_assets(str(record.get("influencer_id") or ""))
                asset = next((item for item in assets if str(item.get("id") or "") == reference_id), None)
                if asset is not None:
                    candidate = Path(str(asset.get("stored_path") or ""))
                    reference_path = candidate if candidate.is_file() else None
            output = run_with_rate_limit_backoff(
                lambda: generate_image_for_card(
                    settings, card, str(record.get("prompt") or ""),
                    topic=str(record.get("caption") or ""), reference_image=reference_path,
                )
            )
        repository.update_content(content_id, {"state": "completed", "artifact_path": str(output), "error": None})
        record_notification(
            "influencer_content_completed",
            "Conteúdo de imagem concluído",
            "A imagem de produção foi gerada pela fila de imagens e guardada.",
            metadata={"content_id": content_id, "content_type": "image", "workflow": str(metadata.get("workflow") or "influencer")},
            dedupe_key=f"image-queue:completed:{content_id}:{output}",
        )
        return {"ok": True, "content_id": content_id, "image_path": str(output)}
    except Exception as exc:
        message = str(exc)[:1000]
        try:
            repository.update_content(content_id, {"state": "failed", "error": message})
        except Exception:
            pass
        record_notification(
            "influencer_content_failed",
            "Falha na geração de imagem",
            f"A imagem de produção {content_id} falhou na fila: {message[:300]}",
            metadata={"content_id": content_id, "content_type": "image"},
            dedupe_key=f"image-queue:failed:{content_id}:{message[:80]}",
        )
        return {"ok": False, "content_id": content_id, "error": message}
    finally:
        with _state_lock:
            _inflight.discard(f"content:{content_id}")


def _process_facebook_post(post_id: str) -> dict[str, Any]:
    """Processa UM post Facebook da fila ('imagens_na_fila' → colecta imagens)."""
    from hermes_ui.facebook_automation import list_posts, save_post
    from hermes_ui.facebook_storytelling import collect_storytelling_images
    from hermes_ui.notifications import record_notification

    settings = _settings()
    post = next((dict(item) for item in list_posts() if str(item.get("id") or "") == post_id), None)
    if post is None:
        return {"ok": False, "post_id": post_id, "error": "Post não encontrado."}
    try:
        source = str(post.get("image_source") or "web")
        save_post({**post, "status": "coletando_imagens"})
        run_with_rate_limit_backoff(lambda: collect_storytelling_images(settings, post, source=source))
        record_notification(
            "facebook_images_collected",
            "Imagens Facebook processadas",
            f"As imagens do post '{post.get('theme') or post_id}' foram processadas pela fila de imagens.",
            metadata={"post_id": post_id},
            dedupe_key=f"image-queue:facebook:{post_id}",
        )
        return {"ok": True, "post_id": post_id}
    except Exception as exc:
        message = str(exc)[:1000]
        try:
            save_post({**post, "status": "erro"})
        except Exception:
            pass
        record_notification(
            "facebook_images_failed",
            "Falha nas imagens Facebook",
            f"As imagens do post {post_id} falharam na fila: {message[:300]}",
            metadata={"post_id": post_id},
            dedupe_key=f"image-queue:facebook-failed:{post_id}:{message[:80]}",
        )
        return {"ok": False, "post_id": post_id, "error": message}
    finally:
        with _state_lock:
            _inflight.discard(f"facebook:{post_id}")


def _ensure_executor(max_workers: int) -> ThreadPoolExecutor:
    global _executor, _executor_workers
    with _state_lock:
        if _executor is not None and _executor_workers != max_workers and not _inflight:
            _executor.shutdown(wait=False)
            _executor = None
        if _executor is None or _executor_workers != max_workers:
            _executor = ThreadPoolExecutor(max_workers=max(1, max_workers), thread_name_prefix="image-task")
            _executor_workers = max(1, max_workers)
        return _executor


def _future_done(future: Future) -> None:
    try:
        future.result()
    except Exception:
        pass  # o processamento persiste o erro no próprio registo.


def run_once() -> dict[str, Any]:
    """Um tick da fila de imagens: claim + submissão ao pool limitado."""
    from hermes_ui.render_capacity import motor_limits

    lock = acquire_pid_lock(_lock_path(), WORKER_MARKER)
    if lock is None:
        return {"ok": True, "status": "busy"}
    try:
        settings = _settings()
        limit = max(1, int(motor_limits(settings)["images"]))
        with _state_lock:
            inflight_count = len(_inflight)
        _heartbeat(status="running", active_tasks=inflight_count, limit=limit, last_error="")
        submitted: list[str] = []
        executor = _ensure_executor(limit)
        repository = _repository(settings)
        if repository is not None:
            for record in _queued_image_contents(repository):
                with _state_lock:
                    if inflight_count >= limit:
                        break
                content_id = str(record.get("id") or "")
                key = f"content:{content_id}"
                with _state_lock:
                    if key in _inflight:
                        continue
                try:
                    repository.update_content(content_id, {"state": "running"})
                except Exception:
                    continue
                with _state_lock:
                    _inflight.add(key)
                    inflight_count = len(_inflight)
                executor.submit(_process_image_content, content_id).add_done_callback(_future_done)
                submitted.append(key)
        for post in _queued_facebook_posts():
            with _state_lock:
                if inflight_count >= limit:
                    break
            post_id = str(post.get("id") or "")
            key = f"facebook:{post_id}"
            with _state_lock:
                if key in _inflight:
                    continue
            with _state_lock:
                _inflight.add(key)
                inflight_count = len(_inflight)
            executor.submit(_process_facebook_post, post_id).add_done_callback(_future_done)
            submitted.append(key)
        if submitted or inflight_count:
            _heartbeat(status="running", active_tasks=inflight_count, submitted=submitted)
            return {"ok": True, "status": "running", "submitted": submitted, "inflight": inflight_count}
        _heartbeat(status="idle", active_tasks=0)
        return {"ok": True, "status": "idle"}
    except Exception as exc:
        _heartbeat(status="error", last_error=str(exc)[:1000])
        return {"ok": False, "status": "error", "error": str(exc)[:1000]}
    finally:
        with _state_lock:
            worker_idle = not _inflight
        try:
            if worker_idle:
                lock.unlink()
        except (FileNotFoundError, OSError):
            pass


def _recover_orphaned_claims() -> None:
    """Arranque: claims de um processo morto voltam à fila (retry).

    Só o worker cria 'running' de IMAGEM (a UI agora só marca 'image_queued');
    os vídeos UGC (content_type 'video') continuam síncronos na UI e não são
    tocados. Posts Facebook em 'coletando_imagens' voltam a 'imagens_na_fila'.
    """
    settings = _settings()
    repository = _repository(settings)
    if repository is not None:
        try:
            records = repository.list_content("", limit=200)
        except Exception:
            records = []
        for item in records:
            if not isinstance(item, dict):
                continue
            if str(item.get("state") or "") == "running" and str(item.get("content_type") or "") == "image":
                try:
                    repository.update_content(str(item.get("id") or ""), {"state": "image_queued"})
                except Exception:
                    pass
    try:
        from hermes_ui.facebook_automation import list_posts, save_post

        for post in list_posts():
            if str(post.get("status") or "") == "coletando_imagens":
                save_post({**dict(post), "status": "imagens_na_fila"})
    except Exception:
        pass


def run_worker(interval_seconds: int = ACTIVE_INTERVAL_SECONDS) -> None:
    try:
        from hermes_ui.storage import ensure_storage

        ensure_storage()
        _heartbeat(status="starting")
        _recover_orphaned_claims()
        while True:
            result = run_once()
            idle = bool(result.get("ok")) and result.get("status") == "idle"
            sleep_seconds = max(2, int(interval_seconds))
            time.sleep(max(sleep_seconds, IDLE_INTERVAL_SECONDS) if idle else sleep_seconds)
    except KeyboardInterrupt:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Executor da fila de imagens de produção Thunderbolt")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=ACTIVE_INTERVAL_SECONDS)
    args = parser.parse_args()
    if args.once:
        print(json.dumps(run_once(), ensure_ascii=False), flush=True)
    else:
        run_worker(args.interval)


if __name__ == "__main__":
    main()
