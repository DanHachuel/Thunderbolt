# Changelog
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
