"""Teste e2e do Remotion (spec 11.5) — opt-in.

Só corre quando o ambiente tem o Remotion operacional
(get_remotion_status()["available"] é True) E a variável
THUNDERBOLT_REMOTION_E2E=1 está definida — o primeiro render compila o
bundle e pode demorar vários minutos no primeiro run (depois o bundle fica
em storage/remotion-cache/bundle/).

Correr manualmente:
  THUNDERBOLT_REMOTION_E2E=1 .venv/Scripts/python -m pytest tests/test_remotion_e2e.py -v
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("THUNDERBOLT_REMOTION_E2E"),
    reason="e2e do Remotion é opt-in: defina THUNDERBOLT_REMOTION_E2E=1 com as dependências instaladas",
)


class _NoopHooks:
    def stop_process(self, process, **kwargs):
        pass

    def update(self, task_id, **updates):
        return {}

    def heartbeat(self, **updates):
        pass

    def task_by_id(self, task_id):
        return None

    def persist_diagnostics(self, task, output):
        pass


def test_remotion_e2e_renders_a_short_synchronized_mp4(tmp_path):
    from hermes_ui.remotion_provider import get_remotion_status, run_remotion_render

    status = get_remotion_status()
    if not status.get("available"):
        pytest.skip("Remotion indisponível: " + "; ".join(status.get("reasons", [])))

    input_props = {
        "videoId": "e2e-remotion",
        "title": "E2E Remotion",
        "language": "pt",
        "fps": 30,
        "width": 1920,
        "height": 1080,
        "audioUrl": "",
        "scenes": [
            {
                "id": "hook",
                "type": "hook",
                "durationInSeconds": 2,
                "narration": "Primeira cena.",
                "visual": {"type": "text_overlay", "text": "E2E Remotion", "background": "gradient"},
            },
            {
                "id": "scene-1",
                "type": "scene",
                "durationInSeconds": 2,
                "narration": "Segunda cena.",
                "visual": {"type": "text_overlay", "text": "Hand-drawn", "background": "hand_drawn_paperInk"},
            },
            {
                "id": "outro",
                "type": "outro",
                "durationInSeconds": 2,
                "narration": "Fim.",
                "visual": {"type": "text_overlay", "text": "Fim", "background": "grid"},
            },
        ],
        "metadata": {"channel": "E2E"},
    }
    hooks = _NoopHooks()
    video_path = tmp_path / "e2e-remotion.mp4"
    result = run_remotion_render(
        {"id": "e2e-remotion"},
        video_path,
        "LongFormVideo",
        input_props,
        timeout_seconds=15 * 60,
        stop_process=hooks.stop_process,
        update=hooks.update,
        heartbeat=hooks.heartbeat,
        task_by_id=hooks.task_by_id,
        persist_diagnostics=hooks.persist_diagnostics,
    )
    rendered = Path(result["video_path"])
    assert rendered.is_file(), "o MP4 foi escrito"
    assert rendered.stat().st_size > 0, "o MP4 não está vazio"

    # Valida MP4 com vídeo: dimensões e duração (3 cenas de 2s + margem do
    # frame extra da composição).
    from moviepy import VideoFileClip

    with VideoFileClip(str(rendered)) as clip:
        assert clip.duration >= 5, f"duração inesperada: {clip.duration}s"
        assert tuple(clip.size) == (1920, 1080), f"dimensões inesperadas: {clip.size}"
