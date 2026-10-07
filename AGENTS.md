# Instruções do Repositório Thunderbolt

## Versionamento NPM

O Thunderbolt usa a convenção visual de lançamento `0.MINOR.PATCH`, com **dois dígitos no PATCH**. Ao atingir o patch `99`, a próxima publicação deve incrementar o componente `MINOR` e reiniciar o PATCH em `00`.

> Exemplo obrigatório: depois de `0.3.99`, a etiqueta apresentada é **`0.4.00`**. Nunca apresentar `0.3.100` nem qualquer patch acima de `99`.

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
