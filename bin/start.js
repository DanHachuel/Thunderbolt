#!/usr/bin/env node
/**
 * 1.0.85 - ARRANQUE SEM A CAMADA DO npx.cmd (o vilão real do prompt devolvido).
 *
 * O `npx` no Windows é um ficheiro em lote (`npx.cmd`): quando o
 * PowerShell/MobaXterm lhe envia um Ctrl+C (ou fecha a consola), o .cmd morre
 * e leva o Node do launcher consigo — o utilizador fica com o prompt
 * `PS C:\...>` de volta e a stack a morrer silenciosamente, mesmo com o
 * keep-alive e a absorção de sinais a funcionar (o sinal nunca chega a tempo).
 *
 * Este wrapper corre o launcher no MESMO processo Node (`import` directo, zero
 * spawn, zero camada batch): o sinal de console chega ao Node, que o absorve
 * (ver `scripts/cli.mjs` — 1.0.74/1.0.85). Uso:
 *
 *   node bin/start.js          (ou `npm start`, que aponta para isto)
 *
 * Distribuição normal continua a ser via npx; este caminho é a alternativa
 * pedida pelo utilizador quando o terminal devolve o prompt sozinho.
 */
import "../scripts/cli.mjs";
