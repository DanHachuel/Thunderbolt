# Tasks — Hubs de navegação + erro React nos Shorts (1.1.08)

## Contexto

Pedido do utilizador (18/11/2026):

1. Criar um componente **reutilizável** de "hub" (botões coloridos no topo da
   página) e aplicá-lo a **Growth, Canais e Perfis, Blueprints, Niche Finder,
   Edição, Pipeline Vídeos e Pipeline Música**, limpando os submenus desses
   grupos na sidebar (fica só o nome principal, como já acontece na Automação).
2. Cor **roxa `#8a2be2` por omissão** quando `colors` é nulo; cores específicas
   quando informadas (Growth mantém as cores actuais).
3. **Pipeline Vídeos**: botões **Vídeos** (título interno "Criação de Vídeos") e
   **Shorts** (título interno "Criação de Videos Shorts"), cor roxa única.
4. **NÃO** alterar a lógica de negócio dos renderizadores internos; não remover
   o botão "Atualizar Versão" da Início; não quebrar abas que funcionam.
5. Corrigir o erro React `NotFoundError: Failed to execute 'removeChild'` na aba
   "Criação de Shorts".

## Regras que este plano tinha de respeitar

- `AGENTS.md`: 5 auditorias de skills têm de devolver 0 antes do commit.
- `AGENTS.md` — Regra de UI «Inserção de Itens»: não reordenar o que já existe.
- `AGENTS.md` — Versionamento: `MAJOR.MINOR.PATCH` com **2 dígitos no PATCH**;
  depois de `1.1.07` vem **`1.1.08`**.
- Publicação NPM só via workflow `Publish npm package` (dispatch **sem** o input
  `version` + push da tag `vX.Y.ZZ` com patch de 2 dígitos).
- `git add <arquivo>` cirúrgico (há sessões paralelas); `git fetch origin` +
  rebase antes de cada push.
- Ficheiros de outras sessões NÃO tocados: `AUDIT_UI.md`,
  `docs/audit/queue_concurrency.md`, `storage/scenes/`, `storage/state/`.

## Feito

### A. Componente reutilizável do hub
- [x] A1. `render_hub_navigation(tabs_list, active_tab, colors=None, *, scope, state_key)`
      criado em `app/main.py` (antes de `AUTOMATION_TAB_SPECS`), com:
      - `tabs_list` = `[(chave, rótulo, renderizador)]`; valor desconhecido cai na
        primeira aba;
      - `colors=None` (ou chave ausente) → roxo `#8a2be2` em todos os botões;
      - chip invisível por coluna (`tb-hub-chip-<scope>-<chave>`) + CSS **gerado**
        a partir da paleta, selector exigindo a coluna (não pinta mais ninguém);
      - aba activa destacada (`is-active`);
      - clique → `session_state[state_key]` + `?hub=<scope>:<aba>` + **1 único**
        `st.rerun()`; clicar na aba activa não dispara nada;
      - devolve o renderizador da aba activa (`None` só com lista vazia).
- [x] A2. `_hub_nav_css(scope, palette)`: fundo preto leva texto branco + borda
      clara (contraste), como o TikTok da Automação.
- [x] A3. Sem `time.sleep` nem laços no componente (travado por teste AST).
- [x] A4. `render_hub_page(page, title=None, caption="")`: título + barra +
      conteúdo; usado por 5 dos 7 hubs. `render_pipeline` desenha os cartões das
      filas e depois chama o hub.

### B. Hubs aplicados (7 grupos)
- [x] B1. **Growth** — Youtube `#ff0000`, TikTok `#000000`, Instagram (gradiente),
      Facebook Pages `#1877f2`, Bilibili `#00a1d6` («manter as cores»).
- [x] B2. **Canais/Perfis (Vídeos)** — YouTube, TikTok, Instagram, Facebook; roxo.
- [x] B3. **Blueprints** — Youtube, Música, Thumbnails, Brandings, Prompt-Masters,
      Facebook; roxo.
- [x] B4. **Niche Finder** — Kaggle, Apify; roxo.
- [x] B5. **Edição** — Limpador, Cortes, Editor Python, Download Mídia; roxo.
- [x] B6. **Pipeline Vídeos** — Vídeos, Shorts, Backlog, Roteiros, Thumbnails,
      Upload, Update Youtube; roxo. Cartões das filas mantidos no topo.
- [x] B7. **Pipeline Música** — Músicas, Backlog, Vozes, Upload; roxo.

### C. Sidebar
- [x] C1. Os 7 grupos saíram do `groups` (listas de itens mantidas); só o nome
      principal aparece, na mesma posição. Só AI Influencers e Configurações
      mantêm filhos.
- [x] C2. `HUB_PAGE_ROUTES` + `aliases.update(...)`: link directo para sub-página
      antiga colapsa no pai e semeia a aba colorida certa.
- [x] C3. `?hub=<scope>:<aba>` persiste a aba (sobrevive a F5/partilha); `?tab=`
      continua exclusivo da Automação.
- [x] C4. «Canais/Perfis», «Blueprints», «Niche Finder» e «Pipeline Música» (que
      caíam no dashboard) ganharam renderizador próprio.

### D. Erro React `removeChild` nos Shorts
- [x] D1. Causa raiz encontrada por investigação (sub-agente `explore`) e
      confirmada por leitura directa do fonte: o `MutationObserver` do
      `_FLAG_RENDER_BOOTSTRAP` fazia `replaceWith` sobre **nós de texto do React**
      (as opções do selectbox «Script Language» vivem em `div[role=option]`, que
      o guarda não cobria).
- [x] D2. Corrigido sem tocar em lógica de negócio:
      1. o nó de texto **nunca** é desanexado — fragmento inserido antes, nó
         esvaziado;
      2. contentores reconciliados por lista (`role=listbox/option/menu/menuitem`)
         entraram no guarda;
      3. `setInterval` do detector de tema passou a ser único (`clearInterval`
         antes de criar) — acabou a fuga de timers acumulados.
- [x] D3. Contrato novo: `tests/test_flag_observer_dom_safety.py` (12 testes).

### E. Validação
- [x] E1. Suite completa: **2364 passed, 4 skipped, 10 subtests** — 3 falhas de
      launcher eram **flake por carga** (deadlines de tempo real); repetidos
      isoladamente, passam todos (5/5 e 2/2).
- [x] E2. 5 auditorias de skills `.opencode/skills/*/scripts/verificar-*.py` → 0.
- [x] E3. `tests/test_hub_navigation.py` (32 testes, metade funcional) +
      `tests/test_flag_observer_dom_safety.py` (12) + 3 ficheiros de contrato
      actualizados (`test_ui_navigation.py`, `test_real_subtabs_navigation.py`,
      `test_niche_finder.py`).
- [x] E4. `CHANGELOG.md` + bump `1.1.08` (`package.json` e `pyproject.toml`).
- [x] E5. Commit cirúrgico (10 ficheiros, 1135+/35-), push para `master`
      (`2336b59..5293867`), dispatch do workflow sem input `version`
      (run 1148, success) e push da tag `v1.1.08` (run 1149, success).
      Registry: **`latest = next = 1.1.8`** (rótulo visual `1.1.08`).

## Lições a registar em `tasks/lessons.md`

- O `MutationObserver` do substituto de bandeiras mexia em nós que o React
  possui: substituir texto por fragmento tem de **inserir antes e esvaziar**,
  nunca desanexar.
- Testes de integração do launcher (circuit breaker, keep-alive, consola) têm
  deadlines de tempo real e são **flaky sob carga**; não contam como regressão
  sem serem repetidos isoladamente.