# Instruções do Repositório Thunderbolt

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
