# Changelog
## 1.0.07 — 2026-10-18
- **Integração das 55 skills do hub [iart-ai/motion-skills](https://github.com/iart-ai/motion-skills) (MIT)** — o dropdown "Estilo" da fonte Remotion passa de 3 itens provisórios para **58 opções reais** (3 motores internos + 55 skills extraídas).
  - **Extração completa**: os **18 packs** confirmados via API do GitHub (tiktok, text-message, youtube, ecommerce, ad, data-animation, explainer, map, web, motion-design, kinetic-typography, freelance, webgl, manim, generative-illustration, javascript, lower-thirds, b-roll) foram clonados e as suas **55 skills** copiadas (223 ficheiros, ~1,4 MB): `SKILL.md` (todas as 55 ✓), `README.md` (50; 5 packs upstream não o incluem), `references/` (54; b-roll upstream não tem) e `scripts/`/`templates/` quando existem (13 ficheiros) — skills completas, não apenas os 3 ficheiros mínimos.
  - **Arquitectura seed → storage** (invariante do pacote preservada: nenhum ficheiro de `storage/` entra no tarball, guardada por `test_social_auto_upload_package_exclusions`): **`seed/remotion_skills/<pack>/<skill>/`** é a fonte canónica distribuída (`"seed/remotion_skills/**"` adicionado ao `files` do `package.json`); **`seed_remotion_skills()`** (`hermes_ui/storage.py`, chamado de `ensure_storage()`) materializa a **cópia runtime em `storage/remotion_skills/`** — skills novas de actualizações futuras são adicionadas, o conteúdo já existente do utilizador nunca é sobrescrevido, e o `index.json` (índice da distribuição) é sempre sincronizado; skip rápido quando o índice já está igual. `storage/remotion_skills/` adicionado ao `.gitignore` (cópia de runtime, fonte canónica em seed/).
  - **`seed/remotion_skills/index.json`** (passo 5 da tarefa): índice por pack com `{id, name, description, folder}` — o backend lê sem varrer pastas; `name` legível (H1 do SKILL.md + nomes manuais revistos), descrição do frontmatter; colisão `lower-thirds` (2 packs) resolvida como "Lower Thirds" e "Lower Thirds — TikTok".
  - **`REMOTION_STYLE_OPTIONS`** (`app/main.py`) substituído pela lista completa derivada: 3 manuais ("Sem Estilo/Livre", "Vox-style Motion", "Hand-drawn Canvas Animation") + 55 skills em ordem alfabética de pack; sem duplicados. `VIDEO_SOURCE_STYLES["Remotion"]` herda automaticamente.
  - **UX do selectbox** (58 opções): o Streamlit 1.65 já fornece **busca fuzzy embutida** (`filter_mode="fuzzy"` por defeito — investigação #2); adicionado `help=` ao widget a explicar as opções por fonte. Validado na UI real: scroll do popover revela as 58; busca "YouTube" filtra para "YouTube Intro/Outro".
  - **Performance** (investigação #3): zero I/O novo na inicialização da UI — a lista é uma constante literal; a cópia seed→storage corre 1× por processo/raiz no `ensure_storage` (skip pelo índice); os ficheiros das skills nunca são carregados pela página (existem em disco para consulta/agentes).
- **Screenshots** (`docs/screenshots/`): `depois-5` (formulário Remotion com "Vox-style Motion" gravado), `depois-6` (dropdown aberto com a lista + caixa de busca), `depois-7` (busca "YouTube" filtrada).
- **Testes: 3 novos** (`tests/test_channel_video_source_styles.py`) — lista da UI == 3 manuais + 55 do `index.json` (18 packs, sem duplicados, ordem dos manuais preservada); cada skill extraída tem `SKILL.md` em disco (55/55, fonte seed); `ensure_storage` materializa a cópia runtime (55 pastas + índice) e **não sobrescreve** edições locais. Suíte completa re-correrá após a correcção da invariante.

## 1.0.06 — 2026-10-18
- **Campo "Estilo" dependente da "Fonte do vídeo" nas Configurações de vídeo do canal** (`app/main.py` — `render_channel_video_defaults`). Cada fonte passa a ditar a lista de estilos válidos (novo `VIDEO_SOURCE_STYLES`); nas fontes que não usam estilos de IA (Pexels/Pixabay, Web Images) o campo **oculta** com a legenda *"Esta fonte de vídeo não utiliza estilos de IA."*.
  - **Lista canónica de 14 estilos** (`AI_STYLE_OPTIONS`): "Natural Realista" dividido em **"Natural"** e **"Ultra Realista"**, "Cocomelon style" substituído por **"Cartoon"** (+ **"Stickman Cartoon"**); os restantes 10 rótulos mantêm-se. Os selectbox de criação avulsa ("Estilo IA" e "Estilo visual das imagens") passam automaticamente a usar a nova lista.
  - **`REMOTION_STYLE_OPTIONS`** (skills): `"Sem Estilo/Livre"` (padrão), `"Vox-style Motion"`, `"Hand-drawn Canvas Animation"` — as restantes skills da lista completa do utilizador são adicionadas quando fornecidas (o motor HandDrawnCanvas já existe nas composições, `docs/remotion.md`).
  - **Selectbox condicional com key estável** `channel_style_{channel_id}`: valor gravado preservado quando ainda é válido para a fonte; troca de fonte com estilo incompatível → **reset determinístico** para o primeiro item da nova lista + `st.info("O estilo foi redefinido porque a fonte de vídeo mudou.")` (session_state limpo antes da instância do widget).
  - **Persistência** no botão "Guardar configurações de vídeo": `default_style_ia` + alias `style_ia` (`""` quando a fonte não usa estilos — o alias é o campo que `automation_worker.py:335` já lê).
  - **Backend**: `create_tasks_for_batch` (`hermes_ui/domain.py`) injeta o estilo do canal em `generation_settings["style_ia"]`/`["text_to_images_style"]` **só quando o canal define estilo** (nunca sobrescreve escolhas explícitas do formulário com `""`); `task["style_ia"]` ganha fallback ao canal; `_refresh_task_channel_video_settings` ("Refazer Vídeo") revalida o estilo actual do canal, como os restantes defaults.
  - **Migração leve** `migrate_channel_style_values()` (`hermes_ui/storage.py`, chamada de `ensure_storage()` — idempotente, sem reescrita quando não há valores antigos): `style_ia`/`default_style_ia` de canais existentes `"Natural Realista"→"Natural"` e `"Cocomelon style"→"Cartoon"` (mapeamento confirmado pelo utilizador); canais sem estilo ou já migrados ficam intactos.
  - **Restrições respeitadas**: `UNAVAILABLE_VIDEO_SOURCES` intocado (`music_clips` continua indisponível mas com lista de estilos pronta); `Montage: Pexels/Pixabay` e `Montage: Web Images` sem alteração de comportamento além do campo oculto; UI de criação avulsa estruturalmente intocada.
- **Screenshots antes/depois** (`docs/screenshots/`): `antes-1` (HEAD — formulário sem campo Estilo), `depois-1` (Text-to-Images — "Anime Style" gravado preservado), `depois-2` (Pexels — campo oculto + legenda), `depois-3` (Remotion — reset + aviso), `depois-4` (dropdown com as skills). Capturados com Playwright headless contra storage de teste (canal fictício, dados reais intocados).
- **Testes: 14 novos** (`tests/test_channel_video_source_styles.py`) — mapeamento fonte→estilos completo, lista canónica de 14, skills Remotion com default livre, selectbox condicional + reset + aviso (source assertions), persistência default+alias, migração de rótulos antigos (legacy, idempotência, tolerância a ficheiro corrompido), estilo do canal nas tarefas (automação, prioridade do formulário, sem estilo não injecta), remake com/sem estilo, wiring do ensure_storage. `tests/test_video_modes.py` actualizado para a lista de 14.
- **Suíte: 1386 passados + 2 skipped + 10 subtests** (1372 + 14), zero falhas.

## 1.0.05 — 2026-10-18
- **CORRECÇÃO DE BUG: `ValueError: I/O operation on closed file` na aba "Automação Youtube"** (`app/main.py`). Ao interagir com a página (ex.: clicar em "Refazer vídeo"), o Streamlit executa um *rerun* que pode fechar o `sys.stdout` do script run; o `_log` da telemetria `[YT-AUTOM]` chamava `print(..., flush=True)` no rerun seguinte e crashava com `ValueError` — **não era um erro da pipeline de vídeo**, mas da arquitetura de logging no Streamlit.
  - **Migração para `logging`**: o `_log` passou a emitir via logger dedicado `thunderbolt.automation` (`logger.info(f"[YT-AUTOM] ...")`) — o logging gere o stream internamente e engole falhas de escrita (`Handler.handleError`), nunca propagando excepção para o rerun.
  - **Handler dedicado no stderr real** (module-level em `app/main.py`): nível INFO, `propagate=False`, `StreamHandler` com **referência estável ao stderr UTF-8 da consola capturado no import** — fora do ciclo de vida do stdout dos reruns. Sem handler próprio, INFO cairia no `lastResort` do logging (que só emite WARNING+) e a telemetria de diagnóstico desapareceria em silêncio. Formato da consola idêntico ao anterior (`[YT-AUTOM] msg: X.XXs`).
  - **Guarda extra no `_log`**: `try/except (ValueError, OSError)` à volta do `logger.info` — a telemetria nunca interrompe o render, mesmo no caso extremo de o stream do próprio handler estar fechado.
  - **Lógica de negócio intacta**: a automação, o pipeline de vídeo e o formato/s cadência das mensagens `[YT-AUTOM]` (sync roteiros, worker status, KPIs, channel cards, TOTAL) ficam byte-a-byte iguais.
- **Testes: 5 novos** (`tests/test_automation_logging.py`) — `_log` usa logging e não `print(flush=True)` (source-structure no bloco `render_automation`); configuração do logger dedicado existe a module-level; forma do logger em runtime (INFO, sem propagação, handler, singleton de `app.main`); `logger.info` não lança com o stream do handler fechado (mecanismo `handleError`); handler com stream estável continua a escrever depois de o stdout do "rerun" ser fechado (cenário do Streamlit reproduzido).
- **Suíte: 1372 passados + 2 skipped**, zero falhas (1367 + 5 novos).

## 1.0.04 — 2026-10-17
- **CORRECÇÃO: imagens de cena separadas das thumbnails — fim do título queimado em todas as cenas e do storage misturado.** A auditoria ao modo "Montage: Text-to-Images" confirmou que o pipeline de cenas reutilizava a maquinaria de THUMBNAIL: `_compose_thumbnail_prompt` injectava uma "MANDATORY LETTERING LAYER" com as primeiras 4 palavras do título (`_fallback_lettering(topic)`) em **todas** as cenas (sobrepondo o "never include words" do storyboard), e o destino era fixo em `storage/thumbnails/` (imagens de cena misturadas com as capas YouTube, com hash de cache que incluía o topic).
  - **Novo modo `is_scene_image`** (`media_generation.generate_image_from_pool` → `generate_image_for_card` → `_image_request`, + `thumbnail_generation.generate_thumbnail_image` para o ramo Nano Banana): prompt puro (as regras de "sem texto" vêm da LLM de storyboard), sem lettering layer, sem topic na composição, e gravação em **`storage/scenes/`** com hash `(prompt, variant_index)` — a cache de cenas sobrevive a mudanças de título. O Canva é saltado para cenas (só produz thumbnails com blueprint/título). **Sem `is_scene_image`, o comportamento das thumbnails reais fica byte-a-byte igual** (lettering obrigatório + `storage/thumbnails/`).
  - **Call sites**: o loop de cenas da rota text_to_images e a rota blueprint (Remotion) passam `is_scene_image=True`; a geração de thumbnails da pipeline (capa) continua no modo por omissão.
  - **Regra dos 5% de texto** (`text_to_images.generate_image_prompts_for_scenes`): no máximo 5% das cenas (`max(1, int(count * 0.05))`, distribuição uniforme — 1 cena marca fica no meio; com várias, início/meio/fim) podem receber um texto curto queimado na imagem. A LLM recebe as cenas marcadas com `allow_text` e devolve `text_overlay` (sanitizado a 3 palavras/32 chars), injectado no prompt como "with the text 'X' written on it.". Todas as restantes saem estritamente sem texto; se a LLM falhar, nenhuma cena recebe texto (0% é sempre seguro).
- **Testes: 14 novos** (`tests/test_scene_images.py`) — cena usa prompt puro e `storage/scenes/`; hash da cena ignora o topic (cache entre títulos); **regressão: thumbnail por omissão mantém lettering + `storage/thumbnails/`**; `_image_request` cena vs default; Canva saltado em cenas e mantido em thumbnails; Nano Banana em modo cena; posições dos 5% (20→{10}, 60→{0,30,59}, 100→{0,25,50,74,99}); overlay marcado injectado/truncado; overlay em cena não-marcada ignorado; falha da LLM → zero texto; wiring das rotas.
- **Validação E2E real (20 cenas)**: narração → cenas → TTS Azure real → prompts via LLM real (regra 5%) → 20 imagens reais do pool (Agnes) com `is_scene_image=True` → escala ao áudio → montagem com subtítulos. Relatório na conversa.
- **Suíte: 1367 passados + 2 skipped**, zero falhas (1353 + 14 novos).

## 1.0.03 — 2026-10-17
- **CORRECÇÃO DE BUG: vídeo text_to_images/web_images saía com 17 segundos de narração (mudo a partir de 0:17) e subtítulos com frontmatter YAML.** Diagnóstico com o vídeo real `video_fecb50306d` (10:19 min, áudio de 16,85 s): a extração da narração devolvia **28 palavras do frontmatter do ficheiro** (`id: ... type: videoscript ...`) em vez das 851 palavras de `[NARRATION]`, e as cenas/subtítulos eram construídas sobre o **markdown cru** (a cena 1 era literalmente `--- id: acc9dc30128b type: video_script ...`).
  - **Extração (`hermes_ui/script_voice.py`)**: a regex de marcadores só conhecia `NARRAÇÃO`/`NARRACAO` — os roteiros em inglês usam `**[NARRATION]**` (não reconhecido → corpo nunca marcado como voz) e os corpos vêm em blockquotes `>`, que eram sempre descartados como "editoriais". Corrigido: `NARRATION` e `VOICE OVER` passam marcadores de voz; **blockquotes DENTRO de um bloco de narração passam a ser lidos** (o prefixo `>` é retirado; fora do bloco continuam editoriais); `ON-SCREEN TEXT` entra na família visual (texto de ecrã não se narra); o **frontmatter YAML** é removido defensivamente (nunca chega ao TTS). Medido no roteiro real: 28 → **851 palavras** extraídas.
  - **Cenas da narração (`pipeline_worker.py`, rotas text_to_images e web_images)**: as cenas — que alimentam as imagens, os prompts e os subtítulos — passam a vir da **narração extraída**, não do markdown cru; antes saíam 132 cenas com frontmatter/directorias visuais, agora **71 cenas de fala real**. O áudio é sintetizado antes do split (mesma narração em ambas as pontas).
  - **Durações escaladas ao áudio real (`_scale_scene_durations_to_audio`)**: as durações estimadas (wpm) erream e o vídeo terminava com minutos de silúncio (ou cortava a narração); agora o total das cenas escala proporcionalmente à duração real do ficheiro TTS (medida via moviepy) — o vídeo termina com o áudio. Falhas de leitura deixam as estimativas intactas.
  - A rota Remotion e o `--video-script` do MPT beneficiam automaticamente da extração corrigida.
- **Testes: 7 novos** (`tests/test_script_voice.py`) — regressão do formato real (NARRATION + blockquotes + frontmatter + ON-SCREEN TEXT + SFX), frontmatter sem narração → vazio (não metadata), `VOICE OVER`, escala de durações (proporcional, no-op quando ≈1, sobrevive a falha do probe) e source-structure das rotas (cenas da narração + escala nas duas rotas).
- **Suíte: 1353 passados + 2 skipped**, zero falhas.

## 1.0.02 — 2026-10-16
- **CORRECÇÃO DE BUG: erro 403 do TTS na geração de vídeo (Edge TTS descontinuado)**. A Microsoft descontinuou o endpoint `wss://speech.platform.bing.com` (Out/2026) e a `edge-tts` do PyPI (≤7.2.8 — o fix só existe no branch principal do GitHub) passou a receber **403** em todas as chamadas. No MoneyPrinterTurbo "Azure TTS V1" **é** Edge TTS (`voice.py` do MPT: qualquer voz sem sufixo `-V2`/prefixo cai no fallback `azure_tts_v1` = edge) — os cards mostravam o 403 críptico do aiohttp seguido de "API não identificada (falha anterior) (provider: unknown)". Reproduzido 1:1: `aiohttp.WSServerHandshakeError: 403, message='Invalid response status', url='wss://speech.platform.bing.com/...'`.
  - **Encaminhamento por credenciais (`hermes_ui/voice_preview.py`, nova `resolve_narration_provider`)**: a cadeia local de narração (Remotion, text_to_images, web_images, blueprints) mapeava "Azure TTS V1" cegamente para o edge (`azure_v1`→`_save_edge`) — a origem do 403. Agora: com credenciais Azure (`azure_speech_key`+`azure_speech_region`) usa-se **sempre Azure Speech real** (`https://{region}.tts.speech.microsoft.com/cognitiveservices/v1`) — o mesmo comportamento que a rota MPT já tinha via `_uses_azure_speech_sdk_v2`; **sem credenciais o edge é bloqueado** com mensagem clara ("Edge TTS descontinuado: a Microsoft passou a recusar o endpoint speech.platform.bing.com (HTTP 403 desde Out/2026). Configure Azure Speech (chave e região em Configuração API) ou seleccione outro provider de narração.") em vez do 403 críptico. ElevenLabs e Azure Speech SDK V2 mapeiam directamente.
  - **Log do provider efectivo** (`hermes_ui/text_to_images.py`): antes de sintetizar, o stderr do worker regista `[tts] provider=azure_speech service=Azure TTS V1 voice=pt-BR-…` — o terminal diz exactamente quem foi chamado quando a narração falha.
  - **Sem fallback silencioso para Edge**: rota MPT ganha guarda pré-render (`pipeline_worker._mpt_edge_narration_blocked_reason`) — voz simples sem `-V2`, sem prefixo de provider e sem credenciais Azure bloqueia a geração antes de gastar o render ("Voz seleccionada usa Edge TTS (descontinuado…) Seleccione uma voz Azure V2 (termina em -V2-) ou configure Azure Speech…"); com credenciais a voz continua a ser promovida a `-V2` (`_azure_speech_v2_voice_name`) e o MPT usa Azure real (`is_azure_v2_voice` do MPT). Modos "Sem narração"/"Upload" e vozes com prefixo (`elevenlabs:`, `siliconflow:`, …) nunca são bloqueados.
  - **Atribuição correcta no card** (`pipeline_worker._failure_attribution`): o 403 do edge (markers `speech.platform.bing.com`, `sec-ms-gec`, `edge_tts`, `azure_tts_v1`) deixa de cair em "API não identificada (falha anterior)" e passa a reportar "Falha no provider: Edge TTS — endpoint descontinuado pela Microsoft em Out/2026. Atualize edge-tts ou use Azure V2 (configure azure_speech_key/region)." com `provider: edge_tts` e campos de configuração indicados. Erros do Azure real mantêm a atribuição "Azure Speech SDK V2 API" própria.
  - **Previews**: o 403 do edge em previews de voz é traduzido na mesma mensagem clara (`_save_edge` envolve o `save()` do edge-tts).
- **Validação E2E com a configuração real do utilizador** (credenciais Azure presentes, region eastus): provider resolvido `azure_speech`; log `[tts] provider=azure_speech …` no terminal; narração real gerada via `https://eastus.tts.speech.microsoft.com/cognitiveservices/v1` (53 KB de MP3, frase curta) — **zero contacto com speech.platform.bing.com**; sem credenciais o bloqueio dispara com a mensagem clara.
- **Testes: 12 novos** (`tests/test_tts_provider_routing.py`) — resolução por credenciais (V1+credenciais→azure_speech, V2→azure_speech, ElevenLabs directo, sem credenciais→bloqueio com mensagem exacta), cadeia local loga e usa o provider resolvido, bloqueio da cadeia local sem credenciais, guarda pré-render do MPT (bloqueia voz simples sem credenciais; não bloqueia com credenciais/-V2/prefixedos/modos especiais), wiring da guarda na pipeline, atribuição do 403 real do bing (card com "Falha no provider: Edge TTS" e sem "API não identificada") e tradução do 403 em previews. Teste antigo da atribuição combinada actualizado para a atribuição precisa.
- **Suíte: 1346 passados + 2 skipped**, zero falhas.

## 1.0.01 — 2026-10-16
- **CORRECÇÃO DE BUG: warning recorrente de política de widgets do Streamlit (`new_video_resume_sections`)** (`app/main.py`). A cada render da tela de criar/editar vídeo o terminal imprimia `The widget with key "new_video_resume_sections" was created with a default value but also had its value set via the Session State API` com stack completo.
  - **Causa raiz**: o `st.multiselect` "Configurações a completar" passava `default=missing_sections` enquanto o seed `_seed_resume_video_settings` pré-escrevia a mesma key em `st.session_state` (via `f"{state_prefix}_sections"`) ao carregar/trocar de registo guardado — o antipadrão default= + pré-escrita que a política de widgets do Streamlit sinaliza (`policies.py` só dispara com `default_value is not None`).
  - **Fix (session_state como fonte única da verdade)**: `default=` removido do multiselect; o widget adopta o valor de session_state, onde o seed continua a ser o escritor canónico por registo (trocar de rascunho continua a actualizar as secções em falta); guard canónico `if sections_key not in st.session_state` cobre o caso improvável de key ausente. Label, options, `format_func` e help intocados; **valor inicial visível idêntico** (tanto o antigo `default` como o seed derivam de `missing_setting_sections(generation_settings)` do mesmo registo).
- **Guard cirúrgico contra warnings futuros de política de widgets**: `logging.getLogger("streamlit.elements.lib.policies").setLevel(logging.ERROR)` no topo de `app/main.py` (module-level, após o import do streamlit). Só este logger específico é rebaixado — erros reais continuam visíveis; `logging.disable()` e `getLogger("streamlit")` propositadamente não usados. O logger é criado e cacheado no import do streamlit, logo o nível persiste (`update_formatter` só mexe em handlers/formatters).
- **Validação E2E (streamlit 1.59.1 headless + sessão real de browser)**: padrão antigo reproduz o warning 1:1 no terminal; padrão novo não dispara nenhum; com o guard activo, o antipadrão deixa de imprimir warning **mesmo sem o fix**; `StreamlitDuplicateElementKey` (duas widgets com a mesma key) continua visível no terminal e na página; valor inicial do multiselect idêntico nos dois padrões (confirmado no accessibility DOM).
- **Testes: 2 novos** (`tests/test_draft_video.py`): o multiselect resume_sections não pode voltar a usar `default=` (guard canónico + seed canónico preservados via source-structure) e o guard de logging existe após o import do streamlit sem silenciamento genérico.
- **Suíte: 1334 passados + 2 skipped**, zero falhas (1332 + 2 novos).

## 1.0.00 — 2026-10-16
- **Nota de versão**: a etiqueta correcta depois de `0.9.99` é `1.0.00` (patch 99 esgota → MINOR avança; com MINOR em 9, o MAJOR avança e MINOR/PATCH reiniciam). A etiqueta `0.10.00`/`0.10.0` foi publicada por engano nesta sequência e fica órfã de dist-tags — usar `1.0.00`/`1.0.0`.
- **CORRECÇÃO DE BUG: legenda queimada com fundo hug-text, sem clip e com wrap** (`hermes_ui/text_to_images.py`). A legenda queimada (rota Pexels/Pixabay com áudio customizado via `burn_captions_on_video`, e montagens text_to_images/web_images via `_subtitle_clips_for_scenes`) saía com três defeitos visuais:
  - **Barra preta full-width**: o `TextClip` do MoviePy em modo caption com cor de fundo pintava a canvas inteira — a largura era forçada por `size[0]` (86% do vídeo) e o fundo cobria-a por completo, em vez de envolver apenas o texto.
  - **Base das letras cortada** (descendentes g/p/q/y desapareciam): a Pillow 11 removeu `draw._multiline_spacing` e o MoviePy 2.1.2 passou a calcular a altura da caixa pelo bbox de tinta do texto enquanto desenhava a baseline pela métrica da fonte. A `MicrosoftYaHeiBold.ttc` (default do canal) tem ascent interno ~1.4× a altura visível das maiúsculas — reproduzido e medido no frame de referência da tarefa `9f2cc9e6`: canvas de 42px com a tinta a descer até ~48px (≈7px cortados).
  - **Frase "truncada"**: o MoviePy até quebrava linhas, mas a percepção de corte vinha da divisão por segmentos (~5s) somada à barra full-width; o wrap passa a ser próprio, medido em pixels com a fonte real (`font.getlength`), com divisão por caracteres para palavras gigantes (URLs, palavras longas).
  - **Renderer novo (PIL determinístico → `ImageClip`)**: cada cena é desenhada com layout de baseline pelas métricas reais da fonte (`font.getmetrics()` — ascendentes/descendentes nunca cortados, Q/ç/ã incluídos), fundo composto numa camada própria **atrás** da tinta, e o clip final é recortado exactamente à caixa hug-text (tinta + padding uniforme 10-15px em 1080p, escala com a fonte). Posição (Top/Center/Bottom), cor, contorno, cor de fundo, tamanho, duração e sincronização por cena mantêm-se iguais; defaults do canal e UI intocados.
  - **`os.replace` do `burn_captions_on_video` robustecido no Windows**: o `CompositeVideoClip.close()` do MoviePy não fecha os clips membros — o leitor do vídeo original mantinha o ficheiro aberto e a substituição in-place falhava com WinError 5 **depois de a queima estar completa** (a legenda perdia-se com aviso no stderr). O leitor é agora fechado explicitamente antes do replace.
- **Testes: 6 novos** (`tests/test_text_to_images_subtitles.py`) — caixa hug-text com padding uniforme nas 4 direcções (gaps de tinta medidos), ascendentes/descendentes completos dentro da caixa, wrap multi-linha centrado dentro da largura máxima (86%), fundo opaco atrás do texto via máscara, `_wrap_text_pixels` com limite de largura e palavras gigantes, e **regressão YaHei** com o segmento real do frame de referência (fonte 35 em 1920×1080: sem barra de 86%, sem descendentes cortados). Asserção de estrutura do source actualizada do `TextClip` para o render PIL (`getmetrics`, `ImageClip`, sem modo caption/`bg_color`).
- **Validação E2E com o vídeo real do canal** (oração nocturna, 3:34, 1920×1080, fonte 35, posição center): `combined-1.mp4` da tarefa `9f2cc9e6` copiado para temp e queimado com a narração real via `burn_captions_on_video` — frames extraídos mostram caixa hug-text, descendentes completos, padding uniforme e wrap em 2 linhas centradas (comparativo antes/depois gerado).
- **Suíte: 1332 passados + 2 skipped**, zero falhas (1326 + 6 novos).

## 0.9.99 — 2026-10-15
- **CORRECÇÃO DE BUG + funcionalidade: música de fundo "Carregar ficheiro" com rodízio por canal**. O dropdown "Fonte da música de fundo" oferecia "Carregar ficheiro" mas **nenhum widget de upload aparecia** — em nenhum dos dois locais. Corrigido nos dois, com componente partilhado único:
  - **Novo módulo `hermes_ui/channel_music.py`** — componente `render_music_upload_section(scope, current_musics, *, volume=None)` partilhado pelos dois locais + toda a persistência: uploader multi-ficheiro (MP3/WAV/M4A/OGG/FLAC, máx 50 MB/ficheiro), lista de músicas anexadas com nome + tamanho legível (KB/MB), botão 🗑️ Remover **com confirmação** (apaga o ficheiro físico + entrada no manifest) e checkbox de rodízio visível **apenas com 2+ músicas** ("Fazer rodízio entre as músicas a cada vídeo gerado").
  - **Local A — card do canal** (`Canais e Perfis de Vídeos → Canais YouTube → Configurações de Audio`): `render_channel_audio_subtitle_defaults` (`app/main.py`) renderiza o uploader quando "Carregar ficheiro" é seleccionado. Botão "Guardar configurações de Audio" e dropdown de Volume inalterados.
  - **Local B — criação de vídeo** (`Pipeline Vídeos → Criação de Vídeos → Configurações de áudio`): `render_video_generation_settings` (`app/main.py`) renderiza o mesmo componente; com canal seleccionado usa a pasta do canal (`background_music_scope`), sem canal (ex.: Lote geral) usa a área global. Volume e restantes fontes ("Sem música", "Random Background Music", "Ficheiro existente", "Criar via Suno API") intocados — mesmas chaves de widget, mesmo default.
  - **Persistência** — `storage/blueprints/canais/{channel_id}/music/` (ficheiros + `manifest.json` com `musics[{id, filename, size, checksum, uploaded_at}]`, `rotation_enabled`, `last_used_index`); escopo global em `storage/blueprints/video_creation/music/`. Nome sanitizado (sem traversal `..`, sem caracteres inválidos, nomes reservados do Windows evitados), sem sobrescrever (`trilha1.mp3` → `trilha1_2.mp3`), duplicados detectados por checksum MD5 (reenvio não duplica bytes), escrita atómica com lock cross-process (`storage.atomic_write`).
  - **Rodízio no pipeline** (`hermes_ui/pipeline_worker.py`): `_with_uploaded_background_music` resolve a faixa UMA vez por tarefa (antes das tentativas de rota Pexels/Pixabay, sem duplo avanço) via `select_music_for_render` — com rodízio activo escolhe `(last_used_index + 1) % len(musics)` e **persiste o novo índice no manifest ANTES do render** (worker que morra a meio não repete a faixa); sem rodízio usa sempre a primeira música. O ficheiro é copiado para `{MPT_ROOT}/storage/bgm/` (o cli.py do MoneyPrinterTurbo só aceita `--bgm-file` dentro das pastas geridas por ele) com nome determinístico por checksum e passado como `--bgm-type custom --bgm-file <nome>`. Sem faixas anexadas mantém o comportamento legado (nenhum `--bgm-type`).
  - **Pipeline de narração intocado** (Azure TTS, voz, volume da narração, velocidade, `--custom-audio-file`).
- **Testes: 17 novos** (`tests/test_channel_music.py`) cobrindo uploader visível, persistência na pasta do canal, dedupe por checksum, sanitização, lista, remoção física+manifest com confirmação, checkbox só com 2+ músicas, ordem circular, índice persistido antes do render, rodízio desligado usa a primeira, componente partilhado nos dois locais, stage para storage/bgm do MPT e contrato `--bgm-type`/`--bgm-file` (legado byte-a-byte).
- **Suíte: 1326 passados + 2 skipped** (1309 + 17), zero falhas.

## 0.9.98 — 2026-10-15
- **Fingerprint persistente do sync de roteiros em disco** (`hermes_ui/storage.py` + `app/main.py`): o sync de roteiros custava ~4,1s (até 11,5s a frio) na primeira abertura de cada sessão nova — cada reload/aba/restart pagava de novo. Agora o fingerprint de (path, mtime_ns, size) dos 62 `.md` + `scripts.json` é guardado em `state/.sync_fingerprint.json` (~8 ms para computar). Se o fingerprint bater, o sync inteiro é pulado — **inclusive entre sessões**. **Medido: 11,5s → 0,01s na 2ª abertura.**
  - `compute_scripts_fingerprint()`: SHA-256 de (path relativo, mtime_ns, size) de cada `.md` + índice — determinístico, read-only.
  - `read_stored_fingerprint()` / `write_stored_fingerprint()` / `clear_stored_fingerprint()`: leitura/escrita/remoção atómica do `.sync_fingerprint.json` em `state/`; corrompido → `None` (força sync, nunca crasha).
  - `_sync_saved_scripts_to_youtube_automation()` (`app/main.py:6033`): 3 camadas — (1) `session_state` intra-sessão (nem o fingerprint computa); (2) fingerprint em disco entre sessões; (3) sync completo quando o fingerprint difere. A checagem antiga por `sync_signature` (IDs de registo) foi substituída — o fingerprint de ficheiros é estritamente mais sensível.
  - Botão discreto **"Forçar sincronização de roteiros"** no rodapé da aba (para OneDrive/Dropbox que preservam mtime): limpa o fingerprint + `session_state` e corre o sync no rerun seguinte.
- `.gitignore` já cobre `storage/state/*.json` — nenhum ajuste necessário.
- **Suíte: 1309 passados + 2 skipped**, zero falhas.

## 0.9.97 — 2026-10-15
- **Removido o botão "Aplicar legenda"** dos cards de vídeo (`app/main.py`) — consolidado no "Refazer Vídeo". O `remake_video_task` (`hermes_ui/domain.py:906-966`) já relê a config actual do canal via `_refresh_task_channel_video_settings` (linha 927), incluindo o bloco de legendas completo (`enable_subtitles`, fonte, posição, cor, fundo, contorno, tamanho). O botão separado era redundante — dava falsa sensação de regeneração parcial quando as legendas são queimadas no render e qualquer reaplicação exige re-renderização.
- **Removida a função `apply_subtitles_to_task`** (`hermes_ui/domain.py`) e a flag `subtitles_regeneration_requested` (código morto — nunca consumida pelo worker). Removidos os 3 testes associados (`tests/test_domain.py`) e a entrada `subtitles_reapplied` do catálogo de notificações (`hermes_ui/notifications.py`). `audio_regeneration_requested` intocada (faz parte do fluxo do remake).
- **Tooltip explicativo adicionado ao "Refazer Vídeo"** (`help=` do `st.button`): *"Reaplica as configurações atuais do canal (legendas, música, voz, duração, proporção, transição) e regenera o vídeo do zero. Use quando a config do canal mudou ou quando o vídeo foi gerado sem legenda por engano."* — sem mudar texto, tamanho, posição ou cor do botão.
- **Layout do card volta a ter exactamente os botões de antes da 0.9.95**: Baixar Thumbnail, Baixar Thumbnail Prompt, Baixar Roteiro, Baixar Vídeo, Refazer Vídeo (full-width, não mais lado a lado), checkbox Upload ok.
- **Grep de validação = vazio**: zero referências a `subtitles_regeneration_requested`, `apply_subtitles`, ou "Aplicar legenda" no repo inteiro.
- **Suíte: 1309 passados + 2 skipped** (1312 − 3 testes removidos da função extinta).

## 0.9.96 — 2026-10-15
- **RECUPERAÇÃO DA UI — Automação YouTube restaurada por inteiro** (`app/main.py`): a 0.9.95 escondeu os cards atrás de botões "Detalhes"/"Editar" — tudo o que o utilizador construiu volta a estar **sempre visível**, sem cliques intermédios:
  - **Cards de canal**: layout original de 8 colunas restaurado — nome, handle, país, avatar (st.image URL remota), Abrir canal, Criar Vídeo, Thumbnail Blueprint, Idioma, Nicho, Fonte + Proporção, Horário, Tempo Médio, Blueprint Padrão, Narrador/Voz, Automação ligada, Guardar. Botão "Editar" removido.
  - **Cards de vídeo**: layout original de 4 colunas restaurado — thumbnail (width="stretch"), player (Reproduzir vídeo → link estático), ID, estado + progresso, fonte, Start, Stop, Baixar Thumbnail, Baixar Thumbnail Prompt, Baixar Roteiro, Baixar Vídeo, Upload, Upload ok, **Refazer Vídeo**, **Aplicar legenda** (Task 3, lado a lado), Apagar + confirmação. Botão "Detalhes" removido; downloads sempre visíveis (o botão "Preparar downloads" saiu).
  - **Sub-abas**: `st.tabs(["Pipeline", "Videos Postados"])` RESTAURADO com a aparência original (`st.segmented_control` removido). O catálogo continua a carregar **1× por rerun** (carregado em `render_automation` e passado às duas sub-abas — zero leituras duplas).
  - **KPIs mantidos** no topo (Task 2): Tarefas / A Fazer / Em Execução (com "● rodando") / Concluídos / Falhas.
- **Otimizações internas mantidas (zero impacto visual)**:
  - `hermes_ui/storage.py`: `ensure_storage()` 1× por processo; cache de leitura por arquivo sem `deepcopy` (read_json ×100 = 26 ms).
  - `app/main.py`: índice de blueprints em processo (TTL 60 s; `_channel_average_video_time` ×6 = 0,5 ms); sync de roteiros O(1) por hash maps; telemetria `[YT-AUTOM]` permanente.
- **AUDIT_UI.md** criado na raiz (fora do commit — checklist de preservação, prova de que todos os elementos visíveis foram restaurados).
- **Suíte: 1312 passados + 2 skipped**, zero falhas.

## 0.9.95 — 2026-10-14
- **[Task 1] Performance da aba "Automação YouTube"** (auditoria prévia: ~430 widgets, ~500 leituras/parse por abertura, aba do Chrome a ~3 GB):
  - **`ensure_storage()` corre 1× por processo** (`hermes_ui/storage.py`): corria a CADA `read_json`/`write_json` e re-parseava `tasks.json` (1,77 MB) + `batches.json` (1,58 MB) + `channels.json` via `migrate_finance_thumbnail_blueprint` — 27-68 ms por leitura × centenas por render. Chave inclui `STORAGE|STATE` (tests com raízes tmp continuam garantidas).
  - **REAL-BUG: o cache de leitura só populava `settings.json`** — todos os outros ficheiros re-parseavam sempre. Agora TODOS os ficheiros são cacheados por fingerprint (mtime+tamanho) e o hit devolve o objecto partilhado (sem `deepcopy`, 12 ms/call só de cópia). Contrato documentado: mutações passam sempre por `write_json`/`update_json` (que invalidam a entrada). **Medido: `read_json(tasks.json)` ×100 = 26 ms (antes: 2,6-6,8 s — 100×; meta < 200 ms ✓).**
  - **Índice de blueprints em processo** (`app/main.py`): `blueprint_catalog`/`blueprint_for_channel` faziam `rglob` + `json.load` + 1 `read_json` por ficheiro POR CANAL (~12 scans completos ≈ 14,7 s medidos na auditoria). O índice carrega a biblioteca 1×/60 s e serve lookups O(1). **Medido: `_channel_average_video_time` ×6 = 0,5 ms (antes: 14,66 s — meta < 200 ms ✓).**
  - **Vista única sem `st.tabs`**: as duas sub-abas (Pipeline/Videos Postados) renderizavam sempre (catálogo carregado e ordenado 2×). Selector `st.segmented_control` + catálogo carregado 1× por rerun e passado aos cards.
  - **Cards compactos com detalhes a pedido**: canal (~9 widgets vs ~24; formulário de agendamento só no canal em edição) e vídeo (linha resumida Start/Stop/Detalhes; thumbnail width=160, leitor, downloads, upload, refazer e legenda só nos detalhes). Avatar remoto (`st.image` de URL do YouTube) saiu do render por defeito (6 fetchs de rede). **Medido no app real: TOTAL render_automation 0,44-0,54 s → 0,10 s; widgets ~430 → ~160; zero bytes de roteiros/thumbnails (4,77 MB) no payload da abertura.**
  - **Sync O(1)**: `_sync_saved_scripts_to_youtube_automation` substituiu o scan aninhado O(62×91) por hash maps (script_document_id → conteúdo → título).
  - **Invariante anti-"aba de 3 GB"** documentada no código: downloads sempre a pedido; imagens por caminho; vídeo/áudio nunca carregados para metadados.
- **[Task 2] KPIs no topo da aba**: 5 cards no estilo da aba Início — Tarefas (total registrado), A Fazer, Em Execução (com indicador verde "● rodando" quando o worker está vivo), Concluídos, Falhas. 1 passada de `Counter` sobre o catálogo já carregado (zero leituras extra), zero imagens.
- **[Task 3] Botão "Aplicar legenda" nos cards de vídeo** (ao lado de "Refazer Vídeo"): revalida SÓ o bloco de legendas do canal (`default_enable_subtitles`, fonte, posição, cor, fundo, contorno) e recoloca o vídeo na fila com a flag `subtitles_regeneration_requested` — as legendas são queimadas no render (`pipeline_worker.py` passa `--subtitle-*` ao motor), por isso a remontagem é inevitável; roteiro, blueprint, tags, thumbnail, voz e artefactos baixados ficam intactos. Nunca carrega o `.mp4`. Toast + notificação "Legendas reaplicadas" com marca de acção manual. Desabilitado sem vídeo ou com tarefa em execução; canal sem config → "Canal sem config de legendas — configure em Canais e Perfis".
- **Instrumentação permanente** `[YT-AUTOM]` no `render_automation` (sync/worker/KPIs/cards/TOTAL) para diagnóstico futuro de lentidão.
- **Suíte: 1312 passados + 2 skipped** (1309 + 3 novos do Task 3); 9 testes de inspecção de fonte actualizados para o novo layout (intenções preservadas); teste do cache de leitura actualizado para o novo contrato (hit partilha o objecto; escrita invalida).

## 0.9.94 — 2026-10-14
- **[Item 1] CI gate obrigatório**: o workflow `Publish npm package` passa a correr a **suíte completa de testes antes de qualquer publish** (`Run full test suite (gate)`) — qualquer falha bloqueia o publish (dispatch) e a promoção a `latest` (push da tag); sem `continue-on-error`. Novo `requirements-dev.txt` com o subconjunto empírico do `requirements.txt` que a suíte importa (sem os motores pesados que os testes não usam) + `pytest-xdist` (`-n auto`). Paridade local verificada: **1308 passados + 2 skipped, 3 execuções seguidas verdes** (~90-130 s cada com paralelização vs 3:31 serial). 0.9.92 tinha saído com CI vermelho em 3 testes por verificação apenas focal — fenda fechada.
- **[Item 2] Auditoria de leituras de tarefas**: todas as leituras de `tasks.json` em `hermes_ui/*` passam por `load_tasks()` (logs, MCP, notificações, thumbnails ×6, automation worker, stop/summary) — documentado por classificação; excepções sancionadas: `storage.py` (camada de armazenamento, import circular impossível) e a própria implementação de `load_tasks`. Novo **gate estrutural AST** (`test_task_read_migration_gate.py`) falha se algum módulo do pipeline voltar a ler `tasks.json` directamente.
- **[Item 2] REAL-BUG corrigido**: `migrate_task` só remove marcadores de falha (`error`, `failure_api`, …) com `for_requeue=True` (retry/remake) — as leituras/write-backs preservam-nos. Sem isto, a projecção de logs perdia o texto de erro e um write-back de thumbnails apagava a falha do disco. Coberto por 2 testes de regressão.
- **[Item 3] `SCHEMA_MIGRATIONS` encadeado (preparação estrutural)**: migrações registadas por versão de destino (`1: _migrate_v0_to_v1`, …) e corridas em cadeia (v0 → v1 → v2 → …) — quando o schema evoluir, tarefas várias versões atrás migram sozinhas. Idempotência e ordem de execução garantidas por teste; comportamento v0 → v1 preservado.
- **[Item 4] Botão "Reparar Fila"** (aba **Backlog Vídeos**): migra o schema de **todas** as tarefas persistidas de uma vez — até agora o disco só ficava migrado tarefa a tarefa via "Refazer vídeo"/"Retomar". Confirmação explícita em dois passos + relatório ("X migradas, Y já estavam no formato actual, Z descartadas"). Escrita in-place sob o lock de estado; preserva conteúdo criativo **e** marcadores de falha; idempotente. 4 testes novos.
- **[Item 5] Auditoria do Blueprint Oração (veredicto: substituição DELIBERADA)**: a troca da estrutura na 0.9.90 foi pedida explicitamente pelo utilizador (commit `81bb131`, ficheiro melhorado anexado); a versão anterior permanece no histórico git. Nota retroactiva com a trilha completa adicionada à secção 0.9.90. O teste actual (0.9.93) valida o formato novo de forma mais rica do que o antigo (rotation_mandate, regras de título, CTA, extensão).
- **[Item 6] Cobertura de interrupção do worker durante remake**: 3 testes novos (recovery marca `failed`+`worker_interrupted` e pausa a fila; artefactos parciais intactos; o Start retoma no estágio de vídeo sem recomeçar topic/roteiro). **Nenhum bug encontrado** — cobertura preventiva.
- **[Item 1] REAL-BUG capturado pelo gate na primeira execução (Ubuntu)**: `scripts/kill_tree.py` reportava falsos sobreviventes no Linux — um filho terminado fica **zombie** até o reap assíncrono e `psutil.is_running()` devolve `True` para zombies → exit 1 e limpeza repetida à toa pelo guard de instância única (invisível no Windows, onde não existem zombies). Corrigido: zombies contam como terminados (`_is_live_process`), com teste de regressão.
- **Suíte completa: 1309 passados + 2 skipped** (1295 da 0.9.93 + 14 novos), zero falhas. Nota: `test_concurrent_task_mutations_preserve_every_video` mostrou 1 flake em ~6 execuções paralelas sob carga local extrema (5/5 serial); monitorizar no CI.

## 0.9.93 — 2026-10-14
- **Nova camada de migração de schema no "Refazer vídeo"** (`hermes_ui/domain.py`): tarefas antigas (pausadas, standby, ou criadas em versões anteriores com `stage` legado como `"edit"`, `orchestration` em formato antigo e campos estruturais ausentes) passam a ser recriadas com sucesso pela versão actual — sem erro estrutural no `pipeline_worker`.
  - **`migrate_task`** normaliza APENAS campos estruturais (stage legado → válido, `orchestration` reconstruída com `completed_stages` filtrados aos estágios existentes, `schema_version=1`, defaults para `manual_start_required`/`topic_source`/`worker_interrupted`/`failed_stage`, remoção dos marcadores de falha obsoletos). **NUNCA toca** em roteiro, blueprint, prompt master, tags, thumbnail, voz, artefactos baixados ou `generation_settings` criativo. Idempotente; preserva campos desconhecidos (forward-compat); não muta o original.
  - **Integrada no `retry_task_with_current_settings`** (antes da mudança de estado) e no **`remake_video_task`** (o botão "Refazer vídeo" da UI) — ambos continuam a revalidar legendas, duração máxima do clip, fonte de materiais e restantes definições do canal via `_refresh_task_channel_video_settings`.
  - **`load_tasks()`**: leitura do pipeline com migração silenciosa em memória — aplicada nos três pontos de leitura do `pipeline_worker` (dispatch principal, `_task_by_id`, recuperação de tarefas paradas). A escrita em disco nunca é alterada; o registo só fica migrado quando um retry/remake o persiste.
  - **7 testes novos** (`tests/test_domain.py`): stage legado, preservação de conteúdo criativo, idempotência, retry com migração, revalidação de canal pós-migração, remake do botão "Refazer vídeo" com schema legado, e leitura em memória sem tocar no disco.
  - **Corrigidos os 3 testes do `test_azure_speech_chunking.py`** que a 0.9.92 partiu (monkeypatch de `subprocess.run` → `Popen` com o novo `_run_streamed`): a intenção original é preservada — redacção real de credenciais (MPT_LLM_API_KEY, Azure key/region) e detalhe de falha do uv continuam verificados pelo caminho novo.
  - **Corrigido o `test_oracao_blueprint_seed.py`**: validava ainda a estrutura legada (id/name/content markdown) do blueprint substituído na 0.9.90 e falhava desde então; passa a validar o JSON estruturado integral (rotation_mandate de 12 categorias, regras de título, CTA "This is Daniel", 7.000–9.000 caracteres).
  - **Suíte completa verde: 1295 passados + 2 skipped** (1288 base + 7 novos), zero falhas.

## 0.9.92 — 2026-10-13
- **Corrigida a falha de geração de vídeos com stall silencioso no arranque** (diagnóstico forense de 13/10: as tentativas Pexels→Pixabay morreram no idle watchdog com **zero output do helper** — nenhuma chamada às APIs de material chegou a ser feita; a atribuição "Pixabay API / pixabay_api_keys" era enganosa e apontava para as chaves, que estavam correctas):
  - **O helper de vídeo arranca directamente no interpretador do worker** (`sys.executable`, `pipeline_worker.py`) em vez do wrapper `uv run --no-project --python 3.11` — elimina a camada que engasgava intermitentemente na inicialização (resolução de interpretador/cache do uv) sem escrever uma única linha, levando o idle watchdog a matar a etapa aos 5 minutos com o diagnóstico vazio. O wrapper antigo fica apenas como fallback quando nenhum interpretador é localizável.
  - **Heartbeat nas fases silenciosas do helper** (`mpt_agent.py`): a verificação de dependências (`uv sync --frozen` e `uv run --with moviepy`), a síntese Azure segmentada e a geração final emitem agora linhas periódicas ("still running (Xs)") e retransmitem o output do subprocesso linha a linha (segredos removidos) — o idle watchdog (5 min nas rotas pexels/pixabay) deixa de matar etapas vivas e o orçamento de 15 minutos do helper passa a ser respeitado. Sonda `--help` do cli.py registada com linha de rastreio própria.
  - **Atribuição honesta da falha**: quando o idle watchdog mata a etapa sem UMA linha de output e sem log do motor, a falha passa a ser atribuída a **"Runtime MoneyPrinterTurbo"** (falha de arranque do runtime) em vez de "Pixabay API / pixabay_api_keys" — a mensagem final explicita que a API de material nunca foi contactada.
  - Nota operacional: o stall de 13/10 (00:12 e 15:30) desapareceu após reinício completo da app (o launcher antigo acumulava 36,6 h de sessão); o pipeline ficou saudável desde as 21:31.

## 0.9.91 — 2026-10-13 (registo retroactivo)
- **SIGINT absorvido silenciosamente**: o launcher deixou de imprimir duas linhas de aviso ("SIGINT ignorado no Windows…") a cada CTRL_C_EVENT espúrio absorvido — o evento continua registado em `launcher_diagnostics.jsonl`, apenas sem spam no terminal (`scripts/cli.mjs`).

## 0.9.90 — 2026-10-12
- **Substituído o Blueprint Oração (`seed/blueprints/BlueprintOração.json`) pela versão corrigida e melhorada do utilizador**: o ficheiro passa da estrutura legada (invólucro `id`/`name`/`metadata` + `content` em markdown embutido, ~21 KB) para o **JSON estruturado integral** (~40 KB, 14 secções: metadata, cross_sample_system, rotation_mandate, title_analysis, script_architecture, micro_writing_mechanics, psychological_and_persuasive_mechanisms, worldview_embedded_in_scripts, replication_logic, sample_specific_context, generation_instructions_for_another_model, cta_pattern, corrected_script_example_structure, applied_corrections_summary) — o mesmo formato dos FINANCE 0.9.80.
- **Nota de auditoria (0.9.94, item 5)**: substituição **deliberada** — pedida explicitamente pelo utilizador com o ficheiro melhorado anexado ("Substitua o blueprint com este mesmo nome em seed, por esta versão corrigida e melhorada"). A versão anterior (markdown "VERSÃO MELHORADA", commit `520b0a5`, 18/09) permanece recuperável no histórico git. O `test_oracao_blueprint_seed.py` ficou a validar a estrutura antiga por decisão do utilizador nessa sessão (revertido o ajuste inicial) e por isso esteve vermelho da 0.9.90 até à 0.9.93, quando passou a validar o formato novo integralmente.
- **Novo `rotation_mandate` com 12 categorias** (identity_in_christ, peace_trust, strength_endurance, protection_warfare, provision_breakthrough, healing_wholeness, purpose_direction, family_relationships, gratitude_praise, spiritual_growth, morning_consecration, nighttime_rest) com **tecto rígido no nighttime_rest** (no máximo 1 em cada 6 vídeos), regras de selecção (nunca duas seguidas na mesma categoria) e `category_scripture_map` por categoria — corrige o modo de falha em que o modelo caía sempre em orações nocturnas/sono/ansiedade ("A Nighttime Prayer for Overthinking", "Bedtime Prayer…").
- **Regras de título reforçadas**: o título é verdade espiritual/promessa bíblica/identidade em Cristo; proibidos os padrões "A [type] Prayer for [problema]", inícios "Why/How/What/The Reason/Understanding", hora do dia (bedtime/nighttime/morning), sintomas psicológicos e cenários; validação obrigatória com 7 critérios antes de fixar qualquer título.
- **Abertura temática** (declaração sobre a luta humana — nunca oração directa a Deus como primeira frase), **CTA obrigatório** com assinatura "This is Daniel" e o requisito de extensão **estritamente 7.000–9.000 caracteres** mantidos.
- O seed é copiado para `storage/blueprints/importados/` apenas quando o ficheiro ainda não existe; instalações existentes mantêm a cópia local até substituição manual.

## 0.9.89 — 2026-10-12 (registo retroactivo)
- **CREATE_NO_WINDOW estendido a todos os 26 subprocessos de background restantes** — a 0.9.88 cobria o pipeline MPT; esta passa cobre os que faltavam: `hermes_ui/browser_manager.py`, `canva_mcp_client.py`, `cuts.py` (ffmpeg/ffprobe), `media_generation.py`, `metadata_cleaner.py`, `python_editor.py`, `remotion_provider.py`, `social_auto_upload_backend.py` e `integrations/bilibili_upload.py`, `instagram_public.py`, `music_uploads.py`, `youtube_session_manager.py` (+ `tests/test_metadata_cleaner.py` actualizado). Zero janelas CMD ao usar cortes, uploads e geração de média.

## 0.9.88 — 2026-10-11
- **Corrigidas as várias janelas CMD**: `DETACHED_PROCESS` removido por completo de todo o código; substituído por `CREATE_NO_WINDOW` em todos os subprocessos de background (`pipeline_worker.py` Popen do mpt_agent, `mpt_agent.py` uv sync / cli.py --help / render cli.py / Azure TTS chunked, `remotion_provider.py` render Node.js). `CREATE_NO_WINDOW` suprime a janela sem desanexar da consola — output continua via pipes. Zero janelas CMD ao retomar tarefas pausadas.
- Corrigidos 43 caracteres corrompidos (double-encoding UTF-8) no `mpt_agent.py` causados por um `Set-Content` PowerShell anterior.
- Novo teste `tests/test_no_detached_process.py` (4 testes) garante que `DETACHED_PROCESS` nunca volta e que `CREATE_NO_WINDOW` está presente em todos os spawns de background.
- SIGINT absorvido no Windows (0.9.86) continua intacto. Linux/macOS inalterado.
- **1288 testes verdes** (1284 + 4 novos).

## 0.9.87 — 2026-10-11
- **Corrigidas as várias janelas CMD ao retomar tarefas**: o `DETACHED_PROCESS` (0.9.82, restaurado por engano via `git checkout`) fazia cada `uv`/`ffmpeg` abrir a sua própria janela CMD visível quando o pipeline retomava uma tarefa pausada. Substituído por **`CREATE_NO_WINDOW`** — suprime a janela sem desanexar da consola; o output continua a chegar via pipes. Aplicado ao `Popen` do mpt_agent no `pipeline_worker.py` e a todos os subprocessos do `mpt_agent.py` (`uv sync`, `cli.py --help`, render `cli.py`).
- 1284 testes verdes.

## 0.9.86 — 2026-10-11
- **Corrigido o desligamento espúrio por SIGINT no Windows**: o Windows 11 entrega o MESMO sinal SIGINT para Ctrl+C real e para `CTRL_C_EVENT` espúrio gerado quando um navegador é aberto ou um subprocesso `.cmd` é criado em thread secundária (comportamento documentado em Hermes Agent e DeepTutor). Não é possível distingui-los — o Thunderbolt **absorve SIGINT incondicionalmente no Windows** e oferece **quatro formas de encerrar**: Ctrl+Break, arquivo `.thunderbolt.stop`, fechar a janela do terminal, ou Gerenciador de Tarefas. No Linux/macOS, Ctrl+C continua funcionando normalmente.
- 1284 testes verdes.

## 0.9.85 — 2026-10-11
- **Ctrl+C espúrios resolvidos com verificação de janela em primeiro plano**: quando SIGINT chega ao launcher, ele verifica qual processo tem a janela em primeiro plano (`get_foreground.py`, <500ms). Se for um **terminal** (MobaXterm, cmd, PowerShell, Windows Terminal) → Ctrl+C legítimo → encerra imediatamente. Se for **outra aplicação** (Chrome, WhatsApp, etc.) → espúrio do MobaXterm → ignora com log. Baseado na evidência forense: os 5 Ctrl+C espúrios capturados tinham SEMPRE `foreground: chrome.exe/WhatsApp` e `input_records: 0`. Ctrl+C no terminal funciona normalmente (padrão CLI), Ctrl+C espúrio do MobaXterm nunca mais mata a app. Janela separada removida (0.9.84). 1280 testes verdes.

## 0.9.84 — 2026-10-11
- **REVERTIDO o relançamento em janela separada** (0.9.83) — o launcher corre directamente no terminal onde foi chamado, como sempre correu. Ctrl+C único encerra (padrão CLI), filtro de eco de 300ms absorve o duplicado do MobaXterm.

## 0.9.83 — 2026-10-11
- **RESOLUÇÃO DEFINITIVA dos Ctrl+C espúrios**: o launcher desanexa-se COMPLETAMENTE da consola do MobaXterm/PowerShell e auto-relança-se numa **janela de terminal própria e isolada** (visível na barra de tarefas como "Thunderbolt"). A evidência forense de 5 eventos capturados é conclusiva: `input_records: 0` em TODOS (nunca houve tecla), `foreground: chrome.exe/WhatsApp` em TODOS (o utilizador nunca estava no terminal). O CTRL_C_EVENT espúrio é gerado pelo MobaXterm/PowerShell na consola partilhada — fora do controlo do Thunderbolt — e a única solução robusta é o launcher viver numa consola própria.
- **Como funciona**: `npx.cmd @danhachuel/thunderbolt` arranca → o launcher relança-se numa nova janela (com a sua própria consola) → o processo original sai e o prompt volta. A UI continua em **http://localhost:3030**. Para encerrar: **Ctrl+C na janela "Thunderbolt"** ou fechá-la — SIGINT/SIGHUP chegam ao launcher isolado e o shutdown corre normalmente.
- **Porque as versões anteriores falharam**: 0.9.71/0.9.72 ignoravam Ctrl+C (gambiarra contra padrão); 0.9.82 isolava apenas a árvore MPT (DETACHED_PROCESS no mpt_agent), mas o launcher, workers e Streamlit continuavam na consola partilhada — e o CTRL_C_EVENT do MobaXterm atingia o launcher diretamente. 0.9.83 desanexa o LAUNCHER inteiro.
- 1280 testes verdes.

## 0.9.82 — 2026-10-10
- **Corrigida a CAUSA RAIZ dos Ctrl+C espúrios**: a árvore MPT (`uv` → Python `cli.py` → ffmpeg) partilhava a MESMA consola que o launcher Node.js. Quando um subprocesso dessa árvore terminava, emitia um `CTRL_C_EVENT` à consola partilhada — atingindo o launcher e encerrando a aplicação "sozinha". Evidência forense: **3 timestamps ao segundo exacto** entre o fecho de logs MPT e `launcher_exiting ctrl+c` (06/10 23:25:28↔29, 08/10 04:48:47, 08/10 18:42:25↔25).
- **A árvore MPT corre agora numa consola SEPARADA** (`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` no Popen do pipeline_worker e em todos os subprocessos do mpt_agent). Qualquer sinal gerado internamente (uv, ffmpeg, Python) fica **isolado na sua própria consola** e nunca chega ao launcher. O output continua a chegar via PIPE — nunca dependeu da consola.
- **Ctrl+C único encerra (padrão CLI)**, mantido da 0.9.81. O eco de <300 ms é absorvido.
- 1280 testes verdes.

## 0.9.81 — 2026-10-10
- **REVERTIDA a gambiarra do "Ctrl+C duplo para encerrar"** — contra padrão de software e contra o utilizador. Um **Ctrl+C único encerra a aplicação**, como qualquer CLI. O eco de <300 ms da mesma tecla (o MobaXterm/PowerShell gera 2 SIGINTs por um Ctrl+C, com ~27 ms de intervalo) é absorvido silenciosamente — o primeiro evento encerra, o segundo não faz nada.
- A forense de Ctrl+C (`scripts/ctrl_c_forensics.py`, 0.9.73) **continua activa**: no próximo Ctrl+C (encerramento ou espúrio), o launcher captura os registos de input da consola (teclado vs. software), a janela em primeiro plano e os processos anexados — os dados ficam em `launcher_diagnostics.jsonl` com o evento `ctrl_c_forensics` para identificar a causa raiz dos Ctrl+C espúrios que por vezes surgem sem teclado envolvido.

## 0.9.80 — 2026-10-10
- **Substituídos os 16 blueprints FINANCE pelas versões melhoradas do utilizador** (`seed/blueprints/`): os 15 países (AUSTRALIA, BRAZIL, CANADA, FRANCE, GERMANY, IRELAND, ISRAEL, ITALY, JAPAN, MEXICO, POLONY, SOUTH AFRICA, SOUTH COREA, SPAIN, UK) passam de `.md` para **`.json`** com a nova estrutura (metadata, cross_sample_system, rotation_mandate, title_analysis, script_architecture, micro_writing_mechanics, …) e o `FINANCE USA.json` é substituído pela versão melhorada (17 KB → 25,7 KB). O `FINANCE ISRAEL.json` usa a cópia corrigida do utilizador (a aspa do acrónico hebraico תמ״א devidamente escapada — o carácter é preservado na íntegra).
- Os 15 `.md` antigos saem do seed e do storage do utilizador (as cópias antigas foram removidas da raiz do storage); os 16 `.json` são semeados para `storage/blueprints/importados/` como qualquer outro blueprint e aparecem em **Blueprints > Blueprints Youtube** na mesma tabela.
- O pacote do Google Drive incluía ficheiros de apoio (imagens, PDF, LISTA.txt) que **não** entram no seed — só os 16 blueprints.
- Testes: contagens do seed actualizadas (15 FINANCE .json + 16 restantes = 34/33 em importados); `test_finance_content_seeds_are_separate_from_thumbnail_seed` passa a verificar os 16 `.json` — **1281 testes verdes**.

## 0.9.79 — 2026-10-10
- **Um blueprint é um blueprint** (segundo a especificação "Corrigir: os 5 Remotion são blueprints, ponto"): a separação "personalidade vs formato" da 0.9.76/0.9.77 foi **removida por completo**. Não existem "blueprints de personalidade", "formatos Remotion", `format_id`, `packages/remotion/schemas/` nem dois dropdowns — existe **um tipo** de blueprint.
- **Os 5 Remotion voltaram para `seed/blueprints/`** com os nomes originais (Blueprint Remotion - Quiz Videos, Social Media Reels, Top 10 Ranking Videos, Would You Rather, Inspirational Long-Form Videos) e o conteúdo actual (`format_id` removido). São copiados para `storage/blueprints/importados/` no arranque como todos os outros e **aparecem em Blueprints > Blueprints Youtube na mesma tabela** — sem secção separada.
- **Loader simplificado a uma lista**: `list_blueprints()` devolve TODOS os blueprints (storage + seed como fallback), sem filtro, sem distinção; `load_blueprint(id)` carrega por id; `build_system_prompt(blueprint)` usa apenas os campos do próprio blueprint (constraints, output_schema, reference_example, difficulty_calibration) — **um blueprint, um prompt**. Removidas `list_personality_blueprints`, `list_remotion_formats`, `load_remotion_format`, `build_remotion_system_prompt` e toda a migração que apagava os Remotion do storage.
- **UI com UM dropdown**: no modo Remotion existe **um único** dropdown de Blueprint com a lista completa (MILITAR, FINANCE USA, os 5 Remotion, todos); o segundo dropdown "Formato Remotion" desapareceu. Placeholders dinâmicos do blueprint escolhido ({{topic}} liga ao Video Subject, {{language}} ao Script Language, {{difficulty}} com default Average no Quiz).
- **Pipeline decide pelo JSON**: quando o blueprint escolhido tem `composition_id`, o LLM gera o JSON do seu `output_schema` (validação Pydantic indexada por `composition_id`, com 1 retry), os assets são gerados e o Remotion renderiza com a composição do próprio blueprint; **sem `composition_id` → comportamento normal** (roteiro + narração). Os modos `pexels`, `text_to_images`, `web_images`, `full_ia` ficam intocados; `LongFormVideo`/`ShortVideo` intactas.
- `hermes_ui/schemas/` e `hermes_ui/blueprint_assets.py` reindexados por `composition_id` (Quiz, SocialReel, Top10, WouldYouRather, InspirationalVideo); `docs/blueprints.md` reescrito para a regra "um só conceito".
- Testes: os 4 pedidos pela spec (`test_list_blueprints_includes_all_five_remotion`, `test_blueprints_youtube_tab_shows_all`, `test_remotion_ui_has_single_dropdown`, `test_pipeline_uses_blueprint_with_composition_id`) + reescrita dos testes da separação para a lista única — **1280 testes verdes**.

## 0.9.78 — 2026-10-10
- **`{{difficulty}}` reintroduzido — apenas no formato `quiz`** (segundo a especificação "Reintroduzir {{difficulty}} no formato Quiz"): a 0.9.77 tinha removido o placeholder de todos os formatos; o quiz beneficia de um parâmetro de dificuldade para calibrar as perguntas. Os outros 4 formatos (`would_you_rather`, `social_reel`, `top_10`, `inspirational`) ficam **exactamente** como na 0.9.77 — sem `{{difficulty}}`.
- **Schema do quiz** (`packages/remotion/schemas/quiz.schema.json`): nova constraint `"topic and questions must match the difficulty level specified in {{difficulty}}"`, bloco **`default_values.difficulty = "Average"`** (o placeholder é opcional e resolve-se com Average quando o utilizador não escolhe) e a secção de **`difficulty_calibration`** com os três níveis (Easy/Average/Hard) — guia para o LLM, não executada pelo Remotion. O modelo Pydantic do quiz não muda estruturalmente (difficulty é um placeholder do prompt, não do output; nota adicionada em `hermes_ui/schemas/quiz_videos.py`).
- **Pipeline** (`hermes_ui/pipeline_worker.py`, apenas na resolução de placeholders do modo Remotion): quando o formato é `quiz`, o `{{difficulty}}` chega ao LLM com o valor escolhido pelo utilizador (`Easy`, `Average` ou `Hard`); sem escolha, usa o `default_values.difficulty` do próprio formato (Average). Nos formatos sem o placeholder, nada é injectado.
- **UI** (`app/main.py`, apenas no formulário dinâmico do modo Remotion): o dropdown de dificuldade passa a aparecer **só quando o formato declara `{{difficulty}}`** (quiz), com `Average` pré-seleccionado e as opções derivadas do `difficulty_calibration` do formato. Nos outros formatos, nada muda.
- Testes novos (`tests/test_quiz_difficulty.py`): placeholder nas constraints, default Average, pipeline injecta difficulty só no quiz (escolhido e default), UI mostra o dropdown apenas para o quiz, e os outros 4 formatos não ganham `{{difficulty}}`. **1284 testes verdes** (1279 anteriores + 5 novos).

## 0.9.77 — 2026-10-09
- **Correcção da arquitectura do modo Remotion** (segundo a especificação "Corrigir a arquitetura do modo Remotion"): os 5 ficheiros que a 0.9.75 colocou em `seed/blueprints/` são **formatos técnicos de renderização**, não blueprints de personalidade de canal — e foram tratados indevidamente como personalidades. Esta versão corrige a confusão **apenas no modo Remotion**; `pexels`, `text_to_images`, `web_images` e `full_ia` ficam intocados.
- **Os 5 formatos mudaram de casa**: `seed/blueprints/` volta a conter apenas blueprints de personalidade (MILITAR, FINANCE USA, …) como antes da 0.9.75; os formatos vivem agora em **`packages/remotion/schemas/*.schema.json`** (`quiz`, `social_reel`, `top_10`, `would_you_rather`, `inspirational`) no formato de schema técnico com as versões corrigidas do utilizador — `format_id`, `constraints` estruturais, `output_schema`, `reference_example` (estrutural) e `remotion_mapping`; sem `system_instructions`/`style_guide`/`generation_instructions` (essses campos pertencem à personalidade). Regra `{{difficulty}}` removida dos formatos corrigidos; `{{language}}` continua a ser resolvido em runtime.
- **Loader separado** (`hermes_ui/blueprint_loader.py`): `list_personality_blueprints()`/`load_personality_blueprint()` para personalidades (MILITAR, FINANCE USA… — ignora formatos) e `list_remotion_formats()`/`load_remotion_format()` para os schemas técnicos; `build_remotion_system_prompt()` concatena a personalidade do canal com os constraints/output_schema do formato — nada mais.
- **Pipeline Remotion = personalidade + formato** (`hermes_ui/pipeline_worker.py`): carrega o blueprint de personalidade (dropdown da UI, default do canal ou `task.blueprint_id`), carrega o formato, combina-os no system prompt, valida com o **schema Pydantic do formato** (chaves renomeadas para os novos format_ids, com 1 retry), gera os assets e renderiza com a **composição do formato**. Voz, provider de imagem e idioma continuam a vir do canal/Configurações, como nos outros modos.
- **UI com dois dropdowns** (`app/main.py`, apenas na secção Remotion): **Blueprint (personalidade do canal)** — MILITAR, FINANCE USA, etc. — e **Formato Remotion** — quiz, social_reel, top_10, would_you_rather, inspirational — mais os placeholders dinâmicos do formato. Um canal como "Canal Militar" consegue finalmente usar um formato Remotion.
- **Migração**: no arranque, formatos que tenham ficado em `storage/blueprints/` (raiz ou `importados/`, novo ou antigo estilo) são apagados com log (`migrate_remotion_formats_out_of_storage`); as cópias do repo e do storage do utilizador foram limpas. Os canais existentes não são migrados nem alterados.
- Testes da nova arquitectura: personalidades excluem formatos, 5 formatos listados, pipeline combina personalidade+formato, validação usa o schema do formato — **1279 testes verdes**.
- Nota de multi-sessão (regra 7): a 0.9.76 foi publicada pela sessão paralela (fix Composio); esta sessão renumerou para o patch seguinte livre.

## 0.9.76 — 2026-10-09
- Diagnóstico definitivo da quota Composio (testado directamente, com evidência): o projecto Google Cloud usado pela plataforma é **PARTILHADO por todos os utilizadores do Composio** — a quota de uploads (~6/dia) esgotou ontem (429) e hoje, logo após a reposição Pacific, a quota **geral** do YouTube Data API (10.000 unidades/dia) já está igualmente esgotada (403 `quotaExceeded` na descoberta de canais e `RESOURCE_EXHAUSTED` no upload multipart com o par persistido do canal). Não é a quota do canal nem do Thunderbolt — é a infraestrutura do Composio, fora do alcance de qualquer correcção local; a verificação final do processamento multipart fica pendente de uma janela de quota do projecto partilhado deles.
- A classificação de erros do Composio passa a reconhecer **todas** as variantes de quota (403 `quotaExceeded`, `RESOURCE_EXHAUSTED`, "exceeded your quota", 429) com mensagem accionável: explica o projecto partilhado, a reposição Pacific, a verificação do YouTube Studio por vídeos órfãos e recomenda o modo **API Youtube** (credenciais próprias do canal, quota individual) — o pipeline já cai automaticamente para a rota oficial quando o Composio falha.
- Nota de multi-sessão (regra 7): detectada colisão com a sessão dos Remotion Blueprints (publicada até 0.9.75); esta sessão renumerou para o patch seguinte livre antes de publicar.

## 0.9.75 — 2026-10-09
- **Blueprints Remotion executáveis end-to-end** — o ciclo fechado segundo a especificação "Implementação dos Blueprints Remotion no Thunderbolt": o utilizador escolhe **Remotion** como Fonte do Vídeo, vê os **5 blueprints** no dropdown (Inspirational Long-Form, Quiz, Social Media Reels, Top 10, Would You Rather), preenche topic/language/difficulty e a tarefa corre **LLM → JSON validado → assets → Remotion → MP4** sem depender de Airtable, Google Sheets ou JSON2Video.
- **Fundação mergeada do ramo `codex/remotion-blueprints-0.9.69`** (nunca publicado): 5 blueprints em `seed/blueprints/`, `hermes_ui/blueprint_loader.py` (load/validate/placeholders/system prompt), `hermes_ui/blueprint_assets.py` (imagens paralelas do pool + TTS em série + injeção de imageUrl/audioUrl), `hermes_ui/schemas/` (5 modelos Pydantic + registo SCHEMAS), 5 composições Remotion + componentes partilhados, guia `docs/blueprints.md` e testes — conteúdo idêntico ao ramo, agora em `master`.
- **`Root.tsx` com as 7 composições registadas** (Tarefa A): `InspirationalVideo`, `Quiz`, `SocialReel`, `Top10` e `WouldYouRather` mantêm `LongFormVideo`/`ShortVideo` intactos. O `calculateMetadata` espelha exactamente o layout de Sequences de cada componente (intro/outro fixos de 90 frames incluídos) — a duração nunca corta o áudio nem acrescenta frames mortos; `utils.ts` adiciona `estimateAudioFrames`.
- **Pipeline `_run_remotion_blueprint`** (`hermes_ui/pipeline_worker.py`, Tarefa C): detecta a rota `remotion` + `blueprint_id` e executa load → placeholders → LLM (`_chat_json` do pool com failover) → **validação Pydantic com 1 retry** (erro anexado ao prompt) → assets (imagens do pool em paralelo com 4 workers + TTS da cadeia local em série, cancelamento via estado `blocked`) → `run_remotion_render` na composição do blueprint. O JSON validado fica persistido como script/documento da tarefa e o MP4 entra nos artefactos — as etapas padrão de título/thumbnail/upload correm sem alterações e as restantes 4 pipelines (`pexels`, `text_to_images`, `web_images`, `full_ia`) ficam intocadas.
- **UI de seleção** (`app/main.py`, Tarefa D): com Fonte "Remotion", o formulário mostra o seletor de blueprints (formato `blueprint_id — domain`), a legenda de versão/domínio/composição/dimensões/fps, os **placeholders dinâmicos** ({{topic}} liga ao Video Subject, {{language}} ao Script Language, {{difficulty}} com dropdown Easy/Average/Hard, qualquer outro placeholder ganha campo próprio) e o preview colapsável com must_include/must_avoid/reference_example. Os valores viajam em `generation_settings.blueprint_id/blueprint_values` — sem alterar o domínio nem as restantes fontes.
- **Loader procura os blueprints em `storage/blueprints/` e `importados/`** com filtro de formato (só ficheiros com `blueprint_id`+`composition_id`): os blueprints de canal clássicos continuam na lista de Blueprints sem poluir o seletor Remotion; `load_blueprint` tem fallback ao seed do pacote. O install (cli.mjs) continua a copiar os seeds para `importados/` na primeira arrancada.
- **Testes (Tarefa E)**: `tests/test_blueprint_pipeline.py` (happy-path end-to-end com providers/render mockados, retry de validação, Remotion indisponível, cancelamento, tópico obrigatório), `tests/test_blueprint_ui.py` (7 composições registadas + metadata fiel ao layout + componentes existem + seletor na UI + 5 seeds listados + exclusão dos blueprints clássicos), mais os 23 do loader/assets da fundação. Contagens do seed actualizadas (14→19) e contratos novos do launcher/workers reflectidos — **1275 testes verdes**.
- Restrições respeitadas: composições `LongFormVideo`/`ShortVideo` intocadas; guard de instância única sem alterações; bundle continua em `storage/remotion-cache/`; sem paths de credenciais em logs; arquitectura pronta para `@remotion/lambda`.

## 0.9.74 — 2026-10-09
- Corrigida a aba **Blueprints > Blueprints Youtube** que expunha ficheiros de controlo e artefactos de outras abas como se fossem Blueprints seleccionáveis: o `rglob("*.json")` mostrava o registo **`thumbnail_blueprint_pairs`**, o blueprint demo **"Canal Hermes Demo"** (`demo-content-hermes.json`, resíduo de versões antigas — já não existe no seed) e ficheiros das pastas `thumbnails/`, `brandings/`, `music/` e `conteudo/`. O catálogo (`list_blueprint_files`) passa a filtrar control files e pastas de outras abas (`_is_selectable_blueprint`) — a correcção aplica-se a todos os selectores (canais, pares, MCP) porque usam o mesmo catálogo.
- **Removido o seletor de pastas** da importação ("Pasta": importados/canais/nichos) — os blueprints importados vão directamente para a raiz da biblioteca, sem pastas de separação (`app/main.py` e `main.py` legado).
- **Removido o separador "Blueprints de conteúdo"** (introduzido sem autorização na 0.9.6x junto com a pasta `conteudo/`): a aba passa a ter **uma única lista `Blueprints (N)`** com os JSON e os .md de conteúdo juntos, uma única pesquisa, sem divisões.
- **"FINANCE USA_Thumbnail_Blueprint" eliminado**: era resíduo de uma versão antiga que guardava Thumbnail Blueprints na raiz da biblioteca (o fluxo actual escreve sempre em `thumbnails/`). O Thumbnail Blueprint de finanças é **um só — `FINANCE_Thumbnail_Blueprint` — para TODOS os blueprints de finanças**; o registo de pares já associava os 16 FINANCE ao geral (confirmado, sem alterações). Ficheiros `*_Thumbnail_Blueprint` ficam de fora da lista de Blueprints Youtube e pertencem apenas a **Blueprints > Thumbnails Blueprints**.
- **Limpeza do storage do utilizador** (executada na máquina): removidos `FINANCE USA_Thumbnail_Blueprint.md` da raiz, os 15 `FINANCE *.md` duplicados dentro de `thumbnails/` (eram blueprints de conteúdo da disposição antiga, não thumbnails), a pasta não autorizada `conteudo/`, `importados/demo-content-hermes.json` e a cópia de `thumbnail_blueprint_pairs.json` em `importados/`. O `thumbnail_blueprint_pairs.json` da raiz mantém-se — é o registo de associações em uso.
- Removido do repositório o `storage/blueprints/importados/demo-content-hermes.json` (dados de desenvolvimento rastreados).
- Confirmado o seed sem alterações: 16 blueprints FINANCE (.md) + `FINANCE USA.json` + 12 JSON de canais + 17 Thumbnail Blueprints + music/ continuam em `seed/blueprints`.
- Testes: catálogo sem control files/demo/pastas de outras abas (JSON e MCP); .md de conteúdo excluem `*_Thumbnail_Blueprint`; UI sem seletor de pastas nem separador (verificação de fonte).

## 0.9.73 — 2026-10-09
- Corrigido o **arranque bloqueado por locks obsoletos dos workers** (reproduzido em 09/10 13:03): o worker de automação recusava arrancar com *"Já existe um worker de automação activo (PID 7292)"* — **com o PID 7292 confirmadamente inexistente**. O `_pid_alive` usava `ctypes.windll` + `GetLastError()`: o windll não preserva o last-error da chamada, o valor vinha obsoleto (frequentemente 5 = ACCESS_DENIED de chamadas anteriores) e devolvia "vivo" para PIDs mortos. A correção usa **psutil com verificação de identidade por cmdline**: um PID só bloqueia o arranque quando é realmente um worker do Thunderbolt (`hermes_ui.automation_worker` / `hermes_ui.pipeline_worker`) — o que protege também contra o **reuso do número de PID** por processos alheios. Aplicado ao lock do pipeline worker e à recuperação de tarefas interrompidas (o mesmo falso positivo aí bloqueava a auto-pausa da fila).
- **Fim do loop infinito de respawn do worker de automação** (`scripts/cli.mjs`): depois das 5 falhas consecutivas, o monitor de 2 s continuava a re-tentar o worker para sempre (sem o travão que o worker do pipeline já tinha) — com o lock obsoleto, o terminal enchia de *"falhou 5 vezes seguidas"* num ciclo sem fim. Passa a existir `automationAutoRestartDisabled`, desactivado após 5 falhas e reactivado após 60 s de execução estável, com o mesmo padrão do pipeline.
- **Forense das rajadas de Ctrl+C** (`scripts/ctrl_c_forensics.py`, novo): quando o launcher ignora um Ctrl+C, fotografa a consola no momento exacto — **registos de input** (um KEY_EVENT Ctrl=C prova entrega por teclado/terminal; a ausência aponta para `GenerateConsoleCtrlEvent` chamado por software), **janela em primeiro plano** (o utilizador estava no terminal?) e **processos anexados à consola** (todos os candidatos a emissor). Corre no máximo uma vez por rajada (10 s) e é registado como `ctrl_c_forensics` no `launcher_diagnostics.jsonl` — a próxima rajada identifica a origem de forma definitiva.
- Contexto da investigação em curso: as rajadas foram confirmadas como **um único evento entregue por dois caminhos** na camada pty do MobaXterm (gaps medidos de 3 ms e 27 ms; winpty/MoTTY entregam o ^C por `GenerateConsoleCtrlEvent` e por registo de input). A blindagem 0.9.71/0.9.72 já faz a app sobreviver (evidência 13:04-13:05: burst filtrado, launcher órfão activo, interface utilizável); a origem externa do primeiro evento fica identificada pela forense desta versão.
- Testes: `tests/test_worker_lock_recovery.py` (novo) reproduz os três cenários do lock — PID morto recuperado, PID vivo alheio reusado recuperado e worker verdadeiro recusado — para os dois workers; imunidade actualizada com forense e travão de respawn.

## 0.9.72 — 2026-10-09
- Corrigida a falha restante do ciclo **"a app encerra-se sozinha"**, agora com a prova completa do mecanismo: a telemetria da 0.9.71 registou **dois SIGINT separados por 27 milissegundos** (`ctrl_c_ignored` 04:29:09.510Z → `launcher_exiting ctrl+c` 04:29:09.537Z) — uma **rajada** de Ctrl+C gerada pela fonte externa, impossível de ser teclado humano. A janela de confirmação "Ctrl+C duplo em 3 s" da 0.9.71 interpretava o eco da rajada como segunda pressão e encerrava na mesma. Nessa altura o worker renderizava a tarefa `video_a19eca2aa9` em plena saúde (heartbeat 6 s antes; a imunidade dos workers da 0.9.71 funcionou — quem matou a stack foi o encerramento do próprio launcher).
- **Filtro de rajada no launcher (`scripts/cli.mjs`)**: um segundo Ctrl+C a menos de **300 ms** do anterior é eco da mesma interrupção externa — registado (`ctrl_c_burst_ignored`) e **ignorado sem contar como confirmação**. Encerrar continua a exigir dois Ctrl+C com **0,3-3 s de intervalo** (janela humana impossível de confundir com o eco de 27 ms).
- **Aviso de launcher órfão**: a rajada mata a cadeia npx/cmd (que não ignora Ctrl+C) e o terminal devolve o prompt enquanto o launcher sobrevive — a app continua a correr em segundo plano. O launcher detecta a morte do processo pai (verificação de 2 em 2 s no `monitorWorkers`), regista `launcher_orphaned` e imprime que a interface continua activa em `http://localhost:3030/` e como encerrar de facto.
- Telemetria acumulada para identificar a fonte: cada evento isolado (`ctrl_c_ignored`), cada eco de rajada (`ctrl_c_burst_ignored` com `gap_ms`) e cada órfão (`launcher_orphaned`) ficam com timestamp em `launcher_diagnostics.jsonl` — o padrão de rajadas (~27 ms) aponta para duplicação na camada do terminal (PowerShell do MobaXterm/pty), confirmável pelos registos futuros.
- Testes actualizados para o novo contrato (janelas de rajada/confirmização, eco ignorado, aviso de órfão no monitor).

## 0.9.71 — 2026-10-09
- Corrigido o ciclo **"a app encerra-se sozinha"** (reproduzido e diagnosticado em 08-09/10): um **CTRL_C_EVENT espúrio atingia toda a consola partilhada** — cadeia npx → launcher node → workers → uv/MPT/ffmpeg — sem ninguém tocar no teclado. Evidência: launcher_exiting com reason `ctrl+c` em todas as sessões (11 registos entre 05-09/10), o worker de vídeo em auto-pausa com heartbeat 1 s antes da saída e o log do MPT a terminar em `KeyboardInterrupt` a meio da escrita dos frames (`self.proc.stdin.write(img_array.tobytes())`) — a tarefa `video_7c85d5e04d` foi interrompida assim duas vezes. O Event Log do Windows não regista qualquer crash/restart nessas alturas, confirmando origem externa na consola.
- **Launcher (`scripts/cli.mjs`)**: um Ctrl+C isolado passa a ser **registado (`ctrl_c_ignored`) e ignorado** — a app continua a correr; para encerrar é preciso **Ctrl+C duplo em 3 s** (como nos dev servers). O **Ctrl+Break** continua a encerrar imediatamente e o **fecho da janela do terminal (SIGHUP)** agora faz shutdown gracioso com motivo `console_closed` em vez de morte abrupta — acaba o ciclo de workers órfãos a disputar os locks do storage.
- **Workers imunes** (`hermes_ui/automation_worker.py`, `hermes_ui/pipeline_worker.py`): `SetConsoleCtrlHandler(None, TRUE)` no arranque de cada worker ignora o CTRL_C_EVENT da consola — um Ctrl+C espúrio já não interrompe execuções nem pausa a fila. O encerramento legítimo continua a funcionar porque o launcher (`worker.kill()`) e o guard de instância única (`kill_tree.py`/psutil) usam `TerminateProcess`, que não é um evento de consola.
- **Árvore MPT isolada** (`hermes_ui/pipeline_worker.py`, `seed/skills/mpt_agent.py`, `pipeline_worker.py` legado): o helper de vídeo e todos os subprocessos do mpt_agent (uv sync, `cli.py --help` de detecção, o próprio `cli.py` do MPT) passam a arrancar com `CREATE_NEW_PROCESS_GROUP` no Windows — um CTRL_C_EVENT do grupo 0 da consola já não mata o MoneyPrinterTurbo/ffmpeg a meio da renderização; o mpt_agent também ignora Ctrl+C directamente.
- O Streamlit já ignorava SIGINT (`scripts/streamlit_bootstrap.py`) e fica sem alterações; a partir desta versão **toda a stack é imune** a um Ctrl+C espúdio, e cada evento ignorado fica registado em `launcher_diagnostics.jsonl` com timestamp para correlação futura.
- Diagnóstico documentado: nenhum componente do Thunderbolt/MPT envia CTRL_C (kill_tree usa psutil terminate; o `_is_windows_process_alive` do MPT só consulta estado), e o Event Log não mostra crashes — a fonte é externa à app (consola/terminal). A blindagem elimina o sintoma qualquer que seja a fonte, e o novo telemetria `ctrl_c_ignored` permite identificar padrões.
- Testes: `tests/test_console_ctrl_c_immunity.py` (nova) cobre a blindagem nos quatro níveis; o teste do launcher actualizado para o contrato Ctrl+C-duplo + SIGHUP/SIGBREAK; fakes do filtro CLI do mpt_agent aceitam o novo kwarg `creationflags`.

## 0.9.70 — 2026-10-08
- Corrigido o **"Refazer Vídeo" que repetia o vídeo anterior** em vez de respeitar as configurações alteradas no canal: a remontagem agora **revalida todo o contexto de geração controlado pelo canal** — legendas (on/off, fonte, posição, cor, tamanho, contorno, fundo), música de fundo, voz, **duração máxima do clip**, proporção, modo de concatenação, transição, correspondência visual-roteiro e a **fonte de materiais (Pexels/Pixabay/…)** — antes de voltar a colocar a tarefa na fila (`hermes_ui/domain.py`).
- **Fonte de vídeo revalidada com novas chamadas**: o valor congelado na tarefa (`material_source`, gravado no momento da criação original) tinha prioridade na resolução da rota (`_normalise_video_route`) e fazia a remontagem repetir as chamadas à fonte anterior; passa a ser derivado de novo do estilo actual do canal + selector global de Fontes de materiais — a nova renderização faz **novas chamadas à fonte configurada**.
- **Duração máxima do clip revalidada em todas as plataformas**: o refresh anterior só revalidava duração/proporção em canais com `platform: youtube`; TikTok, Bilibili e canais legados sem `platform` repetiam sempre os valores antigos. Os defaults do canal são aplicados quando existem, sem sobrescrever escolhas explícitas da tarefa em canais sem default configurado.
- **Estilo completo das legendas no contrato com o MoneyPrinterTurbo** (`hermes_ui/pipeline_worker.py`): antes só chegavam on/off, posição e fonte. Agora são também encaminhados cor do texto (`--text-fore-color`), tamanho (`--font-size`), contorno (`--stroke-color`/`--stroke-width`), fundo (`--subtitle-background-enabled`/`--subtitle-background-color`) e fundo arredondado — respeitando a validação `#RRGGBB` do MPT (fundo desligado nunca é combinado com cor/arredondamento).
- Corrigida a **posição "Bottom (Recommended)"** que era silenciosamente omitida por comparação literal e fazia o MPT usar sempre o seu próprio default; a posição passa a ser normalizada e enviada em todos os casos.
- **Compatibilidade com versões do MoneyPrinterTurbo** (`seed/skills/mpt_agent.py`): o helper detecta as opções suportadas pelo cli.py instalado (via `cli.py --help`) e ignora as restantes em vez de abortar a geração com "unrecognized arguments" — instalações mais antigas usam os defaults do próprio MPT para as opções que ainda não conhecem; em caso de falha da detecção mantém-se o comportamento anterior (encaminhar tudo).
- Mensagens do botão actualizadas nos cartões YouTube, TikTok e Bilibili (`app/main.py`): o help e a mensagem de sucesso explicitam a revalidação das definições actuais do canal e as novas chamadas à fonte de vídeo.
- Testes: revalidação completa do remake (fonte de materiais, duração máxima do clip, concatenação, transição, proporção, correspondência visual-roteiro), preservação de tarefas legadas sem defaults no canal, contrato CLI de legendas completo (cores/tamanho/contorno/fundo) e filtragem de opções suportadas no helper.

## 0.9.68 — 2026-10-08
- **upload_video resolve automaticamente à ferramenta multipart** (`YOUTUBE_MULTIPART_UPLOAD_VIDEO`, um único pedido com o campo `videoFile`) — decisão de backend, sem qualquer opção nova no frontend. Evidência: a resumável `YOUTUBE_UPLOAD_VIDEO` cria o vídeo na API (`uploadStatus: uploaded`) mas a cadeia do Composio entrega bytes que o YouTube abandona no processamento — confirmado com o vídeo `wfeYjNh9R9w` do teste de 08/10 04:23, que o Studio reporta como "Processamento interrompido" e cujo oEmbed/thumbnail devolvem 404; o ficheiro local decodifica sem um único erro (verificado com ffmpeg).
- O pedido multipart está validado até ao endpoint do YouTube (`uploadType=multipart`, rejeitado apenas pela quota diária esgotada do projecto Composio, 429) — a verificação final do processamento fica pendente da reposição da quota (~04:00 de Brasília) e será confirmada no primeiro teste do dia seguinte.
- Em falha de descoberta de ferramentas, cai-se para a resumável validada — o upload nunca deixa de funcionar.
- Removido o alias `multipart_upload_video` (0.9.67) — a decisão é do backend; sem opções no frontend.

## 0.9.67 — 2026-10-08
- Diagnóstico do **"Processamento interrompido"** no YouTube Studio: o upload Composio restaurado (0.9.65) funciona na API — o log de 08/10 04:23 mostra o vídeo criado com `uploadStatus: uploaded` — e o ficheiro local de teste decodifica sem um único erro (H.264/AAC verificados com ffmpeg); o processamento falha **depois**, na cadeia resumable do Composio, que entrega bytes danificados ao YouTube.
- Adicionada a opção **`multipart_upload_video`** para os canais: resolve pela descoberta à ferramenta `YOUTUBE_MULTIPART_UPLOAD_VIDEO` (upload num único pedido, sem sessões resumable) e injecta o ficheiro no campo correcto **`videoFile`** (a resumável usa `videoFilePath`) — o erro 400 da 0.9.56 estava exactamente no nome do campo, agora tratado por ferramenta. O alias `upload_video` mantém-se no `YOUTUBE_UPLOAD_VIDEO`, como estava antes de todas as alterações.
- Para usar: no cartão do canal, definir a Ferramenta Composio como `multipart_upload_video` e repetir o Test Upload Videos — se o vídeo processar normalmente no YouTube Studio, a cadeia multipart passa a ser a recomendada para o canal.

## 0.9.66 — 2026-10-08
- Corrigido o painel **"Resultado do teste de upload"** que ficava vazio: o `st.rerun()` que activa o botão Download Log após cada teste recriava o painel (`st.empty`) sem conteúdo — o resultado piscava durante milissegundos e desaparecia, deixando o utilizador sem saber o que deu no upload. O resultado (sucesso/erro/aviso) e os **Logs de diagnóstico Composio** passam a persistir no `session_state` e são renderizados fora do bloco do botão — ficam visíveis após o rerun e até à próxima alteração, em todos os modos de upload.

## 0.9.65 — 2026-10-08
- **Revertido o upload Compsio ao comportamento pré-0.9.56** (pedido do utilizador; incidente confirmado no log de 08/10 01:24): a priorização do multipart introduzida na 0.9.56 trocou a ferramenta para `YOUTUBE_MULTIPART_UPLOAD_VIDEO`, que exige o campo **`videoFile`** — mas o Thunderbolt injecta o ficheiro em **`videoFilePath`** (o campo de `YOUTUBE_UPLOAD_VIDEO`, validado com o staging manual FileUploadable/s3key) — e o Composio passou a devolver 400 `"Following fields are missing: {'videoFile'}"`. O alias `upload_video` volta a usar directamente `YOUTUBE_UPLOAD_VIDEO`, sem descoberta de ferramentas nem cache de slug; mantém-se a classificação de erros de quota em mensagens accionáveis (0.9.56) e o texto integral nos diagnostics.
- Removido do Test Upload Videos o aviso sobre quota diária de uploads (introduzido na 0.9.56 sem pedido do utilizador).

## 0.9.64 — 2026-10-08
- Corrigida a causa real de **nenhum vídeo Pexels sair com legendas** (confirmado nos logs do MPT de 08/10): com áudio customizado (ElevenLabs, Azure Speech SDK V2 ou modo upload) o MPT não constrói o `sub_maker` e salta a etapa com o aviso `"subtitle maker is missing"` — o vídeo final era montado sem legendas, silenciosamente. Nas condições de áudio customizado a rota passa agora `--no-subtitle-enabled` ao MPT e o **Thunderbolt queima as legendas no vídeo final**: narração dividida em segmentos, durações reescaladas para o vídeo real, mesmo motor e estilo das outras fontes (fonte, tamanho, cor, contorno, fundo e posição das Configurações de legendas). Com TTS nativo do MPT (edge/Azure V1), as legendas continuam a cargo do MPT — word-accurate, com maker válido.
- A queima pós-MPT é tolerante a falhas: qualquer erro deixa o vídeo original intacto (o ficheiro é substituído in-place só quando a versão com legendas é escrita com sucesso; nenhum temporário fica para trás).
- Estado das fontes quanto a legendas: **pexels/pixabay** — MPT nativo word-accurate ou queima Thunderbolt com áudio custom; **text_to_images/web_images** — queimadas na montagem (0.9.63); **full_ia** — o provider devolve o clip pronto, sem queima local; **Remotion** — TextOverlay por cena (não é legenda de narração).

## 0.9.63 — 2026-10-08
- Corrigido o defeito de **nenhum vídeo das automações sair com legendas**: as Configurações de legendas existiam na UI e nos defaults por canal (e a rota pexels/pixabay já as enviava ao MPT via `--subtitle-enabled`/`--subtitle-position`/`--font-name`), mas a montagem por cenas usada por **text_to_images e web_images** nunca as aplicava. As montagens queimam agora as legendas por cena — texto sincronizado com a duração de cada cena, honrando fonte, tamanho (escalado pela altura do vídeo), cor, contorno/outline, fundo (cor + flag) e posição (top/center/bottom) das Configurações de legendas.
- Adicionada a resolução de fonte por cascata: `resource/fonts` do MoneyPrinterTurbo instalado → Fonts do Windows/sistema → genéricos (Arial/DejaVu); sem fonte, o vídeo sai sem legendas com aviso no stderr em vez de falhar.
- As legendas são tolerantes a falhas: qualquer erro de fonte/PIL/texto cai para a montagem simples — a legenda nunca destrói o vídeo.
- Nota: a fonte Remotion mantém o seu próprio TextOverlay por cena; o full_ia depende do provider de vídeo e não queima legendas localmente.
- Verificado o **modo manual** end-to-end: o formulário Criação de Vídeos (`render_video_generation_settings`) → `create_tasks_for_batch` (o form vence os defaults do canal; na automação o canal é a fonte de verdade) → config resolvido → render com legendas queimadas. O fluxo "refazer vídeo" reaplica os defaults de legendas do canal (`_refresh_task_channel_video_settings`).

## 0.9.62 — 2026-10-08
- Adicionado **progresso por cena** às fontes text_to_images e web_images: a geração de imagens de um roteiro longo (uma cena a cada ~11s, dezenas de cenas) corria com o progresso congelado em 52 e a tarefa "doing" sem sinal de vida — o progresso avança agora dentro da banda 52–79 a cada cena concluída, com `video_helper_status` a mostrar "imagem da cena X/N pronta".
- Torna-se **observável a saída do loop de heartbeat** das tarefas: quando o loop termina porque a tarefa deixou de estar "doing" (ou desapareceu), o motivo fica registado no heartbeat do worker (`task_heartbeat_stopped`, estado e stage no momento) — no incidente de 07/10 o heartbeat morreu às 00:05:51 sem deixar qualquer rasto.
- Adicionado o **registo de eventos de recuperação** (`storage/state/storage-recovery.log`): restaurar um ficheiro protegido de um backup de corrupção era silencioso — cada backup criado, restauro e falha da recuperação fica agora documentado no disco.
- Nota de incidente (transparência): durante o diagnóstico do problema original, um teste de escrita meu substituiu o `tasks.json` real por um ficheiro de teste e a recuperação silenciosa restaurou um backup de Agosto; a lista de tarefas foi recuperada no mesmo dia a partir dos ficheiros temporários de escrita atómica sobreviventes (4 → 70 tarefas) e as três falhas acima (progresso invisível, heartbeat mudo, recuperação silenciosa) foram corrigidas na sequência.

## 0.9.61 — 2026-10-07
- Corrigido o erro inútil "Todos os providers do pool image falharam — API não identificada (falha anterior)" nos vídeos com fonte **text_to_images**: a rota de imagem/vídeo é por **cartão único**, e quando o primeiro cartão falhava (tipicamente em cooldown — incluindo os cooldowns até 3600s gravados pelo Retry-After do 0.9.60), o texto genérico não tinha marcador de retry e o `generate_image_from_pool` **abortava todo o pool sem tentar os cartões seguintes**, com a causa real perdida.
- As falhas de rota de cartão único passam a produzir mensagens accionáveis com os detalhes das tentativas ("O provider de imagem X falhou: X: provider em cooldown por mais de Ns", "X: HTTP 429: ..."), o texto genérico passa a ser retryable (um cartão em cooldown deixa de envenenar o pool) e o mesmo tratamento foi aplicado ao pool de vídeo (`generate_video_for_card`).

## 0.9.60 — 2026-10-07
- Corrigida a causa do vídeo "refazer" ficar horas em "doing" sem avançar: quando o provider LLM devolvia 429 com cabeçalho `Retry-After` longo (ex.: 3600s), o router dormia **até uma hora inline por tentativa** dentro da etapa — o heartbeat mantinha a tarefa viva e o bloqueio ficava invisível (incidente: tarefa 2 horas em "doing" na etapa script). Esperas acima do tecto de 90s (`DEFAULT_RETRY_AFTER_CAP_SECONDS`) passam a **falhar a chamada com mensagem accionável**: o cartão entra em cooldown pelo tempo pedido, a tarefa regista a falha com atribuição e a fila avança; esperas dentro do tecto continuam a ser honradas inline. Aplica-se aos pools LLM, imagem e vídeo.

## 0.9.59 — 2026-10-07
- Gravadas no `AGENTS.md` duas regras permanentes do projecto: (1) **CHANGELOG obrigatório** — qualquer alteração com push (código, docs, configuração, publicação) é registada no `CHANGELOG.md` antes de publicar, incluindo documentação retroactiva de trabalho de outras sessões sem entrada; (2) **rebase obrigatório** — antes de qualquer commit/push as sessões verificam o master remoto e fazem rebase quando avançou, e em colisão de versão a versão já publicada vence, renumerando a sessão para o patch seguinte confirmado no registry.

## 0.9.58 — 2026-10-07
- O browser **Camoufox** (binário Firefox anti-detect da sessão de upload directo) passa a instalar-se automaticamente com o pacote — obrigatório e fatal em falha, como o Python, os FFmpeg, o Chromium do Playwright/Patchright e o Remotion: o instalador corre `python -m camoufox fetch` quando a detecção (via `python -m camoufox version`, espelhando o `hermes_ui/browser_manager.py`) revela que o binário não existe; já descarregado, o passo é saltado, evitando repetir ~150MB a cada actualização.

## 0.9.57 — 2026-10-07
- A Automação passa a **gerar o tópico/título/keywords via LLM no momento da criação da tarefa** — não cria uma casca vazia que dependia do pipeline worker; em falha do LLM, cai no payload pendente (o pipeline gera depois).
- Adicionado o **auto-resume do pipeline**: a pausa automática pós-crash deixa de exigir Start manual — ao criar uma tarefa nova, a fila activa-se sozinha (`_ensure_pipeline_running`).

## 0.9.56 — 2026-10-06
- Restaurada a prioridade da ferramenta **YOUTUBE_MULTIPART_UPLOAD_VIDEO** nos uploads Composio (a decisão do 0.8.62 que o hardcode de 17/09 tinha sobreposto): o alias `upload_video` volta a resolver pela descoberta de ferramentas — a multipart completa o upload num único pedido, em vez da ferramenta resumável básica, que podia falhar **depois** de criar a sessão de upload e consumir a quota diária sem devolver vídeo. O `YOUTUBE_UPLOAD_VIDEO` mantém-se como fallback quando a descoberta falha e o slug resolvido é cacheado por processo.
- Classificados os erros do YouTube atrás do Composio em mensagens accionáveis: a quota 429 ('Video Uploads per day') passa a explicar a reposição (meia-noite, hora do Pacífico), o custo de cada teste e a verificação do YouTube Studio; as falhas 'upload URL' avisam que o vídeo pode ter sido criado mesmo com erro reportado. O texto integral permanece nos diagnostics.
- Adicionado ao Test Upload Videos o aviso de que cada teste publica um vídeo real (não listado) e consome a quota diária de uploads do projecto (~6/dia).

## 0.9.55 — 2026-10-06
- Tornadas as dependências do Remotion **persistentes entre versões**: passam a viver em `THUNDERBOLT_HOME\remotion\` — como o `.venv`, os FFmpeg e os browsers do Playwright — em vez da pasta da versão no cache do npx, que é recriada a cada actualização e reinstalava os 257 pacotes do zero. A detecção usa o hash do `packages/remotion/package.json` (marcador `.remotion-dependencies.sha256`, o mesmo padrão dos `.sha256` do requirements.txt) e a cópia da versão usa as dependências persistentes via junction em `packages/remotion/node_modules`.
- Adicionada ao instalador a validação do binário do **esbuild** após a instalação: o npm novo bloqueia scripts de instalação (`npm warn install-scripts`) e o postinstall do esbuild pode ser bloqueado; o binário chega como pacote normal (`@esbuild/win32-x64`) e a validação confirma que o bundler do Remotion funciona antes de qualquer render — se falhar, a instalação aborta com a instrução `npm install-scripts approve esbuild`.

## 0.9.54 — 2026-10-06
- Corrigidos os erros "Task was destroyed but it is pending!" + `TargetClosedError` no terminal: a verificação de estado do Remotion arrancava o driver do Playwright (`sync_playwright()`) dentro do thread do Streamlit só para ler `executable_path`, e um rerun interrompido destruía a conexão a meio do init. O caminho do Chromium passa a ser lido **directamente da pasta de browsers** (`ms-playwright`), sem driver, sem processos e sem tarefas assíncronas — com suporte a `PLAYWRIGHT_BROWSERS_PATH`, escolha da revisão mais alta e prioridade do Chrome completo sobre o headless shell.

## 0.9.53 — 2026-10-06
- Tornado o **Remotion dependência obrigatória** do pacote: o instalador passa a instalar automaticamente as dependências Node (`npm install` em `packages/remotion/`) da mesma forma que instala o Python, os dois FFmpeg e o Chromium do Playwright — uma falha do npm install **aborta agora a instalação** com mensagem clara (removidos o modo "best-effort" e a flag `--skip-remotion`).
- O npm é invocado via `npm-cli.js` ao lado do node (o Node ≥ 18 recusa-se a criar processos `.cmd` directamente, CVE-2024-27980), com fallback para `cmd /c npm` no Windows e `npm` nos restantes sistemas, seguido da verificação do marcador `node_modules/@remotion/renderer`.

## 0.9.52 — 2026-10-06
- Implementado o **Remotion** como provedor de vídeo local, substituindo o placeholder "Em breve": novo pacote `packages/remotion/` com as composições React `LongFormVideo` (1920×1080) e `ShortVideo` (1080×1920) e os componentes NarrationAudio, TextOverlay, AnimatedBackground, SceneTransition, DataVisualization e HandDrawnCanvas.
- Adicionado o adaptador `scriptToInputProps` (roteiro Markdown → inputProps JSON): secções GANCHO/CENA/ENCERRAMENTO em PT e EN, durações estimadas por palavras e recalculadas proporcionalmente quando o áudio TTS real existe.
- Adicionado o wrapper `render.mjs` — bundle cacheado em `storage/remotion-cache/bundle/` com invalidação por hash, protocolo `OUTPUT=`/`PROGRESS=`, concorrência CPU−1 — e o provider `hermes_ui/remotion_provider.py` (`get_remotion_status`, `prepare_input_props`, `run_remotion_render`) com heartbeat de 5s, timeout de 15 minutos, cancelamento e `_stop_process` (psutil).
- Integrada a rota `remotion` no `pipeline_worker.py` com a mesma banda de progresso (52–79%) e cadeia TTS das outras fontes; as pipelines pexels, text_to_images, web_images e full_ia ficam inalteradas.
- Actualizada a UI: a fonte Remotion habilita-se quando o ambiente está operacional e, caso contrário, apresenta as razões com o botão "Criar tarefas" bloqueado; o expander da Configuração API mostra o estado real (Node.js, Chromium do Playwright, FFmpeg do imageio-ffmpeg e dependências).
- Ajustado o single-instance guard: processos com `--thunderbolt-role=remotion-render` (e as respectivas árvores Chromium/FFmpeg) ficam excluídos da limpeza da instância anterior, mantendo a normalização `\` → `/` do 0.9.50.
- Incluída a skill **hand-drawn-canvas-animation** (alesha-pro/tools) como motor HandDrawnCanvas — cinco looks (`hand_drawn_paperInk`, `risoPop`, `screenSea`, `pencilMinimal`, `doodlePastel`), aleatoriedade com seed, exposição intencional (twos) e a fórmula de timebase 24 fps da skill; resumo operacional em `seed/skills/remotion.md`.
- Adicionado o passo `npm install` em `packages/remotion/` ao instalador (best-effort, contornável com `--skip-remotion`) e os ficheiros do pacote Remotion ao pacote npm publicado.
- Adicionados os testes do provider e do guard (Python), os testes Node do wrapper e do adaptador (37 verificações sem node_modules) e o e2e opt-in (`THUNDERBOLT_REMOTION_E2E=1`); documentação completa em `docs/remotion.md`. Suite: 1174 passed, 2 skipped, 10 subtests.

## 0.9.51 — 2026-10-05
- Preenchido o CHANGELOG com o histórico das versões 0.9.34 a 0.9.50.
- Adicionadas ao `AGENTS.md` as regras permanentes das sessões de agente: push obrigatório após commits e regras de release (bump duplo, publicação sempre via GitHub Actions, transparência pós-versão, comandos de instalação obrigatórios e UX sem travas de pré-registo).
- Bump duplo 0.9.51 (`package.json` + `pyproject.toml`).

## 0.9.50 — 2026-10-05
- Corrigida a causa-raiz do guard de instância única falhar no Windows: os marcadores de processo do `kill_tree` usavam barras normais (`@danhachuel/thunderbolt`) mas o cmdline do Windows usa barras invertidas, pelo que o guard matava os filhos Python e deixava o launcher `node.exe` vivo a segurar a porta 3030 — o launcher novo crashava no bind com `EADDRINUSE`.
- Normalizado o cmdline (barras invertidas convertidas em barras normais) antes do matching no `is_thunderbolt_process`, com três novos testes de caminhos Windows.

## 0.9.49 — 2026-10-05
- Removida toda a instrumentação de diagnóstico da 0.9.47: módulo `hermes_ui/diagnostics.py` apagado, botões de baseline/diagnóstico removidos da UI e eventos de diagnóstico retirados do worker e do launcher; mantêm-se os artefactos por tarefa, a telemetria de saída com motivo e os eventos de erro do guard.
- Tornado o guard tolerante a sobreviventes: o helper `kill_tree` aceita sair com processos vivos (saída JSON interpretável) e o launcher repete a limpeza; os erros do guard passam a incluir status e stderr do helper.
- Corrigida a segunda face do REAL-BUG #1: os escritores do lock de storage fazem agora poll até ao prazo quando o `os.open(O_CREAT|O_EXCL)` devolve um `PermissionError` transitório do antivírus, em vez de propagar o erro.

## 0.9.48 — 2026-10-04
- Corrigido o ciclo “servidor encerra sozinho” no Windows: o guard de instância única passa a correr antes do bind da porta pública, termina a stack anterior (launcher, Streamlit, workers, mpt_agent), incluindo órfãos de launchers mortos abruptamente, e reclama `storage/state/launcher.lock`, usando o novo helper `scripts/kill_tree.py` com psutil.
- Corrigido o REAL-BUG #1: adicionado um retry curto (3×50ms) no unlink do lock de estado — um `PermissionError` transitório do antivírus deixava o lock vazado e envenenava todas as escritas seguintes (TimeoutError de 30s).
- Corrigido o REAL-BUG #2 (bump duplo): `package.json` e `pyproject.toml` passam a ser mantidos sincronizados por `scripts/sync_pyproject_version.mjs`, com passo obrigatório no workflow de publicação que falha o release em divergência.
- Adicionada telemetria de saída com motivo em todos os caminhos do launcher (Ctrl+C, external kill, crash, update) e registo de `uncaughtException`/`unhandledRejection`.
- Realinhada a suite de testes com a UI actual: 101 falhas do baseline eliminadas com evidência git por teste, testes herméticos no Windows (sem rede nem paths reais) e a suite de social networks ~2,7× mais rápida.

## 0.9.47 — 2026-10-01
- Adicionados baseline e snapshots aos diagnósticos de crash do launcher e do worker: novo módulo `hermes_ui/diagnostics.py`, botões de registo/exportação na UI e eventos de ciclo de vida no launcher.

## 0.9.46 — 2026-09-30
- Adicionadas instalação e validação das dependências dos workers no arranque, com a psutil declarada em `pyproject.toml` e verificação no launcher.

## 0.9.45 — 2026-09-30
- Protegido o Streamlit durante a recriação de vídeos, com paragem segura de processos via psutil e validação HTTP das respostas do Pexels.
- Adicionados testes de paragem de processos, de validação HTTP do Pexels e regressões do gestor de actualizações.

## 0.9.44 — 2026-09-30
- Colocados os blueprints financeiros na raiz de `seed/blueprints`, simplificando o catálogo e a importação.

## 0.9.43 — 2026-09-30
- Reclassificados os blueprints financeiros (FINANCE) como conteúdo, com migração dos seeds de `thumbnails` para `conteudo` e actualização do catálogo e do instalador.

## 0.9.42 — 2026-09-30
- Adicionado o Music Blueprint com cerca de 50 seeds Markdown de géneros musicais por idioma e tipo de voz, novo módulo `hermes_ui/music_blueprints.py` e integração na UI e no instalador.

## 0.9.41 — 2026-09-30
- Mantido o heartbeat do worker activo durante as chamadas longas de geração de vídeo, evitando falsas detecções de bloqueio.

## 0.9.40 — 2026-09-30
- Impedidos os ciclos de crash do worker de vídeos, com protecção adicional do launcher contra reinícios em loop.

## 0.9.39 — 2026-09-29
- Melhorados os diagnósticos e a robustez da kernel Kaggle do Niche Finder: execução, mensagens de erro, metadata da kernel e verificação das chaves de API.
- Endurecida a verificação do tarball npm no workflow de publicação: espera activa pela metadata publicada e confirmação de que o tarball é descarregável.

## 0.9.38 — 2026-09-28
- Ocultado o ficheiro `LISTA.txt` dos catálogos de blueprints, na UI e no MCP server.

## 0.9.37 — 2026-09-28
- Renomeado o seed de blueprint financeiro para **FINANCE USA**, com actualização do catálogo e da importação de canais.

## 0.9.36 — 2026-09-28
- Paginada a pesquisa de imagens do Google (SerpApi) com o parâmetro `ijn`, permitindo recolher resultados além da primeira página nos Web Images.

## 0.9.35 — 2026-09-28
- Integrado o motor social-auto-upload para publicação com browsers reais e proxies próprios: novo backend (`hermes_ui/social_auto_upload_backend.py`), UI dedicada (`app/social_auto_upload_ui.py`) e encaminhamento de uploads por alvo (`integrations/upload_routing.py`).
- Adicionados os gestores de browsers (`hermes_ui/browser_manager.py`) e de proxies (`hermes_ui/proxy_manager.py`), com dependências, exclusões de pacote e testes próprios.

## 0.9.34 — 2026-09-28
- Adicionado carregamento tardio (lazy) da media da Automação YouTube: os vídeos locais só são lidos quando pedidos, em vez de carregar tudo ao abrir a aba.

## 0.9.33 — 2026-09-28
- Integrada a pipeline editorial **Facebook Storytelling** em três fases: tema, produção e publicação controlada.
- Adicionado SQLite dedicado em `storage/state/facebook.db`, com isolamento por Facebook Page, histórico de estados, cards de imagens e migração não destrutiva dos JSON legados.
- Adicionada escolha explícita entre os pools **Scrapt de Imagens na Web** e **Imagem e Video IA**, respeitando a prioridade e o fallback interno de cada pool.
- Adicionados overlays Pillow com quebra de texto, contorno preto, posicionamento configurável e preview antes da publicação Meta Graph API.
- Mantido o selector de Facebook Page vazio sem trava de pré-cadastro; a validação de credenciais ocorre apenas no momento da publicação.

## 0.9.32 — 2026-09-28
- Removida a actualização automática da página ao trocar de aba, voltar após inactividade, recuperar a ligação ou detectar textos de `connection timed out`.
- Restaurada a recuperação limitada apenas a falhas de carregamento de bundles dinâmicos, preservando o estado da sessão e deixando a actualização normal sob controlo manual/F5.

## 0.9.31 — 2026-09-28
- Corrigido o `IndexError` ao clicar em `↓` no último cartão de **Web Images**.
- Adicionadas verificações de limites aos botões de reordenação `↑` e `↓`, mantendo-os desactivados nos extremos e impedindo swaps fora da lista.

## 0.9.30 — 2026-09-28
- Corrigida a activação do worker de automação para tarefas pendentes de vídeos refeitos, mesmo quando nenhum canal está actualmente com a automação ligada.
- O launcher agora detecta tarefas `to_do` ou `doing` marcadas com `automation_worker=true` e inicia o worker sob demanda.

## 0.9.29 — 2026-09-28
- Corrigido o arranque para não importar nem autenticar o SDK Kaggle antes de uma acção explícita do Niche Finder.
- Isolado `KAGGLE_CONFIG_DIR` numa pasta temporária vazia e adicionada compatibilidade explícita com Kaggle 1.x e 2.x através das variáveis da UI.
- Melhorada a mensagem apresentada na UI quando a autenticação Kaggle falha.

## 0.9.12 — 2026-09-26
- Adicionadas as sub-abas **Pipeline** e **Videos Postados** na Automação YouTube, abaixo dos canais cadastrados.
- Vídeos com publicação remota confirmada ou marcados manualmente como “Upload ok” são separados da fila e apresentados em **Videos Postados**.
- Cada vídeo da Pipeline e de Videos Postados passou a ser uma aba expansível fechada por defeito, com apenas nome do vídeo e canal no cabeçalho.

## 0.8.96 — 2026-09-23
- Refatorado o Niche Finder para publicar e executar a análise remotamente no Kaggle através da biblioteca Python `kaggle`.
- Adicionada a kernel privada com o dataset Trending YouTube Videos e os três resultados CSV: clusters, itemsets frequentes e regras de associação.
- Adicionado cache local dos resultados, sem CLI Kaggle, `subprocess` ou gravação de `kaggle.json`.

## 0.8.83 — 2026-09-19
- Adicionada renderização consistente de emojis de bandeira como SVGs locais nos conteúdos da interface, com conversão global no Streamlit, fallback seguro e suporte aos temas claro e escuro.

## 0.8.79 — 2026-09-19
- Corrigido loop infinito de reinicialização do automation_worker com lock obsoleto. Adicionado backoff exponencial e limite de 5 tentativas.

## 0.8.62 — 2026-09-17
- Priorizada a ferramenta `YOUTUBE_MULTIPART_UPLOAD_VIDEO` na operação `upload_video` do Composio.
- Adicionados logs do caminho absoluto, tamanho, tipo, valor do campo de ficheiro e resposta completa do Composio.
- Adicionado o verificador `scripts/verify_video_media.py`, baseado em `ffprobe`, para confirmar MP4 faststart, H.264, AAC estéreo e 44.1/48 kHz.

## 0.8.61 — 2026-09-17
- Suprimido no bootstrap apenas o aviso `missing ScriptRunContext` emitido pelo Streamlit durante o arranque bare mode, preservando os restantes warnings.

## 0.8.60 — 2026-09-17
- Corrigido o upload de vídeos via Composio para passar sempre o caminho local puro ao SDK, removendo a conversão manual duplicada para descriptors `{name, mimetype, s3key}`.
- Mantido o auto-upload de ficheiros do SDK Composio e adicionado log explícito do valor e tipo do argumento enviado à ferramenta.
- Adicionados testes regressivos para impedir o reaparecimento de descriptors S3 manuais.

## 0.8.59 — 2026-09-17
- Tornada idempotente e tolerante a corridas a criação das pastas de storage durante arranque e shutdown concorrentes dos workers, incluindo protecção contra ficheiros com o nome esperado de uma pasta.
- Tornada a migração do Blueprint de thumbnails TikTok executável uma única vez por processo.
- Adicionada verificação de `ScriptRunContext` aos fragments periódicos de automação e às notificações globais, evitando acessos Streamlit fora do contexto activo.
- Removida definitivamente a API depreciada `st.components.v1.html`; o bootstrap de tema usa exclusivamente `st.html`.

## 0.8.57 — 2026-09-17
- Substituída completamente a API depreciada `st.components.v1.html` por `st.iframe`.
- Implementado shutdown silencioso dos workers em Ctrl+C, sem gravação de estado durante a interrupção.

## 0.6.86 — 2026-09-07
- Adicionado o botão **Refazer Vídeo** às abas de Automação Youtube e Automação Tiktok.
- A remontagem preserva roteiro, Blueprint/Prompt Master, tags, voz, thumbnail e artefactos de media existentes, invalidando apenas o vídeo e o resultado de publicação.

## 0.6.43 — 2026-09-06
- Corrigido o arranque Windows para carregar `.env` em UTF-8 antes dos imports da UI e do cliente Instagram, permitindo a sessão usada pelo país de “Sobre esta conta”.
- Corrigida a raiz do entrypoint legado, que apontava um nível acima do pacote.
- Corrigida a indentação inválida no entrypoint legado, garantindo compilação Python antes do arranque.
- Mantidas as correcções de payload, estado dos widgets e fallback Chromium para os posts, sem alteração de layout.

## 0.6.42 — 2026-09-06
- Tornadas únicas por payload as chaves dos widgets da pesquisa Instagram, impedindo que Bio, seguindo, posts e país vazios sejam reutilizados pela mesma conta.
- Adicionado fallback Chromium específico ao botão **Carregar últimos 10** quando o HTML HTTP não contém os posts.
- Mantidas todas as funcionalidades anteriores e nenhum ajuste de layout.

## 0.6.41 — 2026-09-06
- Corrigido o estado dos widgets do formulário de pesquisa Instagram: uma nova pesquisa limpa os valores antigos de Bio, posts, seguidores, seguindo, país, idioma e personagem antes de renderizar o novo perfil.
- Mantidas integralmente as correcções de parsing Windows, fallback Chromium e payload Instagram das versões anteriores.
- Nenhuma alteração de layout.

## 0.6.40 — 2026-09-06
- Corrigido o parser Instagram para aceitar também respostas Windows no formato directo `{"user": {...}}`, além de `data.user`, `graphql.user` e `data.profile`.
- Evitado o fallback indevido para HTML parcial quando o endpoint já devolveu o perfil completo.
- Mantidas integralmente as funcionalidades de 0.6.39 e nenhuma alteração de layout.

## 0.6.39 — 2026-09-06
- Renumeração da correcção de compatibilidade Windows/Chromium que estava identificada como 0.6.38; inclui integralmente o fallback Chromium, as variantes de headers e a protecção contra payload Instagram parcial.
- Mantidas todas as funcionalidades e correcções da 0.6.38, sem alteração de layout.

## 0.6.38 — 2026-09-06
- Adicionado fallback Chromium para o endpoint público Instagram quando o Windows devolve HTML parcial a `requests` e `curl`.
- A pesquisa só usa os dados obtidos pelo navegador quando o payload contém bio, following, followers, posts e username.
- Nenhuma alteração de layout.

## 0.6.37 — 2026-09-06
- Corrigida a consulta Instagram para Windows com variantes de headers de navegador e aplicação móvel, evitando que respostas parciais deixem bio e seguindo vazios no formulário.
- Validado o fluxo completo da UI com **@simoes.vi**: bio, posts `65`, seguidores `868` e seguindo `933` renderizados no formulário.
- Nenhuma alteração de layout.

## 0.6.36 — 2026-09-06
- Corrigida a selecção do payload público Instagram: a aplicação consulta primeiro a resposta HTTP completa e só usa `curl` como fallback, combinando respostas parciais em vez de aceitar um perfil incompleto.
- Corrigido o caso reproduzido com **@simoes.vi**, que passa a preencher bio, seguindo, seguidores e posts no formulário sem qualquer alteração de layout.

## 0.6.35 — 2026-09-06
- Corrigido o estado dos widgets do formulário de pesquisa Instagram: cada conta pesquisada passa a ter chaves próprias, impedindo que bio, posts, seguidores ou seguindo fiquem presos aos valores de uma pesquisa anterior.
- Integrada a leitura do país pelo endpoint Bloks de **Sobre esta conta** quando existe sessão Instagram autenticada, sem inferência pela bio ou morada comercial.
- Mantido integralmente o layout existente, incluindo o botão compacto **↻**.

## 0.6.34 — 2026-09-06
- Restaurado o formato visual anterior do botão de actualização Instagram: ícone **↻** com tooltip, sem alterar a lógica corrigida de actualização de posts, seguidores e seguindo.

## 0.6.33 — 2026-09-06
- Corrigido o cadastro e refresh de Contas Instagram para preservar o ID interno do canal e normalizar bio, seguidores, seguindo e posts entre versões antigas dos dados.
- O botão **Carregar últimos 10** passa a guardar os posts por conta no storage local, mantendo-os disponíveis após o rerun da interface.
- O botão **Actualizar posts, seguidores e seguindo** actualiza o perfil e os posts sem substituir a identidade interna da conta.
- O campo **País** usa exclusivamente o país explícito publicado em **Sobre esta conta**; a bio nunca é usada para inferir o país.

## 0.6.10 — 2026-09-05
- Adicionado suporte à selecção explícita de uma connected account YouTube no Composio por ID ou alias.
- O executor resolve o alias contra as contas activas da mesma entidade antes de chamar a ferramenta, evitando depender da conta predefinida errada.
- A configuração passa a permitir guardar o `connected_account_id` e clarifica que o `composio_user_id` tem de ser exactamente o mesmo usado no momento da ligação das contas.

## 0.6.09 — 2026-09-05
- Corrigido o falso `AssertionError` durante a verificação do MoviePy: o helper passa a validar o metadado da distribuição instalada, que identifica correctamente `moviepy==2.2.1` mesmo quando o módulo expõe uma versão interna diferente.
- Eliminadas tentativas repetidas do mesmo provider no fallback de vídeo. Pexels e Pixabay deixam de ser executados uma vez por cada cartão/chave, evitando reinstalações redundantes e cascatas como Pexels → Pexels → Pixabay.

## 0.6.08 — 2026-09-05
- Corrigida a resolução da conta Google usada no upload YouTube quando o canal conserva o e-mail mas perdeu ou tem um ID de conta desactualizado.
- A interface manual, o worker automático e o routing oficial/direct passam a usar um resolver comum por ID, e-mail ou conta única não ambígua.
- O erro de conta YouTube não ligada no Composio continua a ser tratado como falha de fallback, permitindo avançar para a API Oficial e para o upload directo quando a conta OAuth local está configurada.

## 0.5.96 — 2026-09-05
- Integrado explicitamente o MoviePy 2.2.1 no runtime MoneyPrinterTurbo, alinhando o motor de composição/renderização com o upstream.
- O helper valida a versão MoviePy antes da geração e executa o CLI upstream com essa dependência garantida.

## 0.5.95 — 2026-09-05
- Forçado `h264_nvenc` na configuração de renderização do runtime MoneyPrinterTurbo.
- Actualizadas as operações locais de clips e editor de vídeo para usar NVENC com `p1` e `yuv420p`.
- Adicionado fallback automático para `libx264` quando NVENC/driver CUDA não estiver disponível, preservando ficheiros reproduzíveis.
- Confirmado que este fork não contém chamadas `write_videofile`; a renderização principal é feita pelo runtime FFmpeg/MoneyPrinterTurbo.

## 0.5.94 — 2026-09-05
- Corrigido o indicador **YouTube Analytics API: Métricas internas** da aba **Analista Growth Youtube** para validar exclusivamente a conta Google associada ao canal seleccionado.
- Uma conta Google configurada para outro canal deixa de activar falsamente o estado verde.
- Adicionados testes de regressão para associação explícita e ausência de fallback para contas não relacionadas.

## 0.5.93 — 2026-09-05
- Removidos das abas de **Documentação** os botões e referências de fonte externa adicionados sem autorização.
- Removido o link do Google Drive e o título Markdown duplicado do tutorial **YouTube Data API Key (Public Data)**.
- Preservados os links operacionais que já faziam parte dos documentos, incluindo os links úteis do tutorial Meta/Facebook.

## 0.5.92 — 2026-09-05

- Corrigido o botão **Start** dos cards da aba **Automação Youtube**, que agora usa o mesmo helper de arranque verificado pelo Backlog e TikTok.
- O Start confirma a actualização persistida da tarefa antes de recarregar a interface e apresenta erro explícito se a tarefa tiver sido removida entretanto.
- O launcher mantém o pipeline worker disponível mesmo com a fila inicialmente vazia, permitindo recolher imediatamente novas tarefas manuais.

## 0.5.91 — 2026-09-05

- Corrigido o arranque de vídeos pelo botão **Start** na aba **Automação Youtube**.
- O launcher passa a procurar `tasks.json` no mesmo `THUNDERBOLT_STORAGE_DIR` usado pela interface e pelo pipeline worker, permitindo iniciar imediatamente o worker quando uma tarefa entra em `doing`.
- Adicionado teste de regressão para impedir divergência entre o storage detectado pelo launcher e o storage persistente da aplicação.

## 0.5.90 — 2026-09-05

- Adicionada em **Documentação** a aba **Tutorial YouTube Data API Key (Public Data)**, baseada no documento fornecido do Google Drive.
- O tutorial explica a criação, restrição, configuração no campo `INNERTUBE_API_KEY`, quota e segurança da chave para dados públicos.

## 0.5.89 — 2026-09-05

- Corrigida a orientação do tutorial OAuth: o fluxo de callback local requer uma credencial **Aplicativo para computador (Desktop app)**, não **Aplicativo da Web**.
- A mensagem `redirect_uri_mismatch` agora identifica explicitamente o tipo correcto de credencial e o callback loopback utilizado.
- Actualizada a configuração documentada para usar os campos Client ID e Client Secret em **Contas Google** na interface do Thunderbolt.

## 0.5.88 — 2026-09-04

- Corrigido o erro Windows `WinError 10048` ao autorizar contas Google via OAuth quando a porta local `8765` já está ocupada.
- O callback OAuth tenta primeiro a porta configurada e faz retry automático numa porta loopback livre, mantendo a autenticação normal do Google.
- Adicionado teste de regressão que reproduz a porta ocupada e confirma a autorização na porta dinâmica.

## 0.5.87 — 2026-09-04

- Corrigida a renovação de `sessionInfo` quando o executável Chromium do Playwright não existe no cache do Windows.
- O instalador passa a executar `playwright install chromium` depois de instalar as dependências Python.
- A renovação tenta primeiro o Google Chrome instalado e, se necessário, instala automaticamente o Chromium gerido pelo Playwright antes de falhar.
- Adicionada validação explícita da dependência Playwright no diagnóstico do launcher e cobertura de testes para o fallback do browser.

## 0.5.86 — 2026-09-04

- Adicionada a dependência Python `deno`, com binário gerido automaticamente e suporte multiplataforma.
- O downloader yt-dlp passa a receber explicitamente `--js-runtimes deno:<caminho>` através da API Python.
- Actualizado o yt-dlp para o extra `default`, incluindo os scripts EJS necessários para os desafios JavaScript do YouTube.
- Adicionado fallback para um executável `deno` disponível no `PATH` e diagnóstico do runtime em `dependency_status()`.

## 0.5.85 — 2026-09-04

- Corrigido o `UnboundLocalError` em Automação Youtube ao renderizar o Thumbnail Blueprint dos cards de canais.
- O valor inicial é agora calculado antes da renderização e continua a ser actualizado após a selecção do Blueprint.

## 0.5.84 — 2026-09-04

- Corrigida a regressão de percentagem nos cards de vídeos em `doing` quando tarefas antigas são retomadas.
- O progresso persistido passa a ser monotónico: uma actualização posterior nunca reduz o maior avanço confirmado.
- Mantido o watchdog de actividade para marcar tarefas sem heartbeat como falhadas, evitando execução indefinida.

## 0.5.83 — 2026-09-04

- Adicionados ao Analista Growth Youtube os indicadores de configuração da YouTube Data API v3 e da YouTube Analytics API.
- Os estados usam o padrão visual existente: verde “Configured” e amarelo “Missing configuration”.

## 0.5.82 — 2026-09-04

- Reorganizados os cards de canais da aba Automação Youtube numa grelha compacta de duas linhas.
- Removidos o selector Formato e a informação Formato redundantes dos cards de canais.
- Reduzido o espaço vertical vazio e ajustadas as larguras dos controlos.
- O botão Guardar passou a usar o estilo azul primário da interface.

## 0.5.81 — 2026-09-04

- Implementado o Dashboard de Growth Youtube com Nota Geral do canal e oito cards categorizados.
- Adicionados os três cards de destaque — Validação de Nicho, Thumbnail e Título dos Vídeos — e cinco cards secundários com tabelas KPI, Valor, Meta e Status.
- Adicionada a indicação “Análise concluída” junto ao botão de análise.
- KPIs sem dados disponíveis continuam identificados como “A verificar”, sem inventar métricas privadas do YouTube Analytics.

## 0.5.80 — 2026-09-04

- Corrigida a rotação das chaves individuais das fontes de vídeo stock.
- Os cartões Pexels e Pixabay activos passam a ser tentados pela prioridade configurada, uma chave por tentativa, antes de avançar para o provider seguinte.
- Falhas de actividade, quota ou credenciais numa chave passam correctamente para a próxima chave elegível; a configuração legada sem cartões mantém o comportamento anterior.

## 0.5.79 — 2026-09-04

- Corrigido o refresh da versão 0.5.78: as páginas completas de Automação Youtube e Automação Tiktok deixaram de ser fragmentos.
- O refresh automático de cinco segundos ficou limitado exclusivamente às secções dos cards de vídeos e respectivas barras de progresso.

## 0.5.78 — 2026-09-04

- Corrigida a actualização das barras de progresso nas abas **Automação Youtube** e **Automação Tiktok**.
- As duas filas passam a actualizar automaticamente a cada cinco segundos enquanto a aba está aberta, sem necessidade de premir F5.
- O refresh só ocorre enquanto a respectiva aba está aberta, sem afectar as restantes páginas.

## 0.5.77 — 2026-09-04

- Aplicado à aba **Automação Tiktok** o mesmo arranque manual do pipeline usado no YouTube.
- O botão **Start** de tarefas TikTok agora usa a rotina comum para iniciar tarefas `to_do` e `doing` ou repetir tarefas `blocked`/`failed`, permitindo ao launcher iniciar o worker e o processo de geração do vídeo sem automação horária activa.

## 0.5.76 — 2026-09-04

- Corrigido o arranque do pipeline ao clicar em **Start** num vídeo parado, mesmo quando não existe nenhum canal com automação activa.
- O launcher passa a monitorizar os estados `to_do` e `doing`, que são os estados realmente consumidos pelo worker do pipeline.

## 0.5.56 — 2026-09-04

- Corrigido o encerramento por `Ctrl+C` no launcher Streamlit.
- O handler SIGINT agora tenta parar o event loop, aguarda uma janela curta de drenagem e encerra sem callbacks tardios.
- Mantidos os shims UTF-8, as variáveis de ambiente e a protecção contra substituição do handler pelo Streamlit.
- Reduzida a poluição do terminal causada por tracebacks `RuntimeError: Event loop is closed` e `asyncio.exceptions.CancelledError` durante o shutdown.
