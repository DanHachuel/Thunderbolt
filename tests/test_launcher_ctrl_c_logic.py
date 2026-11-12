"""1.0.94 — a lógica do Ctrl+C no Windows, exercitada a sério.

O `npx`/terminal entrega o CTRL_C_EVENT pelo mecanismo do console, que este
ambiente de agente não consegue simular (`AttachConsole` falha a partir de um
processo que já tem consola, e `GenerateConsoleCtrlEvent` só alcança o grupo
próprio do chamador). Por isso o teste extrai o handler REAL do
`scripts/cli.mjs` e exercita-o com stubs — a lógica que escrevemos é que fica
crava, não uma cópia dela.

Cenários travados:
1. um toque único avisa e NÃO encerra (o fantasma não fecha a app);
2. um eco de rajada (< 1 s) não conta como confirmação;
3. o segundo toque com 1 s–5 s de intervalo encerra a stack;
4. um toque depois da janela (> 5 s) volta a avisar em vez de encerrar.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")

HARNESS = r"""
import fs from "node:fs";
const say = (msg) => process.stdout.write(String(msg) + "\n");
const CLI = fs.readFileSync("scripts/cli.mjs", "utf8");
const anchor = "// 1.0.94 - CTRL+C PASSA A ENCERRAR";
const commentIndex = CLI.indexOf(anchor);
if (commentIndex < 0) { say("FALHA: bloco do handler não encontrado"); process.exit(1); }
const start = CLI.lastIndexOf('if (platform() === "win32") {', commentIndex);
const block = CLI.slice(start).split("} else {", 1)[0];
if (!block.includes("SIGINT")) { say("FALHA: bloco extraído sem handler de SIGINT"); process.exit(1); }
const eventos = [];
const saidas = [];
globalThis.diagnostic = (evento) => eventos.push(evento);
globalThis.stopWorker = (motivo) => saidas.push(motivo);
globalThis.console = { log: (msg) => saidas.push("LOG:" + String(msg).slice(0, 70)) };
const handlers = {};
globalThis.process = { ...process, pid: 4242, on: (sinal, fn) => { handlers[sinal] = fn; }, uptime: () => 42 };
const platform = () => "win32";
eval(block + "\n}");
if (typeof handlers["SIGINT"] !== "function") { say("FALHA: handler não registado"); process.exit(1); }
const disparar = () => handlers["SIGINT"]();
const resumo = () => ({ eventos: eventos.length, saidas: saidas.slice(-3) });
disparar();
const r1 = resumo();
say(`1º toque -> ${JSON.stringify(r1)}`);
if (r1.saidas.includes("ctrl+c")) { say("FALHA: um toque único encerrou"); process.exit(1); }
if (!r1.saidas.some((s) => s.includes("Ctrl+C ignorado"))) { say("FALHA: o primeiro toque não avisou"); process.exit(1); }
disparar();
const r2 = resumo();
say(`rajada -> ${JSON.stringify(r2)}`);
if (!eventos.includes("terminal_echo_ignored")) { say("FALHA: o eco da rajada não foi ignorado"); process.exit(1); }
await new Promise((resolve) => setTimeout(resolve, 1100));
disparar();
const r3 = resumo();
say(`2º toque -> ${JSON.stringify(r3)}`);
if (!r3.saidas.includes("ctrl+c")) { say("FALHA: o segundo toque não encerrou"); process.exit(1); }
if (!r3.saidas.some((s) => s.includes("Encerrando o Thunderbolt"))) { say("FALHA: falta o log de encerramento"); process.exit(1); }
await new Promise((resolve) => setTimeout(resolve, 5200));
const antes4 = saidas.length;
disparar();
const r4 = resumo();
say(`toque tardio -> ${JSON.stringify(r4)}`);
if (saidas.lastIndexOf("ctrl+c") >= antes4) { say("FALHA: toque fora da janela encerrou"); process.exit(1); }
if (!r4.saidas.some((s) => s.includes("Ctrl+C ignorado"))) { say("FALHA: toque fora da janela deveria voltar a avisar"); process.exit(1); }
say("TODOS OS CENÁRIOS DO CTRL+C PASSARAM");
"""


def test_windows_ctrl_c_logic_is_confirmed_not_blind(tmp_path):
    """Os 4 cenários do Ctrl+C, exercitados contra o handler real do launcher."""
    harness = tmp_path / "ctrlc_logic.mjs"
    harness.write_text(HARNESS, encoding="utf-8")
    result = subprocess.run(
        ["node", str(harness)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    output = (result.stdout or "") + (result.stderr or "")
    assert "TODOS OS CENÁRIOS DO CTRL+C PASSARAM" in output, output[-2000:]
    assert "FALHA" not in output, output[-2000:]


def test_ctrl_c_handler_contract_in_source():
    """O handler está no launcher, com a confirmação e a telemetria certas."""
    assert "[LAUNCHER] Encerrando o Thunderbolt (Ctrl+C)..." in CLI
    assert "intervalo > 1000 && intervalo <= 5000" in CLI
    assert 'stopWorker("ctrl+c")' in CLI
    assert "terminal_echo_ignored" in CLI
    assert "ctrl_c_confirmed_shutdown" in CLI


def test_ctrl_c_log_is_craved_in_the_tests():
    """O log pedido pelo utilizador existe no código."""
    assert "console.log(\"\\n[LAUNCHER] Encerrando o Thunderbolt (Ctrl+C)...\");" in CLI.replace(
        'console.log("[LAUNCHER] Encerrando o Thunderbolt (Ctrl+C)...");',
        'console.log("\\n[LAUNCHER] Encerrando o Thunderbolt (Ctrl+C)...");',
    ) or 'console.log("[LAUNCHER] Encerrando o Thunderbolt (Ctrl+C)...");' in CLI
