# Padrões Streamlit

## 1. Atualização em Tempo Real
Para tarefas que rodam em background, use `@st.fragment(run_every="3s")` para atualizar APENAS o card da tarefa, sem recarregar a página inteira.

## 2. Persistência
Nunca use `time.sleep()` para esperar um worker. Leia o estado do arquivo JSON com `@st.cache_data(ttl=2)`.

## 3. st.rerun()
Use apenas para forçar a atualização logo após o clique de um botão de ação. Não coloque `st.rerun()` dentro de blocos que são executados repetidamente.