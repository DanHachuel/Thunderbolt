---
name: Processos e Sinais no Windows
description: Blindagem contra erros de 0xC000013A, EBUSY e EPIPE. Use ao mexer em subprocessos ou no launcher.
---

# 🪟 Skill: Processos e Sinais no Windows

## 1. Isolamento de Workers (Spawn)
- É **PROIBIDO** usar `stdio: "inherit"` para iniciar workers (o terminal mata o worker). Use `stdio: ["ignore", "pipe", "pipe"]` ou `"ignore"`.
- Todo spawn no Windows **DEVE** conter:
  - `windowsHide: true`
  - `creationFlags: 0x00000200 | 0x08000000` (`CREATE_NEW_PROCESS_GROUP` + `CREATE_NO_WINDOW`).

## 2. Proteção Contra Sinais (Python)
- Todo arquivo principal de worker Python (`image_worker.py`, etc.) **DEVE** ter no topo:
  ```python
  import signal, sys
  if sys.platform == "win32":
      signal.signal(signal.SIGINT, signal.SIG_IGN)