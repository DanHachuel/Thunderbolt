# Instruções do Repositório Thunderbolt

## Versionamento NPM

O Thunderbolt usa a convenção visual de lançamento `0.MINOR.PATCH`, com **dois dígitos no PATCH**. Ao atingir o patch `99`, a próxima publicação deve incrementar o componente `MINOR` e reiniciar o PATCH em `00`.

> Exemplo obrigatório: depois de `0.3.99`, a etiqueta apresentada é **`0.4.00`**. Nunca apresentar `0.3.100` nem qualquer patch acima de `99`.

O NPM aplica SemVer e normaliza zeros à esquerda: a etiqueta visual `0.4.00` é publicada no registry como a versão canónica **`0.4.0`**. Antes de cada publicação, confirmar a versão em `package.json`, no workflow NPM e no registry. Nos comandos Windows/MobaXterm, usar a versão canónica literal confirmada no registry; na interface e comunicação de lançamento, usar a etiqueta visual com patch de dois dígitos.

## Push obrigatório

Sempre que uma sessão de agente criar commits, o ramo deve ser **enviado de imediato para o origin (push)** — nunca deixar trabalho apenas commitado no disco local. Não perguntar ao utilizador se deve fazer push: fazer sempre, automaticamente, no final de cada tarefa que produza commits.
