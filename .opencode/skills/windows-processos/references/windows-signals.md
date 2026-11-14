# Sinais no Windows e MobaXterm

- **Erro 0xC000013A**: STATUS_CONTROL_C_EXIT. O processo recebeu um Ctrl+C ou sinal de consola espúrio e morreu.
- **Solução**: O spawn do Node.js deve usar `CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`. O worker Python deve usar `signal.SIG_IGN` no topo do arquivo.
- **Erro EPIPE**: O terminal fechou, mas o Node tentou continuar escrevendo logs.
- **Solução**: Guardar as streams de `stdout`/`stderr` e redirecionar para um arquivo se a consola morrer.