# Tasks — Paginação em barra de botões (substituir o selectbox) — 1.1.09

## Pedido

Substituir o `st.selectbox` "Página X de Y" das listas de vídeos por uma **barra
horizontal de botões numéricos** (`❮ 1 2 3 4 5 … 9 ❯`), no mesmo sítio, com
destaque na página activa e reticências quando houver mais de 7 páginas.

## Investigação (read-only)

Locais com paginação por selectbox em `app/main.py`:

| Local | Chave session_state | Rótulo | page_size |
|---|---|---|---|
| `render_automation` (8640-8676) | `youtube_automation_page` | "Página de vídeos cadastrados" | 12 |
| `render_thumbnails` (8127-8160) | `thumbnail_gallery_page` | "Página de thumbnails" | 24 |

Não existem outros selectboxes de paginação no projecto (verificado por
`format_func=lambda value: f"Página {value} de {page_count}"` e por chaves
`*_page` em `st.session_state`). O Backlog Vídeos e as outras abas de Automação
(TikTok, Facebook, Músicas, Bilibili) **não paginam** — mostram tudo. Por isso
esta versão cobre os dois pontos que existiam.

## Plano

- [ ] P1. Criar `render_pagination(current_page, total_pages, key_prefix) -> int`
      em `app/main.py`, antes de `render_thumbnails`, com:
      - lógica de números/reticências isolada num helper **puro**
        (`_pagination_page_numbers`, testável sem Streamlit);
      - `st.columns` com pesos ( Prev `0.6` | números `0.5` | reticências `0.35` |
        Next `0.6` ) e `gap="small"` — barra compacta **sem CSS global**, para
        não pintar nenhum outro botão da app;
      - botões `❮` / `❯` com `disabled` nos extremos;
      - página activa com `type="primary"`;
      - devolve a nova página; `total_pages <= 1` devolve a página actual sem
        desenhar nada.
- [ ] P2. Substituir os dois selectbox, preservando:
      - a mesma chave de `st.session_state` (`youtube_automation_page`,
        `thumbnail_gallery_page`) — o fatiação `tasks[start:start+page_size]`
        continua igual;
      - a `st.caption("A mostrar …")` no mesmo lugar;
      - clamp da página actual e **escrita do clamp de volta** ao
        session_state (sem selectbox a chave fica livre, e o valor deixa de
        poder ficar preso acima do novo total).
- [ ] P3. `st.rerun()` único e só quando a página muda (clicar na aba activa não
      dispara nada) — skill `streamlit-estado`: sem `time.sleep`, sem laços.
- [ ] P4. Teste de contrato `tests/test_pagination_ui.py`:
      - assinatura e ausência dos dois selectbox;
      - lógica de reticências (pura) para 1, 6, 7, 8, 10 páginas;
      - prova funcional com o Streamlit substituído (barra desenhada, página
        devolvida, rerun zero quando nada é clicado).
- [ ] P5. Suite + 5 auditorias `.opencode/skills/*/scripts/verificar-*.py`.
- [ ] P6. CHANGELOG + bump `1.1.09`, commit cirúrgico, push, publicação
      (dispatch sem input `version` + tag `v1.1.09`).

## Riscos a controlar

- Chaves de widget de botão têm de ser únicas por lista: `f"{key_prefix}_page_{n}"`.
- `st.rerun()` dentro de `render_automation` é um rerun completo (a página não é
  fragmento) — mesmo comportamento do selectbox, sem regressão.
- Não tocar no menu lateral nem nos workers (AGENTS.md).

## Estado REAL (21:12) — BLOQUEADO por sessão paralela

Implementação **pronta e validada**, mas não pode ser commitada nem publicada.

- [x] P1/P2/P3 aplicados em `app/main.py` (bloco `PAGINATION_VISIBLE_TAIL`,
      `_pagination_page_numbers`, `render_pagination`, `_render_page_navigation`;
      os dois selectbox substituídos).
- [x] P4 `tests/test_pagination_ui.py` (28 testes) e `tests/test_music_backlog.py`
      ajustado — **36 verdes** num worktree sobre a base íntegra `d553d40` (1.1.08).
- [ ] P5/P6: suite + auditorias + publicação — **bloqueado**.

### Porque está bloqueado

Outra sessão está a trabalhar no mesmo ficheiro, ao mesmo tempo:

1. `app/main.py` no working tree **não importa**:
   `NameError: name 'render_ugc_product_review' is not defined`. O hub novo
   `UGC_HUB_SPECS` (linha ~14238, trabalho deles) usa `render_ugc_product_review`,
   `render_ad_creator`, `render_ad_strategist` e `render_hook`, que só são
   definidos mais abaixo (linhas 14616+). Ficheiro escrito às 20:42 e não tocado
   desde então.
2. O **master** (`f9b1108`, commits `fe5ebf7`/`5e4d194`/`f9b1108` deles) também
   está quebrado: `app/main.py` importa `store_uploaded_media` de
   `app.influencers_ui`, e essa função existe apenas no working tree deles
   (não commitada).
3. `hermes_ui/higgsfield_integration.py` e `tests/test_ugc_ui.py` são ficheiros
   **novos, não rastreados** — o commit deles ficou pela metade.
4. **A versão `1.1.09` já foi bumpada por eles** (`f9b1108`), por isso não há
   número livre para a paginação.

### Decisão de escopo

Não corrigi o trabalho da outra sessão (não é meu e eles podem estar a meio) e
não commitei por cima de um master quebrado. Backup do meu trabalho em
`%TEMP%\opencode\backup-paginacao-1.1.09\`.

### Para retomar

1. A outra sessão fecha o trabalho dela (`UGC_HUB_SPECS` + higgsfield +
   `influencers_ui.py` commitados juntos, master a importar).
2. `git fetch origin` + rebase; escolher o patch seguinte livre (1.1.10?).
3. Aplicar o backup (`tests/test_pagination_ui.py`, `tests/test_music_backlog.py`)
   e as 3 edições de `app/main.py` documentadas neste ficheiro.
4. Suite + 5 auditorias + CHANGELOG + bump + commit + tag.
</content>
</invoke>