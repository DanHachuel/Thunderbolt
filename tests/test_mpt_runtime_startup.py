"""Arranque concorrente do runtime MPT (1.0.17).

Com 3+ vídeos em paralelo o mpt_agent.py não chegava a produzir a primeira
linha dentro dos 5 minutos do idle watchdog e a etapa morria com «zero
output do helper» — falha de ARRANQUE do runtime, não da API de material.
Mitigações: janela de arranque dedicada (``motor.helper_start_timeout_seconds``,
default 600 s), gate do runtime (``motor.max_parallel_mpt_runtimes``, default 2),
telemetria de spawn (PID + comando) e higiene de file handles.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from hermes_ui import pipeline_worker
from hermes_ui import storage


ROOT = Path(__file__).resolve().parents[1]
PIPELINE_SOURCE = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")
APP_MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


class _FakeStdout:
    def __init__(self, lines):
        self._lines = iter(lines)

    def readline(self):
        return next(self._lines, "")

    def close(self):
        return None


class _FakePopen:
    def __init__(self, lines, stays_alive=True):
        self.stdout = _FakeStdout(lines)
        self.returncode = None if stays_alive else 0
        self.pid = 999999

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


def _isolate(tmp_path, monkeypatch, task_id="mpt-task"):
    root = tmp_path / "storage"
    monkeypatch.setattr(storage, "STORAGE", root)
    monkeypatch.setattr(storage, "STATE", root / "state")
    monkeypatch.setattr(storage, "BLUEPRINTS", root / "blueprints")
    monkeypatch.setattr(pipeline_worker, "STORAGE", root)
    storage.ensure_storage()
    storage.write_json("settings.json", {"pexels_api_keys": ["pexels-test-key-1234567890123456"]})
    storage.write_json("tasks.json", [{"id": task_id, "state": "doing", "stage": "video", "progress": 50, "topic": "Tema"}])


# ---------------------------------------------------------------------------
# Configuração: janela de arranque + gate do runtime
# ---------------------------------------------------------------------------


def test_helper_start_timeout_defaults_to_600_and_honours_settings():
    assert pipeline_worker._video_helper_start_timeout_seconds({}) == 600
    assert pipeline_worker._video_helper_start_timeout_seconds({"motor": {"helper_start_timeout_seconds": 900}}) == 900
    # vazio/zero/inválido volta ao default (desligar o watchdog continua a
    # ser feito com VIDEO_IDLE_TIMEOUT_SECONDS = 0)
    assert pipeline_worker._video_helper_start_timeout_seconds({"motor": {"helper_start_timeout_seconds": 0}}) == 600
    assert pipeline_worker._video_helper_start_timeout_seconds({"motor": {"helper_start_timeout_seconds": None}}) == 600
    assert pipeline_worker._video_helper_start_timeout_seconds({"motor": {"helper_start_timeout_seconds": "x"}}) == 600
    assert pipeline_worker._video_helper_start_timeout_seconds(None) == 600


def test_max_parallel_mpt_runtimes_defaults_to_2_and_honours_settings():
    assert pipeline_worker._max_parallel_mpt_runtimes({}) == 2
    assert pipeline_worker._max_parallel_mpt_runtimes({"motor": {"max_parallel_mpt_runtimes": 4}}) == 4
    assert pipeline_worker._max_parallel_mpt_runtimes({"motor": {"max_parallel_mpt_runtimes": 0}}) == 2
    assert pipeline_worker._max_parallel_mpt_runtimes({"motor": {"max_parallel_mpt_runtimes": "x"}}) == 2
    assert pipeline_worker._max_parallel_mpt_runtimes(None) == 2


# ---------------------------------------------------------------------------
# Gate: apenas N runtimes MPT em simultâneo; espera re-lê a configuração
# ---------------------------------------------------------------------------


def test_mpt_runtime_gate_limits_concurrency_and_releases_to_waiters():
    settings = {"motor": {"max_parallel_mpt_runtimes": 2}}
    entered = threading.Event()
    release = threading.Event()
    third_entered = threading.Event()
    held: list[threading.Thread] = []

    def hold_both():
        with pipeline_worker._mpt_runtime_slot("holder-1", settings):
            with pipeline_worker._mpt_runtime_slot("holder-2", settings):
                assert pipeline_worker._mpt_runtime_in_flight() == 2
                entered.set()
                release.wait(timeout=10)

    holder = threading.Thread(target=hold_both)
    holder.start()
    assert entered.wait(timeout=5)

    def third_task():
        with pipeline_worker._mpt_runtime_slot("terceira", settings):
            third_entered.set()

    waiter = threading.Thread(target=third_task)
    waiter.start()
    # dois slots ocupados: a terceira tarefa fica à espera do gate
    assert not third_entered.wait(timeout=0.6)
    release.set()
    holder.join(timeout=5)
    waiter.join(timeout=5)
    assert third_entered.is_set()
    assert pipeline_worker._mpt_runtime_in_flight() == 0


def test_mpt_runtime_gate_rereads_settings_while_waiting():
    # A espera re-lê a configuração a cada ciclo: baixar o limite com gente
    # em fila mantém a espera; libertar o último slot deixa entrar.
    settings = {"motor": {"max_parallel_mpt_runtimes": 2}}
    entered = threading.Event()
    release = threading.Event()
    second_entered = threading.Event()

    def hold_first():
        with pipeline_worker._mpt_runtime_slot("primeira", settings):
            entered.set()
            release.wait(timeout=10)

    holder = threading.Thread(target=hold_first)
    holder.start()
    assert entered.wait(timeout=5)

    with pipeline_worker._mpt_runtime_slot("segunda", settings):
        settings["motor"]["max_parallel_mpt_runtimes"] = 1

        def blocked_task():
            with pipeline_worker._mpt_runtime_slot("terceira", settings):
                second_entered.set()

        waiter = threading.Thread(target=blocked_task)
        waiter.start()
        # limite lido de novo: 1 slot e 1 activo → continua à espera
        assert not second_entered.wait(timeout=0.6)
    release.set()
    holder.join(timeout=5)
    waiter.join(timeout=5)
    assert second_entered.is_set()


# ---------------------------------------------------------------------------
# Telemetria de spawn: comando depurado (roteiro resumido)
# ---------------------------------------------------------------------------


def test_spawn_command_summary_masks_script_value_and_keeps_the_contract():
    command = [
        "python.exe",
        "mpt_agent.py",
        "--video-source",
        "pexels",
        "--video-script",
        "uma narração muito longa " * 50,
        "--video-clip-duration",
        "15",
    ]
    summary = pipeline_worker._mpt_spawn_command_summary(command)

    assert "mpt_agent.py" in summary
    assert "--video-source pexels" in summary
    assert "uma narração muito longa" not in summary
    assert "<" in summary and "chars>" in summary
    assert "--video-clip-duration 15" in summary
    assert len(summary) <= 2000


# ---------------------------------------------------------------------------
# Watchdog: a janela de arranque aplica-se apenas ao silêncio sem output
# ---------------------------------------------------------------------------


def test_startup_window_expires_with_the_zero_output_attribution(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch, task_id="mpt-startup")
    # idle watchdog normal GRANDE; janela de arranque 1 s: quem mata é a
    # janela de arranque, com a atribuição rica ao runtime MPT.
    monkeypatch.setattr(pipeline_worker, "_video_idle_timeout_seconds", lambda task, settings=None: 999)
    monkeypatch.setattr(pipeline_worker, "_video_helper_start_timeout_seconds", lambda settings=None: 1)
    monkeypatch.setattr(pipeline_worker, "_video_timeout_seconds", lambda task, settings=None: 999)
    process = _FakePopen([], stays_alive=True)
    monkeypatch.setattr(pipeline_worker.subprocess, "Popen", lambda *args, **kwargs: process)

    with pytest.raises(pipeline_worker.PipelineError, match="zero output do helper"):
        pipeline_worker._run_video_helper({"id": "mpt-startup", "topic": "Tema"})

    assert process.returncode == -9


def test_startup_window_protects_silent_helper_from_the_regular_idle_watchdog(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch, task_id="mpt-protected")
    # idle normal 1 s MAS janela de arranque 999 s: helper mudo não morre ao
    # 1 s — a etapa só termina pelo timeout TOTAL (3 s), provando que o idle
    # watchdog não disparou durante o silêncio inicial.
    monkeypatch.setattr(pipeline_worker, "_video_idle_timeout_seconds", lambda task, settings=None: 1)
    monkeypatch.setattr(pipeline_worker, "_video_helper_start_timeout_seconds", lambda settings=None: 999)
    monkeypatch.setattr(pipeline_worker, "_video_timeout_seconds", lambda task, settings=None: 3)
    process = _FakePopen([], stays_alive=True)
    monkeypatch.setattr(pipeline_worker.subprocess, "Popen", lambda *args, **kwargs: process)

    with pytest.raises(pipeline_worker.PipelineError, match="excedeu o limite"):
        pipeline_worker._run_video_helper({"id": "mpt-protected", "topic": "Tema"})


def test_disabled_idle_watchdog_stays_disabled_during_startup(tmp_path, monkeypatch):
    # VIDEO_IDLE_TIMEOUT_SECONDS = 0 desliga o watchdog INTEIRO — a janela de
    # arranque não o reactiva (contrato do teste histórico de idle da 0.9.92).
    _isolate(tmp_path, monkeypatch, task_id="mpt-disabled")
    monkeypatch.setattr(pipeline_worker, "VIDEO_IDLE_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(pipeline_worker, "_video_helper_start_timeout_seconds", lambda settings=None: 600)
    process = _FakePopen([], stays_alive=True)
    monkeypatch.setattr(pipeline_worker.subprocess, "Popen", lambda *args, **kwargs: process)

    with pytest.raises(pipeline_worker.PipelineError, match="actividade comprovada"):
        pipeline_worker._run_video_helper({"id": "mpt-disabled", "topic": "Tema"})


def test_irrelevant_early_line_does_not_close_the_startup_window(tmp_path, monkeypatch):
    """1.0.20: linha stdout irrelevante (validação de chaves/config) NÃO encerra
    a janela de arranque — o carregamento pesado do runtime vem DEPOIS dela e
    o idle de 5 min matava o arranque a meio (relato 1.0.19). A janela é lida
    do settings.json REAL (motor.helper_start_timeout_seconds=2), provando o
    encadeamento settings → watchdog; o idle normal (1 s) não pode matar."""
    _isolate(tmp_path, monkeypatch, task_id="mpt-early-line")
    storage.write_json("settings.json", {"pexels_api_keys": ["pexels-test-key-1234567890123456"], "motor": {"helper_start_timeout_seconds": 2}})
    monkeypatch.setattr(pipeline_worker, "_video_idle_timeout_seconds", lambda task, settings=None: 1)
    monkeypatch.setattr(pipeline_worker, "_video_timeout_seconds", lambda task, settings=None: 999)
    process = _FakePopen(["Pexels key validation completed: ok\n"], stays_alive=True)
    monkeypatch.setattr(pipeline_worker.subprocess, "Popen", lambda *args, **kwargs: process)

    with pytest.raises(pipeline_worker.PipelineError, match="nunca chegou a começar a renderizar"):
        pipeline_worker._run_video_helper({"id": "mpt-early-line", "topic": "Tema"})

    assert process.returncode == -9


def test_generation_log_activity_starts_the_regular_idle_watchdog(tmp_path, monkeypatch):
    """Log do MoneyPrinterTurbo a avançar (mtime) = o motor COMEÇOU a renderizar:
    a partir daí vale o idle watchdog normal — helper mudo morre ao 1 s SEM a
    atribuição de arranque do runtime."""
    _isolate(tmp_path, monkeypatch, task_id="mpt-rendering")
    engine_log = tmp_path / "moneyprinter-video.log"
    engine_log.write_text("start\n", encoding="utf-8")
    monkeypatch.setattr(pipeline_worker, "_video_idle_timeout_seconds", lambda task, settings=None: 1)
    monkeypatch.setattr(pipeline_worker, "_video_timeout_seconds", lambda task, settings=None: 999)
    calls = {"count": 0}

    def fake_log_activity(path, previous_mtime):
        calls["count"] += 1
        if calls["count"] == 1:
            return 1234.5, True
        return 1234.5, False

    monkeypatch.setattr(pipeline_worker, "_latest_helper_log_activity", fake_log_activity)
    process = _FakePopen([f"full generation log: {engine_log}\n"], stays_alive=True)
    monkeypatch.setattr(pipeline_worker.subprocess, "Popen", lambda *args, **kwargs: process)

    with pytest.raises(pipeline_worker.PipelineError, match="actividade comprovada") as excinfo:
        pipeline_worker._run_video_helper({"id": "mpt-rendering", "topic": "Tema"})

    assert "nunca chegou a começar a renderizar" not in str(excinfo.value)
    assert "zero output do helper" not in str(excinfo.value)


# ---------------------------------------------------------------------------
# Source-structure: gate + spawn instrumentado + higiene + aba Motor
# ---------------------------------------------------------------------------


def test_gate_wraps_the_mpt_spawn_until_the_process_is_reaped():
    gate_at = PIPELINE_SOURCE.index('with _mpt_runtime_slot(str(task.get("id") or ""), settings):')
    popen_at = PIPELINE_SOURCE.index("        process = subprocess.Popen(", gate_at)
    wait_at = PIPELINE_SOURCE.index("process.wait(timeout=5)", gate_at)
    assert gate_at < popen_at < wait_at
    assert "@contextmanager" in PIPELINE_SOURCE
    assert "def _mpt_runtime_slot(" in PIPELINE_SOURCE


def test_spawn_carries_close_fds_and_immediate_io_error_logging():
    spawn_region = PIPELINE_SOURCE.split("with _mpt_runtime_slot(str(task.get(\"id\") or \"\"), settings):", 1)[1][:4000]
    assert "close_fds=True," in spawn_region
    assert "except OSError as exc:" in spawn_region
    assert '_mpt_runtime_log(f"[MPT-SPAWN] falha de I/O ao arrancar o runtime MPT' in spawn_region
    # banner com PID persistido na diagonal da tarefa
    assert "[MPT-SPAWN] pid={process.pid}" in spawn_region
    assert "_append_bounded_video_helper_output(output_lines, spawn_banner, output_chars)" in spawn_region


def test_watchdog_uses_the_configurable_startup_window_only_while_silent():
    loop = PIPELINE_SOURCE.split("startup_pending = not generation_started", 1)[1][:900]
    assert "helper_start_timeout_seconds if startup_pending and idle_timeout_seconds > 0 else idle_timeout_seconds" in loop
    assert "effective_idle_seconds // 60} minutos" in loop
    # declaração da janela junto dos timeouts base
    assert "helper_start_timeout_seconds = _video_helper_start_timeout_seconds(settings)" in PIPELINE_SOURCE
    # 1.0.20: só o log do motor a avançar encerra a janela de arranque
    assert "startup_pending = not generation_started" in PIPELINE_SOURCE
    assert "generation_started = True" in PIPELINE_SOURCE
    assert "nunca chegou a começar a renderizar" in PIPELINE_SOURCE


def test_stop_process_releases_the_helper_pipes():
    block = PIPELINE_SOURCE.split("def _stop_process(", 1)[1].split("def _normalise_video_route", 1)[0]
    assert "for stream in (getattr(process, \"stdout\", None), getattr(process, \"stderr\", None)):" in block


def test_motor_tab_exposes_the_new_mpt_runtime_fields():
    block = APP_MAIN[APP_MAIN.index("with motor_tab:"):APP_MAIN.index("with ffmpeg_tab:")]
    for needle in (
        '"Runtimes MPT em simultâneo"',
        'key="motor_max_parallel_mpt_runtimes"',
        '"Timeout de arranque do MPT (segundos)"',
        'key="motor_helper_start_timeout"',
        '"max_parallel_mpt_runtimes": int(max_parallel_mpt_runtimes)',
        '"helper_start_timeout_seconds": int(helper_start_timeout)',
    ):
        assert needle in block, f"campo do Motor ausente: {needle}"
