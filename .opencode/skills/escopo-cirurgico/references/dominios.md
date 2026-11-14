# Mapa de Domínios do Thunderbolt
- **Infraestrutura/Instalação**: `install.mjs`, `requirements.txt`, `package.json`.
- **Interface do Usuário (UI)**: `app/main.py`, páginas do Streamlit, componentes visuais.
- **Backend/Orquestração**: `pipeline_worker.py`, `automation_worker.py`, `domain.py`.
- **Launcher e Sinais**: `cli.mjs` (Node.js).

**Regra:** Uma tarefa de UI nunca deve alterar Infraestrutura. Uma tarefa de Backend nunca deve alterar a ordem do menu (UI). Se a tarefa exigir mudanças cruzadas, pergunte ao usuário antes.