# Tasks — UGC (renomear AI Influencers) + integrar Higgsfield AI (via CLI/Skills)

## Contexto

Pedido do utilizador (18/11/2026), tarefa em 4 fases:

1. Renomear a secção **"AI Influencers" → "UGC"** na sidebar e no router; renomear a
   sub-aba **"Personagens" → "AI Influencers"**; adicionar sub-abas **UGC Product
   Review, Ad-Creator, Ad Strategist, Hook** com áreas de upload de média.
2. Integrar o **Higgsfield AI** via **CLI + Skills** (`@higgsfield/cli` +
   `higgsfield-ai/skills`) como novo provedor de geração, com módulo backend novo
   e secção nova na aba "Configuração API".

### Factos verificados na investigação (Fase 1)

- **Nenhuma** referência a higgsfield no repositório (grep: 0 resultados).
- `@higgsfield/cli` **existe** no npm (v1.2.2, binários `higgs` e `higgsfield`,
  repo `github.com/higgsfield-ai/cli`, cross-plataforma via `npm install -g`).
- `higgsfield-ai/skills` **existe** no GitHub (2020 ⭐): as skills são
  `higgsfield-generate`, `higgsfield-soul-id`, `higgsfield-product-photoshoot`
  (mais 6 outras). Instalam-se com `npx skills add higgsfield-ai/skills`
  (CLI `skills` da vercel-labs, requer Node ≥ 22.20).
- Comandos verificados na documentação oficial: `higgsfield auth login`,
  `higgsfield account status` (é assim que as skills verificam a autenticação),
  `higgsfield generate create <job_set_type> [--prompt] [--image/--video/--audio]
  --wait --json`, `higgsfield generate get/wait/list <id> --json`,
  `higgsfield soul-id create --name X --soul-2 --image ... `,
  `higgsfield product-photoshoot create ...`,
  `higgsfield upload create`. Flags `--wait`, `--wait-timeout` (10m),
  `--wait-interval` (3s), `--json`.
- Uma flag de média aceita **caminho local (auto-upload) ou UUID** — não é
  preciso implementar upload separado para o fluxo básico.
- O repo já tem padrão de hub reutilizável da 1.1.08 (`render_hub_page`,
  `HUB_PAGES`, `HUB_TABS_BY_PAGE`, `HUB_COLORS_BY_PAGE`) — **reutilizar**, não
  reinventar (7 grupos já migrados; seria incoerrente criar outro mecanismo).

### Decisão de arquitectura (a propor)

- **UI:** "AI Influencers" → **"UGC"** passa a ser mais um hub (`HUB_PAGES`), com
  8 abas: `AI Influencers` (ex-Personagens), `Geração de Conteúdo IA`,
  `Motion Control`, `UGC Products`, `UGC Product Review`, `Ad-Creator`,
  `Ad Strategist`, `Hook`. Nada de lógica antiga removido (regra da tarefa).
- **Backend:** `hermes_ui/higgsfield_integration.py` — wrapper do CLI com
  `subprocess` (flags Windows do AGENTS.md: `CREATE_NEW_PROCESS_GROUP`,
  `CREATE_NO_WINDOW`, `windowsHide`, sem `detached`, sem `stdio: "inherit"`,
  `PYTHONIOENCODING=utf-8`), parsing de `--json`, tempo limite e degradação
  graciosa quando o CLI não está instalado.
- **Polling:** o job é criado **sem** `--wait` (devolve o id imediatamente) e a UI
  acompanha com `@st.fragment(run_every=...)` a chamar `generate get/wait` —
  polling controlado, sem bloquear a thread do Streamlit (skill streamlit-estado).
- **Configuração API:** secção "Higgsfield AI" com estado da autenticação
  (`account status`), instruções para `higgsfield auth login` e AJUDA para
  instalar o CLI. Sem campo de API Key (a autenticação é do CLI).

## Decisões do utilizador (18/11/2026)

- **Instalador:** confirmado — adicionar o passo a `scripts/install.mjs`
  (`npx skills add higgsfield-ai/skills`), com registo no commit de que isso
  contraria a regra inviolável do AGENTS.md e foi autorizado explicitamente.
- **Sub-abas do hub UGC (ordem):** as 4 antigas primeiro, depois as 4 novas:
  AI Influencers (ex-Personagens), Geração de Conteúdo IA, Motion Control,
  UGC Products, UGC Product Review, Ad-Creator, Ad Strategist, Hook.
- **Nomes internos:** mantêm-se (`Personagens`, `Geração de Conteúdo IA`, …) —
  só o RÓTULO de "Personagens" passa a "AI Influencers" e o pai "AI Influencers"
  passa a "UGC" (menu + router). Links directos antigos resolvem por alias.

## Factos apurados na UI (além da Fase 1)

- Padrão de hub da 1.1.08: `HUB_PAGES = [(pai, scope, SPECS, CORES)]`, com
  `UGC_HUB_SPECS = [(nome interno, rótulo, renderizador)]`,
  `_hub_slug(nome interno)` como chave; `render_hub_page(pai, title, caption)`.
  Basta juntar o UGC a `HUB_PAGES`, tirar `"AI Influencers"` de `groups`,
  acrescentar `models_ai_items` a `hub_child_items` e mudar `top_pages`.
- `app/influencers_ui.py` já tem `_store_uploaded_file(uploaded, folder)` (para
  `storage/influencer_workflows/<folder>/<sha>-<nome>`) e
  `render_ugc_products/render_motion_control/render_ai_influencer_*` — as 4 abas
  novas ficam neste módulo, a reutilizar esse helper.
- Flags Windows canónicas (`pipeline_worker._render_spawn_creationflags`):
  `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`, sem `detached`, sem `inherit`.
- Polling já controlado por `@st.fragment(run_every=…)` + `_stop_own_fragment_auto_rerun()`.
- Comandos verificados: `higgsfield account status` (autenticação),
  `higgsfield auth login`, `higgsfield generate create <jst> --wait --json`,
  `generate get/wait/list <id>`, `soul-id create --name X --soul-2 --image … `,
  `soul-id wait <id>`, `product-photoshoot create --mode <mode> [--count N] [prompt]`.

## Plano (execução)

- [x] 1. `hermes_ui/higgsfield_integration.py` (NOVO): wrapper do CLI —
      `higgsfield_executable`, `auth_status`, `submit_generation`,
      `get_generation`, `wait_generation`, `list_generations`,
      `submit_product_photoshoot`, `train_soul`, `wait_soul`, `list_souls`,
      `submit_media_upload`. Parsing tolerante de `--json`, tempo limite,
      `HiggsfieldError` em vez de traceback, degradação sem CLI/auth. Flags
      Windows canónicas (`CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`), sem
      `detached`, sem `inherit`, `PYTHONIOENCODING=utf-8`.
- [x] 2. `tests/test_higgsfield_integration.py` (NOVO, 25 testes) — **apanhou 3
      bugs reais** no módulo: flags de média sem o nome (`--image`), timeout/OSError
      a escapar como excepção crua, e `--image` duplicado no `train_soul`.
- [x] 3. 4 renderizadores novos em `app/main.py` (não em `influencers_ui.py`: os
      fragments de polling precisam de `_stop_own_fragment_auto_rerun`, que vive
      em main.py): upload múltiplo + lista com remoção via
      `store_uploaded_media` (helper do influencers_ui tornado público), formulário
      e fragment `run_every="4s"` por aba. **Bug apanhado a tempo:** os specs
      referenciavam funções definidas abaixo deles — o bloco foi movido para
      antes de `UGC_HUB_SPECS`.
- [x] 4. Hub "UGC": `UGC_HUB_SPECS` (8 abas), `HUB_PAGES`, `groups`,
      `hub_child_items`, `top_pages`, `nav_paths`, `renderers`, aliases
      (`AI Influencers`/`Models AI` → `UGC`) e `render_ugc_hub`.
- [x] 5. Secção "Higgsfield AI" na aba AI Influencers da Configuração API:
      estado, instruções de instalação/login, botão "Verificar Status", sem
      campo de API Key.
- [x] 6. Passo no instalador: `installHiggsfieldCli()` (npm -g, silencioso,
      aborta se falhar) e `installHiggsfieldSkills()` (`npx skills add ... -y`
      não interactivo — o passo era interactivo por omissão e teria travado o
      instalador). Excepção **cirúrgica e documentada** no auditor de escopo,
      provada nos dois sentidos (passa no bloco autorizado, falha em linha
      estranha fora dele).
- [x] 7. Testes: `tests/test_ugc_ui.py` (NOVO, 15 contratos) + actualizados os
      que cravavam a rota antiga (hub_navigation, ui_navigation, niche_finder,
      navigation_ui, navigation_reorganization, instagram_model_blueprints).
- [ ] 8. Suite completa + os 5 auditores.
- [ ] 9. Commit cirúrgico, push, bump + CHANGELOG.

## Notas de convivência com a sessão paralela

- `app/main.py` é partilhado. Os hunks deles (música/thumbnail) ficaram
  commitados em `f9b1108`/`f50dea9`; o commit `f50dea9` removeu o import
  `store_uploaded_media` para manter o master importável durante uma janela em
  que o meu ficheiro estava quebrado — o meu working tree repõe o import.
- O bump deles chegou a 1.1.09; esta tarefa sai como **1.1.10** (a excepção do
  auditor já grava esse número).

## Revisão

(a preencher no fim)