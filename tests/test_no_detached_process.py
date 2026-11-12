"""1.0.94 - Nenhuma tela de CMD e NENHUM `detached` na stack (foreground).

Regra reposta com a reversão do modelo destacado (1.0.89–1.0.93): o terminal
tem de ficar ocupado a mostrar os logs, por isso os spawns da stack são filhos
normais do launcher — `detached: true`/`DETACHED_PROCESS` voltam a ser
proibidos. O que continua proibiddo é a **janela de consola visível**:
`windowsHide: true` + grupos de processos próprios nos filhos, e `stdio` nunca
herdando a consola do terminal (a saída vai para `storage/logs/` ou por pipes).

Lado Python: `DETACHED_PROCESS` continua proibido — lá os spawns usam
`CREATE_NO_WINDOW` (suprime a janela sem desanexar).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY_DIRS = [ROOT / "app", ROOT / "hermes_ui", ROOT / "scripts", ROOT / "seed" / "skills"]
NODE_FILES = sorted((ROOT / "scripts").glob("*.mjs"))


def _all_source_files() -> list[Path]:
    result: list[Path]
    result = []
    for directory in PY_DIRS:
        if not directory.is_dir():
            continue
        result.extend(directory.glob("*.py"))
    return result


def _stdio_ignores_the_console(block: str) -> bool:
    """stdio nunca herda consola: `"ignore"` puro ou array começando em ignore."""
    if re.search(r'^\s*stdio:\s*"ignore"', block, flags=re.MULTILINE):
        return True
    match = re.search(r"^\s*stdio:\s*\[([^\]]*)\]", block, flags=re.MULTILINE)
    return bool(match) and '"ignore"' in match.group(1)


def test_python_side_never_uses_detached_process():
    """Lado Python intacto: CREATE_NO_WINDOW sucumbe a janela sem desanexar."""
    for path in _all_source_files():
        content = path.read_text(encoding="utf-8", errors="replace")
        assert "DETACHED_PROCESS" not in content, f"{path.name} contém DETACHED_PROCESS"


def test_python_side_keeps_create_no_window():
    for name in ("pipeline_worker.py",):
        content = (ROOT / "hermes_ui" / name).read_text(encoding="utf-8")
        assert "CREATE_NO_WINDOW" in content
        assert "DETACHED_PROCESS" not in content


# ---------------------------------------------------------------------------
# Lado Node (scripts/*.mjs): a stack é foreground — zero `detached` nos spawns
# do servidor/workers. A única exceção permitida é o respawn do launcher
# depois de uma actualização (tem de sobreviver ao job object do libuv).
# ---------------------------------------------------------------------------


def test_no_detached_spawn_in_the_launcher():
    for path in NODE_FILES:
        content = path.read_text(encoding="utf-8", errors="replace")
        for block in re.split(r"(?=spawn\()", content):
            if "spawn(" not in block[:40]:
                continue
            if not re.search(r"^\s*detached\s*:\s*true", block, flags=re.MULTILINE):
                continue
            # a exceção é o wrapper da actualização (é único e identificável)
            assert "--prefer-online" in block and 'stdio: "ignore"' in block, (
                f"{path.name}: spawn destacado que não é o respawn da actualização"
            )


def test_launcher_has_no_detached_mode_left():
    """Os helpers do modo destacado desapareceram (1.0.94)."""
    cli = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")
    for gone in ("spawnDetached(", "function esperarPorta(", "foregroundRequested"):
        assert gone not in cli, f"ainda existe código do modo destacado: {gone}"


def test_queue_workers_spawns_never_inherit_the_console():
    """Workers: saída por pipes com log próprio — nunca a consola do terminal."""
    for path in NODE_FILES:
        content = path.read_text(encoding="utf-8", errors="replace")
        for block in re.split(r"(?=spawn\()", content):
            if "spawn(" not in block[:40]:
                continue
            if "hermes_ui." not in block[:240]:
                continue
            if _stdio_ignores_the_console(block):
                continue
            assert 'stdio: ["ignore", "pipe", "pipe"]' in block, (
                f"{path.name}: worker deve levar a saida por pipes ou arquivo, nunca inherit"
            )


def test_windows_spawns_hide_the_console():
    """Filhos sem consola visível: windowsHide + grupo próprio no Windows."""
    cli = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")
    assert "windowsHide: true" in cli
    assert "const WINDOWS_CREATE_NEW_PROCESS_GROUP = 0x00000200;" in cli
    assert "function workerCreationFlags()" in cli
    # DETACHED_PROCESS (0x00000008) não pode entrar nas flags de criação —
    # procurar no código, não nos comentários (a regra está documentada lá).
    code_without_comments = "\n".join(
        line.split("//")[0] for line in cli.splitlines()
    )
    assert "0x00000008" not in code_without_comments
    assert "DETACHED_PROCESS" not in code_without_comments


def test_agents_md_declares_the_foreground_rule():
    content = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "PROIBIDO ABRIR TELAS DE CMD NO COMPUTADOR DO UTILIZADOR" in content
    # o keep-alive passa a ser regra do modo único (foreground)
    assert "Keep-Alive Obrigatório (modo único, foreground)" in content
    # e o Ctrl+C com confirmação está escrito
    assert "SIGINT (Ctrl+C) encerra, com confirmação no Windows (1.0.94)" in content
    assert "test_no_detached_process.py" in content
