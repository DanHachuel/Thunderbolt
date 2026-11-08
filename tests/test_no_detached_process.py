"""Garante que DETACHED_PROCESS nunca volta ao código (causava janelas CMD).

O DETACHED_PROCESS desassocia o subprocesso da consola pai — em Windows,
cada uv/ffmpeg/MPT precisava da sua própria consola e abria janelas CMD
visíveis. CREATE_NO_WINDOW suprime a janela sem desanexar.
1.0.75 - REGRA INVIOLAVEL (AGENTS.md): "PROIBIDO ABRIR TELAS DE CMD NO
COMPUTADOR DO UTILIZADOR". O teste passa a cobrir tambem o lado Node
(`scripts/*.mjs`), porque o respawn do launcher depois de uma atualizacao usava
`detached: true` + `windowsHide: false` - a unica maneira de o Windows criar
uma consola visivel para o successor.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY_DIRS = [ROOT / "app", ROOT / "hermes_ui", ROOT / "scripts", ROOT / "seed" / "skills"]
NODE_FILES = sorted((ROOT / "scripts").glob("*.mjs"))


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


# ---------------------------------------------------------------------------
# 1.0.75 - lado Node (scripts/*.mjs): nenhuma tela de CMD
# ---------------------------------------------------------------------------


def test_node_files_never_detach_without_hiding_the_console():
    """Um `detached: true` em Node so sobrevive ao pai se vier com
    `windowsHide: true` - caso contrario o Windows abre uma consola visivel."""
    for path in NODE_FILES:
        content = path.read_text(encoding="utf-8", errors="replace")
        for block in re.split(r"(?=spawn\()", content):
            if "spawn(" not in block[:40]:
                continue
            if not re.search(r"^\s*detached\s*:\s*true", block, flags=re.MULTILINE):
                continue
            assert "windowsHide: true" in block, (
                f"{path.name}: spawn destacado sem windowsHide: true (abre janela de CMD)"
            )
            assert 'stdio: "ignore"' in block, f"{path.name}: spawn destacado deve usar stdio ignore"


def test_workers_of_queue_never_inherit_the_console():
    """Os spawns normais (workers) levam a saida por pipes - nunca 'inherit'
    (o gatilho documentado do Fatal Python error: init_sys_streams)."""
    for path in NODE_FILES:
        content = path.read_text(encoding="utf-8", errors="replace")
        for block in re.split(r"(?=spawn\()", content):
            if "spawn(" not in block[:40]:
                continue
            if "hermes_ui." not in block[:240]:
                continue
            if "automation_worker" in block[:240]:
                continue  # 1.0.18: o worker de automacao escreve no terminal de proposito
            assert 'stdio: ["ignore", "pipe", "pipe"]' in block, (
                f"{path.name}: worker de fila/pipeline deve levar a saida por pipes"
            )


def test_agents_md_declares_the_no_cmd_windows_rule():
    """A regra inviolavel tem de estar escrita (quem a remover tem de a ver)."""
    content = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "PROIBIDO ABRIR TELAS DE CMD NO COMPUTADOR DO UTILIZADOR" in content
    assert "test_no_detached_process.py" in content
