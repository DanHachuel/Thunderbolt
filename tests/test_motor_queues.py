from __future__ import annotations

import time
from pathlib import Path

import pytest

from hermes_ui import storage

ROOT = Path(__file__).resolve().parents[1]
APP_MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
INFLUENCERS_MAIN = (ROOT / "app" / "influencers_ui.py").read_text(encoding="utf-8")
CLI_SOURCE = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")


def _storage(tmp_path, monkeypatch):
    root = tmp_path / "storage"
    monkeypatch.setattr(storage, "STORAGE", root)
    monkeypatch.setattr(storage, "STATE", root / "state")
    monkeypatch.setattr(storage, "BLUEPRINTS", root / "blueprints")
    monkeypatch.setattr(storage, "TIKTOK_PROMPT_MASTERS", root / "tiktok" / "prompts_master")
    monkeypatch.setattr(storage, "MEDIA_DOWNLOADS", root / "media_downloads")
    monkeypatch.setattr(storage, "NICHES_DATA", root / "data" / "niches")
    storage.ensure_storage()
    return root


# ---------------------------------------------------------------------------
# 1.0.11 — Auto-detecção de hardware e limites do Motor
# ---------------------------------------------------------------------------


def test_detect_render_capacity_gpu_with_hw_encoder(monkeypatch):
    from hermes_ui import render_capacity

    monkeypatch.setattr(render_capacity, "_DETECTION_CACHE", {})
    monkeypatch.setattr(render_capacity, "_nvidia_gpu_present", lambda: True)
    monkeypatch.setattr(render_capacity, "_ffmpeg_hardware_encoder_present", lambda: True)
    assert render_capacity.detect_render_capacity() == render_capacity.GPU_VIDEO_CAPACITY == 6


def test_detect_render_capacity_cpu_only(monkeypatch):
    from hermes_ui import render_capacity

    monkeypatch.setattr(render_capacity, "_DETECTION_CACHE", {})
    monkeypatch.setattr(render_capacity, "_nvidia_gpu_present", lambda: False)
    monkeypatch.setattr(render_capacity, "_ffmpeg_hardware_encoder_present", lambda: False)
    assert render_capacity.detect_render_capacity() == render_capacity.CPU_VIDEO_CAPACITY == 3


def test_motor_limits_manual_overrides_and_auto_defaults(monkeypatch):
    from hermes_ui import render_capacity

    monkeypatch.setattr(render_capacity, "detect_render_capacity", lambda: 6)
    assert render_capacity.motor_limits({}) == {"videos": 6, "thumbnails": 5, "images": 3}
    assert render_capacity.motor_limits({"motor": {"max_parallel_videos": 2, "max_parallel_thumbnails": 9, "max_parallel_images": 1}}) == {"videos": 2, "thumbnails": 9, "images": 1}
    # Vazio/zero/inválido volta ao automático (regra da aba Motor).
    assert render_capacity.motor_limits({"motor": {"max_parallel_videos": 0, "max_parallel_thumbnails": "", "max_parallel_images": None}}) == {"videos": 6, "thumbnails": 5, "images": 3}


# ---------------------------------------------------------------------------
# Runtime partilhado: backoff 429 + lock por PID
# ---------------------------------------------------------------------------


def test_rate_limit_backoff_retries_exponentially_and_other_errors_raise():
    from hermes_ui.queue_worker_runtime import is_rate_limit, run_with_rate_limit_backoff

    calls: list[int] = []
    sleeps: list[float] = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("HTTP 429 Too Many Requests: rate limit exceeded")
        return "ok"

    assert run_with_rate_limit_backoff(flaky, attempts=3, base_delay=1.0, sleep=sleeps.append) == "ok"
    assert sleeps == [1.0, 2.0]  # backoff exponencial: 30s → 60s → 120s no real
    assert is_rate_limit(RuntimeError("429 Too Many Requests")) is True
    assert is_rate_limit(RuntimeError("auth token invalid")) is False
    # Erros que não são Rate Limit propagam imediatamente (sem retry às cegas).
    with pytest.raises(RuntimeError):
        run_with_rate_limit_backoff(lambda: (_ for _ in ()).throw(RuntimeError("bad api key")), attempts=3, sleep=sleeps.append)
    assert len(calls) == 3


def test_pid_lock_allows_reentry_of_same_process(tmp_path):
    from hermes_ui.queue_worker_runtime import acquire_pid_lock

    lock = acquire_pid_lock(tmp_path / "queue.lock", "marker")
    assert lock is not None
    # Workers de fila mantêm o lock entre ticks com tarefas em voo — o MESMO
    # processo tem de continuar a deter o lock, não bloquear-se a si próprio.
    assert acquire_pid_lock(tmp_path / "queue.lock", "marker") == lock


# ---------------------------------------------------------------------------
# Estado `standby` (Na fila de vídeo)
# ---------------------------------------------------------------------------


def test_standby_is_valid_state_and_transition(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    from hermes_ui.domain import VALID_STATES, transition_task

    assert "standby" in VALID_STATES
    storage.write_json("tasks.json", [{"id": "task-standby", "channel_id": "ch", "state": "to_do"}])
    updated = transition_task("task-standby", "standby")
    assert updated is not None and updated["state"] == "standby"


def test_runnable_tasks_include_standby_and_exclude_manual_start(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    from hermes_ui.pipeline_worker import _next_runnable_task, _runnable_tasks

    tasks = [
        {"id": "a", "state": "to_do", "manual_start_required": True},
        {"id": "b", "state": "standby"},
        {"id": "c", "state": "doing"},
        {"id": "d", "state": "to_do"},
        {"id": "e", "state": "done"},
    ]
    assert [task["id"] for task in _runnable_tasks(tasks)] == ["b", "c", "d"]
    assert _next_runnable_task(tasks)["id"] == "b"
    # As em voo (in-flight) não são resubmetidas pelo pump.
    assert [task["id"] for task in _runnable_tasks(tasks, exclude={"b", "c"})] == ["d"]


# ---------------------------------------------------------------------------
# Pump paralelo da fila de vídeos
# ---------------------------------------------------------------------------


def _reset_pipeline_parallel_state(pipeline_worker):
    with pipeline_worker._parallel_state_lock:
        pipeline_worker._inflight_futures.clear()
        executor = pipeline_worker._parallel_executor
        pipeline_worker._parallel_executor = None
        pipeline_worker._parallel_executor_workers = 0
        pipeline_worker._worker_lock_path = None
    if executor is not None:
        executor.shutdown(wait=False)


def _wait_for(condition, timeout_seconds: float = 6.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if condition():
            return
        time.sleep(0.05)


def _mark_done(storage_module, task_id: str) -> None:
    tasks = storage_module.read_json("tasks.json")
    for item in tasks:
        if item.get("id") == task_id:
            item["state"] = "done"
    storage_module.write_json("tasks.json", tasks)


def test_pump_once_submits_up_to_motor_limit_and_does_not_resubmit_inflight(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    from hermes_ui import pipeline_worker

    storage.write_json("settings.json", {"motor": {"max_parallel_videos": 2}})
    monkeypatch.setattr(pipeline_worker, "_recover_interrupted_pipeline_worker", lambda: False)
    monkeypatch.setattr(pipeline_worker, "_recover_stale_tasks", lambda: [])
    monkeypatch.setattr(pipeline_worker, "check_all_accounts_session_info_health", lambda *args, **kwargs: [])
    monkeypatch.setattr(pipeline_worker, "emit_session_info_health_alerts", lambda items: [])
    monkeypatch.setattr("hermes_ui.social_auto_upload_backend.reconcile_uncertain_uploads", lambda: [])

    import threading

    release = threading.Event()
    started: list[str] = []

    def fake_execute(candidate):
        started.append(candidate["id"])
        release.wait(timeout=10)
        # Na produção, _run_task persiste o estado final da tarefa no disco.
        tasks = storage.read_json("tasks.json")
        for item in tasks:
            if item.get("id") == candidate["id"]:
                item["state"] = "done"
        storage.write_json("tasks.json", tasks)
        return {"ok": True, "task_id": candidate["id"], "status": "completed"}

    monkeypatch.setattr(pipeline_worker, "_execute_task_safely", fake_execute)
    storage.write_json("tasks.json", [{"id": f"v{index}", "state": "standby"} for index in range(5)])

    try:
        first = pipeline_worker._pump_once()
        assert first["status"] == "running", first
        assert first["submitted"] == ["v0", "v1"]  # limite do Motor: 2 em paralelo
        assert first["inflight"] == 2
        _wait_for(lambda: sorted(started) == ["v0", "v1"])
        # Segundo tick com as duas em voo: nada novo é submetido.
        second = pipeline_worker._pump_once()
        assert second["submitted"] == []
        assert second["inflight"] == 2
        release.set()
        _wait_for(lambda: not pipeline_worker._inflight_snapshot()[1])
        # Depois de livres, o próximo tick puxa mais duas.
        third = pipeline_worker._pump_once()
        assert set(third["submitted"]) == {"v2", "v3"}
        assert third["inflight"] == 2
    finally:
        release.set()
        _wait_for(lambda: not pipeline_worker._inflight_snapshot()[1])
        _reset_pipeline_parallel_state(pipeline_worker)


def test_pump_once_respects_raised_motor_limit_without_restart(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    from hermes_ui import pipeline_worker

    monkeypatch.setattr(pipeline_worker, "_recover_interrupted_pipeline_worker", lambda: False)
    monkeypatch.setattr(pipeline_worker, "_recover_stale_tasks", lambda: [])
    monkeypatch.setattr(pipeline_worker, "check_all_accounts_session_info_health", lambda *args, **kwargs: [])
    monkeypatch.setattr(pipeline_worker, "emit_session_info_health_alerts", lambda items: [])
    monkeypatch.setattr("hermes_ui.social_auto_upload_backend.reconcile_uncertain_uploads", lambda: [])
    monkeypatch.setattr(pipeline_worker, "_execute_task_safely", lambda candidate: (_mark_done(storage, candidate["id"]), {"ok": True, "task_id": candidate["id"], "status": "completed"})[1])
    storage.write_json("settings.json", {"motor": {"max_parallel_videos": 1}})
    storage.write_json("tasks.json", [{"id": f"v{index}", "state": "standby"} for index in range(3)])
    try:
        assert pipeline_worker._pump_once()["submitted"] == ["v0"]
        _wait_for(lambda: not pipeline_worker._inflight_snapshot()[1])
        # Mudança em tempo real: settings.json relido no próximo tick.
        storage.write_json("settings.json", {"motor": {"max_parallel_videos": 3}})
        result = pipeline_worker._pump_once()
        assert set(result["submitted"]) == {"v1", "v2"}
    finally:
        _wait_for(lambda: not pipeline_worker._inflight_snapshot()[1])
        _reset_pipeline_parallel_state(pipeline_worker)


# ---------------------------------------------------------------------------
# Worker da fila de thumbnails
# ---------------------------------------------------------------------------


def _reset_queue_worker_state(worker):
    with worker._state_lock:
        worker._inflight.clear()
        if worker._executor is not None:
            worker._executor.shutdown(wait=False)
        worker._executor = None
        worker._executor_workers = 0


def test_thumbnail_worker_claims_queued_task_and_generates(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    from hermes_ui import thumbnail_worker

    storage.write_json("tasks.json", [{"id": "t1", "channel_id": "ch", "title": "Título", "thumbnail_status": "thumbnail_queued", "thumbnail_prompt": "prompt"}])
    generated: dict[str, str] = {}

    def fake_generate(task_id, settings):
        generated["task_id"] = task_id
        return {}, Path(tmp_path / "thumb.png")

    monkeypatch.setattr("hermes_ui.thumbnails.generate_thumbnail_for_task", fake_generate)
    try:
        result = thumbnail_worker.run_once()
        assert result["submitted"] == ["t1"]
        # Claim imediata: o próximo tick não resubmete (idle quando o fake
        # instantâneo já completou).
        assert thumbnail_worker.run_once().get("submitted", []) == []
        _wait_for(lambda: storage.read_json("tasks.json")[0]["thumbnail_status"] == "generated")
        task = storage.read_json("tasks.json")[0]
        assert task["thumbnail_status"] == "generated"
        assert task["thumbnail_queue_action"] is None
        assert generated["task_id"] == "t1"
    finally:
        _reset_queue_worker_state(thumbnail_worker)


def test_thumbnail_worker_marks_failed_and_keeps_queue_action_clear(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    from hermes_ui import thumbnail_worker

    storage.write_json("tasks.json", [{"id": "t2", "channel_id": "ch", "thumbnail_status": "thumbnail_queued", "thumbnail_queue_action": "regenerate_prompt"}])

    def boom(task_id, settings):
        raise RuntimeError("provider de imagem indisponível")

    monkeypatch.setattr("hermes_ui.thumbnails.regenerate_thumbnail_prompt", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("LLM 429")))
    monkeypatch.setattr("hermes_ui.thumbnails.generate_thumbnail_for_task", boom)
    try:
        thumbnail_worker.run_once()
        _wait_for(lambda: storage.read_json("tasks.json")[0]["thumbnail_status"] == "failed")
        task = storage.read_json("tasks.json")[0]
        assert task["thumbnail_status"] == "failed"
        assert "thumbnail_error" in task and task["thumbnail_queue_action"] is None
    finally:
        _reset_queue_worker_state(thumbnail_worker)


# ---------------------------------------------------------------------------
# Worker da fila de imagens de produção
# ---------------------------------------------------------------------------


class _FakeContentRepository:
    def __init__(self, records):
        self.records = records

    def list_content(self, influencer_id="", limit=200):
        return self.records

    def update_content(self, content_id, updates):
        for record in self.records:
            if str(record.get("id") or "") == str(content_id):
                record.update(dict(updates))
                return record
        return None

    def list_assets(self, influencer_id):
        return []


def test_image_worker_processes_queued_influencer_image(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    from hermes_ui import image_worker

    record = {"id": "c1", "influencer_id": "inf1", "content_type": "image", "state": "image_queued", "prompt": "uma cena", "caption": "cap", "provider": "nano_banana", "model": "gemini", "metadata": {"provider_card_id": "card1"}}
    monkeypatch.setattr(image_worker, "_repository", lambda settings: _FakeContentRepository([record]))
    monkeypatch.setattr(image_worker, "_queued_facebook_posts", lambda: [])
    monkeypatch.setattr("hermes_ui.media_providers.media_cards_for_pool", lambda settings, pool: [{"id": "card1", "provider": "nano_banana", "model": "gemini"}])
    monkeypatch.setattr("hermes_ui.media_generation.generate_image_for_card", lambda settings, card, prompt, **kwargs: Path(tmp_path / "img.png"))
    try:
        result = image_worker.run_once()
        assert result["submitted"] == ["content:c1"]
        assert image_worker.run_once().get("submitted", []) == []
        _wait_for(lambda: record["state"] == "completed")
        assert record["artifact_path"] == str(tmp_path / "img.png")
        assert record["error"] is None
    finally:
        _reset_queue_worker_state(image_worker)


def test_image_worker_processes_queued_facebook_post(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    from hermes_ui import image_worker

    post = {"id": "p1", "theme": "Tema", "status": "imagens_na_fila", "image_source": "ai"}
    saved: list[dict] = []
    monkeypatch.setattr(image_worker, "_repository", lambda settings: None)
    monkeypatch.setattr(image_worker, "_queued_facebook_posts", lambda: [dict(post)])
    monkeypatch.setattr("hermes_ui.facebook_automation.list_posts", lambda: [dict(post)])
    monkeypatch.setattr("hermes_ui.facebook_automation.save_post", lambda p: saved.append(dict(p)))
    collected: list[dict] = []
    monkeypatch.setattr(
        "hermes_ui.facebook_storytelling.collect_storytelling_images",
        lambda settings, target, *, source="web": collected.append({"post_id": target.get("id"), "source": source}),
    )
    try:
        result = image_worker.run_once()
        assert result["submitted"] == ["facebook:p1"]
        _wait_for(lambda: collected)
        assert collected[0] == {"post_id": "p1", "source": "ai"}
        assert any(item.get("status") == "coletando_imagens" for item in saved)
    finally:
        _reset_queue_worker_state(image_worker)


# ---------------------------------------------------------------------------
# UI — aba Motor, standby, KPIs e acções instantâneas (source-structure)
# ---------------------------------------------------------------------------


def test_motor_tab_between_subtitles_and_ffmpeg_with_three_limits():
    block = APP_MAIN[APP_MAIN.index("with motor_tab:"):APP_MAIN.index("with ffmpeg_tab:")]
    for needle in (
        '"Vídeos em paralelo"',
        '"Thumbnails em paralelo"',
        '"Imagens de produção em paralelo"',
        'key="motor_max_parallel_videos"',
        'key="motor_max_parallel_thumbnails"',
        'key="motor_max_parallel_images"',
        'key="save_motor_settings"',
        '"max_parallel_videos"',
        '"max_parallel_thumbnails"',
        '"max_parallel_images"',
        "detect_render_capacity",
    ):
        assert needle in block, f"campo do Motor ausente: {needle}"
    assert APP_MAIN.index("with subtitles_tab:") < APP_MAIN.index("with motor_tab:") < APP_MAIN.index("with ffmpeg_tab:")
    assert '"Legendas", "Motor", "FFmpeg"' in APP_MAIN


def test_start_button_places_tasks_in_standby_not_doing():
    start_block = APP_MAIN[APP_MAIN.index("def _start_pipeline_task("):APP_MAIN.index("def _remake_video_from_card(")]
    assert 'transition_task(task_id, "standby")' in start_block
    assert 'transition_task(task_id, "doing")' not in start_block


def test_automation_kpis_include_em_fila_and_state_labels_show_standby():
    kpis = APP_MAIN[APP_MAIN.index("def _render_youtube_automation_kpis("):APP_MAIN.index("def render_automation():")]
    assert 'card("Em Fila", counts.get("standby", 0), "aguardando slot")' in kpis
    assert '"standby": "Aguardando na fila"' in APP_MAIN


def test_thumbnail_page_actions_queue_instead_of_blocking():
    for needle in (
        '"thumbnail_status": "thumbnail_queued", "thumbnail_queue_action": None, "thumbnail_queued_at": now()',
        '"thumbnail_queue_action": "regenerate_prompt"',
        '"thumbnail_queue_action": "regenerate_lettering"',
    ):
        assert needle in APP_MAIN
    # Os spinners de geração síncrona desapareceram das thumbnails.
    assert "A gerar a imagem com Nano Banana" not in APP_MAIN
    assert "A refazer o prompt e a imagem" not in APP_MAIN
    assert "A refazer apenas o lettering" not in APP_MAIN


def test_facebook_and_influencer_actions_queue_instantly():
    assert '"status": "imagens_na_fila", "image_source"' in APP_MAIN
    assert '"state": "image_queued"' in INFLUENCERS_MAIN
    assert '"provider_card_id"' in INFLUENCERS_MAIN
    assert '"image_queued": "Na fila de imagens"' in INFLUENCERS_MAIN


def test_cli_mjs_spawns_and_stops_the_two_queue_workers():
    assert '"-m", "hermes_ui.thumbnail_worker"' in CLI_SOURCE
    assert '"-m", "hermes_ui.image_worker"' in CLI_SOURCE
    assert "startQueueWorkers();" in CLI_SOURCE
    assert "stopQueueWorkers();" in CLI_SOURCE
    assert "thumbnail-worker" in CLI_SOURCE
    assert "image-worker" in CLI_SOURCE
    assert "let thumbnailWorker = null;" in CLI_SOURCE
    assert "let imageWorker = null;" in CLI_SOURCE
