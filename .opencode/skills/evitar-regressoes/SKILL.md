---
name: Evitar Regressões e Visão Sistêmica
description: Leitura obrigatória antes de qualquer alteração. Define a visão sistêmica do projeto, normas para sessões concorrentes e prevenção de perda de dados (Atomic).
---

# 🛡️ Skill: Evitar Regressões e Visão Sistêmica

## 1. Visão Sistêmica (O Mapa do Território)
O Thunderbolt é um ecossistema interconectado. Antes de alterar um arquivo, entenda as dependências:
- `scripts/cli.mjs`: Launcher e orquestrador de processos.
- `hermes_ui/domain.py`: Regras de negócio e estados das tarefas.
- `hermes_ui/pipeline_worker.py`: Orquestração de vídeo/thumbnails.
- `app/main.py`: Interface Streamlit.
- **Regra de Ouro:** Se a sua alteração afeta um destes módulos, verifique se os dependentes continuam a funcionar.

## 2. Sessões Concorrentes (Fim do Caos)
- **Proibido** rodar duas sessões de IA alterando o mesmo repositório simultaneamente.
- Antes de qualquer commit, execute `git status` e `git diff`. Se houver arquivos alterados que não são da sua tarefa, **PARE**.
- Faça commits cirúrgicos (`git add <arquivo>`), nunca `git add .` se houver trabalho paralelo na árvore.

## 3. Preservação da Escrita Atômica (Atomic)
- O projeto depende de arquivos JSON (`tasks.json`, `channels.json`). 
- **Verificação Obrigatória:** Antes de alterar qualquer função de persistência, leia o arquivo de referência em `references/atomic-write-policy.md` para entender a implementação correta (escrever em `.tmp` e usar `os.replace`).
- **Proibição:** Nunca use `open(..., 'w')` ou `json.dump` diretamente em arquivos de estado.
- **Auditoria:** Antes de commitar, execute o script `python scripts/verificar-atomic.py`. Se ele retornar falha, corrija as violações antes de prosseguir.