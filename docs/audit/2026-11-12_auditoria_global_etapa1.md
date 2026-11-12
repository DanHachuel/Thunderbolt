# Auditoria Global de Código — Etapa 1 (READ-ONLY)

**Thunderbolt — 2026-11-12 · zero alterações de código, zero commits**

## 0. O que foi auditado

Varredura completa do repositório (working tree em `master`, HEAD = `9660a39` / 1.0.93), com foco nas
regressões das últimas mudanças arquitecturais: servidor destacado (1.0.89), `.runtime` (1.0.81),
player FFmpeg/libass + HTML5 (1.0.91/1.0.93), e reaproveitamento de áudio/filas (1.0.66/1.0.86).

Ficheiros lidos integralmente ou em secções relevantes: `scripts/cli.mjs` (2 208 linhas),
`scripts/kill_tree.py`, `app/main.py` (12 552 linhas, secções de média/player/downloads/versão/rerun),
`hermes_ui/pipeline_worker.py` (4 389 linhas), `hermes_ui/automation_worker.py`,
`hermes_ui/storage.py`, `hermes_ui/render_capacity.py`, `hermes_ui/thumbnail_worker.py`,
`hermes_ui/image_worker.py`, `hermes_ui/queue_worker_runtime.py`, `hermes_ui/blueprint_length_guard.py`,
`hermes_ui/blueprint_governance.py`, `hermes_ui/script_generation.py`, `hermes_ui/creative_generation.py`,
`hermes_ui/keyword_context.py`, `hermes_ui/script_voice.py`, `hermes_ui/text_to_images.py`,
`hermes_ui/update_manager.py`, `hermes_ui/blueprint_loader.py`, `scripts/streamlit_bootstrap.py`.

Contratos de teste executados como evidência (leitura de fonte / execução isolada em `tmp_path`,
sem tocar no storage): `tests/test_launcher_detached.py`, `tests/test_runtime_isolation.py`,
`tests/test_no_detached_process.py`, `tests/test_launcher_keep_alive.py`,
`tests/test_launcher_worker_boot_guard.py` (64 passados), `tests/test_video_player_detached.py`,
`tests/test_launcher_video_streaming.py`, `tests/test_video_catalog_sync.py`,
`tests/test_script_length_guard.py` (45 passados). Nenhuma falha encontrada — os contratos de
regressão do launcher e da regra de tamanho de roteiro continuam verdes.

---

## 1. Resumo Executivo

A arquitectura destacada (1.0.89) cumpriu o objectivo imediato — o terminal pode fechar, a UI
sobrevive, não há janelas de CMD — **mas transfere para o launcher a responsabilidade de
supervisionar a stack, e esse launcher encerra-se de propósito**. O resultado é um sistema que
funciona no "caminho feliz" e **não tem nenhuma recuperação quando um worker ou o próprio
servidor morre**: em modo destacado ninguém relê `force_restart.json`, ninguém reinicia workers, e
a UI não sabe lançar o `pipeline_worker`/`thumbnail_worker`/`image_worker`. É a raiz de vários
sintomas que o utilizador está a sentir.

Em paralelo, a **árvore de trabalho está num estado misturado e perigoso**: o commit HEAD publicou
1.0.93 (tag `v1.0.93` já no `origin`) com o player HTML5 local que resolvia o spinner infinito, e
a working tree **reverteu essa correcção** (`app/main.py`, apagou `tests/test_custom_video_player.py`,
baixou `package.json`/`pyproject.toml` para 1.0.92 e apagou a entrada do CHANGELOG), sem commit.
Quem correr a app a partir desta árvore volta a ter o player preso no spinner.

Estado geral: **funcional, mas frágil**. 3 bugs críticos, 8 altos, 8 médios, 4 baixos. Os bugs
críticos e a maioria dos altos concentram-se num único eixo: *o modo destacado ficou sem supervisor
e sem rede de segurança*.

---

## 2. Tabela de Bugs

### 🔴 CRÍTICO

| # | Arquivo:linha | Sintoma | Causa |
|---|---|---|---|
| C1 | `scripts/cli.mjs:1046-1103` (bloco destacado) vs `scripts/cli.mjs:2317` (`workerMonitorTimer = setInterval(monitorWorkers, 2000)`) | Streamlit ou pipeline/thumbnail/image worker morre → a stack fica morta até o próximo `npx` manual. Vídeos em fila param sem erro visível. | Em modo destacado o launcher escreve o lock e faz `process.exit(0)` (linha 1103) **antes** de qualquer supervisão. `monitorWorkers`, `startStreamlit` e todos os circuit breakers vivem apenas no caminho `--foreground`. |
| C2 | `app/main.py:6351-6368` (botão "Forçar Reinício do Sistema") + `scripts/cli.mjs:2012-2040` | O utilizador clica no botão, vê "Reinício pedido… dentro de segundos" e **nada aconteça**. | O botão escreve `storage/state/force_restart.json`; o único leitor é `consumeForceRestartRequest()`, chamado por `monitorWorkers()` — que só corre em foreground. Em modo destacado o ficheiro fica lá para sempre. |
| C3 | `app/main.py:197-198` + `app/main.py:256-259` | **Player preso no spinner infinito**, precisamente o sintoma que a 1.0.93 corrigiu. | `_tb_media_video_url` devolve `None` em `THUNDERBOLT_LAUNCHER_MODE=detached`, e o fallback é `st.video(str(resolved))`. No Streamlit 1.65 o `MemoryMediaFileStorage` faz `open(f).read()` + hash do conteúdo **a cada render** — MP4 inteiro em RAM,枷 lock global do media manager. A correcção 1.0.93 (`_custom_video_player` + `ThreadingHTTPServer` local) está **revertida na working tree** (ver `git diff app/main.py`) e o seu teste foi apagado. |

### 🟠 ALTO

| # | Arquivo:linha | Sintoma | Causa |
|---|---|---|---|
| A1 | `app/main.py:8746-8760`, `app/main.py:8797-8798`, `app/main.py:8737-8743` | Banner verde "Sistema activo em background (modo destacado)" com **nada a correr** — falso positivo. | `_worker_automation_operacional` considera o worker operacional se `_launcher_rodando_destachado()`; este devolve `True` se `THUNDERBOLT_LAUNCHER_MODE=detached` **ou** se existir `storage/state/thunderbolt.pid` com `server`/`workers`. Um `taskkill /F`, crash ou update deixam o lock óbfico → verde para sempre. |
| A2 | `app/main.py:8668-8722`, em especial `:8682` | Canal com automação ligada nunca gera lote depois de uma falha do worker. | `_iniciar_worker_automacao_sob_demanda()` tem `if _launcher_rodando_destachado(): return False` — a UI deliberadamente **não** arranca o worker em modo destacado (o launcher é que o faria), mas o launcher já saiu e ninguém mais o faz. |
| A3 | `app/main.py:105-130` (`_cached_file_bytes`) + `:7825` (TikTok) e `:3444` (Bilibili) | Memória a crescer sem limite e página lenta: o MP4 inteiro fica em cache (até 256 entradas) e é lido a cada render. | `_file_bytes()` é `@st.cache_data(max_entries=256)` que devolve `Path(path).read_bytes()`. Os cartões TikTok/Bilibili passam `data=_file_bytes(video_path)` directamente; o cartão YouTube (corrigido na 1.0.87) usa o padrão "Preparar Vídeo para download" (`:8220-8244`). Inconsistência entre plataformas. |
| A4 | `scripts/cli.mjs:1065-1068` vs `scripts/cli.mjs:1555` (`WORKER_SPAWN_STAGGER_MS`) | Workers secundários podem morrer no arranque com `0xC0000142` (STATUS_DLL_INIT_FAILED), sintoma documentado no próprio repo. | Em modo destacado o spawn do servidor + 3 workers é um `for` sem qualquer respiro. O stagger de 500 ms do Windows e o limite `SECONDARY_WORKER_INIT_LIMIT` só existem no caminho foreground (`monitorWorkers`, `handleSecondaryWorkerInitFailure`). |
| A5 | `scripts/cli.mjs:732-746` + `scripts/cli.mjs:702-720` (`pidDaPorta`) | Uma aplicação alheia que use a porta 3030 é morta com `taskkill /PID /F /T`. | `killServerInstances` mata o dono da porta encontrado pelo `netstat -ano` **sem verificar** se é um processo Thunderbolt. |
| A6 | `scripts/cli.mjs:218` (`claimLauncherLock`) vs bloco destacado | Dois `npx` quase simultâneos criam duas stacks (dois Streamlit, dois conjuntos de workers). | O `launcher.lock` só é escrito em foreground (`:1437`). Em modo destacado a única defesa é o lock `thunderbolt.pid` — e se o segundo `npx` arrancar antes de o primeiro o escrever, não há nada a matar. `tests/test_launcher_single_instance.py` não cobre o modo destacado. |
| A7 | `scripts/cli.mjs:1014` (`THUNDERBOLT_VERSION: packageVersion`) + `scripts/cli.mjs:889-900` (`ensureRuntimeSources`) | A sidebar mostra a versão nova enquanto corre código velho. | A versão é injectada do `package.json` do pacote npx, mas o código só é copiado para o `.runtime` pelo `install`. Quem correr `npx thunderbolt` (sem `install`) depois de uma actualização vê a versão nova com o `.runtime` antigo. |
| A8 | `scripts/cli.mjs:1174-1185` (`tbMediaRoots`) + `app/main.py:203` | Em foreground, o `/tb-media/` pode dar 404 se a porta/armazenamento forem overridados. | O launcher fixa `videos: join(thunderboltHome, "storage", "videos")` ignorando `THUNDERBOLT_STORAGE_DIR` (definido em `:47`), e a app lê a porta de `settings.port` enquanto o launcher faz o bind em `THUNDERBOLT_PORT`/`HERMES_PORT`. |

### 🟡 MÉDIO

| # | Arquivo:linha | Sintoma | Causa |
|---|---|---|---|
| M1 | `tests/test_video_player_detached.py:136-157` | Um teste **desapareceu silenciosamente**: o corpo do teste do caminho absoluto ficou dentro de `_video_call`, depois do `raise` (código morto). | Erro de edição no commit `97b3546` (“contratos do player actualizados”). pytest passa, a cobertura perdeu-se. |
| M2 | `package.json:3`, `pyproject.toml:3`, `CHANGELOG.md:1-4`, `tests/test_custom_video_player.py` (apagado) | working tree contradiz a release publicada: diz 1.0.92, a tag `v1.0.93` está no `origin` e a entrada 1.0.93 do CHANGELOG foi apagada. | Reverter não Commitado de 1.0.93. Viola a regra 6 do AGENTS.md (nenhuma versão sem registo) e vai colidir no próximo publish. |
| M3 | `app/main.py:7729-7874` (TikTok) vs `:8381-8392` (YouTube) | Aba Automação TikTok lê o catálogo de tarefas 2× (e canais 2×) por render; a variante YouTube lê 1×. | `_render_tiktok_automation_task_list` não aceita `tasks=` e é chamado duas vezes pelos `st.tabs`. |
| M4 | `app/main.py:8062` | Thumbnails dos cartões servidas em resolução cheia ao browser. | `st.image(str(path), width="stretch")` — o servidor não gera miniatura; só o browser escala. |
| M5 | `app/main.py:7805,7810,7842,7847,7378,7382` | Cliques em Start/Stop/Apagar dentro de fragments disparam rerun **completo** da app. | `st.rerun()` sem `scope="fragment"` (default `"app"`, confirmado em `streamlit/commands/execution_control.py`). |
| M6 | `app/main.py:6451-6465` | `_stop_own_fragment_auto_rerun` pode deixar de cancelar timers numa actualização do Streamlit. | Usa APIs internas (`ForwardMsg_pb2`, `ThreadState`, `ctx.enqueue`). Está protegido por `try/except`, mas degrada em silêncio. |
| M7 | `hermes_ui/update_manager.py:61-67` vs `scripts/cli.mjs:2070` | Depois de actualizar, o restart segue um caminho diferente em modo destacado (`os.execv` do próprio servidor) em vez do handoff `exit 75` → launcher. | `THUNDERBOLT_LAUNCHER_RESTART` só é injectado em `startStreamlit` (foreground). Caminho menos testado. |
| M8 | `storage/scenes/` (3 000+ ficheiros), `storage/_temp_test/`, `tests/test_winerror32_temp_isolation.py:180` | Lixo de execução/testes dentro do storage do utilizador; `_temp_test` é criado por um teste que aponta `LOCALAPPDATA` para dentro do repo. | Testes sem isolamento total + `ensureRuntimeStorage` do launcher não cobre tudo. |

### 🟢 BAIXO

| # | Arquivo:linha | Sintoma | Causa |
|---|---|---|---|
| B1 | `app/main.py:133-160` | `_local_video_static_url`/`_local_video_download_link` (mecanismo de symlink da 1.0.32) continuam definidos e já não são usados. | Código morto mantido só por contrato de teste (`tests/test_video_catalog_sync.py:54`). |
| B2 | `app/main.py:242` | Extensões de vídeo desconhecidas caem em `"video/mp4"`. | Fallback de `mimetypes.guess_type`. |
| B3 | `app/main.py:6346` | Banner do worker de vídeo diz "O launcher deve estar aberto" — falso em modo destacado. | Texto escrito antes da 1.0.89. |
| B4 | `scripts/cli.mjs:232-239` (`run`) | `stdio: "inherit"` + `windowsHide: false` nos subcomandos `worker`/`pipeline-worker`… | Herdado do modo antigo; só usado quando o launcher é chamado explicitamente com esses argumentos. |

---

## 3. Riscos Arquiteturais

1. **O modo destacado não tem "dono" (C1/A2/A6).** O desenho actual assume que o launcher vive e
   supervisiona; a partir da 1.0.89 ele é descartável. Sem supervisor, sem mutex e sem forma de a UI
   repor `pipeline`/`thumbnail`/`image`, um único crash deixa o sistema meio-morto e *verde* na
   interface. Recomenda-se, na Etapa 2, um supervisor residente (um único processo watch-dog fora do
   terminal) ou um "sob demanda" na UI equivalente ao que já existe para o automação.

2. **O contrato de "falso positivo" está espalhado por três camadas** (env var + lock + heartbeat) e
   dois dos três podem mentir (A1). Qualquer correcção pontual de banner não resolve: o lock
   `thunderbolt.pid` precisa de dono verificável (PID vivo + marcador de cmdline), como já faz o
   `_pid_alive(expect_marker=...)` dos workers.

3. **Regressão do player é um "vai-e-vem" de duas releases** (C3). A 1.0.91 resolveu o 404 e a 1.0.93
   resolveu o spinner, mas a working tree está de volta ao estado quebrado **sem commit**, com
   `package.json` em 1.0.92 e tag `v1.0.93` publicada (M2). Se este estado for commitado, a próxima
   publicação colide com o registry e viola a regra 6 do AGENTS.md.

4. **Invariante 0.9.95 ("o servidor nunca carrega o .mp4") está quebrada em 4 pontos** (C3, A3, e os
   `st.download_button` com `read_bytes()` em `app/main.py:11439`, `:6126`, `:12942`, `:12958`,
   `:6255`, `:7345`). A causa é sempre a mesma: ler o ficheiro durante o render em vez de o servir.
   Os bons padrões já existem no repo (`data=video_stream` com "Preparar Vídeo para download", e o
   endpoint local da 1.0.93) — a padronização é mecânica.

5. **O `.runtime` é uma fonte de verdade duplicada e silenciosamente dessincronizada** (A7). Não há
   forma de a app saber que o código em `.runtime` é mais velho que o pacote: ela injecta a versão
   do pacote e corre o código antigo. Um `install` não detectivo (ou não corrido) produz um sistema
   que se identifica com a versão errada.

6. **A sanitização de blueprints (regra inviolável do AGENTS.md) está correcta no caminho principal,
   mas não é verificada em todos os emissores de prompt.** `hermes_ui/script_generation.py:94,113`
   sanitiza; `hermes_ui/text_to_images.py:406` só extrai requisitos visuais (seguro);
   `hermes_ui/creative_generation.py:311-325` usa `reference_bundle`. O caminho Remotion
   (`hermes_ui/pipeline_worker.py:3392-3478` → `hermes_ui/blueprint_loader.py:89-131`) monta o prompt
   a partir do blueprint bruto com `json.dumps` — **nenhum sanitizador é aplicado**. Os 5 blueprints
   Remotion do seed não têm chaves de comprimento hoje, mas um blueprint de composição criado pelo
   utilizador com `output_length_requirement` passaria directo para a LLM. `tests/test_script_length_guard.py`
   só crava o caminho `script_generation` (`:246-250`).

7. **A extração de narração/legendas está sólida** (`hermes_ui/script_voice.py:34-120`, com bloqueio
   de blockquotes/headings/tags de produção/herança de 1.0.03/1.0.17) e os limites de GPU do Motor
   são honrados pelas três filas (`hermes_ui/render_capacity.py:84-96`, `pipeline_worker.py:4741`,
   `thumbnail_worker.py:217`, `image_worker.py:277`) — **estas áreas não têm regressão**. O mesmo
   para o gate `max_parallel_mpt_runtimes` (`pipeline_worker.py:1964-2012`) e o kill de subprocessos
   com limpeza de handles (`pipeline_worker.py:1269-1324`).

8. **A árvore de trabalho está suja em 5 ficheiros** (`M CHANGELOG.md`, `M app/main.py`,
   `M package.json`, `M pyproject.toml`, `D tests/test_custom_video_player.py`) mais 3 não
   rastreados. Qualquer sessão que faça pull/rebase vai herdar este estado; a Etapa 2 deve começar
   por decidir o que fazer com 1.0.93.

---

## 4. Itens do checklist que ficaram **sem** regressão

- **Regra de tamanho de roteiro (AGENTS.md)**: `average_video_time` é a única fonte da verdade;
  `sanitize_blueprint_for_prompt` remove as chaves a qualquer profundidade; instrução no topo do
  system prompt; validação em código com 80 % de tolerância e retry. Testes verdes.
- **Filtro de metáforas do Pexels** (1.0.62/1.0.69): `sanitize_visual_keywords` +
  `keyword_queries_enriched` aplicados em `pipeline_worker.py:1760,4135,4206` e
  `creative_generation.py:344,673`; nicho de saúde isento; âncoras do nicho sempre presentes.
- **Legendas sem metadados**: narração extraída sem títulos/blockquotes/tags; `[Visual]/[Audio]/SCENE`
  removidos; limpeza única das flags `has_subtitles` adivinhadas (`domain.py:712-747`).
- **Reaproveitamento de áudio no "Refazer Vídeo"** (1.0.66/1.0.86): `_task_audio_for_reuse`
  (`pipeline_worker.py:1697`) + `remake_video_task(force_audio_regeneration=...)`
  (`domain.py:908-1000`); a flag morta não voltou.
- **Versão na sidebar**: `THUNDERBOLT_VERSION` → `package.json` → `pyproject.toml`, com
  `display_version` no formato de patch de dois dígitos (`app/main.py:305-344`, `13289-13290`).
- **`WinError 32`**: retry em `_ensure_streamable_mp4` (`pipeline_worker.py:3269-3320`), temp
  isolado (`storage.py:28-50`), `GpuTempLockError` propagado em vez de engolido
  (`pipeline_worker.py:3139-3154`).

---

## 5. Nota sobre o estado do repositório

Nada foi alterado, corrigido ou commitado nesta auditoria. As 5 modificações e 3 ficheiros não
rastreados listados em M2/M8 já existiam antes desta sessão e são do trabalho de outra sessão.

**FIM DA ETAPA 1 — a aguardar instruções para a Etapa 2 (correcção dos bugs priorizados).**
