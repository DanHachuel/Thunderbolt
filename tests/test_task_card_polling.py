"""Polling em tempo real dos cards de tarefa (1.0.15).

Backlog Vídeos e Automação Youtube deixaram de precisar de F5: cada card vive
no seu próprio fragment e RELÊ o tasks.json em cada execução. Regra de ouro do
``run_every`` (herdada da fila de thumbnails, 1.0.14): a variante live
(``@st.fragment(run_every=_VIDEO_TASK_POLL_SECONDS)``) só existe em
``to_do``/``standby``/``doing``; estados terminais renderizam pela variante
idle (``@st.fragment`` sem ``run_every`` → zero polling de rede em repouso).
Quando o live detecta um estado terminal, CANCELA o próprio timer via
``_stop_own_fragment_auto_rerun()`` (1.0.16: a mensagem ``stop_auto_rerun``
que o runtime usa internamente) — zero reruns completos a partir do polling,
sem os avisos "The fragment ... does not exist anymore" que o antigo
``st.rerun(scope="app")`` inundava no terminal e sem destruir os outros cards.
O memo de 2s partilhado garante que N cards a pollar custem 1 leitura do
catálogo por janela, e as acções da UI (Start/Stop/Refazer/Apagar) invalidam-no
para responderem no instante. Zero alterações ao worker de background.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import app.main as main
from app.main import _invalidate_live_tasks_snapshot, _live_task_by_id, _live_tasks_snapshot, _video_task_is_live


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Estrutura do fragment: a regra de ouro do run_every
# ---------------------------------------------------------------------------


def test_live_states_are_exactly_the_progressing_ones():
    assert '_VIDEO_TASK_LIVE_STATES = frozenset({"to_do", "standby", "doing"})' in MAIN_SOURCE
    assert "_VIDEO_TASK_POLL_SECONDS = 3" in MAIN_SOURCE


def test_backlog_card_variants_follow_the_golden_run_every_rule():
    assert "@st.fragment(run_every=_VIDEO_TASK_POLL_SECONDS)\ndef _video_backlog_card_live(" in MAIN_SOURCE
    # A variante idle nunca força reruns: sem run_every, sem loop de rede.
    idle = MAIN_SOURCE.split("@st.fragment\ndef _video_backlog_card_idle(", 1)[1].split("def _music_backlog_records(", 1)[0]
    assert "st.rerun(" not in idle


def test_youtube_card_variants_follow_the_golden_run_every_rule():
    assert "@st.fragment(run_every=_VIDEO_TASK_POLL_SECONDS)\ndef _youtube_task_card_live(" in MAIN_SOURCE
    idle = MAIN_SOURCE.split("@st.fragment\ndef _youtube_task_card_idle(", 1)[1].split("@st.fragment\ndef _render_youtube_automation_cards", 1)[0]
    assert "st.rerun(" not in idle


def test_live_cards_stop_polling_when_the_task_reaches_a_terminal_state():
    backlog_live = MAIN_SOURCE.split("def _video_backlog_card_live(", 1)[1].split("@st.fragment\ndef _video_backlog_card_idle(", 1)[0]
    assert "state = _video_backlog_card_body(task_id)" in backlog_live
    assert "if state not in _VIDEO_TASK_LIVE_STATES:" in backlog_live
    # 1.0.16: paragem sem rerun — o fragment cancela o PRÓPRIO timer.
    assert "_stop_own_fragment_auto_rerun()" in backlog_live
    assert "st.rerun(" not in backlog_live

    youtube_live = MAIN_SOURCE.split("def _youtube_task_card_live(", 1)[1].split("@st.fragment\ndef _youtube_task_card_idle(", 1)[0]
    assert "state = _youtube_task_card_body(task_id)" in youtube_live
    assert "if state not in _VIDEO_TASK_LIVE_STATES:" in youtube_live
    assert "_stop_own_fragment_auto_rerun()" in youtube_live
    assert "st.rerun(" not in youtube_live


def test_card_bodies_always_re_read_the_current_task_from_disk():
    backlog_body = MAIN_SOURCE.split("def _video_backlog_card_body(", 1)[1].split("@st.fragment(run_every=", 1)[0]
    assert "task = _live_task_by_id(task_id)" in backlog_body
    # Tarefa apagada noutra aba/sessão: sem card fantasma + memo invalidado.
    assert '_invalidate_live_tasks_snapshot()\n        return ""' in backlog_body

    youtube_body = MAIN_SOURCE.split("def _youtube_task_card_body(", 1)[1].split("@st.fragment(run_every=", 1)[0]
    assert "task = _live_task_by_id(task_id)" in youtube_body
    assert '_invalidate_live_tasks_snapshot()\n        return ""' in youtube_body


# ---------------------------------------------------------------------------
# Dispatch por parte da página (Backlog, Automação Youtube e painel da pipeline)
# ---------------------------------------------------------------------------


def test_render_videos_dispatches_panel_and_cards_by_liveness():
    block = MAIN_SOURCE.split("def render_videos():", 1)[1].split("# 1.0.15: card do Backlog", 1)[0]
    # O painel da pipeline polla enquanto existir trabalho vivo.
    assert "if any(_video_task_is_live(task) for task in tasks):" in block
    assert "_render_pipeline_progress_panel_live()" in block
    assert "_render_pipeline_progress_panel()" in block
    # Cada card é um fragment escolhido pelo estado actual.
    assert "if task_state in _VIDEO_TASK_LIVE_STATES:" in block
    assert '_video_backlog_card_live(str(task["id"]))' in block
    assert '_video_backlog_card_idle(str(task["id"]))' in block


def test_youtube_task_list_dispatches_cards_by_liveness():
    block = MAIN_SOURCE.split("def _render_youtube_automation_task_list", 1)[1].split("# 1.0.15: card da Automação Youtube", 1)[0]
    assert "if _catalog_task_state(task) in _VIDEO_TASK_LIVE_STATES:" in block
    assert "_youtube_task_card_live(task_id)" in block
    assert "_youtube_task_card_idle(task_id)" in block


def test_start_and_remake_invalidate_the_snapshot_for_instant_feedback():
    start_block = MAIN_SOURCE.split("def _start_pipeline_task(", 1)[1].split("def _remake_video_from_card(", 1)[0]
    assert "resume_pipeline_worker()" in start_block
    assert "_invalidate_live_tasks_snapshot()" in start_block
    remake_block = MAIN_SOURCE.split("def _remake_video_from_card(", 1)[1].split("def _catalog_task_state(", 1)[0]
    assert "_invalidate_live_tasks_snapshot()" in remake_block
    # Stop/Apagar/Upload ok nos cards também respondem no instante.
    for anchor in ("stop_task_by_user(task_id)", 'delete_task(task["id"])', '"upload_status": "manual" if checked_upload_ok else "pending"'):
        handler = MAIN_SOURCE.split(anchor, 1)[1].split("st.rerun()", 1)[0]
        assert "_invalidate_live_tasks_snapshot()" in handler


# ---------------------------------------------------------------------------
# Painel da pipeline: o contrato estático continua intacto
# ---------------------------------------------------------------------------


def test_progress_panel_keeps_the_static_fragment_contract():
    assert "@st.fragment\ndef _render_pipeline_progress_panel()" in MAIN_SOURCE
    body = MAIN_SOURCE.split("def _pipeline_progress_panel_body()", 1)[1].split("VIDEO_TASK_STATE_LABELS", 1)[0]
    assert "recovered = recover_stale_tasks()" in body
    assert "return True" in body
    assert "return False" in body


def test_progress_panel_live_variant_polls_and_stops_outside_the_guarded_slice():
    live = MAIN_SOURCE.split("@st.fragment(run_every=_VIDEO_TASK_POLL_SECONDS)\ndef _render_pipeline_progress_panel_live()", 1)[1].split("def load_video_tasks_for_catalog", 1)[0]
    assert "if not _pipeline_progress_panel_body():" in live
    # 1.0.16: o painel também pára cancelando o próprio timer, sem rerun.
    assert "_stop_own_fragment_auto_rerun()" in live
    assert "st.rerun(" not in live
    # O guard anti-rerun do painel (test_pipeline_worker) continua a cumprir-se:
    # o mecanismo de paragem vive DEPOIS de VIDEO_TASK_STATE_LABELS, fora da fatia.
    panel_slice = MAIN_SOURCE.split("@st.fragment\ndef _render_pipeline_progress_panel()", 1)[1].split("VIDEO_TASK_STATE_LABELS", 1)[0]
    assert 'st.rerun(scope="app")' not in panel_slice


def test_thumbnail_live_fragment_stops_the_same_way_without_rerun():
    live = MAIN_SOURCE.split("def _thumbnail_status_fragment_live(", 1)[1].split("@st.fragment(run_every=None)\ndef _thumbnail_status_fragment_idle(", 1)[0]
    assert "if status not in _THUMBNAIL_POLLING_STATES:" in live
    assert "_stop_own_fragment_auto_rerun()" in live
    assert "st.rerun(" not in live


def test_stop_own_fragment_auto_rerun_degrades_silently_without_script_context():
    # Fora de um script run (bare mode, testes): False silencioso, sem excepções.
    assert main._stop_own_fragment_auto_rerun() is False


def test_fragment_gone_noise_filter_drops_only_the_race_line():
    import logging

    noise_filter = main._FragmentGoneNoiseFilter()
    race_line = logging.LogRecord(
        "streamlit.runtime.app_session", 20, "app_session.py", 1,
        "The fragment with id abc123 does not exist anymore - it might have been removed during a preceding full-app rerun.",
        (), None,
    )
    normal_line = logging.LogRecord(
        "streamlit.runtime.app_session", 20, "app_session.py", 1,
        "Session started for the app", (), None,
    )
    assert noise_filter.filter(race_line) is False
    assert noise_filter.filter(normal_line) is True
    # O filtro fica instalado no logger exacto que emite a linha (app_session.py).
    assert any(isinstance(item, main._FragmentGoneNoiseFilter) for item in logging.getLogger("streamlit.runtime.app_session").filters)


# ---------------------------------------------------------------------------
# Unidade: memo partilhado de leitura + lookups frescos
# ---------------------------------------------------------------------------


class _CatalogCounter:
    def __init__(self, tasks):
        self.tasks = tasks
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.tasks


@pytest.fixture(autouse=True)
def _clean_snapshot_memo(monkeypatch):
    monkeypatch.setattr(main, "_live_tasks_snapshot_memo", (0.0, []))


def test_snapshot_memo_shares_one_read_across_all_cards(monkeypatch):
    counter = _CatalogCounter([{"id": "t1", "state": "doing"}])
    monkeypatch.setattr(main, "load_video_tasks_for_catalog", counter)
    first = _live_tasks_snapshot()
    second = _live_tasks_snapshot()
    _live_task_by_id("t1")
    _live_task_by_id("t1")
    # 20 cards a pollar na mesma janela → continua a ser UMA leitura do catálogo.
    assert counter.calls == 1
    assert first is second


def test_snapshot_expires_after_the_short_ttl(monkeypatch):
    counter = _CatalogCounter([{"id": "nova", "state": "standby"}])
    monkeypatch.setattr(main, "load_video_tasks_for_catalog", counter)
    main._live_tasks_snapshot_memo = (0.0, [{"id": "velha"}])
    fresh = _live_tasks_snapshot()
    assert counter.calls == 1
    assert fresh[0]["id"] == "nova"


def test_invalidate_forces_the_next_read_to_be_fresh(monkeypatch):
    counter = _CatalogCounter([{"id": "t1", "state": "doing"}])
    monkeypatch.setattr(main, "load_video_tasks_for_catalog", counter)
    _live_tasks_snapshot()
    _invalidate_live_tasks_snapshot()
    assert main._live_tasks_snapshot_memo == (0.0, [])
    _live_tasks_snapshot()
    assert counter.calls == 2


def test_live_task_by_id_finds_the_task_and_ignores_the_rest(monkeypatch):
    counter = _CatalogCounter([{"id": "a", "state": "doing"}, {"id": "b", "state": "done"}, "lixo"])
    monkeypatch.setattr(main, "load_video_tasks_for_catalog", counter)
    assert (_live_task_by_id("a") or {}).get("state") == "doing"
    assert (_live_task_by_id("b") or {}).get("state") == "done"
    assert _live_task_by_id("inexistente") is None


@pytest.mark.parametrize("task_id", ["", "   ", None])
def test_live_task_by_id_requires_a_task_id(monkeypatch, task_id):
    monkeypatch.setattr(main, "load_video_tasks_for_catalog", _CatalogCounter([{"id": "a"}]))
    assert _live_task_by_id(task_id) is None


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("to_do", True),
        ("standby", True),
        ("doing", True),
        ("done", False),
        ("failed", False),
        ("cancelled", False),
        ("blocked", False),
    ],
)
def test_video_task_is_live_covers_exactly_the_progressing_states(state, expected):
    assert _video_task_is_live({"state": state}) is expected
