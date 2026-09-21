# Thunderbolt UI

> Consulte o [Manual completo de instalação](MANUAL-INSTALACAO.md) antes do primeiro teste local.

Thunderbolt — UI web local da Fase 3, baseada no fluxo Streamlit do [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo). A aplicação organiza canais, blueprints, lotes de vídeos, filas, artefactos e upload em armazenamento local JSON. O pacote npm distribui apenas os seeds versionados em `seed/`; não inclui `storage/` persistente, pelo que Blueprints, personagens, configurações e artefactos locais não são enviados durante uma actualização.

## Estado actual

A primeira versão implementa a camada UI independente com:

| Área | Incluído |
|---|---|
| Início | Resumo de canais, tarefas, backlog, execução e falhas, com as filas do Pipeline inline |
| Pipeline Vídeos | Menu expansível com Criação de Vídeos, Backlog Vídeos, Roteiros, Thumbnails e Upload |
| Worker de vídeo | Heartbeat persistido, barra de progresso por etapas, timeout de 20 minutos, recuperação de tarefas abandonadas e diagnóstico bounded do helper MoneyPrinterTurbo |
| Pipeline Música | Menu expansível com Criação de Músicas e Upload Música |
| Blueprints Youtube | Leitura da pasta `storage/blueprints/`, upload/validação de JSON e criação a partir de link YouTube |
| Brandings | Subaba própria dentro de Blueprints, upload/listagem de Brandings e criação conjunta com Blueprint |
| Canais Youtube | Subabas de importação pública sem API Key, Canais em lote gmail por conta Google/YouTube via OAuth e cadastro manual independente; cartões com botão Editar, nicho/referências visível, Prompts do Canal/Blueprint, Narrador/voz e gestão dos últimos 10 vídeos |
| Criação de Vídeos / Criação de Músicas | Subabas Criar vídeo e Vídeos; idiomas históricos preservados e dez códigos MoneyPrinterTurbo com bandeiras; Pexels/Pixabay, full IA com Estilo IA e Apenas Música com agente musical; a segunda página reutiliza o mesmo fluxo com título próprio |
| Upload Música | Subabas **JewelMusic**, **Pushtunes**, **ytmusicapi** e **DistroKid** para upload/sincronização musical com credenciais e histórico locais |
| Automação | Menu expansível com a subaba **Automação Youtube**, onde ficam os vídeos e canais, selectores editáveis de Blueprint/voz padrão, Automação ON, horário diário HH:MM e worker local baseado no relógio do computador |
| AI Influencers | Menu expansível com Personagens, Geração de Conteúdo IA, Motion Control, UGC Products e Redes Sociais; Personagens aceita múltiplas imagens e documentos `.md`/`.json`, e os dois workflows standalone guardam os resultados localmente sem Telegram ou publicação social |
| Niche Finder | Menu expansível com duas alternativas independentes: Niche Finder Kaggle e Niche Finder Apify, com parâmetros, execução e resultados separados |
| Edição | Menu expansível abaixo de Automação com Limpador de Metadados, Clip Generator local em Cortes e Editor Python inspirado no PYEdit para vídeos e scripts locais |
| Upload | YouTube via `youtube-automation-agent` adaptado internamente, fallback ordenado API Oficial → Upload directo → Postiz, Upload-Post textual e destinos locais Bilibili/TikTok/Instagram/Facebook Pages |
| MCP | Catálogo local opcional de Short Video Maker, AutoVio, OpenMontage e OpenCut, com portas editáveis e activação |
| Configurações | **Contas Google**, **Configuração API** e **Notificações**; Notificações contém as subabas **Geral** e **Telegram Gateway**, com envio das mesmas operações locais para um Chat ID; API Keys divididas entre **Serviços e modelos**, **API Tiktok** e **Fontes de materiais**, com várias chaves independentes por fonte, além de contas Google/YouTube por cartão, `INNERTUBE_API_KEY` global para todas as contas, providers, TTS, Nano Banana, Postiz, TikTok e Upload-Post |
| Launcher | Execução via `npx`, instalação assistida, diagnóstico e preparação para distribuição |

## AI Influencers — personagens e geração de conteúdo

A área **AI Influencers > Personagens** permite guardar um personagem com nome, biografia, idioma, Instagram Business ID opcional, várias imagens de referência e documentos `.md` ou `.json`. O campo **Idioma** é um selector que reutiliza exactamente a lista, os códigos e os labels visuais de **Pipeline Vídeos > Criação de Vídeos**. Cada asset é validado, sanitizado, deduplicado por SHA-256 e guardado separado do perfil; imagens têm pré-visualização e documentos são mostrados como Markdown ou JSON estruturado.

O backend local predefinido é **SQLite**, por isso Personagens e Geração de Conteúdo IA funcionam imediatamente sem credenciais externas. Em **Configurações > Configuração API > AI Influencers**, o selector **Backend da base de dados de AI Influencers** aparece logo abaixo do estado do backend. O card **Supabase** contém apenas **Supabase Project URL** e **Supabase API key**. Se **Supabase** estiver seleccionado mas faltar qualquer uma dessas credenciais, o **Backend activo** muda automaticamente para **SQLite**; quando ambas estão preenchidas, passa para Supabase. O SQLite usa internamente `storage/state/ai_influencers.db` e `storage/influencers/`, sem campos editáveis de caminho ou Storage bucket. O botão **Testar ligação do backend** é read-only e não bloqueia a utilização local. A base SQLite fica na pasta persistente do Thunderbolt, fora da instalação temporária do pacote npm; durante uma actualização normal, personagens, assets e configurações são preservados. Se uma versão anterior tiver guardado `ai_influencers.db` no cache npm, o instalador procura uma cópia válida e recupera-a sem substituir uma base persistente já existente.

A página **AI Influencers > Geração de Conteúdo IA** contém as subabas **Imagens** e **Vídeos**. Imagens usam os cartões activos do **Pool Imagem**; Vídeos usam os cartões activos do **Pool Vídeo** e exigem uma imagem inicial image-to-video. O selector de modelo não está preso ao Veo 3.1: pode utilizar KIE AI, Replicate, FAL AI, Pollinations ou outro cartão que declare suporte para vídeo. Para Replicate, o campo Modelo deve conter o identificador aceito pela API, como `owner/model` ou `owner/model:version`; a tarefa usa `POST /v1/predictions`, consulta o estado assíncrono e guarda o resultado localmente. A publicação para Instagram, TikTok, YouTube Shorts ou Facebook não é automática.

A página **AI Influencers > Motion Control** adapta apenas a criação do workflow Kling 2.6 Motion Control. O formulário recebe um vídeo original `.mp4`/`.mov` de 3–30 segundos, uma imagem `.jpg`/`.jpeg`/`.png` até 10 MB e um prompt opcional até 2500 caracteres. Os ficheiros são preservados no storage local, enviados temporariamente para o upload oficial KIE e usados em `POST /api/v1/jobs/createTask`; o estado é consultado em `/api/v1/jobs/recordInfo`, o MP4 é descarregado imediatamente e a tarefa é guardada no backend AI Influencers. Não existe callback público, Telegram, Postiz, Google Drive, upload ou publicação social.

A página **AI Influencers > UGC Products** adapta somente a criação do workflow Gemini/VEO3. Recebe uma imagem local do produto e o campo **Roteiro de vídeo**. Um roteiro dividido por `---` é respeitado directamente; caso contrário, o pool LLM estrutura dois prompts com regras de continuidade, preservação do produto, acções fisicamente possíveis e sem texto incorporado, legendas ou watermark. Cada segmento usa `POST /api/v1/veo/generate` com `veo3_fast`, `imageUrls`, `duration: 8` e `resolution: 720p`; o polling usa o endpoint oficial `/api/v1/veo/record-info`. O Thunderbolt descarrega os dois MP4, junta-os localmente com FFmpeg e persiste o artefacto final, sem Telegram, Postiz, Drive ou redes sociais.

A migração é baseada no workflow público [AI Agents A-Z — episódio 35](https://github.com/gyoridavid/ai_agents_az/tree/main/episode_35), mas o runtime do Thunderbolt não instala nem executa n8n. Os formulários, Data Tables, waits e subworkflows são substituídos pela UI Streamlit, pelo repositório dual Supabase/SQLite, pelos adapters multimédia e pelos logs/notificações locais. As API keys são sempre configuradas localmente e não devem ser colocadas nos JSONs do workflow ou no GitHub.

## Pipeline de vídeo — fontes e ordem de execução

Em **Pipeline Vídeos > Criação de Vídeos** e **Automação Youtube**, a opção **Pexels/Pixabay** usa a rota stock do [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo): as keywords do roteiro são encaminhadas para a pesquisa da fonte seleccionada, os clips são descarregados e reutilizados localmente, e o motor faz a composição com MoviePy/FFmpeg, respeitando proporção, duração máxima, concatenação, transições, correspondência visual ao roteiro, narração, legendas e música de fundo. As API keys de Pexels e Pixabay são exportadas para o `config.toml` do motor e a fonte efectiva é encaminhada por tarefa, sem depender apenas da fonte global guardada nas configurações. Em **Configurações > Configuração API > API Keys > Imagem e Video Montagem/MoviePy**, cada cartão possui o campo **Prioridade**: o menor número aparece primeiro e a ordenação fica guardada no storage local.

Quando existem cartões activos de **Pexels** e **Pixabay**, a Pipeline tenta primeiro a fonte seleccionada na tarefa e, se a falha for específica do provider stock, tenta os restantes providers stock configurados por ordem de prioridade. Falhas de LLM, Azure, áudio local ou configuração estrutural não são mascaradas por um fallback de materiais.

A ordem persistida da criação é **Tema → Script → Título → Keywords opcional → Vídeo → Prompt Thumbnail em JSON → Thumbnail → Upload**.
O vídeo é materializado antes do prompt e da imagem da thumbnail; uma falha posterior de thumbnail não invalida um MP4 já pronto. **Full IA** é uma rota separada e usa o pool de vídeo configurável com **FAL AI, KIE AI, Agnes AI, Nano Banana, Replicate AI, Pollinations.ai, Hugging Face Inference API, InferencePort Proxy e HeyGen**, respeitando apenas cartões activos que declarem capacidade de vídeo. **Apenas Música** não chama a pipeline de vídeo nem tenta gerar thumbnail: reutiliza o áudio local/Suno já descarregado e deixa-o pronto para a integração de upload musical.

Quando uma etapa falha, a tarefa, a notificação e a página **Configurações > Logs** guardam e mostram sempre a coluna **API/Provider**, o serviço, a rota e, quando aplicável, os campos de configuração em falta. No caso do MoneyPrinterTurbo, os marcadores `LLM_PROVIDER`, `MISSING` e `INVALID` são convertidos em attribution legível; por exemplo, um erro pode indicar simultaneamente **OpenAI / NVIDIA NIM API** e **Pexels API**, em vez de apresentar apenas a mensagem genérica de credenciais adicionais. Os timeouts `azure_tts_v1`/`edge_tts` são identificados como **Azure Speech / edge_tts API**. Quando há Azure Speech key e região, o worker encaminha a voz para o SDK Azure Speech V2. Para evitar o limite de 10 minutos da síntese em tempo real documentado pela [Microsoft](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-services-quotas-and-limits), o helper divide o roteiro em segmentos seguros, sintetiza-os sequencialmente com retry e concatena o MP3 antes de o entregar ao MoneyPrinterTurbo como áudio customizado. O erro `1007`/`600000ms` é atribuído explicitamente à **Azure Speech SDK V2 API**. Sem credenciais Azure, o fallback edge_tts usa um timeout interno de 90 segundos. O worker invoca o helper com `--` antes das flags MoneyPrinterTurbo, porque `mpt_agent.py` reserva esses argumentos para a CLI filha. Registos históricos sem metadata são identificados explicitamente como anteriores à attribution estruturada.

Na subaba **Configuração API > API Keys > Imagem e Video**, o selector **Provider de media** inclui a mesma lista do pool Full IA. O cartão **HeyGen** usa a API V3, apresenta os campos **Avatar ID** e **Voice ID**, valida a credencial com uma chamada read-only e participa no failover de vídeo quando estiver activo e configurado. Nano Banana e Hugging Face permanecem disponíveis no catálogo; a participação efectiva no pool de vídeo depende da capacidade declarada pelo cartão, para não encaminhar vídeo para um endpoint que apenas suporte imagem.

## API Tiktok — múltiplas aplicações TikTok

A subaba **Configuração API > API Tiktok** fica entre **Contas Google** e **API Bilibili**. Cada aplicação TikTok é apresentada num card separado e contém apenas **TikTok Client ID** e **TikTok Client Secret**, ambos guardados no storage local. O botão **Adicionar nova API** cria cards adicionais; cada card dispõe de **Guardar card**, **Testar chamada API** e **Apagar card**. A autorização OAuth, os scopes e os tokens de publicação continuam fora desta subaba, no fluxo próprio do TikTok for Developers.

As credenciais antigas dos campos únicos `tiktok_client_key` e `tiktok_client_secret` são migradas automaticamente para o primeiro card sem serem eliminadas. Para compatibilidade com integrações existentes, o adapter TikTok utiliza o primeiro card completo e mantém fallback para os campos legados; a UI não altera os campos pedidos nem mistura Client ID/Secret com tokens, redirect URI ou scopes.

## Upload-Post — publicação para múltiplas plataformas

A página **Upload** contém quatro subabas: **Upload convencional**, **Upload directo**, **Postiz** e **Upload-Post**. A quarta alternativa usa a API oficial do [Upload-Post](https://docs.upload-post.com/) para enviar um vídeo local para uma ou mais plataformas ligadas ao perfil configurado. Seleccione as plataformas na própria subaba, confirme o título e a descrição e clique em **Enviar vídeo pelo Upload-Post**.

A API key, o username/perfil e a lista inicial de plataformas continuam em **Configuração API > API Keys > Serviços e modelos**, no expander **Publicação através do Upload-Post**. **Plataformas Upload-Post** é um campo textual: escreva os slugs separados por vírgulas, como `youtube,tiktok`, tal como os destinos da página Upload. A subaba não pede novamente a credencial. O cliente envia `multipart/form-data` para `https://api.upload-post.com/api/upload`, repete `platform[]` para cada destino e guarda a resposta, o `request_id` e o resultado no histórico local de uploads. A opção **Processar em segundo plano** usa `async_upload=true` quando a API estiver configurada para processamento assíncrono.

O Upload-Post é independente do Postiz: Postiz continua a usar o seu fluxo próprio de asset + post, enquanto Upload-Post publica directamente nas plataformas ligadas ao username configurado. Uma publicação aceite pelo Upload-Post também é reconciliada no centro de **Notificações**.

## Bilibili — upload via bilibili-api (Python)
A opção **Bilibili** está disponível em **Upload > Upload convencional > Destinos**. Seleccione uma conta Bilibili activa, reveja título, descrição, tags e ID da secção, e clique em **Enviar via bilibili-api (Python)**. O adapter usa `bilibili-api-python` 17.4.2, que expõe `Credential` com `SESSDATA`, `bili_jct` e `BUVID3` e executa o `VideoUploader` assíncrono a partir da UI síncrona. A capa usa a thumbnail do vídeo quando existe; caso contrário, é extraído localmente um primeiro frame com FFmpeg.

A subaba **Configuração API > API Bilibili**, colocada entre **API Tiktok** e **AI Influencers**, permite criar, editar, testar e apagar vários cards. Cada card guarda label, estado activo, `SESSDATA`, `bili_jct`, `BUVID3` e campos opcionais `BUVID4`, `DedeUserID`, `ac_time_value` e proxy. Os cookies são campos protegidos, não entram no histórico de uploads nem em logs, e o teste de chamada é read-only. O repositório upstream foi arquivado e encerrado em 2026; por isso a integração é opcional e os erros de disponibilidade do SDK são apresentados sem falhar o arranque do Thunderbolt.

## Upload Música — JewelMusic, Pushtunes, ytmusicapi e DistroKid

A página **Upload Música** contém quatro subabas independentes. **JewelMusic** usa a API documentada do [JewelMusic SDK](https://github.com/jewelmusic/sdk) para enviar tracks com metadados de título, artista, álbum, ano e género; a API key, a Base URL, o proxy opcional e o timeout ficam no storage local. O teste de ligação é read-only e não cria uma track.

**Pushtunes** usa o pacote [Pushtunes](https://pypi.org/project/pushtunes/) instalado pelo Thunderbolt para sincronizar tracks, álbuns ou playlists entre uma fonte Subsonic/Jellyfin/CSV/Spotify/YouTube Music e um destino Spotify/YouTube Music/Tidal/CSV. A UI aceita perfil `.toml`, CSV, `browser.json`, `tidal-session.json`, playlist, similaridade, directório de trabalho e credenciais Spotify; a execução chama o CLI sem shell e mascara segredos na saída. Pushtunes é uma sincronização de biblioteca, não um upload de bytes de um MP3 isolado.

**ytmusicapi** adapta o [ytmusicapi](https://github.com/sigma67/ytmusicapi) para upload directo de MP3, M4A, WMA, FLAC ou OGG para YouTube Music. O método exige um `browser.json` configurado pelo utilizador, que pode ser carregado na subaba e guardado em `storage/ytmusicapi/`; o teste consulta a biblioteca de uploads sem escrever. O histórico de cada operação é guardado localmente em `uploads.json` e não inclui o conteúdo dos segredos.

**DistroKid** adapta somente a etapa de upload do [musikai](https://github.com/igolaizola/musikai): recebe várias faixas e uma capa local, abre o formulário de novo lançamento no browser, preenche artista, título, record label, género e títulos das faixas, e carrega os ficheiros. O cookie de sessão é guardado localmente e nunca é mostrado nos resultados. A submissão final permanece manual no browser; o Thunderbolt não clica automaticamente em Submit. O browser pode usar o Chrome instalado ou um executável indicado na configuração.

As credenciais destes quatro métodos são opcionais e independentes das credenciais de vídeo. O instalador acrescenta `ytmusicapi`, `pushtunes`, `bilibili-api-python` e `playwright`; o adaptador JewelMusic usa o contrato HTTP documentado porque o SDK Python upstream não estava publicado no PyPI no momento da implementação. Consulte `THIRD-PARTY-NOTICES.md` antes de redistribuir o runtime.


## Upload directo — credenciais por conta e por canal

O Upload directo baseado no [YouTube-Video-Upload-Frontend-Api](https://github.com/Nojus10/YouTube-Video-Upload-Frontend-Api) usa um único documento JSON por conta Google. Em **Configurações > Contas Google > Contas Google/YouTube — canais em lote**, cada conta aparece como um cartão expansível identificado por **nome — e-mail**. Dentro do cartão existe o uploader **Subir documento de cookies/credenciais** e o único campo técnico permitido na UI, **sessionInfo token desta conta Google**. Cookies, `chunk_size` e `delegated_session_ids` continuam no documento de cada conta; `INNERTUBE_API_KEY` é configurada uma única vez como chave global para todas as contas e para todo o sistema.

O botão **Adicionar outra conta Gmail** fica abaixo de uma divisória, fora dos cartões existentes. Ao criar uma conta, o Thunderbolt cria imediatamente `credentials.json` com placeholders vazios. Um upload completo ou parcial é incorporado por merge: os cookies enviados actualizam apenas os cookies fornecidos e valores como `sessionInfo`, `chunk_size` e `delegated_session_ids` existentes não são apagados. O alerta de documento incompleto permanece visível por conta quando necessário; a `INNERTUBE_API_KEY` global é validada separadamente.

O documento é guardado por Gmail em `storage/youtube_direct_accounts/<id-da-conta>/credentials.json`, com permissões locais restritas. Em **Canais > Canais cadastrados**, a UI apenas associa o canal à conta Google; essa associação continua permitida mesmo quando o documento está incompleto. O uploader resolve a `INNERTUBE_API_KEY` global nas configurações e procura o ID do canal dentro do mapa `delegated_session_ids` do documento, usando-o como `pageId`/`onBehalfOfUser`; só a operação de Upload directo é bloqueada quando faltarem os dados técnicos. Não existem campos de `INNERTUBE_API_KEY` por conta, nem campos separados de cookies, `chunk_size` ou `DELEGATED_SESSION_ID` na UI.

Os dados são segredos de sessão. Os valores não aparecem em tabelas ou logs, o ficheiro é escrito com permissões locais restritas e não é incluído no Git. O Thunderbolt não extrai cookies automaticamente do browser e não envia as credenciais para o GitHub. O método é não oficial e pode deixar de funcionar se o YouTube alterar os endpoints internos.


Os adaptadores do MoneyPrinterTurbo e de publicação nas plataformas são ligados pelas configurações locais e pelos pontos de integração em `integrations/`. A UI não inventa dados quando um serviço externo ou credencial não está disponível.

## Idiomas e selector rápido da UI

O Thunderbolt mantém os idiomas históricos da criação de vídeos e acrescenta as dez opções canónicas do MoneyPrinterTurbo: **Inglês (en) 🇺🇸**, **Chinês Simplificado (zh) 🇨🇳**, **Alemão (de) 🇩🇪**, **Vietnamita (vi) 🇻🇳**, **Turco (tr) 🇹🇷**, **Português (pt) 🇧🇷**, **Russo (ru) 🇷🇺**, **Espanhol (es) 🇪🇸**, **Indonésio (id) 🇮🇩** e **Italiano (it) 🇮🇹**. Os códigos curtos são os valores persistidos e sincronizados com `ui.video_language` no `config.toml`; a bandeira e o nome são apenas a apresentação visual.

No topo da área principal da aplicação existe o menu nativo de idioma no padrão do MoneyPrinterTurbo, sem sobrepor o toolbar do Streamlit. O selector mostra o rótulo visível **Language** acima do campo, cada opção aparece como **nome do idioma + código**, e a bandeira é uma imagem SVG local real, não um emoji ou sigla dependente da fonte do sistema. Ao escolher outra opção, a preferência é guardada em `storage/state/settings.json` como `ui_language`, e a navegação lateral e o dashboard inicial actualizam-se sem alterar o idioma seleccionado para os vídeos. O indicador de execução, o botão **Deploy** e o menu principal do Streamlit permanecem totalmente nativos e clicáveis.

## Temas claro e escuro

A UI suporta os temas **Dark** e **Light** através do menu nativo de três pontos do Streamlit, no local original do toolbar. Não existe um selector Theme adicional dentro da página. A configuração distribuída em `.streamlit/config.toml` disponibiliza as variantes nomeadas **Dark** e **Light**, e o menu nativo continua responsável por alternar entre os modos, seguindo o padrão do [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo). O CSS próprio do Thunderbolt usa cores semânticas, `currentColor` e `color-mix` para acompanhar o tema activo, sem alterar a posição nem a funcionalidade do toolbar, do botão Deploy e do menu principal.

## Navegação da UI 0.3.77

A barra lateral apresenta os níveis principais nesta ordem: **Início**, **Automação**, **Niche Finder**, **Canais/Perfis (Vídeos)**, **Pipeline Vídeos**, **Pipeline Música**, **AI Influencers**, **Edição**, **Growth**, **Documentação** e **Configurações**. **Canais/Perfis (Vídeos)** é expansível e contém **Canais YouTube**, **Blueprints Youtube**, **Contas TikTok**, **Prompt Masters** e **Facebook Pages**, nessa ordem. O menu **Arquivos Base** foi removido por ficar vazio.
**Pipeline Vídeos** contém **Criação de Vídeos**, **Backlog Vídeos**, **Roteiros**, **Thumbnails** e **Upload**; **Pipeline Música** contém **Criação de Músicas** e **Upload Música**; **Automação** contém **Automação Youtube**; **Niche Finder** contém **Niche Finder Kaggle** e **Niche Finder Apify**; **AI Influencers** contém **Personagens**, **Geração de Conteúdo IA**, **Motion Control**, **UGC Products** e **Redes Sociais**. O Início reúne o dashboard e as filas do Pipeline, sem botões de acções rápidas.

A subaba **Tutorial Supabase** apresenta o guia de criação das tabelas `plans` e `posts` e do bucket `instagram-images`, com ligação para a fonte original no GitHub. As duas frases promocionais da comunidade foram omitidas. Todas as subabas internas também são localizadas pelo helper nativo de tabs:

O conteúdo interno das páginas também é localizado, não apenas a navegação: títulos, subtítulos, descrições, labels de campos, placeholders, opções de selectores, botões, avisos, mensagens de sucesso/erro, estados vazios, métricas, expanderes e blocos Markdown/HTML são traduzidos no idioma seleccionado através da camada global de conteúdo. Valores técnicos, chaves de estado, IDs de formulários, nomes de ficheiros, URLs e dados introduzidos pelo utilizador permanecem inalterados.

Todas as subabas internas também são localizadas pelo helper nativo de tabs: **Blueprints/Brandings**, **Pesquisa pública/Cadastro manual/Contas cadastradas**, **Upload/Biblioteca**, **Importar do YouTube/Canais em lote gmail/Cadastro manual**, **Criar vídeo/Vídeos**, **Novo roteiro/letra/Histórico guardado**, as três abas de análise de clusters, as quatro abas de cortes, **Vídeos/Código Python**, as quatro opções de Upload, **JewelMusic/Pushtunes/ytmusicapi**, **API Keys/Teste de vozes**, os expanders **Imagem e Video Montagem/MoviePy** e **Imagem e Video IA**, **Client MCP/Servidor MCP/Skill** e **Notificações/Geral/Telegram**. As chaves técnicas e a ordem funcional permanecem inalteradas.

Dentro de **Configurações > Contas Google**, a UI contém os cartões expansíveis de contas Google/YouTube, `sessionInfo` por conta, documentos de Upload directo, o formulário **Adicionar outra conta Gmail**, o bloco global de `INNERTUBE_API_KEY` e a configuração global do YouTube (OAuth Client ID, OAuth Client Secret e YouTube Data API Key). A página **Configuração API** contém as restantes credenciais, providers, modelos, serviços, os expanders **Imagem e Video Montagem/MoviePy** e **Imagem e Video IA**, TikTok e Postiz.

Em **Configuração API > API Keys**, o expander **Imagem e Video Montagem/MoviePy** segue o padrão do MoneyPrinterTurbo: seleccione uma fonte — **Pexels**, **Pixabay**, **Coverr**, **WaveSpeed AI**, **LoomLoom**, **TwelveLabs** ou **Ficheiros locais** — e introduza as API keys dessa fonte. **Adicionar outra chave** cria outra linha para a mesma fonte; as listas são guardadas separadamente por fonte, deduplicadas e exportadas para o `config.toml` do motor como arrays para rotação. O expander não expõe endpoint, proxy, qualidade, codec, FFmpeg, Whisper, directório ou filtros técnicos: esses valores permanecem internalizados e a fonte local não requer credencial. Ele aparece acima do expander **Imagem e Video IA**.

O expander **Imagem e Video IA** mantém as credenciais dos providers de geração que não são fontes de montagem. A chave `gemini_image_api_key` da Nano Banana continua separada de `gemini_api_key` do LLM textual. `INNERTUBE_API_KEY` permanece exclusivamente em **Configurações > Contas Google**, no bloco de configuração global fora dos cartões, e não é duplicada em API Keys.

A área expansível **Voz, TTS e música — Azure Speech, restantes serviços e Suno** está organizada em cartões independentes para **Azure Speech**, **ElevenLabs**, **SiliconFlow**, **MiniMax TTS**, **Chatterbox**, **Sonilo** e **Suno**. Cada cartão contém apenas os campos do respectivo serviço e o seu próprio botão de diagnóstico; o Suno fica visualmente separado por ser um agente de criação musical, não um provider TTS. Em **Pipeline Vídeos > Criação de Vídeos > Configurações de áudio**, o modo **Upload** disponibiliza um uploader de narração, botão para guardar o ficheiro, pré-visualização e validação antes da criação. O caminho é passado ao MoneyPrinterTurbo através de `--custom-audio-file`, conforme o fluxo oficial documentado no [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo).

Nos cartões de **LLM — providers e modelos**, o campo **Prioridade** define a ordem de tentativa do pool textual. O valor **1** é usado primeiro; em quota, timeout, erro de transporte ou falha transitória, o router tenta a prioridade **2**, depois **3** e assim sucessivamente. O checkbox antigo **LLM principal** deixou de existir. O card **Limite LLM NVIDIA NIM** fica dentro deste mesmo expander, acima dos cartões de providers, e os seus controlos continuam partilhados pela UI, pipeline e automações. Quando **LLM Telegram** está marcado, o cartão fica reservado exclusivamente às notificações Telegram: o campo Prioridade é desactivado e o cartão é excluído do pool textual normal. A chave interna de cartão activo continua apenas como espelho de compatibilidade para instalações antigas.

O expander **Imagem e Video IA** reúne cartões independentes para **Nano Banana**, **Pollinations.ai**, **Agnes AI**, **Hugging Face Inference API**, **Cloudflare Workers AI**, **InferencePort Proxy**, **阿里云 (Alibaba Cloud Model Studio)**, **KIE AI** e **FAL AI**. Cada cartão permite configurar API key/token quando necessário, modelo, Base URL, activar o provider, escolher participação no **Pool Imagem** e/ou **Pool Vídeo**, definir prioridade e executar **Testar Chamada API**. Os parâmetros técnicos de composição, como **Image Size** e **Aspect Ratio**, não são apresentados nem editáveis nos cartões: ficam como defaults internos e são acrescentados automaticamente ao prompt da geração de imagem e/ou vídeo. O InferencePort usa por defeito `http://localhost:8080/v1` e não exige chave; o Cloudflare requer Account ID; os restantes providers devem ser preenchidos de acordo com a conta e endpoint disponibilizados pelo serviço.

O router mantém três pools independentes: **LLM textual**, **imagem** e **vídeo**. O failover só passa ao cartão seguinte em quota, timeout, erro de transporte ou HTTP transitório; erros de credencial, endpoint/modelo inexistente ou payload inválido ficam registados e não são mascarados por um provider diferente. O pool de vídeo externo é opcional: quando desligado, o worker continua a usar o motor local MoneyPrinterTurbo; quando ligado, usa apenas os cartões marcados para Pool Vídeo.

No bloco **Limite LLM NVIDIA NIM**, a opção **Activar limitador NVIDIA NIM — 40 RPM** reserva no máximo 40 pedidos por janela configurável para cada cartão/chave cujo endpoint seja `integrate.api.nvidia.com`. O estado do limitador é persistido localmente e partilhado entre geração manual, pipeline e automações. A opção vem desligada por defeito para preservar o comportamento anterior.

A correcção da integração Nano Banana remove o campo de entrega `inline` rejeitado pelo contrato actual da Interactions API e mantém a edição de lettering com imagem de referência quando suportada pelo provider.

A página **AI Influencers > Tutorial Meta** apresenta o guia de configuração de uma conta Instagram profissional e das credenciais Meta para automações com n8n, distribuído localmente em `seed/references/guide-instagram.md` e com ligação para a [fonte original no GitHub](https://github.com/gyoridavid/ai_agents_az/blob/main/episode_8/guide-instagram.md). A página **Configurações > Notificações** mantém um histórico persistente de conclusões e falhas, reconcilia estados escritos por componentes locais e disponibiliza um checkbox independente para cada operação mapeada. A subaba **Geral** mantém esse centro local; a subaba **Telegram** permite configurar Bot Token, Chat ID e proxy opcional e envia as mesmas notificações pela Bot API oficial, sem polling ou mensagens recebidas. As notificações novas também aparecem automaticamente como pop-ups no canto inferior direito enquanto o utilizador está noutra página, sem precisar de abrir Notificações; cada aviso é mostrado uma vez por sessão e o histórico continua a controlar o estado de leitura. A página **Configurações > Logs**, colocada imediatamente abaixo de Notificações e acima de Configuração API, apresenta o histórico unificado de tarefas e notificações, com filtro livre por operação, filtros adicionais por operação e estado, e as colunas Operação, Estado, Data, Hora, Registo, Origem, Progresso e Detalhes. A tabela mantém uma barra vertical e, quando a soma das colunas excede a largura disponível, disponibiliza também uma barra de rolagem horizontal na parte inferior para consultar integralmente células longas, sobretudo em **Detalhes**.

A página **Edição > Download Mídia** utiliza a API Python do [yt-dlp](https://github.com/yt-dlp/yt-dlp) para descarregar vídeos e áudio de URLs públicas, com qualidade, contentor, formato de áudio, legendas, metadados, playlists, progresso e histórico local em `storage/downloads/` e `storage/state/media_downloads.json`. O Thunderbolt instala o pacote Python **Deno** e resolve automaticamente o executável gerido por ele, passando-o ao yt-dlp como runtime `deno:<caminho>`. O pacote `yt-dlp[default]` inclui também os scripts EJS necessários para os desafios JavaScript do YouTube. Se existir um Deno instalado no `PATH`, ele é usado como fallback. Conversão e combinação de streams podem exigir FFmpeg.

## Catálogo comum do Backlog e da Automação

**Backlog Vídeos** e **Automação Youtube > Vídeos cadastrados** usam o mesmo catálogo completo persistido em `storage/state/tasks.json`. Assim, todas as tarefas criadas manualmente ou pela automação diária aparecem nos dois fluxos, sem duplicação nem filtros implícitos por origem. O filtro de estado do Backlog mantém os estados conhecidos e acrescenta estados novos encontrados no storage.

Os dois cards mostram de forma consistente o estado técnico, o rótulo legível, a barra de progresso, a etapa e o formato do vídeo. São suportados estados como `to_do`, `doing`, `blocked`, `done`, `failed` e `cancelled`; formatos ausentes usam `format`, `style_wide` ou `wide` como fallback. Quando existe `artifacts.video`, o Backlog mostra que o vídeo está pronto e disponibiliza a descarga do MP4 mesmo que a thumbnail esteja pendente.

Em **Automação Youtube > Vídeos cadastrados**, o botão **Start** retoma a tarefa a partir dos artefactos persistidos. O worker reutiliza o roteiro, título/keywords, MP4, prompt de thumbnail e imagem já existentes; só volta a gerar uma etapa quando o respectivo resultado não está disponível, e repete o upload apenas quando ele ainda não foi concluído. O botão **Apagar** remove o vídeo da fila e de `tasks.json` após confirmação, preservando os ficheiros de artefactos; tarefas em execução devem ser paradas antes de serem removidas.

**Não existe expiração automática de vídeos ou limpeza periódica da fila.** As actualizações normais não usam `--purge-data`, preservam o storage local e, quando encontram uma instalação antiga juntamente com um storage novo, unem as tarefas e filas por ID em vez de substituir a lista. Se `tasks.json` ficar corrompido, a aplicação preserva a cópia danificada e interrompe a leitura protegida para evitar apresentar uma fila vazia e gravá-la por cima dos dados existentes. A remoção de uma tarefa só ocorre por confirmação explícita em **Apagar** ou pela opção destrutiva `--purge-data`.

## Canais Youtube — edição por cartão e vídeos recentes

A página **Canais Youtube** mantém o cadastro e a importação existentes, mas cada cartão agora tem o botão **Editar**. O editor permite alterar nome, URL, handle, idioma, estilo wide, **Nicho**, **Blueprint Padrão**, **Narrador/Voz Padrão**, conta Google do Upload directo, descrição e Automação ON/horário. O nicho aparece imediatamente abaixo do nome do canal no cartão; quando não existe, a UI mostra **SEM NICHO CONFIGURADO**.

Os quatro blocos compactos do cartão usam a nomenclatura solicitada: **Blueprint Padrão**, **Nicho**, **Narrador/Voz Padrão** e **Idioma**. Os botões de acção abrem o mesmo editor persistente, sem criar um segundo canal nem perder as associações existentes.

Abaixo do cartão, a secção **Últimos 10 vídeos publicados** fica num expander fechado por defeito e usa o feed público RSS do YouTube, sem Data API Key. O carregamento ocorre quando se clica em **Actualizar últimos 10 vídeos**, evitando chamadas automáticas ao abrir a página. Os vídeos ficam guardados em `storage/state/channel_videos.json` e são apresentados apenas no modo **Lista**. Cada vídeo tem **Editar vídeo** para alterar localmente o título, estado, data, URL e notas. A fonte pública não substitui o vídeo nem publica alterações no YouTube; os campos editáveis são overrides locais de gestão.

## Criação de Vídeos — geração editorial por canal

A aba **Criação de Vídeos** permite escrever manualmente o **Tópico ou briefing** ou usar **Gerar tópico/briefing com IA**. A geração usa o pool **LLM textual** configurado localmente em **Configuração API > API Keys > LLM — providers e modelos**, incorpora o Blueprint, a descrição, o idioma e a voz do canal e só ocorre depois do clique do utilizador. Se não houver credenciais ou modelo, a UI mostra uma mensagem accionável e não inventa conteúdo. Quando o limitador NVIDIA está activo, todas as chamadas LLM passam pelo mesmo contador persistente de 40 RPM.

Entre **Canal** e **Estilo wide**, a UI mostra o Blueprint padrão resolvido do canal, a voz associada e o **Idioma** configurado nesse canal. Ao trocar o canal, o selector **Script Language** é sincronizado automaticamente com o código canónico do novo canal, incluindo a conversão de rótulos legados como `Português` ou `36 – Português (Brasil)`. O valor sincronizado é usado no roteiro, keywords, geração criativa e payload da tarefa; o idioma global só serve como fallback quando não existe canal seleccionado. Quando não existe configuração, apresenta **SEM BLUEPRINT CONFIGURADO** e mantém o idioma do canal visível. Depois do tópico e do título inicial, **Gerar Thumbnail com IA** gera apenas um briefing/prompt de thumbnail e preserva o título existente, sem chamar o gerador de títulos. Em lotes no mesmo canal, é gerada uma variante independente por vídeo e o payload correspondente é atribuído a cada task. A geração da imagem final passa pelo **Pool Imagem**, com failover para os cartões activos elegíveis; as thumbnails guardam conceito, overlay de até quatro palavras, composição, cores, prompt e sinergia com o título.

A cascata de criação no worker segue agora a ordem **Tema → Roteiro → Título → Keywords → Vídeo → Prompt da thumbnail em JSON → Thumbnail (gerar imagem) → Upload**. O vídeo é guardado em `artifacts.video` e marcado como `video_ready` antes de qualquer chamada ao provider de imagem. Se a quota da imagem for excedida, a tarefa pode ficar em falha na etapa Thumbnail, mas o MP4 permanece pronto no Backlog para descarregar, utilizar no Upload ou editar a thumbnail posteriormente.

O pacote editorial é persistido na task. O título e as keywords são preparados antes do vídeo; o prompt JSON e a variante visual são criados depois de existir um MP4 válido. A thumbnail é usada no Upload quando existe um ficheiro em `artifacts.thumbnail`. Sem provider de imagem configurado, a aplicação conserva o prompt e apresenta **Prompt de thumbnail pronto — imagem pendente de provider de imagem**, sem criar um PNG falso. A página **Thumbnails** continua a permitir gerar a imagem ou carregar manualmente uma PNG, JPG, JPEG ou WEBP para a tarefa.

No modo **Lote geral**, o Thunderbolt remove a selecção parcial e processa automaticamente todos os canais cadastrados. **Gerar Thumbnail com IA para todos os vídeos** percorre os tópicos individuais já preparados e gera apenas uma thumbnail por canal/vídeo, sem regenerar títulos. É criada exactamente uma tarefa por canal, com briefing, título, thumbnail, Blueprint, voz e contexto próprios; o mesmo tópico nunca é reutilizado para todos os canais. A Automação diária usa o mesmo serviço no horário local de cada canal e não cria o placeholder antigo quando o provider LLM não está configurado.

## Automação Youtube — layout compacto por canal

A aba **Automação Youtube** usa um cartão compacto de duas linhas. Na primeira ficam avatar, nome, handle, **Automação ligada** e **Horário (HH:MM)**; na segunda ficam **Idioma Padrão**, **Nicho Padrão**, **Blueprint Padrão**, **Narrador/Voz Padrão** e o botão **Guardar**. As chaves e funções dos controlos permanecem as mesmas: Blueprint e Narrador/Voz são editáveis, enquanto Idioma e Nicho são apresentados a partir do canal.

## OpenAI/ NVIDIA NIM — descoberta de modelos

Em **Configuração API > API Keys > Serviços e modelos > LLM — providers e modelos**, a área anteriormente chamada **OpenAI — API key, Base URL e modelo** passa a chamar-se **OpenAI/ NVIDIA NIM — API key, Base URL e modelo**. O campo de modelo manual usa o parâmetro `help` suportado pelas versões do Streamlit instaladas pelo Thunderbolt, evitando o erro de argumento `help_text`. O provider interno continua a ser `openai`, para preservar a compatibilidade com o MoneyPrinterTurbo e com os restantes endpoints OpenAI-compatible.

A Base URL predefinida para NVIDIA NIM é `https://integrate.api.nvidia.com/v1`. Depois de inserir a API key, clique em **Consultar/actualizar modelos NIM**. O Thunderbolt consulta a Base URL acrescentando `/models`, lê os identificadores do formato OpenAI (`data[].id`) e apresenta-os num selector. O modelo escolhido é guardado em `openai_model_name` e é sincronizado para o `config.toml` do motor.

A consulta só é executada quando o utilizador carrega no botão; a aplicação não envia a API key ao abrir a página. Se o endpoint estiver offline, recusar a credencial ou não disponibilizar `/models`, a UI mostra o erro sem expor a API key e mantém a opção **Escrever modelo manualmente**. Também é possível manter um endpoint local NIM ou outro servidor OpenAI-compatible substituindo a Base URL.

## Contas Google/YouTube e OAuth local

Para autorizar uma conta, use no Google Cloud um cliente OAuth do tipo **Desktop app**. O Thunderbolt usa o loopback local determinístico `http://127.0.0.1:8765/`, abre o browser e guarda o token por conta. Se estiver a usar um cliente do tipo Web application, adicione exactamente essa URI em **Google Cloud > APIs e serviços > Credenciais > URIs de redireccionamento autorizados**; a URI deve incluir a porta e a barra final. O erro `400: redirect_uri_mismatch` significa que a URI registada no cliente Google não coincide exactamente com a enviada pela aplicação.

A área **Contas Google/YouTube — canais em lote** permite manter várias contas em cartões expansíveis com nome e e-mail. Cada cartão tem OAuth Client ID, OAuth Client Secret, sessionInfo e documento de Upload directo; o formulário separado **Adicionar outra conta Gmail** cria o documento padrão automaticamente. Use **Apagar conta** para remover a conta, os tokens e os dados directos associados. O sessionInfo é sincronizado com o documento JSON da própria conta; cookies e os restantes parâmetros de Upload directo permanecem apenas nesse documento.

## Instalação

Recomenda-se Python 3.11 ou superior e Node.js 18 ou superior.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

No Windows PowerShell:

```powershell
py -m venv .venv
.venv\\Scripts\\Activate.ps1
python -m pip install -r requirements.txt
```

## Execução

A porta da aplicação é `3030`:

```bash
python -m streamlit run app/main.py --server.port 3030
```

Ou através do launcher Node:

```bash
node scripts/cli.mjs --check
node scripts/cli.mjs
```

O comando normal inicia a UI e o worker local de Automação. O worker verifica o relógio local do computador e coloca na fila os lotes de canais com **Automação ON** quando o horário `HH:MM` coincide. Para executar apenas o worker, sem abrir a UI:

```bash
node scripts/cli.mjs worker
```

O pacote está publicado no npm como `@danhachuel/thunderbolt` e pode ser executado directamente via `npx`:

```bash
npx --yes @danhachuel/thunderbolt
```

Para instalar automaticamente o ambiente completo — Python 3.11+, ambiente virtual, dependências Python do Thunderbolt, dependências Python do MoneyPrinterTurbo, Streamlit e `imageio-ffmpeg` — execute:

```bash
npx --yes @danhachuel/thunderbolt install
```

Por defeito, o instalador cria automaticamente a pasta `~/.thunderbolt` — no Windows, `%LOCALAPPDATA%\\THUNDERBOLT` —, clona o MoneyPrinterTurbo para `THUNDERBOLT/MoneyPrinterTurbo`, cria o ambiente em `THUNDERBOLT/.venv` e guarda o estado em `THUNDERBOLT/storage`. No Windows, se Python 3.11+ não estiver instalado, o instalador tenta instalá-lo automaticamente através do `winget`. A instalação normal é segura para actualizações: preserva `storage`, Blueprints, Brandings, configurações e artefactos, removendo apenas `.venv` e o clone técnico do MoneyPrinterTurbo para os recriar. A antiga pasta sem dados do utilizador em `C:\Users\<utilizador>\AppData\Local\hermes` pode ser removida. O caminho `AppData\Local\npm-cache\_npx` é apenas cache temporária do npm, não é a pasta de instalação final. Para apagar dados intencionalmente, use o parâmetro explícito `--purge-data`; nunca o use numa actualização normal. Para usar uma cópia existente do MoneyPrinterTurbo:

```bash
MONEYPRINTER_PATH=/caminho/MoneyPrinterTurbo npx --yes @danhachuel/thunderbolt install
```

Para instalar apenas a UI sem clonar o MoneyPrinterTurbo:

```bash
npx --yes @danhachuel/thunderbolt install --skip-moneyprinter
```

Para verificar o ambiente sem iniciar a aplicação:

```bash
npx --yes @danhachuel/thunderbolt doctor
```

Para executar apenas o diagnóstico do ambiente:

```bash
npx --yes --package=@danhachuel/thunderbolt thunderbolt --check
```

Para instalar globalmente e disponibilizar o comando `thunderbolt`:

```bash
npm install --global @danhachuel/thunderbolt
thunderbolt
```

No Windows PowerShell, se `npx` for bloqueado por `npx.ps1`, use directamente `npx.cmd`:

```powershell
npx.cmd --yes --prefer-online @danhachuel/thunderbolt@0.3.44 install
npx.cmd --yes --prefer-online @danhachuel/thunderbolt@0.3.44 doctor
npx.cmd --yes --prefer-online @danhachuel/thunderbolt@0.3.44
```

Como alternativa, pode permitir scripts para o seu utilizador:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Ou apenas para a sessão actual:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Após `install`, o launcher usa o ambiente virtual instalado em `~/.thunderbolt/.venv` — no Windows, `%LOCALAPPDATA%\\THUNDERBOLT\\.venv` — e inicia a UI em `localhost:3030`. No Windows, a raiz é `%LOCALAPPDATA%\\THUNDERBOLT`; no computador indicado, o caminho será `C:\\Users\\danha\\AppData\\Local\\THUNDERBOLT`. Isto evita a redirecção de `HOME` que pode ocorrer no MobaXterm.
 O instalador não instala drivers de GPU, Docker, chaves de API, modelos Whisper ou credenciais de plataformas; esses componentes continuam dependentes do sistema e da configuração do utilizador. Para desenvolvimento a partir do clone, continue a usar `node scripts/cli.mjs`.

## Niche Finder

O menu expansível **Niche Finder** contém duas alternativas independentes. **Niche Finder Kaggle** é a página actual de análise e integra a lógica do projecto open source [johanfortus/Niche-Finder](https://github.com/johanfortus/Niche-Finder) directamente no processo Streamlit. O Thunderbolt não inicia Flask, não abre uma porta adicional e não copia templates HTML ou D3. Ao abrir a página, o Thunderbolt não descarrega dados, não prepara o dataset e não executa análises. A instalação das dependências continua automática, mas a operação é manual: o utilizador define os parâmetros dentro da própria aba e clica em **Analisar Nichos**. Só nesse momento o KaggleHub prepara ou reutiliza a cache local do dataset e a análise é executada.

A interface apresenta dentro da aba os parâmetros da busca: número de clusters entre 2 e 10, suporte mínimo entre 0,01 e 0,50, país, categoria de engagement, intervalo de datas e tags. A página permanece sem resultados até o primeiro clique em **Analisar Nichos**; depois, se os parâmetros forem alterados, mostra os resultados anteriores e pede novo clique para aplicar os filtros actuais. O núcleo aplica normalização, filtros, `log1p`, `StandardScaler`, K-Means e FP-Growth. Os resultados aparecem em DataFrames para clusters, itemsets frequentes, regras de associação e dados analisados, acompanhados por uma visualização Plotly nativa e pesquisa de palavras nos clusters.

**Niche Finder Apify** é a segunda alternativa e não usa o dataset, filtros, execução ou resultados Kaggle. Define três palavras-chave, período, limite de resultados, Shorts, duração, idioma de legendas e ordenação; depois de clicar em **Pesquisar no Apify**, inicia o actor `streamers~youtube-scraper`, acompanha o run, carrega o dataset, normaliza vídeos, limpa SRT, calcula VSC Ratio e tenta resumir as transcrições com o provider LLM configurado. Os resultados ficam na sessão própria `niche_apify_results`, o histórico pequeno fica em `storage/state/niche_apify_runs.json` e existem exportações JSON/CSV. Configure o **Apify API Token** em **Configuração API > API Keys > Serviços e modelos**. As dependências adicionais são instaladas pelo fluxo normal do pacote: `requests`, `pandas` e os componentes já existentes da análise. Em instalações existentes, execute novamente `npx.cmd --yes --prefer-online @danhachuel/thunderbolt@0.3.44 install`; o instalador detecta e reutiliza componentes já válidos.

## Editor Python baseado no PYEdit

O **Editor Python** combina o recorte seguro do [PYEdit](https://github.com/Congren/PYEdit) com o armazenamento local do Thunderbolt. Na subaba **Vídeos**, pode escolher um vídeo já gerado e registado nos artefactos da pipeline, indicar qualquer pasta local de vídeos ou fazer upload manual. A página não inicia nenhuma edição ao ser aberta.

As operações disponíveis são cortar trecho, remover áudio, extrair áudio, substituir áudio, alterar velocidade e redimensionar vídeo. Cada operação cria uma cópia em `storage/python_editor/outputs/`, preserva o original, regista um histórico separado em `storage/state/python_editor_edits.json` e permite descarregar o resultado e um manifesto JSON. As operações usam FFmpeg local, aproveitando a detecção interna e o fallback `imageio-ffmpeg`; a subaba de fontes não expõe caminhos técnicos.

Na subaba **Código Python**, pode criar e guardar scripts em `storage/python_editor/scripts/` ou carregar scripts existentes. Por segurança, a UI não executa código Python, não possui botão de execução e não executa scripts automaticamente.

## Armazenamento local

O sistema cria automaticamente:

```text
storage/
├── blueprints/       # blueprints JSON lidos pela aba Blueprints
├── state/
│   ├── channels.json
│   ├── tasks.json
│   ├── queues.json
│   ├── batches.json
│   ├── uploads.json
│   ├── metadata_edits.json
│   ├── mcp_integrations.json
│   └── settings.json
├── music/             # músicas locais para o modo Apenas Música
├── voice_previews/    # amostras isoladas do teste de vozes
├── data/
│   └── niches/        # dados automáticos cacheados para o Niche Finder
├── skills/            # skill MoneyPrinterTurbo guardada pelo utilizador
├── metadata_cleaner/
│   ├── originals/    # cópias dos vídeos terceiros enviados
│   └── outputs/      # versões com metadados limpos
└── artifacts/        # ficheiros produzidos e caminhos referenciados
```

Para usar outro local, defina `THUNDERBOLT_STORAGE_DIR`. O estado é escrito de forma atómica e ficheiros JSON inválidos são preservados com cópia `.corrupt-*` antes de serem recriados.

## Blueprints Youtube e Brandings

Coloque ficheiros `.json` em `storage/blueprints/canais`, `storage/blueprints/nichos` ou `storage/blueprints/importados`. A aba **Blueprints Youtube** relê a pasta e mostra o conteúdo estruturado. A instalação já inclui 13 Blueprints seed, copiados apenas quando o ficheiro ainda não existe; actualizações não substituem Blueprints locais. Também é possível importar através do carregador da própria interface.

A mesma aba possui a subaba **Brandings**. No formulário **Criar blueprint a partir de link**, cole um link de canal, informe o **Nome do Blueprint**, o nicho e o idioma e escolha entre **Apenas Blueprint** ou **Blueprint + Branding completo**. O nome é guardado no campo `name` do JSON e também é usado no nome do ficheiro. O primeiro modo grava o blueprint forense local; o segundo grava também um ficheiro de Branding com identidade do canal, handle, descrição, hashtags, keywords, prompts de imagem de perfil e banner, direcção visual de thumbnails, assets e checklist de revisão.

O fluxo foi modelado a partir do blueprint de clonagem com Branding anexado, incluindo a distinção entre entrada de canal/vídeo, normalização do link, metadados de nicho/idioma, perfil do canal, estratégia de conteúdo, pesquisa, identidade visual e brand pack. Placeholders de serviços externos são tratados como configuração local; chaves presentes em workflows importados não devem ser commitadas.

## Limpador de Metadados

A aba **Limpador de Metadados** foi adaptada do workflow `YTBMetadataGenerator.json`. Ela recebe apenas um vídeo externo já pronto, guarda uma cópia original separada, remove os metadados do contentor com FFmpeg e grava uma nova cópia com título, descrição, links, timestamps, tags e outros campos opcionais. O original nunca é alterado e os vídeos produzidos pelas páginas **Criação de Vídeos** e **Criação de Músicas** não aparecem nesta área.

A descrição segue a composição do workflow de referência: preview, secção de links e capítulos/timestamps. O resultado inclui um manifesto JSON para utilizar os metadados num fluxo posterior de upload. A versão local não usa o trigger RSS, o Apify ou a actualização automática de um vídeo YouTube; em vez disso, o utilizador fornece directamente o vídeo terceiro e controla a edição antes de publicar.

## Cortes — Clip Generator local

A aba **Cortes** é um Clip Generator local inspirado no fluxo do [OpenShorts](https://github.com/mutonby/openshorts). Permite fazer upload de um vídeo, descarregar uma URL directa de vídeo, seleccionar um vídeo gerado pela pipeline ou escolher uma pasta local. O original é preservado em `storage/cuts/inputs/`.

O formulário apresenta os formatos **9:16 — Shorts/Reels/TikTok**, **1:1 — Feed posts** e **16:9 — YouTube/landscape**, além de opções avançadas para modo automático por segmentos locais ou corte manual, número de clips, durações mínima/máxima e intervalo de início/fim. A execução só começa depois da confirmação explícita de direitos e do clique em **Gerar Clips**.

Os clips são gerados localmente com FFmpeg, redimensionados para o formato escolhido sem ampliar desnecessariamente a fonte e guardados em `storage/cuts/runs/<id>/`. A página apresenta estado de análise, preview dos resultados, download individual, download ZIP, manifesto JSON e histórico em `storage/state/cuts_runs.json`. A selecção automática de momentos virais por IA permanece um ponto de extensão: sem transcrição/provider configurado, o modo manual continua disponível e não são inventados resultados.

## Canais YouTube

A aba **Canais Youtube** está dividida em dois fluxos independentes. Em **Importar do YouTube**, o método padrão **Página pública — sem API Key** consulta a página pública do canal e preenche nome, ID, handle, URL, descrição e thumbnail quando esses dados estão disponíveis. A opção **YouTube Data API — API Key opcional** pode ser escolhida para métricas oficiais quando uma **YouTube Data API Key própria** estiver configurada em **Configurações** ou em `YOUTUBE_API_KEY`; essa chave é distinta do OAuth Client ID e Client Secret.

Em **Cadastro manual**, nenhum pedido ao YouTube é feito e não existe qualquer dependência de API Key. O utilizador pode preencher nome, URL, handle, descrição, métricas, thumbnail, idioma, estilo, Blueprint padrão, voz padrão, `DELEGATED_SESSION_ID` e configuração de Automação. A importação pública nunca grava automaticamente: os dados aparecem num formulário de revisão antes de guardar. A resolução pública aceita URLs `/channel/UC...`, handles e subpáginas; quando existe um ID mas o HTML não traz todos os dados, tenta o feed RSS público. Se o YouTube responder que o canal não existe ou não fornecer metadados, a UI mostra uma mensagem clara e não mantém o formulário de uma pesquisa anterior. Cada cartão de canal tem **Activo** e, logo abaixo, **Apagar canal**, com confirmação; tarefas e artefactos não são apagados.

## Upload YouTube e fallback Postiz

O Upload usa como caminho **principal** a lógica do `PublishingSchedulingAgent` do [youtube-automation-agent](https://github.com/darkzOGx/youtube-automation-agent), adaptada para Python e executada dentro do processo Streamlit do Thunderbolt. Não é necessário instalar ou iniciar um segundo servidor Node. O fluxo valida o MP4 real, constrói `snippet/status`, faz upload resumível e tenta enviar thumbnail e legendas.

Na aba **Upload**, configure primeiro apenas o **YouTube OAuth Client ID** e o **YouTube OAuth Client Secret** em **Configurações**. Em seguida, use **Autorizar agente YouTube**. O navegador local abrirá a autorização Google e o token será guardado apenas em `storage/state/youtube_agent_tokens.json`. Se a publicação principal falhar, o Thunderbolt tenta automaticamente o **OAuth directo de redundância**, usando o token local compatível; a Data API Key nunca é usada para autorizar ou publicar.

Use **Autorizar fallback OAuth** apenas se precisar de uma autorização separada para o caminho de redundância. Os resultados guardam no histórico local qual mecanismo foi utilizado e as tentativas realizadas, sem guardar segredos.

A subaba **Postiz**, dentro de **Upload**, permite carregar as integrações ligadas através de `GET /integrations`, enviar um MP4 para `POST /upload` e criar o post YouTube em `POST /posts`. A API key é enviada como valor bruto do cabeçalho `Authorization`; a base cloud é `https://api.postiz.com/public/v1` e pode ser substituída por uma instalação self-hosted. O modo MCP guarda também a URL Streamable HTTP configurável para uso futuro/alternativo.

O botão principal de YouTube usa a ordem **API Oficial → Upload directo → Postiz**. A API Oficial tem um contador local de cinco envios bem-sucedidos por dia por conta Gmail; quando a quota é atingida, ou o método falha, o Thunderbolt tenta o documento de sessão do Upload directo. Só depois de esse caminho falhar tenta o Postiz, desde que esteja activo, tenha API key e tenha um ID de integração configurado.

A subaba **Upload directo** adapta o [YouTube-Video-Upload-Frontend-Api](https://github.com/Nojus10/YouTube-Video-Upload-Frontend-Api). Ela usa cookies, `sessionInfo`, `INNERTUBE_API_KEY` e `DELEGATED_SESSION_ID` fornecidos manualmente pelo utilizador, cria o vídeo através do endpoint interno e envia o ficheiro em chunks de 256 KiB. Este caminho é experimental, não extrai cookies automaticamente e fica separado do agente YouTube principal.

## Pipeline: Criação de Vídeos, Criação de Músicas e Automação Youtube

Em **Criação de Vídeos**, **Fonte do vídeo** oferece `Montage: Pexels/Pixabay`, `Montage: Text-to-Images`, `Montage: Google Imagem API`, `Full IA: Text-to-Video`, `Remotion`, `Only Music` e `Clipes de Música`. **Montage: Text-to-Images** divide o roteiro em cenas, gera prompts de imagens, sintetiza a narração e monta o MP4 com MoviePy/FFmpeg; `Full IA: Text-to-Video` mantém o pool de vídeo IA existente. **Only Music** aceita apenas uma música já existente em `storage/music/` ou carregada pelo utilizador, gera a thumbnail e não cria vídeo, narração nem música nova. `Montage: Google Imagem API`, `Remotion` e `Clipes de Música` aparecem como placeholders controlados e não permitem submissão nesta versão. **Criação de Músicas** continua a guardar os seus ficheiros em `storage/music/`, que ficam disponíveis automaticamente para **Only Music**.

A subaba **Roteiros**, entre **Criação de Músicas** e **Upload**, permite escolher um canal opcional, um Blueprint, o tipo **Roteiro de vídeo** ou **Letra de música**, idioma, briefing e notas de estrutura. O botão **Gerar com IA a partir do Blueprint** usa o provider LLM configurado, devolve um rascunho Markdown editável e só guarda o documento quando o utilizador confirmar. Os ficheiros ficam em `storage/scripts/` e o índice do histórico em `storage/state/scripts.json`; a própria página mostra o caminho absoluto correspondente ao storage local.

Na subaba **Vídeos** de **Criação de Vídeos**, a frase `Os vídeos são guardados em <storage>/videos` identifica a pasta real onde os artefactos de vídeo devem ser procurados.

O agente musical guarda os ficheiros em `storage/music/`, aceita formatos de áudio comuns e pode descarregar uma URL de áudio devolvida por um endpoint Suno compatível. Em **Canais Youtube**, abra **Definir Blueprint e voz padrão** no cartão do canal para guardar os defaults; em **Automação Youtube**, os mesmos dois selectores aparecem no cartão e são sincronizados. Esses valores são usados automaticamente em novas tarefas criadas para o canal. A aba **Automação Youtube** também guarda `Automação ON` e um horário diário `HH:MM` por canal e lista os vídeos cadastrados. Nos cards, **Start** retoma o processamento sem regenerar etapas já prontas, enquanto **Apagar** remove o card da fila e elimina os artefactos locais associados, incluindo roteiro, áudio/voz, vídeo e thumbnail. O worker continua a ser executado pelo processo local configurado.

## Teste de vozes

A área **Configurações > Configuração API > Teste de vozes** é isolada da pipeline.
 Permite escolher Edge/Azure Speech ou um provider HTTP configurado, seleccionar voz/ID, alterar a velocidade, sintetizar uma amostra, reproduzi-la e descarregá-la. O áudio é guardado em `storage/voice_previews/` e nunca altera vídeos ou tarefas. Se uma instalação antiga não tiver `edge-tts`, execute `npx.cmd --yes @danhachuel/thunderbolt install`; o instalador detecta a dependência em falta sem reinstalar componentes válidos.

## MCP e integrações externas opcionais

A aba **MCP** está organizada em três subabas independentes. **Client MCP** lista **Short Video Maker**, **AutoVio**, **OpenMontage** e **OpenCut** com links oficiais, protocolo/capacidade conhecida, porta local editável, detecção passiva e toggle **Activo**. Os repositórios externos não são clonados, instalados ou incluídos no pacote npm do Thunderbolt.

As portas iniciais são `3123` para Short Video Maker, `3001` para a API backend do AutoVio, `8000` como referência editável para OpenMontage — que não documenta uma porta HTTP padrão — e `8787` para a API do OpenCut, cujo frontend de desenvolvimento usa `5173`. A detecção do Client MCP apenas consulta `localhost` e nunca inicia processos externos.

**Servidor MCP** activa, mediante confirmação explícita na UI, um endpoint local em `http://127.0.0.1:3031/mcp`. O endpoint usa JSON-RPC sobre HTTP POST, disponibiliza ferramentas de leitura para estado da pipeline, canais, vídeos e Blueprints e exige um token quando o host é exposto fora do computador local. As ferramentas de escrita ficam desactivadas por padrão; quando o utilizador as activa, o agente pode criar lotes de vídeos através de uma ferramenta controlada. O endpoint `/health` serve apenas para verificação de disponibilidade.

**Skill** contém exclusivamente os botões para guardar localmente ou descarregar `moneyprinterturbo-video.md`. A skill é guardada em `storage/skills/` e não é misturada com o catálogo de clientes MCP.


## TikTok

A subaba **Vídeos**, dentro de **Criação de Vídeos** ou **Criação de Músicas**, mostra o backlog e permite iniciar/parar tarefas; deixou de existir como botão principal na barra lateral.

As credenciais do TikTok ficam em **Configuração API > API Keys > Serviços e modelos**, no expander próprio de TikTok.
 Para YouTube, o bloco principal pede o OAuth Client ID e Client Secret; a Data API Key, se usada, fica numa área opcional separada. Client ID + Client Secret não formam uma Data API Key nem um token OAuth.
 Redirect URI, scopes, autorização OAuth e tokens são geridos no TikTok for Developers Playground. O adaptador rejeita o upload quando faltam credenciais ou OAuth, em vez de indicar sucesso falso.

## Segurança

Não coloque chaves, cookies, tokens YouTube ou segredos TikTok no Git. Use a configuração local, variáveis de ambiente ou um ficheiro fora do repositório. O `.gitignore` exclui o storage de estado real, ambientes virtuais e ficheiros de segredo. O adaptador interno foi baseado na lógica publicada sob licença MIT do [youtube-automation-agent](https://github.com/darkzOGx/youtube-automation-agent).

## Growth
As páginas **Analista Facebook Pages** e **Analista Bilibili** foram adicionadas ao grupo **Growth** como áreas reservadas e permanecem vazias nesta versão, prontas para futuras implementações específicas.

## Documentação técnica interna
A documentação de API interna, os contratos de persistência, o health check de `sessionInfo` e os diagramas de sequência estão em [`docs/api-internal.md`](docs/api-internal.md). Os ficheiros Mermaid editáveis ficam em [`docs/diagrams/`](docs/diagrams/).

A pipeline do worker usa agora um orquestrador local em cascata, com artefactos retomáveis e transições persistidas. As escritas de estado JSON e de Blueprints usam substituição atómica para evitar documentos truncados após interrupções.

## Selector de modelos LLM
O campo **Modelo** em **Configuração API > API Keys > LLM — providers e modelos** é apresentado como lista suspensa permanente. A lista usa os modelos descobertos pelo endpoint e preserva o modelo guardado; a opção manual continua disponível apenas como fallback explícito.

## Correcção prioritária de geração de vídeo

No fluxo MoneyPrinterTurbo, a voz Azure Speech SDK V2 é preparada antes da CLI upstream. O Thunderbolt divide o roteiro em segmentos conservadores ajustados à velocidade, concatena o áudio localmente e só inicia o motor depois de confirmar o ficheiro e a contagem de segmentos. Se essa preparação falhar, a tarefa é interrompida e não existe fallback silencioso para uma chamada monolítica sujeita ao limite de 600000 ms.

Durante a execução, o backlog mostra a actividade recente do helper e o tempo da etapa Vídeo. Em caso de falha, a mensagem terminal é extraída do output accionável, enquanto as linhas `using existing project` e `updated configuration fields` deixam de ser tratadas como causa. Os caminhos do log e do manifesto são preservados mesmo quando a falha ocorre antes da criação do MP4.

## Correcção de diagnóstico da etapa Vídeo — 0.3.78

A mensagem do card de vídeo deixou de mostrar apenas os primeiros 240 caracteres. A UI apresenta um resumo de erro com até 700 caracteres e disponibiliza um expander não editável com o diagnóstico completo, incluindo os caminhos do log e do manifesto quando existem. Linhas de sucesso de Pexels, sincronização do projecto, verificação do `uv` e marcadores de caminho são excluídas do resumo terminal.

A verificação `uv sync --frozen` tem agora timeout controlado, detalhe seguro do resolver em caso de falha e confirmação explícita quando termina. O estado do manifesto é marcado como `failed` mesmo quando a falha acontece antes de a CLI do MoneyPrinterTurbo iniciar.

## Optimização nativa de tokens com jusTokenMax

O Thunderbolt integra o [jusTokenMax](https://github.com/Kalmantic/jusTokenMax) como optimizador local e reversível de contexto. Payloads JSON e transcrições muito extensas podem ser compactados antes de serem enviados aos providers LLM. Prompts criativos estruturados e conteúdos pequenos são preservados integralmente para evitar alteração semântica.

A configuração encontra-se em **Configuração API > API Keys > Optimização de tokens — jusTokenMax**. É possível activar ou desactivar o optimizador, controlar os levers por tipo, verificar a versão instalada, consultar métricas e limpar apenas os artefactos derivados. Os originais permanecem em `storage/state/token_optimizer_originals/` e podem ser recuperados pelo hash através do módulo interno.

A instalação do pacote inclui `justokenmax` a partir do repositório oficial. Se o CLI não estiver disponível ou ocorrer um erro, o Thunderbolt usa o conteúdo original e regista um fallback local; a geração não fica bloqueada. API keys, passwords, tokens e blobs base64 são redigidos antes de serem guardados em artefactos derivados.

## Canva Skills — automação criativa

O Thunderbolt inclui as seis Canva Skills activas do pacote oficial `canva-sdks/canva-skills`, adaptadas para chamadas REST directas: `resize-for-social-media`, `bulk-create`, `implement-feedback`, `edit-design`, `get-design-feedback` e `brand-check`. A página `Canva Skills` permite executar as operações sobre um card Canva autorizado em **Configuração API > API Keys > Imagem e Video IA**.

A criação em lote usa o endpoint oficial de Autofill e requer Canva Enterprise (ou quota de trial durante desenvolvimento). A criação de variantes sociais copia o design e exporta cada variante; a Connect REST pública não oferece um endpoint geral de resize responsivo, por isso a dimensão alvo é registada e o link de edição Canva é disponibilizado para ajustes finais. A API REST também não expõe as transacções de edição usadas pelo MCP; `edit-design` e `implement-feedback` funcionam como preparação aprovada e identificam claramente as alterações que exigem edição manual, sem efectuar commits falsos.

O fluxo automático de thumbnails continua a usar Canva exclusivamente no Pool de Imagem para thumbnails. Canva nunca é seleccionado para geração de vídeo. Consulte `app/modules/canva_skills/` para os módulos e `app/pages/canva_skills.py` para a interface.
