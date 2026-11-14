---
name: Arquitetura Streamlit e Gestão de Estado
description: Evita bugs de tela congelada, barras de progresso que não atualizam e loops de rerun no Streamlit.
---

# 🌊 Skill: Streamlit e Estado

## 1. Polling e Atualização em Tempo Real
- Para tarefas em background (workers), é **PROIBIDO** usar `time.sleep()` na thread principal.
- Use `@st.fragment(run_every="3s")` para isolar a atualização do card da tarefa. Quando a tarefa terminar (`done`, `failed`), o `run_every` deve ser desligado (`None`) para poupar recursos.

## 2. Proibição de Reruns Infinitos
- Use `st.rerun()` **apenas uma vez** após uma ação de botão.
- Nunca use `st.rerun()` dentro de condições que possam se repetir em loop.

## 3. Persistência de Estado
- Nunca guarde o estado de uma tarefa em andamento apenas em `st.session_state` (um F5 perde tudo).
- O estado **deve** ser lido do arquivo JSON (via `storage.py`) usando cache curto (ex: `@st.cache_data(ttl=2)`).