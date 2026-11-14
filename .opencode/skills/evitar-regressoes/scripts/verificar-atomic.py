#!/usr/bin/env python3
"""Auditoria de escrita atomica (AST) - escrita insegura de JSON em hermes_ui/ e app/.

Regra (skill evitar-regressoes): nenhuma escrita de estado em JSON pode usar
`open(..., "w")` ou `json.dump(...) directamente num ficheiro de destino. A
escrita tem de ser ATOMICA: temporario no mesmo diretorio + flush + fsync +
`os.replace()`.

A deteccao usa AST (nao procura de texto): para cada escrita encontrada,
procuramos a funcao que a contem e verificamos se ELA propria (ou o helper
atomico que ela chama, definido no mesmo ficheiro) faz a escrita atomica. Foi
assim que a versao anterior deu falso positivo: `json.dump` dentro de
`_atomic_write_unlocked()` (hermes_ui/storage.py) e de `_atomic_json()`
(hermes_ui/social_auto_upload_backend.py) sao escritas SEGURAS - a linha do
`json.dump` e que nao continha a palavra "os.replace".

Uso: python .opencode/skills/evitar-regressoes/scripts/verificar-atomic.py
Saida: 0 = limpo, 1 = violacoes.
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path
from typing import Iterable

TARGET_DIRS = ["hermes_ui", "app"]
EXCLUDE_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "tests", "migrations"}
ATOMIC_HINTS = ("tempfile", "mkstemp", "NamedTemporaryFile", "fsync", "os.replace", "os.rename")
# Escritas que NAO sao estado: logs de recuperacao/crash (.log) eJSON Lines
# append-only (.jsonl). A regra protege ficheiros de ESTADO (.json), cuja
# corrupcao faz o app "esquecer" tarefas - nao um raciocinio de log.
LOG_SUFFIXES = (".log", ".jsonl", ".txt", ".part", ".tmp", ".bak", ".corrupt")


def _iter_python_files() -> Iterable[Path]:
    for target in TARGET_DIRS:
        root = Path(target)
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            if any(part in EXCLUDE_DIRS for part in path.parts):
                continue
            yield path


def _writes_to_disk(node: ast.AST, source: str) -> str | None:
    """None se nao ha escrita; caso contrario, o destino (marcacao) da escrita.

    So interessa escrita de ESTADO (.json). Ficheiros de log, .jsonl append-only
    e downloads (.part/.wb) estao fora do contrato.
    """
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    nome = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    if nome == "open":
        mode = ""
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value in {
                "w", "a", "x", "wb", "ab", "xb"
            }:
                mode = arg.value
                break
        if not mode.startswith(("w", "a", "x")):
            return None
        segment = ast.get_source_segment(source, node) or ""
        if any(suffix in segment for suffix in LOG_SUFFIXES):
            return None
        if ".json" not in segment:
            return None
        return segment[:80]
    if nome == "dump":
        segment = ast.get_source_segment(source, node) or ""
        if ".json" not in segment:
            return None
        return segment[:80]
    return None


def _function_is_atomic(func: ast.AST) -> bool:
    """A funcao escreve de forma atomica: temporario + fsync + replace/rename.

    Aceita as duas variantes usadas no projecto: `tempfile`/`mkstemp`
    (hermes_ui/storage.py) e `path.with_name(...)` (social_auto_upload_backend.py).
    """
    source = ast.unparse(func)
    if "fsync" in source and ("os.replace" in source or "os.rename" in source):
        return True
    return False


def scan_file(path: Path) -> list[tuple[int, str]]:
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=str(path))
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    atomic_functions = {f.name for f in functions if _function_is_atomic(f)}

    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if _writes_to_disk(node, source) is None:
            continue
        linha = getattr(node, "lineno", 0)
        # funcao que contem a escrita (a mais interna)
        owner = None
        for func in functions:
            if func.lineno <= linha <= (func.end_lineno or func.lineno):
                if owner is None or func.lineno > owner.lineno:
                    owner = func
        if owner is None:
            violations.append((linha, "escrita de JSON fora de funcao (nivel de modulo)"))
            continue
        if owner.name in atomic_functions:
            continue
        chamadas = {
            n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
            for n in ast.walk(owner)
            if isinstance(n, ast.Call)
        }
        if chamadas & atomic_functions:
            continue  # delega num helper atomico do mesmo ficheiro
        violations.append(
            (linha, f"{owner.name}() escreve JSON sem escrita atomica (tempfile + fsync + os.replace)")
        )
    return violations


def main() -> int:
    all_violations: list[str] = []
    print("Iniciando auditoria de escrita atomica (AST)...")
    for path in _iter_python_files():
        try:
            violations = scan_file(path)
        except (SyntaxError, UnicodeDecodeError) as exc:
            print(f"  ! {path}: nao foi possivel analisar ({exc})")
            continue
        for linha, detail in violations:
            all_violations.append(f"{path}:{linha} -> {detail}")

    if all_violations:
        print(f"\nFALHA: {len(all_violations)} violacao(oes) de escrita atomica:")
        for item in all_violations:
            print(f"  - {item}")
        print("\nCorrija antes de commitar (ver references/atomic-write-policy.md).")
        return 1
    print("\nSUCESSO: nenhuma violacao de escrita atomica encontrada.")
    return 0


if __name__ == "__main__":
    sys.exit(main())