# Upload YouTube via Composio

O Upload YouTube usa o alias configurado apenas para localizar a conta. Antes da chamada da ferramenta, o Thunderbolt lista as connected accounts activas do toolkit `youtube`, compara o alias e envia à API somente o ID técnico imutável. Aliases duplicados são recusados para evitar publicar na conta errada.

A conta também precisa de `https://www.googleapis.com/auth/youtube.force-ssl`. Uma autorização apenas de leitura não é suficiente para publicar vídeos. O Thunderbolt verifica o scope antes do upload e mostra o alias e o ID técnico na mensagem de erro quando a permissão falta.

## Reautorizar uma conta

A reautorização exige interação humana. O utilizador deve criar ou seleccionar no Composio um auth config do toolkit YouTube que inclua os scopes de leitura e upload, definir `COMPOSIO_YOUTUBE_AUTH_CONFIG_ID`, `COMPOSIO_API_KEY` e `COMPOSIO_USER_ID`, e executar na raiz do projecto:

```text
python scripts/reauth_youtube.py --account The-Navy-Vector
```

O comando tenta primeiro actualizar a ligação existente. Se o scope de escrita continuar ausente, imprime um link de autorização. Abra esse link no navegador, seleccione a conta Google correcta e conceda a permissão de upload. Depois, execute o Upload novamente; a resolução dinâmica localizará o novo ID técnico.

O comando não concede permissões automaticamente, não usa o alias como ID técnico e não apaga uma conta sem uma acção explícita do utilizador.
