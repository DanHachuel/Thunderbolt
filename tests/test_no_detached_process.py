"""1.0.89 - Nenhuma tela de CMD; `detached` OBRIGATÓRIO no servidor/workers.

A regra inverteu (auditoria contra o PandaNews, 2026-11-10): a proibição que
fica é a de **janelas de consola visíveis** — não a do `detached`. Enquanto a
stack esteve presa ao terminal, o terminal foi ponto único de falha (o
`npx.cmd` morre com o sinal de console antes de o Node absorver). Agora o
servidor e os workers correm DESTACADOS (grupo próprio) com `windowsHide: true`
e `stdio` em ficheiro; no Windows sobe o interpretador BASE do venv com o
`site-packages` no `PYTHONPATH` — a armadilha do redirector do venv, que fazia
o neto nascer sem as flags de ocultação e abrir uma consola nova.

Lado Python: continua PROIBIDO `DETACHED_PROCESS` cru — lá os spawns usam
`CREATE_NO_WINDOW` (suprime a janela sem desanexar).
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


def _stdio_ignores_the_console(block: str) -> bool:
    """stdio nunca herda consola: `"ignore"` puro ou array começando em ignore."""
    if re.search(r'^\s*stdio:\s*"ignore"', block, flags=re.MULTILINE):
        return True
    match = re.search(r'^\s*stdio:\s*\[([^\]]*)\]', block, flags=re.MULTILINE)
    return bool(match) and '"ignore"' in match.group(1)


def test_python_side_never_uses_detached_process():
    """Lado Python intacto: CREATE_NO_WINDOW succumbe a janela sem desanexar."""
    for path in _all_source_files():
        content = path.read_text(encoding="utf-8", errors="replace")
        assert "DETACHED_PROCESS" not in content, f"{path.name} contém DETACHED_PROCESS"


def test_python_side_keeps_create_no_window():
    for name in ("pipeline_worker.py",):
        content = (ROOT / "hermes_ui" / name).read_text(encoding="utf-8")
        assert "CREATE_NO_WINDOW" in content
        assert "DETACHED_PROCESS" not in content


# ---------------------------------------------------------------------------
# Lado Node (scripts/*.mjs): destacado OBRIGATÓRIO no servidor/workers, com
# windowsHide e saída em ficheiro — nunca uma consola visível.
# ---------------------------------------------------------------------------


def test_every_detached_spawn_hides_the_console_and_ignores_stdio():
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
            assert _stdio_ignores_the_console(block), (
                f"{path.name}: spawn destacado deve ignorar/herdar arquivo — nunca a consola"
            )


def test_streamlit_server_spawn_is_detached_with_log_file():
    """O servidor da interface é destacado por omissão (regra nova AGENTS.md)."""
    cli = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")
    block = cli.split("function spawnDetached(", 1)[1].split("\nasync function portaTcpAbertaAtiva", 1)[0]
    assert "detached: true," in block
    assert "windowsHide: true," in block
    assert 'stdio: ["ignore", fd, fd]' in block
    assert "filho.unref();" in block
    assert "cwd: executionRoot," in block
    # o servidor é lançado por esse helper (nunca um spawn foreground por omissão)
    start_block = cli.split("if (!foregroundRequested) {", 1)[1].split("const port = process.env.THUNDERBOLT_PORT", 1)[0]
    assert "spawnDetached(" in start_block
    assert '"--server.port", String(serverPort)' in start_block
    assert "process.exit(0);" in start_block  # o launcher descartável termina


def test_queue_workers_spawns_never_inherit_the_console():
    """Workers: foreground por pipes OU destacados com stdio em ficheiro."""
    for path in NODE_FILES:
        content = path.read_text(encoding="utf-8", errors="replace")
        for block in re.split(r"(?=spawn\()", content):
            if "spawn(" not in block[:40]:
                continue
            if "hermes_ui." not in block[:240]:
                continue
            if _stdio_ignores_the_console(block):
                continue  # destacado (arquivo) ou ignore: nunca herda a consola
            assert 'stdio: ["ignore", "pipe", "pipe"]' in block, (
                f"{path.name}: worker deve levar a saida por pipes ou arquivo, nunca inherit"
            )


def test_agents_md_declares_the_new_rule():
    content = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    # a proibição de janelas continua escrita…
    assert "PROIBIDO ABRIR TELAS DE CMD NO COMPUTADOR DO UTILIZADOR" in content
    # …e a nova obrigatoriedade do detached também.
    assert "`detached: true` é **OBRIGATÓRIO**" in content
    assert "test_no_detached_process.py" in content
