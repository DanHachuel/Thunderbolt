"""Garante que DETACHED_PROCESS nunca volta ao código (causava janelas CMD).

O DETACHED_PROCESS desassocia o subprocesso da consola pai — em Windows,
cada uv/ffmpeg/MPT precisava da sua própria consola e abria janelas CMD
visíveis. CREATE_NO_WINDOW suprime a janela sem desanexar.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY_DIRS = [ROOT / "app", ROOT / "hermes_ui", ROOT / "scripts", ROOT / "seed" / "skills"]


def _all_source_files() -> list[Path]:
    result: list[Path] = []
    for directory in PY_DIRS:
        if not directory.is_dir():
            continue
        result.extend(directory.glob("*.py"))
    return result


def test_no_detached_process_in_codebase():
    for path in _all_source_files():
        content = path.read_text(encoding="utf-8", errors="replace")
        assert "DETACHED_PROCESS" not in content, f"{path.name} contém DETACHED_PROCESS"


def test_pipeline_worker_mpt_popen_uses_create_no_window():
    content = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")
    assert "CREATE_NO_WINDOW" in content
    assert "DETACHED_PROCESS" not in content


def test_mpt_agent_subprocesses_use_create_no_window():
    content = (ROOT / "seed" / "skills" / "mpt_agent.py").read_text(encoding="utf-8")
    assert "CREATE_NO_WINDOW" in content
    assert "DETACHED_PROCESS" not in content


def test_remotion_render_uses_create_no_window():
    content = (ROOT / "hermes_ui" / "remotion_provider.py").read_text(encoding="utf-8")
    assert "CREATE_NO_WINDOW" in content
    assert "DETACHED_PROCESS" not in content
