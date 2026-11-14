#!/usr/bin/env python3
"""Auditoria do launcher (scripts/cli.mjs) - blindagem de processos no Windows.

Regra (skill windows-processos):
1. Todo spawn de stack (servidor Streamlit e workers) tem de criar grupo proprio
   (`CREATE_NEW_PROCESS_GROUP`, 0x00000200) e esconder a consola
   (`windowsHide: true`).
2. Nenhum spawn ASSINCRONO (`spawn(`) pode usar `stdio: "inherit"` - o sinal do
   console mata o filho. Os spawns usam `["ignore", "pipe", "pipe"]`.
3. Os ficheiros principais dos workers Python ignoram o SIGINT no Windows
   (`signal.signal(signal.SIGINT, signal.SIG_IGN)`) - um Ctrl+C do utilizador
   nao pode derrubar o worker.

A versao anterior procurava o texto `stdio: "inherit"` em todo o ficheiro e
falava em dois `spawnSync` LEGITIMOS: `run()` e `runInstaller()`, que correm
comandos de primeiro plano (install, worker) e TÊM de partilhar a consola do
terminal para o utilizador ver a saida. `spawnSync` e sincrono - o pai espera -
por isso nao ha filho a sobreviver ao terminal. A regra certa e: so os spawns
ASSINCRONOS de stack e que nao podem herdar a consola.

Uso: python .opencode/skills/windows-processos/scripts/verificar-spawn.py
Saida: 0 = limpo, 1 = violacoes.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

CLI_PATH = Path("scripts/cli.mjs")
WORKERS = ("automation_worker.py", "pipeline_worker.py", "thumbnail_worker.py", "image_worker.py")
SIG_IGN = "signal.signal(signal.SIGINT, signal.SIG_IGN)"


def main() -> int:
    if not CLI_PATH.exists():
        print(f"{CLI_PATH} nao encontrado.")
        return 1

    content = CLI_PATH.read_text(encoding="utf-8")
    erros: list[str] = []

    # 1. grupo proprio + consola escondida em algum spawn da stack
    if "CREATE_NEW_PROCESS_GROUP" not in content and "0x00000200" not in content:
        erros.append("Falta a flag CREATE_NEW_PROCESS_GROUP nos spawns do Windows.")
    if "windowsHide: true" not in content:
        erros.append("Falta a flag 'windowsHide: true' nos spawns (vai abrir janelas pretas).")

    # 2. stdio/windowsHide proibidos apenas nos spawns ASSINCRONOS (spawn(, nunca spawnSync()
    for idx, linha in enumerate(content.splitlines(), 1):
        if "spawnSync(" in linha:
            continue  # comando de primeiro plano: partilhar a consola e o objetivo
        if "spawn(" not in linha:
            continue
        if re.search(r'stdio:\s*["\']inherit["\']', linha):
            erros.append(f"spawn assincrono com stdio 'inherit' (linha {idx}) - o sinal do console mata o filho.")
        if "windowsHide: false" in linha:
            erros.append(f"spawn assincrono com windowsHide: false (linha {idx}) - abre consola visivel.")

    # 3. workers Python ignoram o SIGINT no Windows
    for worker in WORKERS:
        path = Path("hermes_ui") / worker
        if not path.exists():
            erros.append(f"worker {worker} nao encontrado (nao deu para validar o SIG_IGN).")
            continue
        if SIG_IGN not in path.read_text(encoding="utf-8"):
            erros.append(f"{worker}: falta '{SIG_IGN}' no topo do ficheiro.")

    if erros:
        print("FALHA NA BLINDAGEM DO LAUNCHER:")
        for erro in erros:
            print(f" - {erro}")
        return 1

    print("Launcher blindado corretamente para Windows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())