# Instruções do Repositório Thunderbolt

## 🛡️ AUDITORIA OBRIGATÓRIA DAS SKILLS LOCAIS (`.opencode/skills/`)

O repo carrega as skills de auditoria em `.opencode/skills/` e o workflow
`.github/workflows/publish-npm.yml` corre os cinco scripts como **gate bloqueante**
antes de qualquer publicação (passo «Rodar Auditorias das Skills (Gate)»).
**Qualquer alteração de código feita neste repo tem de passar por essas validações** —
localmente, antes de commitar:

```bash
python .opencode/skills/evitar-regressoes/scripts/verificar-atomic.py   # escrita atómica de JSON
python .opencode/skills/escopo-cirurgico/scripts/verificar-escopo.py    # escopo cirúrgico (instalador/menus)
python .opencode/skills/streamlit-estado/scripts/verificar-streamlit.py # anti-padrões Streamlit (time.sleep/loops na UI)
python .opencode/skills/windows-processos/scripts/verificar-spawn.py    # flags de spawn/sinal no Windows
python .opencode/skills/testes-contrato/scripts/verificar-testes.py     # testes frágeis (só string)
```

Todos têm de devolver **0**. Uma violação corrige-se no código (ou, quando a regra
está errada para o código legado, no próprio script — nunca silenciando o passo).
O contrato está cravado em `tests/test_skills_audit_gate.py`.

## 🚨 REGRAS INVIOLÁVEIS DE ESCOPO, TERMINAL E PROJETO

1. **Proibido tocar no instalador para tarefas de UI:** Se a tarefa pedir uma mudança visual ou nova aba (ex: "Criar aba de Dependências"), é TERMINANTEMENTE PROIBIDO alterar `install.mjs`, `requirements.txt` ou scripts de setup.
2. **Silêncio Absoluto no Terminal:** O comando de instalação NUNCA deve imprimir a saída do `pip` (barras de progresso, "Uninstalling...", "Successfully installed..."). Use `--quiet` ou redirecione a saída (ex: `> install.log 2>&1`). O terminal deve exibir APENAS as mensagens amigáveis do Thunderbolt.
3. **Fim do Mojibake:** Nenhum subprocesso pode emitir caracteres corrompidos. Force `PYTHONIOENCODING=utf-8` em todas as chamadas `subprocess`.
4. **Verificação de Importação Correta:** A checagem pós-instalação DEVE usar o Python do `.venv` (ex: `.venv/Scripts/python.exe -c "import uploader"`) e não o Python global.

## 🚨 REGRA INVIOLÁVEL: ESCOPO DO INSTALADOR

- É TERMINANTEMENTE PROIBIDO alterar o arquivo `install.mjs`, `requirements.txt`, `package.json` (dependências) ou rodar comandos de instalação (`pip install`, `npm install`, `npx ... install`) se a tarefa solicitada não for explicitamente sobre gerenciamento de dependências ou setup do ambiente.
- Tarefas de UI, correção de layout, ajuste de lógica ou criação de abas NÃO DEVEM, sob nenhuma hipótese, tocar no instalador.
- O agente NUNCA deve tentar "consertar", "verificar" ou "reinstalar" dependências do ambiente por conta própria. Se houver um problema de dependência, ele deve apenas reportar ao usuário.

## Regra de UI: Inserção de Itens

- Ao adicionar um novo item a um menu existente, NUNCA mova, reordene ou toque na posição dos itens que já estavam lá.
- Insira o novo item EXATAMENTE na posição solicitada, mantendo o fluxo visual e a ordem original do restante do menu intocados.

## Pré-requisitos e Dependências Obrigatórias (IMUTÁVEL)

1. O comando padrão `npx @danhachuel/thunderbolt install` DEVE instalar TODAS as dependências listadas abaixo. Nenhuma delas pode ser "opt-in" ou exigir flags adicionais (ex: `--with-uploaders`).
2. Dependências Obrigatórias:
   - Ambiente Python (venv)
   - Node.js / NPM
   - MoneyPrinterTurbo (MPT)
   - Remotion + Dependências de Renderização
   - Playwright (Chromium e Firefox)
   - Patchright (Chromium)
   - Camoufox (com GeoIP)
   - FFmpeg (binário)
   - social-auto-upload (SAU) + `sau_cli` (CLI multi-plataforma)
3. É proibido criar lógica de "skip" no instalador para qualquer uma dessas dependências. Se a instalação falhar, ela deve abortar com erro claro, e não pular silenciosamente.
4. Toda PR (Pull Request) ou release deve conter um teste que valide que o instalador padrão não possui flags condicionais para as dependências acima.

## Versionamento NPM

O Thunderbolt usa a convenção visual de lançamento `MAJOR.MINOR.PATCH`, com **dois dígitos no PATCH**. Ao atingir o patch `99`, a próxima publicação deve incrementar o componente `MINOR` e reiniciar o PATCH em `00`; quando o `MINOR` está em `9`, é o `MAJOR` que avança e `MINOR`/`PATCH` reiniciam em `00`.

> Exemplos obrigatórios: depois de `0.3.99`, a etiqueta apresentada é **`0.4.00`**; depois de `0.9.99`, a etiqueta apresentada é **`1.0.00`** (nunca `0.10.00`). Nunca apresentar patch acima de `99` nem minor acima de `9`.

O NPM aplica SemVer e normaliza zeros à esquerda: a etiqueta visual `0.4.00` é publicada no registry como a versão canónica **`0.4.0`**. Antes de cada publicação, confirmar a versão em `package.json`, no workflow NPM e no registry. Nos comandos Windows/MobaXterm, usar a versão canónica literal confirmada no registry; na interface e comunicação de lançamento, usar a etiqueta visual com patch de dois dígitos.

## Push obrigatório

Sempre que uma sessão de agente criar commits, o ramo deve ser **enviado de imediato para o origin (push)** — nunca deixar trabalho apenas commitado no disco local. Não perguntar ao utilizador se deve fazer push: fazer sempre, automaticamente, no final de cada tarefa que produza commits.

## Regras de release (permanentes)

1. Sempre que algo for actualizado no repositório, enviar para o GitHub (push) e publicar de imediato a nova versão no NPM.
2. As publicações NPM ocorrem sempre via GitHub Actions (workflow `Publish npm package`), nunca por `npm publish` local. Sequência: bump duplo → commit/push → dispatch manual com dist-tag `next` → push da tag `vX.Y.ZZ`, que verifica o tarball e promove a versão a `latest`.
3. Transparência: depois de criar ou publicar uma versão, relatar explicitamente a versão e as áreas ou ficheiros alterados.
4. UX: nunca criar travas de pré-registo; validações de credenciais apenas no momento da acção que realmente precisa delas.
5. Após cada versão, entregar sempre os comandos de instalação no formato: CMD/MobaXterm `npx.cmd --yes --prefer-online @danhachuel/thunderbolt@<VERSAO> install` e `npx.cmd --yes --prefer-online @danhachuel/thunderbolt@<VERSAO>`; instalação normal `npx --yes @danhachuel/thunderbolt@<VERSAO> install` e `npx --yes @danhachuel/thunderbolt@<VERSAO>`.
6. Sempre que existir qualquer alteração com push (código, docs, configuração, correção, publicação npm), escrever a entrada correspondente no `CHANGELOG.md` antes de publicar — nenhuma versão sai sem registo. Ao integrar trabalho de outra sessão sem entrada, documentá-la retroactivamente.
7. Antes de qualquer commit/push, verificar o master remoto (`git fetch origin` + comparar) e fazer **rebase** sempre que o master tiver avançado — o utilizador corre várias sessões simultâneas. Em colisão de versão, a versão já publicada vence e a sessão renumera para o patch seguinte (confirmar no registry antes de publicar).

## 🚨 REGRA INVIOLÁVEL: TAMANHO DE ROTEIRO E BLUEPRINTS

1. A variável `average_video_time` (Tempo Médio de Vídeo) do canal é a **ÚNICA fonte de verdade** para o tamanho do roteiro.
2. É **TERMINANTEMENTE PROIBIDO** enviar para a LLM regras de `character_length`, `strict_character_range`, `output_length_requirement` ou `hard_fail_condition` provenientes de arquivos JSON de Blueprints.
3. O código que monta o prompt **DEVE** ativamente deletar/ignorar essas chaves do JSON do Blueprint antes de enviá-lo à LLM (`hermes_ui/blueprint_length_guard.py` — `sanitize_blueprint_for_prompt`).
4. Nenhuma alteração no sistema de Blueprints pode quebrar ou contornar esta regra. Qualquer PR que tocar em geração de roteiro deve passar pelos testes de regressão específicos (`tests/test_script_length_guard.py`).

## 🚨 REGRA INVIOLÁVEL: RUNTIME PERMANENTE E PROTEÇÃO CONTRA EBUSY

O Thunderbolt **nunca** corre do cache do `npx` (`.npm/_npx/<hash>/...`). Enquanto o processo vive, o npm não consegue actualizar a pasta — o utilizador fica preso à versão velha com `EBUSY`. A partir da **1.0.81** a arquitectura é a do ProdMaker (já validada em produção):

1. **O servidor NUNCA deve rodar do cache do `npx` (`_npx`).** Todo o spawn (`app/main.py`, `scripts/streamlit_bootstrap.py`, `-m hermes_ui.<worker>`) usa `cwd: executionRoot`, que é `THUNDERBOLT_HOME/.runtime` quando o runtime existe.
2. **O comando `install` deve copiar os ficheiros de código para `THUNDERBOLT_HOME/.runtime` antes de qualquer execução.** O `install` **apenas prepara**: mata o que está atrelado ao runtime anterior (`kill_tree.py --cleanup`), corre o instalador (venv/dependências), copia os ficheiros e **encerra sem servidor** — o `npx` é libertado imediatamente.
3. **O comando `run` deve sempre ler do `.runtime`** (`cwd: runtimeDir`). Se o runtime ainda não existe (corrida directa sem `install`), ele é preparado silenciosamente no arranque (`ensureRuntimeSources`) — nenhum caminho pode arrancar do cache.
4. **O diretório `storage/` e o arquivo `.env` NUNCA devem ser movidos para dentro do `.runtime`**, para preservar a persistência dos dados do utilizador. A whitelist de cópia (`RUNTIME_COPY_TARGETS` em `scripts/cli.mjs`) só contém **código**: `app/`, `hermes_ui/`, `integrations/`, `scripts/`, `seed/`, `packages/`, `requirements.txt`, `pyproject.toml`, `sitecustomize.py`, `.streamlit/`, docs e `legal/`. Dados, chaves, logs, venv e locks ficam na raiz do `THUNDERBOLT_HOME`.
5. **A separação de responsabilidades é inviolável**: `install` = cópia segura para `.runtime`; `run` = execução isolada. Quem reescrever o `run` a arrancar o servidor a partir da raiz do pacote, ou o `install` a spawnar a stack, quebra a regra. Crave: `tests/test_runtime_isolation.py` (lê o `scripts/cli.mjs` e falha se o `.runtime`, o `cwd: executionRoot`, a whitelist só-de-código ou o encerramento sem servidor desaparecerem).
6. **Keep-alive, absorção de sinais e isolamento de workers (regras acima) continuam válidos por cima do runtime** — a mudança de raiz não pode remover `CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`, `windowsHide: true`, stdio sem `inherit` nem os handlers do terminal desvinculado.

## 🚨 REGRA INVIOLÁVEL: ARQUITETURA DO LAUNCHER (WINDOWS/MOBAXTERM)

Estas linhas do `scripts/cli.mjs` foram escolhidas a CONTA de evidência (teleometria real do utilizador + sondas ao sistema operativo). **Não são gambiarras e não devem ser removidas** por nenhuma sessão futura. Quem as alterar tem de actualizar, na mesma PR, a regra e os testes que as crave (`tests/test_launcher_keep_alive.py`).

1. **Keep-Alive Obrigatório (modo único, foreground):** o launcher DEVE terminar com `const keepAliveTimer = setInterval(() => {}, 1000);` — um handle referenciado, **sem `unref`**. O Node só encerra quando o event loop esvazia; sem isto, o terminal devolve o prompt `PS>` com a aplicação ainda a arrancar ou já a correr. **Desde a 1.0.94 existe um único modo — foreground**: o launcher arranca o Streamlit e os workers como filhos normais, imprime os logs e **não sai**. (O modelo destacado/descartável da 1.0.89–1.0.93 foi **revertido a pedido do utilizador**: banner verde e prompt de volta não eram o comportamento desejado.) Crave: `tests/test_launcher_foreground.py`.
2. **Absorção de sinais fantasma no Windows:** `SIGHUP` deve ser **absorvido** quando `process.platform === "win32"` (`absorbTerminalSignal`), com o aviso `[LAUNCHER] Sinal ignorado. Mantendo processo activo.`. Razão: no Windows o SIGHUP do Node é derivado do console (CTRL_CLOSE/LOGOFF) e chega **sem que ninguém feche nada** — a teleometria regista 82 encerramentos `console_closed`, vários 5 segundos depois do arranque. No Linux/macOS o SIGHUP continua a encerrar (lá é sinal real).
   - **`SIGTERM` e `SIGBREAK` NÃO são absorvidos** — são paragens legítimas em todas as plataformas (`stopWorker`). Quem os absorver quebra o encerramento deliberado.
   - **SIGINT (Ctrl+C) encerra, com confirmação no Windows (1.0.94):** o primeiro Ctrl+C avisa e não encerra; o segundo, com mais de 1 s (eco de rajada não conta) e menos de 5 s, encerra a stack. Motivo: o Windows entrega o MESMO SIGINT para o Ctrl+C real e para o CTRL_C_EVENT fantasma — 17 717 eventos na teleometria, muitos em rajadas de milissegundos. Encerrar ao primeiro sinal devolveria o «fecha sozinho»; ignorar para sempre é o que o utilizador rejeitou. Crave: `tests/test_launcher_sigint.py`.
   - O enceramento real da aplicação é **deliberado**: `Ctrl+C` (2× no Windows), `Ctrl+Break`, arquivo `.thunderbolt.stop`, `npx thunderbolt kill` ou reinício pela interface.
3. **Guarda de Consola (EPIPE):** `guardConsoleStream` (a cobrir stdout **e** stderr), `noteConsoleDetached` e o espelho `storage/logs/launcher_console.log` NUNCA devem ser removidos. Sem ouvinte de `error` na stream, o primeiro write depois de o terminal morrer emite `EPIPE` na stream → `uncaughtException` → `launcherExiting("crash")` → saída silenciosa com o prompt de volta.
4. **Isolamento dos filhos:** os spawns de worker usam `workerCreationFlags()` (`CREATE_NEW_PROCESS_GROUP` = `0x00000200`, com `CREATE_NO_WINDOW` no Windows) para o sinal do console não matar os workers, e o encerramento é sempre o do launcher (`child.kill()`/`stopStackComponents`, que usa TerminateProcess e não depende de grupos). **`detached: true` / `unref()` NÃO podem voltar** aos spawns da stack: o terminal ocupado é o comportamento pedido (regra 1). Crave: `tests/test_launcher_foreground.py` e `tests/test_no_detached_process.py`.

5. **PROIBIDO ABRIR TELAS DE CMD NO COMPUTADOR DO UTILIZADOR:** nenhuma versao do Thunderbolt pode publicar processos que deixem janelas de consola (CMD/PowerShell) a pairar no ecra do utilizador. Fica proibido, sem excepcao:
   - `detached: true` (Node) ou `DETACHED_PROCESS` (Python) em **qualquer** spawn da stack — a fuga tira a consola ao processo e os subprocessos seguintes passam a abrir a sua própria consola (regra 1: o terminal tem de ficar ocupado);
   - `windowsHide: false` num processo que não escreve na consola do terminal;
   - `stdio: "inherit"` num processo **destacado** (o gatilho documentado do `Fatal Python error: init_sys_streams` tambem vive aí) ou em qualquer filho que escreva na consola do terminal — a saida dos filhos vai para `storage/logs/` ou por pipes com log proprio.
   A unica excepcao, ja medida, e o **respawn do launcher depois de uma atualizacao** (precisa de `detached` para sobreviver ao job object do libuv) — e esse caso tem obrigacao de levar `windowsHide: true` + `stdio: "ignore"`, para nenhuma janela aparecer. Crave: `tests/test_no_detached_process.py`, que varre o Python **e** os `scripts/*.mjs`. Quem introduzir um spawn novo tem de o cobrir no mesmo PR.
