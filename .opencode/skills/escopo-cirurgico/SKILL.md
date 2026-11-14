---
name: Controle de Escopo Cirúrgico
description: Impede alterações não solicitadas no instalador, dependências, menus ou refatorações desnecessárias. Use ao fazer correções pontuais.
---

# ✂️ Skill: Escopo Cirúrgico

## 1. Regra do Menor Arquivo Possível
- **Tarefas de UI** (mudar texto, criar aba, ajustar layout): Você está **PROIBIDO** de tocar em `install.mjs`, `requirements.txt`, `package.json` ou arquivos de workers.
- **Tarefas de Backend** (corrigir lógica, loops): Você está **PROIBIDO** de alterar a ordem visual do menu lateral ou o layout do Streamlit.

## 2. Proibição de Refatoração Não Solicitada
- Não "limpe" imports que não estão a causar erro.
- Não renomeie variáveis ou funções que já funcionam.
- Não mude a formatação de arquivos inteiros. Altere **apenas as linhas estritamente necessárias**.

## 3. Verificação Pré-Commit
- Antes de commitar, rode `git diff`. Se houver mais de 3 arquivos alterados numa tarefa simples, **PARE** e justifique.
- Se houver alteração num arquivo não relacionado, reverta com `git checkout -- <arquivo>`.