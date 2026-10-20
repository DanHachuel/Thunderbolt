"""Polling da fila de thumbnails + layout da card da galeria (1.0.12).

A card da thumbnail passou a actualizar-se sozinha: o bloco de imagem+estado
vive num ``@st.fragment`` que RELÊ o JSON da tarefa em cada execução. Regra
de ouro do ``run_every``: 2s apenas em ``thumbnail_queued``/``generating``
(fila activa); estados terminais renderizam com ``run_every=None`` (sem loop
infinito de rede). O layout da card usa pesos proporcionais para que a
coluna de botões não amasse a imagem.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hermes_ui import thumbnails as thumbnails_module
from hermes_ui.thumbnails import get_thumbnail_task_record


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def _thumbnails_slice() -> str:
    """render_thumbnails → render_automation: a card da galeria + helpers."""
    return MAIN_SOURCE.split("def render_thumbnails():", 1)[1].split("def render_automation():", 1)[0]


# ---------------------------------------------------------------------------
# Fragments de polling: a regra de ouro do run_every
# ---------------------------------------------------------------------------


def test_status_block_lives_in_a_fragment_that_re_reads_the_task_json():
    block = _thumbnails_slice()
    # O fragment relê sempre o estado ACTUAL da tarefa (não o snapshot da página).
    assert "record = get_thumbnail_task_record(task_id) or fallback_record" in block
    assert "get_thumbnail_task_record" in MAIN_SOURCE.split("from hermes_ui.thumbnails import (", 1)[1].split(")", 1)[0]


def test_live_fragment_polls_every_two_seconds_only_while_queued_or_generating():
    block = _thumbnails_slice()
    assert '_THUMBNAIL_POLLING_STATES = {"thumbnail_queued", "generating"}' in block
    # O decorator run_every=2 está directamente sobre a variante live.
    assert '@st.fragment(run_every=2)\ndef _thumbnail_status_fragment_live(' in block


def test_idle_fragment_disables_the_network_loop_for_terminal_states():
    block = _thumbnails_slice()
    assert '@st.fragment(run_every=None)\ndef _thumbnail_status_fragment_idle(' in block
    # A variante idle nunca força reruns: sem polling, sem loop de rede.
    idle = block.split("def _thumbnail_status_fragment_idle(", 1)[1].split("def _render_tiktok_automation_task_list(", 1)[0]
    assert "st.rerun(" not in idle


def test_live_fragment_stops_polling_when_worker_reaches_a_terminal_state():
    block = _thumbnails_slice()
    live = block.split("def _thumbnail_status_fragment_live(", 1)[1].split("def _thumbnail_status_fragment_idle(", 1)[0]
    # 1.0.16: ao chegar a terminal (generated/failed/...) o fragment cancela o
    # PRÓPRIO timer (stop_auto_rerun) — sem rerun da página, sem avisos
    # "fragment does not exist anymore" e sem destruir as outras cards.
    assert "if status not in _THUMBNAIL_POLLING_STATES:" in live
    assert "_stop_own_fragment_auto_rerun()" in live
    assert "st.rerun(" not in live


def test_card_dispatches_the_fragment_variant_by_current_status():
    block = _thumbnails_slice()
    card = block.split("for record in visible_records:", 1)[1].split("def _thumbnail_status_block(", 1)[0]
    assert 'if record["status"] in _THUMBNAIL_POLLING_STATES:' in card
    assert "_thumbnail_status_fragment_live(task_id, record)" in card
    assert "_thumbnail_status_fragment_idle(task_id, record)" in card


def test_status_block_renders_image_status_and_queue_placeholder():
    block = _thumbnails_slice()
    status_block = block.split("def _thumbnail_status_block(", 1)[1].split("@st.fragment", 1)[0]
    assert '"Descarregar thumbnail"' in status_block
    assert "key=f\"thumbnail_download_{task_id}_{record['variant_index']}\"" in status_block
    assert 'f"Estado: {_thumbnail_status_label(status)} · Variante: {record[\'variant_index\'] + 1}"' in status_block
    assert 'st.markdown("### Na fila")' in status_block
    labels = block.split("_THUMBNAIL_STATUS_LABELS = {", 1)[1].split("}", 1)[0]
    for label in ("Na fila de thumbnails", "A gerar na fila", "Falhou na geração", "Gerada"):
        assert label in labels


def test_card_layout_uses_proportional_column_weights():
    card = _thumbnails_slice().split("for record in visible_records:", 1)[1].split("def _thumbnail_status_block(", 1)[0]
    assert "st.columns([1, 2, 1.5], gap=\"small\")" in card
    # Os quatro botões de acção continuam agrupados na coluna direita.
    action = card.split("with action_col:", 1)[1]
    for label in (
        '"Refazer Prompt Thumb"',
        '"Gerar Imagem"',
        '"Refazer Prompt e Gerar Imagem"',
        '"Refazer Lettering"',
    ):
        assert label in action


# ---------------------------------------------------------------------------
# get_thumbnail_task_record: leitura FRESCA de uma única tarefa
# ---------------------------------------------------------------------------


def _task(task_id: str = "task-1", status: str = "thumbnail_queued", **extra):
    return {
        "id": task_id,
        "title": "Peace Beyond Pressure",
        "topic": "peace",
        "channel_name": "Canal Oração",
        "thumbnail_status": status,
        "thumbnail_prompt": "prompt de imagem",
        **extra,
    }


def test_get_thumbnail_task_record_returns_fresh_normalized_record(monkeypatch):
    monkeypatch.setattr(thumbnails_module, "load_tasks", lambda: [_task()])
    record = get_thumbnail_task_record("task-1")
    assert record is not None
    assert record["task_id"] == "task-1"
    assert record["status"] == "thumbnail_queued"
    assert record["prompt"] == "prompt de imagem"
    assert record["title"] == "Peace Beyond Pressure"


def test_get_thumbnail_task_record_reflects_worker_updates(monkeypatch):
    # O worker de background termina e grava o estado final + caminho da imagem.
    monkeypatch.setattr(
        thumbnails_module,
        "load_tasks",
        lambda: [_task(status="generated", thumbnail_path="storage/thumbnails/task-1.png")],
    )
    record = get_thumbnail_task_record("task-1")
    assert record is not None
    assert record["status"] == "generated"
    assert record["image_path"] is not None


def test_get_thumbnail_task_record_ignores_other_tasks_and_bad_entries(monkeypatch):
    monkeypatch.setattr(
        thumbnails_module,
        "load_tasks",
        lambda: ["lixo", {"id": "outra"}, _task(task_id="alvo")],
    )
    assert get_thumbnail_task_record("alvo") is not None
    assert get_thumbnail_task_record("inexistente") is None


@pytest.mark.parametrize("task_id", ["", "   ", None])
def test_get_thumbnail_task_record_requires_a_task_id(monkeypatch, task_id):
    monkeypatch.setattr(thumbnails_module, "load_tasks", lambda: [_task()])
    assert get_thumbnail_task_record(task_id) is None
