"""1.0.59 — timer do passo desde o roteiro, teto da fase de roteiro, telemetria
e watchdog da fase de materiais (Pexels) e recuperacao de tarefas orfas.

Contexto do relato do utilizador: "timer desapareceu" + "preso em 18% (suposta
fase de download Pexels) por mais de 20 minutos". A investigacao provou que:

* o timer so existia na etapa de VIDEO (``_VideoStageTimer`` arrancado em
  ``stage=video``): durante o roteiro o card nao tinha ``video_elapsed_seconds``
  e mostrava 18% congelado;
* a fase presa era a de ROTEIRO (3 tentativas de LLM x cartoes do pool, cada
  chamada com timeout de 120 s) - sem heartbeat e sem limite temporal;
* o download de clipes acontece no motor MPT externo (fork), que JA tem timeout
  por clipe (60 s/240 s) e SALta clipes com falha - o que faltava era o
  Thunderbolt saber o que se passa (telemetria) e limitar a SOMA da fase;
* o pump paralelo nao escreve ``last_task_id``, por isso a recuperacao de
  worker interrompido cobria UMA tarefa e deixava as restantes "doing" para
  sempre (duas tarefas reais presas em 18%, fila pausada, sem erro).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_ui import pipeline_worker, storage


ROOT = Path(__file__).resolve().parents[1]
WORKER_SOURCE = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")
SCRIPT_SOURCE = (ROOT / "hermes_ui" / "script_generation.py").read_text(encoding="utf-8")
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# UI: o timer do card
# ---------------------------------------------------------------------------


def test_ui_keeps_the_video_stage_timer_caption_below_the_progress_bar():
    """O card mostra 'Tempo da etapa Video' colado a barra de progresso."""
    block = MAIN_SOURCE.split("def _render_video_task_state(", 1)[1].split(
        "def _render_youtube_automation_task_list", 1
    )[0]
    progress_index = block.index("st.progress(")
    caption_index = block.index('st.caption(f"Tempo da etapa')
    assert caption_index > progress_index, "a legenda vem abaixo da barra"
    assert "video_elapsed_seconds" in block.split('st.caption(f"Tempo da etapa', 1)[0]
    assert "{elapsed_seconds // 60}m {elapsed_seconds % 60:02d}s" in block


# ---------------------------------------------------------------------------
# _VideoStageTimer: relogio do passo + actividade da fase
# ---------------------------------------------------------------------------


def test_video_stage_timer_accepts_the_activity_provider(monkeypatch):
    import threading as real_threading

    monkeypatch.setattr(pipeline_worker, "VIDEO_STAGE_HEARTBEAT_INTERVAL_SECONDS", 0.05)
    writes: list[dict] = []

    monkeypatch.setattr(
        pipeline_worker,
        "_task_by_id",
        lambda _tid: {"state": "doing", "stage": "script", "progress": 18},
    )
    monkeypatch.setattr(pipeline_worker, "_update", lambda _tid, **updates: writes.append(dict(updates)))
    monkeypatch.setattr(pipeline_worker, "_worker_heartbeat", lambda **updates: writes.append(dict(updates)))

    timer = pipeline_worker._VideoStageTimer(
        "task-timer-status",
        pipeline_worker.time.monotonic() - 1,
        status_provider=lambda: "[SCRIPT] a gerar roteiro (tentativa 2/3)",
    ).start()
    real_threading.Event().wait(0.45)
    timer.stop()

    statuses = [w.get("video_helper_status") for w in writes if "video_helper_status" in w]
    assert statuses, "o timer escreve a actividade da fase no tasks.json"
    assert all(s.startswith("[SCRIPT]") for s in statuses)


def test_video_stage_timer_stops_when_the_task_is_no_longer_doing(monkeypatch):
    import threading as real_threading

    monkeypatch.setattr(pipeline_worker, "VIDEO_STAGE_HEARTBEAT_INTERVAL_SECONDS", 0.05)
    writes: list[dict] = []
    monkeypatch.setattr(
        pipeline_worker, "_task_by_id", lambda _tid: {"state": "failed", "stage": "video"}
    )
    monkeypatch.setattr(pipeline_worker, "_update", lambda _tid, **updates: writes.append(dict(updates)))
    monkeypatch.setattr(pipeline_worker, "_worker_heartbeat", lambda **updates: writes.append(dict(updates)))

    pipeline_worker._VideoStageTimer("task-failed", pipeline_worker.time.monotonic()).start()
    real_threading.Event().wait(0.35)
    assert not [w for w in writes if "video_elapsed_seconds" in w], (
        "tarefa falhada nao recebe mais batimentos do relogio"
    )


def test_step_clock_is_wired_from_the_script_stage():
    assert (
        "_VideoStageTimer(\n        task_id, _step_started_at, status_provider=_step_activity\n    ).start()"
        in WORKER_SOURCE
    )
    assert "_video_stage_timer = _step_timer" in WORKER_SOURCE
    assert "_video_stage_timer.stop()" in WORKER_SOURCE


# ---------------------------------------------------------------------------
# Fase de roteiro: heartbeat + teto temporal
# ---------------------------------------------------------------------------


def test_generate_script_with_heartbeat_reports_each_attempt(monkeypatch):
    captured: dict = {}
    logs: list[str] = []
    monkeypatch.setattr(pipeline_worker, "_mpt_runtime_log", logs.append)

    def fake_generate(settings, on_attempt=None, **kwargs):  # noqa: ANN001
        captured["settings"] = settings
        assert on_attempt is not None, "o worker passa o callback de tentativas"
        on_attempt(1, 3, "a chamar o LLM")
        on_attempt(1, 3, "rejeitada: tags de producao")
        on_attempt(2, 3, "a chamar o LLM")
        return {"content": "apenas texto falado"}

    monkeypatch.setattr(
        "hermes_ui.script_generation.generate_script_document", fake_generate
    )
    status: dict[str, str] = {}
    result = pipeline_worker._generate_script_with_heartbeat(
        {"id": "video-hb"}, {"motor": {}}, status=status, document_type="x"
    )

    assert result["content"] == "apenas texto falado"
    assert "tentativa 2/3" in status.get("status", "")
    assert any("[SCRIPT]" in line and "tentativa 1/3" in line for line in logs)
    assert any("inicio da geracao do roteiro" in line for line in logs)


def test_generate_script_with_heartbeat_times_out_with_clear_error(monkeypatch):
    monkeypatch.setattr(pipeline_worker, "_mpt_runtime_log", lambda _message: None)

    def slow_generate(settings, on_attempt=None, **kwargs):  # noqa: ANN001
        pipeline_worker.time.sleep(5)
        return {"content": "nunca chega"}

    monkeypatch.setattr("hermes_ui.script_generation.generate_script_document", slow_generate)

    with pytest.raises(pipeline_worker.PipelineError) as excinfo:
        pipeline_worker._generate_script_with_heartbeat(
            {"id": "video-slow"},
            {"motor": {"script_timeout_seconds": 1}},
            status={},
            document_type="x",
        )
    message = str(excinfo.value)
    assert "roteiro" in message and "excedeu" in message


def test_generate_script_with_heartbeat_propagates_generation_errors(monkeypatch):
    from hermes_ui.creative_generation import CreativeGenerationError

    def failing_generate(settings, on_attempt=None, **kwargs):  # noqa: ANN001
        raise CreativeGenerationError("Após 3 tentativas, o roteiro não cumpre as regras.")

    monkeypatch.setattr("hermes_ui.script_generation.generate_script_document", failing_generate)

    with pytest.raises(CreativeGenerationError):
        pipeline_worker._generate_script_with_heartbeat(
            {"id": "video-fail"}, {}, status={}, document_type="x"
        )


def test_script_stage_timeout_defaults_and_override():
    assert pipeline_worker._script_timeout_seconds({}) == pipeline_worker.SCRIPT_STAGE_TIMEOUT_SECONDS
    assert pipeline_worker._script_timeout_seconds({"motor": {"script_timeout_seconds": 42}}) == 42
    assert pipeline_worker._script_timeout_seconds({"motor": {"script_timeout_seconds": 0}}) == (
        pipeline_worker.SCRIPT_STAGE_TIMEOUT_SECONDS
    )


# ---------------------------------------------------------------------------
# Prompt x validador: a contradicao que reprovava o roteiro 3 vezes
# ---------------------------------------------------------------------------


def test_script_prompt_forbids_brackets_instead_of_ordering_marker_lines():
    """O prompt NAO pode ordenar [VISUAL]/[AUDIO] isolados: o validador rejeita-os.

    O prompt dizia "usa linhas de marcacao isoladas ([VISUAL]/[AUDIO])" e o
    validador 1.0.17 reprova exactamente essas tags - o LLM obedecia e era
    rejeitado 3 vezes (falhas reais a 18% no tasks.json do utilizador).
    """
    assert "usa linhas de marca" not in SCRIPT_SOURCE
    assert "PROIBIDOS em qualquer lugar" in SCRIPT_SOURCE
    assert "zero parenteses rectos" in SCRIPT_SOURCE
    # O validador continua RIGIDO (regra 1.0.17 intacta).
    assert "_PRODUCTION_TAG.search(text)" in (ROOT / "hermes_ui" / "blueprint_governance.py").read_text(
        encoding="utf-8"
    )


def test_generate_script_document_reports_progress_via_on_attempt(monkeypatch):
    from hermes_ui import script_generation

    responses = iter(
        [
            {"title": "T", "summary": "S", "content": "[Visual: cena] narracao com tag"},
            {"title": "T", "summary": "S", "content": "apenas narracao falada, sem tags"},
        ]
    )
    events: list[tuple[int, int, str]] = []

    def fake_chat_json(_settings, _system, _user):  # noqa: ANN001
        return next(responses)

    monkeypatch.setattr(script_generation, "_chat_json", fake_chat_json)

    result = script_generation.generate_script_document(
        {},
        document_type="Roteiro de vídeo",
        title="Tema",
        brief="Um tema qualquer",
        language="pt",
        on_attempt=lambda attempt, attempts, phase: events.append((attempt, attempts, phase)),
    )

    assert "sem tags" in result["content"]
    assert len(events) >= 3, "cada tentativa e cada validacao notificam o worker"
    assert any("rejeitada" in phase for _a, _n, phase in events)
    assert events[-1][2].startswith("resposta validada")


# ---------------------------------------------------------------------------
# Fase de materiais: telemetria [PEXELS] + estado para o watchdog
# ---------------------------------------------------------------------------


def _material_log(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def test_material_parser_announces_the_download_and_counts_clips(monkeypatch):
    logs: list[str] = []
    monkeypatch.setattr(pipeline_worker, "_mpt_runtime_log", logs.append)
    state: dict = {}

    # O worker passa o log INTEIRO a cada leitura (crescente), como no motor real.
    opening = _material_log(
        "2026-11-04 11:22:07 | INFO | found total videos: 3, required duration: 60.0 seconds, found duration: 95 seconds",
        "2026-11-04 11:22:08 | INFO | downloading pexels video: asset_id=123",
    )
    state, status = pipeline_worker._pexels_material_progress(opening, state)
    assert state["clips_total"] == 3
    assert "Iniciando download de 3 clipes" in logs[0]
    assert status.startswith("[Pexels] Baixando clipe 0/3")

    state, status = pipeline_worker._pexels_material_progress(
        opening + _material_log("2026-11-04 11:22:20 | INFO | video saved: C:/cache/vid-abc.mp4"),
        state,
    )
    assert state["clips_done"] == 1
    assert status == "[Pexels] Baixando clipe 1/3 (0 falharam)"
    assert any("Clipe 1/3 baixado com sucesso (tempo:" in line for line in logs)


def test_material_parser_reports_skipped_clips_and_completion(monkeypatch):
    logs: list[str] = []
    monkeypatch.setattr(pipeline_worker, "_mpt_runtime_log", logs.append)
    state: dict = {}

    opening = _material_log(
        "found total videos: 2, required duration: 20 seconds",
        "downloading pexels video: asset_id=1",
        "failed to download material video: provider=pexels, error=Timeout, detail=...",
    )
    state, _status = pipeline_worker._pexels_material_progress(opening, state)
    assert state["clips_failed"] == 1
    assert any("Timeout no clipe 1. Pulando..." in line for line in logs)

    state, status = pipeline_worker._pexels_material_progress(
        opening + _material_log("2026-11-04 11:22:44 | INFO | downloaded 1 videos"), state
    )
    assert state.get("materials_running") is False
    assert status == "", "fase concluida nao ocupa a linha de actividade"
    assert any("Download concluido" in line for line in logs)


def test_material_parser_handles_the_script_order_variant(monkeypatch):
    logs: list[str] = []
    monkeypatch.setattr(pipeline_worker, "_mpt_runtime_log", logs.append)
    state: dict = {}

    state, _status = pipeline_worker._pexels_material_progress(
        _material_log(
            "downloading videos with script-order material matching",
            "found total ordered video candidates: 2, required duration: 30 seconds",
            "downloading ordered pexels video for 'investing': asset_id=9",
            "video saved: C:/cache/vid-9.mp4",
        ),
        state,
    )
    assert state["clips_total"] == 2
    assert state["clips_done"] == 1
    assert any("Iniciando download de 2 clipes" in line for line in logs)
    assert any("Clipe 1/2 baixado com sucesso" in line for line in logs)


def test_material_parser_counts_a_second_engine_phase_without_overflow(monkeypatch):
    """Logs REAIS do motor tem DUAS fases de materiais por geracao: o contador
    nao pode passar do total nem repetir clipes ja anunciados."""
    logs: list[str] = []
    monkeypatch.setattr(pipeline_worker, "_mpt_runtime_log", logs.append)
    state: dict = {}

    first = _material_log(
        "found total videos: 3, required duration: 60 seconds",
        "downloading pexels video: asset_id=1",
        "video saved: C:/cache/vid-1.mp4",
        "downloading pexels video: asset_id=2",
        "video saved: C:/cache/vid-2.mp4",
        "downloaded 2 videos",
    )
    state, status = pipeline_worker._pexels_material_progress(first, state)
    assert state["clips_done"] == 2
    assert status == "", "primeira fase concluida"

    state, status = pipeline_worker._pexels_material_progress(
        first
        + _material_log(
            "found total videos: 3, required duration: 60 seconds",
            "downloading pexels video: asset_id=3",
            "video saved: C:/cache/vid-3.mp4",
        ),
        state,
    )
    assert state["clips_done"] == 1, "a segunda fase reinicia a contagem corrente"
    assert status == "[Pexels] Baixando clipe 1/3 (0 falharam)"
    clipes = [line for line in logs if "baixado com sucesso" in line]
    assert len(clipes) == 3, "cada clipe anunciado uma unica vez"
    assert "Clipe 1/3" in clipes[-1], "a segunda fase numera de novo desde 1"


def test_material_parser_ignores_text_without_material_markers():
    state, status = pipeline_worker._pexels_material_progress("starting video generation", {})
    assert status == ""
    assert "phase_started_at" not in state


def test_material_phase_timeout_defaults_and_override():
    assert (
        pipeline_worker._material_phase_timeout_seconds({})
        == pipeline_worker.MATERIAL_PHASE_TIMEOUT_SECONDS
    )
    assert (
        pipeline_worker._material_phase_timeout_seconds({"motor": {"material_download_timeout_seconds": 33}})
        == 33
    )


def test_helper_loop_wires_the_material_watchdog_and_telemetry():
    assert "_pexels_material_progress(" in WORKER_SOURCE
    assert 'material_state, material_status = _pexels_material_progress(' in WORKER_SOURCE
    assert "Timeout ao baixar materiais do Pexels" in WORKER_SOURCE
    assert 'reason="material_timeout"' in WORKER_SOURCE
    # O heartbeat do download escreve a actividade no tasks.json (o timer sobe).
    heartbeat_block = WORKER_SOURCE.split("material_state, material_status = ", 1)[1]
    assert "video_helper_status=helper_status," in heartbeat_block.split("last_heartbeat = elapsed", 1)[0]


# ---------------------------------------------------------------------------
# Recuperacao de worker interrompido: TODAS as tarefas orfas
# ---------------------------------------------------------------------------


def _isolate_storage(tmp_path, monkeypatch):
    root = tmp_path / "storage"
    monkeypatch.setattr(storage, "STORAGE", root)
    monkeypatch.setattr(storage, "STATE", root / "state")
    monkeypatch.setattr(storage, "BLUEPRINTS", root / "blueprints")
    monkeypatch.setattr(storage, "TIKTOK_PROMPT_MASTERS", root / "tiktok" / "prompts_master")
    monkeypatch.setattr(storage, "MEDIA_DOWNLOADS", root / "downloads")
    monkeypatch.setattr(pipeline_worker, "STORAGE", root)
    storage.ensure_storage()
    return root


def test_interrupted_worker_recovers_every_orphaned_task_without_last_task_id(
    tmp_path, monkeypatch
):
    """O cenario REAL do relato: pump paralelo (last_task_id=None), duas tarefas
    presas em script a 18% e worker morto - nenhuma pode ficar 'doing' para
    sempre."""
    _isolate_storage(tmp_path, monkeypatch)
    stale = "2026-11-04T22:55:16.383379+00:00"
    storage.write_json(
        "tasks.json",
        [
            {
                "id": "video-stuck-1",
                "state": "doing",
                "stage": "script",
                "progress": 18,
                "task_heartbeat_at": stale,
                "updated_at": stale,
            },
            {
                "id": "video-stuck-2",
                "state": "doing",
                "stage": "script",
                "progress": 18,
                "task_heartbeat_at": stale,
                "updated_at": stale,
            },
            {"id": "video-pending", "state": "to_do", "stage": "video"},
        ],
    )
    storage.write_json(
        pipeline_worker.PIPELINE_LOG_FILENAME,
        {
            "status": "running",
            "worker_pid": 987654321,
            "last_task_id": None,
            "last_heartbeat_at": "2026-11-04T22:55:17.974830+00:00",
        },
    )
    monkeypatch.setattr(pipeline_worker, "_pid_alive", lambda _pid, **_kwargs: False)

    assert pipeline_worker._recover_interrupted_pipeline_worker() is True

    tasks = {task["id"]: task for task in storage.read_json("tasks.json")}
    for stuck in ("video-stuck-1", "video-stuck-2"):
        assert tasks[stuck]["state"] == "failed"
        assert tasks[stuck]["worker_interrupted"] is True
        assert "interrompido" in tasks[stuck]["error"]
        assert tasks[stuck]["failed_stage"] == "script"
    assert tasks["video-pending"]["state"] == "to_do", "tarefa na fila nao e tocada"
    status = storage.read_json(pipeline_worker.PIPELINE_LOG_FILENAME)
    assert status["auto_paused"] is True
    assert status["crash_task_id"] == "video-stuck-1", "ha crash_task_id mesmo sem last_task_id"


def test_interrupted_worker_keeps_tasks_adopted_by_a_live_worker(tmp_path, monkeypatch):
    """Tarefa com batimento mais recente que o do worker morto foi adoptada por
    outra instancia viva - nao pode ser marcada como falhada."""
    _isolate_storage(tmp_path, monkeypatch)
    storage.write_json(
        "tasks.json",
        [
            {
                "id": "video-adopted",
                "state": "doing",
                "stage": "video",
                "task_heartbeat_at": "2026-11-04T23:30:00.000000+00:00",
                "updated_at": "2026-11-04T23:30:00.000000+00:00",
            }
        ],
    )
    storage.write_json(
        pipeline_worker.PIPELINE_LOG_FILENAME,
        {
            "status": "running",
            "worker_pid": 987654321,
            "last_task_id": None,
            "last_heartbeat_at": "2026-11-04T22:55:17.974830+00:00",
        },
    )
    monkeypatch.setattr(pipeline_worker, "_pid_alive", lambda _pid, **_kwargs: False)

    assert pipeline_worker._recover_interrupted_pipeline_worker() is True

    task = storage.read_json("tasks.json")[0]
    assert task["state"] == "doing", "tarefa adoptada por instancia viva fica intacta"
