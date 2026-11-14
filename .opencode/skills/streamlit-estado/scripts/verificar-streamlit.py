#!/usr/bin/env python3
"""Auditoria Streamlit (AST) - bloqueio da thread de UI em app/.

Regra (skill streamlit-estado): e PROIBIDO bloquear a thread principal do
Streamlit a espera de trabalho de background (`time.sleep` em funcoes de UI,
`while True` de polling na UI). Usar `@st.fragment(run_every=...)` e ler o
estado do JSON.

A versao anterior procurava o texto `time.sleep(` em toda a arvore `app/` e
falava em 4 situacoes legitimas: `time.sleep(0.8)` de graca antes de reiniciar
o processo apos uma atualizacao, `time.sleep(0.1)` de backoff para uma
PermissionError transitoria do Windows, e os pollings de APIs externas (Apify e
Kaggle), que correm em thread propria e nao na thread de UI.

Deteccao por AST: so contam como violacao os `time.sleep(...)`/`while True`
cuja funcao contida e CODIGO DE UI - usa `st.` ou tem nome de render
(render_/banner/card/kpi/fragment/page/tab/painel/panel/tela). Gracas curtas
(<= 1 s, constante numerica) com justificacao na linha sao aceites: o
`time.sleep(0.8)` antes do restart e documentado no codigo.

Uso: python .opencode/skills/streamlit-estado/scripts/verificar-streamlit.py
Saida: 0 = limpo, 1 = violacoes.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Iterable

TARGET_DIR = "app"
UI_NAME_HINTS = ("render", "banner", "card", "kpi", "fragment", "page", "tab", "painel", "panel", "tela", "view")
GRACE_SECONDS = 1.0


def _iter_python_files() -> Iterable[Path]:
    root = Path(TARGET_DIR)
    if not root.exists():
        return
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def _is_ui_function(func: ast.AST) -> bool:
    nome = func.name.lower()
    if any(hint in nome for hint in UI_NAME_HINTS):
        return True
    for node in ast.walk(func):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "st":
            return True
    return False


def _short_grace(node: ast.Call) -> bool:
    """time.sleep(0.8) com comentario de justificacao na linha fisica.

    O `ast.get_source_segment` devolve so a expressao (`time.sleep(0.8)`), sem o
    comentario que vem a seguir - por isso lemos as linhas reais do ficheiro.
    """
    arg = node.args[0] if node.args else None
    if not isinstance(arg, ast.Constant) or not isinstance(arg.value, (int, float)):
        return False
    if float(arg.value) > GRACE_SECONDS:
        return False
    source = _CURRENT_SOURCE or ""
    linhas = source.splitlines()
    inicio = getattr(node, "lineno", 1) - 1
    fim = getattr(node, "end_lineno", inicio + 1)
    bloco = "\n".join(linhas[inicio:fim])
    return re.search(r"#\s*(graca|backoff|respiro|grace|ux)", bloco, re.IGNORECASE) is not None


_CURRENT_SOURCE: str | None = None


def scan_file(path: Path) -> list[str]:
    global _CURRENT_SOURCE
    _CURRENT_SOURCE = path.read_text(encoding="utf-8")
    tree = ast.parse(_CURRENT_SOURCE, filename=str(path))
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    ui_functions = [f for f in functions if _is_ui_function(f)]

    violations: list[str] = []
    for func in ui_functions:
        for node in ast.walk(func):
            if isinstance(node, ast.While) and getattr(node.test, "value", None) is True:
                violations.append(f"{path}:{node.lineno} -> {func.name}(): loop 'while True' na thread de UI")
            if isinstance(node, ast.Call):
                nome = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                if nome == "sleep" and isinstance(node.func, ast.Attribute):
                    base = node.func.value
                    if isinstance(base, ast.Name) and base.id == "time" and not _short_grace(node):
                        violations.append(
                            f"{path}:{node.lineno} -> {func.name}(): bloqueia a thread de UI com time.sleep()"
                        )
    _CURRENT_SOURCE = None
    return violations


def main() -> int:
    all_violations: list[str] = []
    print("Iniciando auditoria de anti-padroes Streamlit (AST)...")
    for path in _iter_python_files():
        try:
            all_violations.extend(scan_file(path))
        except (SyntaxError, UnicodeDecodeError) as exc:
            print(f"  ! {path}: nao foi possivel analisar ({exc})")

    if all_violations:
        print(f"\nAnti-padroes de Streamlit encontrados ({len(all_violations)}):")
        for item in all_violations:
            print(f" - {item}")
        print("\nUse @st.fragment(run_every=...) e leia o estado do JSON.")
        return 1
    print("\nNenhum anti-padrao do Streamlit detectado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())