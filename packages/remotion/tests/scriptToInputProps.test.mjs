/**
 * Testes do adaptador scriptToInputProps (spec 11.4): dado um roteiro
 * Markdown de exemplo (PT e EN), o JSON resultante é válido e todas as
 * cenas são mapeadas.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { scriptToInputProps } from "../src/adapters/scriptToInputProps.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
let failures = 0;

function check(label, condition) {
  if (condition) {
    console.log(`PASS ${label}`);
  } else {
    failures += 1;
    console.error(`FAIL ${label}`);
  }
}

const script = [
  "---",
  "id: 8e0c0e7563f3",
  "title: Index Funds Are Stealing Your Returns",
  "---",
  "# Index Funds Are Stealing Your Returns",
  "",
  "## GANCHO",
  "NARRAÇÃO: Entre 2010 e 2023, os fundos indexados prometeram democratizar o investimento.",
  "VISUAL: background: gradient; navio de carga aéreo",
  "SFX: low_industrial_hum",
  "ON-SCREEN TEXT: Index funds promised to democratize investing.",
  "",
  "## CENA 1",
  "NARRAÇÃO: A primeira cena explica a estrutura de custos com dados concretos do mercado.",
  "VISUAL: fundo: grid",
  "DATA: barras: S&P 12; Bonds 8",
  "",
  "## CENA 2",
  "NARRAÇÃO: A segunda cena compara o retorno líquido ao longo de uma década inteira.",
  "",
  "## ENCERRAMENTO",
  "NARRAÇÃO: Subscreva o canal para mais análises forenses do mercado.",
  "",
].join("\n");

const props = scriptToInputProps(script, {
  title: "Index Funds Are Stealing Your Returns",
  language: "pt",
  fps: 30,
  width: 1920,
  height: 1080,
  audioUrl: "C:\\audio\\narration.mp3",
  metadata: { channel: "The Financial Mechanics", style: "forensic_narrative" },
});

check("videoId preservado do frontmatter", props.videoId === "8e0c0e7563f3");
check("título vindo do config", props.title === "Index Funds Are Stealing Your Returns");
check("fps/width/height aplicados", props.fps === 30 && props.width === 1920 && props.height === 1080);
check("audioUrl preservado", props.audioUrl === "C:\\audio\\narration.mp3");
check("4 cenas mapeadas", props.scenes.length === 4);
check("tipos hook/scene/outro", props.scenes[0].type === "hook" && props.scenes[1].type === "scene" && props.scenes[3].type === "outro");
check("ids estáveis", props.scenes.map((s) => s.id).join(",") === "hook,scene-1,scene-2,outro");
check("SFX capturado", props.scenes[0].sfx === "low_industrial_hum");
check("background do VISUAL capturado", props.scenes[0].visual.background === "gradient");
check("fundo: PT reconhecido", props.scenes[1].visual.background === "grid");
check("ON-SCREEN TEXT vira visual.text", props.scenes[0].visual.text === "Index funds promised to democratize investing.");
check("DATA vira visualização de barras", props.scenes[1].data && props.scenes[1].data.kind === "bar" && props.scenes[1].data.items.length === 2);
check("durações positivas", props.scenes.every((s) => s.durationInSeconds > 0));
check("narração não vazia", props.scenes.every((s) => s.narration.length > 0));

// Duração explícita.
const explicit = scriptToInputProps(["## GANCHO", "NARRAÇÃO: curto", "DURAÇÃO: 7", ""].join("\n"), {});
check("DURAÇÃO explícita respeitada", explicit.scenes[0].durationInSeconds === 7);

// Reescala com o áudio real (recalcular quando o áudio está pronto).
const rescaled = scriptToInputProps(script, { totalAudioSeconds: 60 });
const total = rescaled.scenes.reduce((acc, s) => acc + s.durationInSeconds, 0);
check("reescala para a duração real do áudio", Math.abs(total - 60) < 1.5);

// Estimativa por palavras.
const wordy = scriptToInputProps(["## GANCHO", "NARRAÇÃO: " + "palavra ".repeat(50), ""].join("\n"), { wpm: 150 });
check("estimativa por palavras (50 palavras @150wpm ≈ 20s)", Math.abs(wordy.scenes[0].durationInSeconds - 20) < 6);

// Roteiro vazio → cena única de fallback.
const empty = scriptToInputProps("", { title: "Fallback" });
check("fallback com roteiro vazio", empty.scenes.length === 1 && empty.scenes[0].type === "hook");

// Roteiro EN.
const english = scriptToInputProps(
  ["## HOOK", "NARRATION: A quick opening line.", "VISUAL: background: particles", "", "## OUTRO", "NARRATION: Subscribe for more.", ""].join("\n"),
  {},
);
check("roteiro EN mapeado", english.scenes.length === 2 && english.scenes[0].type === "hook" && english.scenes[1].type === "outro");
check("background EN capturado", english.scenes[0].visual.background === "particles");

// Serializabilidade.
const serialized = JSON.parse(JSON.stringify(props));
check("JSON round-trip idêntico", JSON.stringify(serialized) === JSON.stringify(props));
check("sem undefined no JSON", !JSON.stringify(props).includes("undefined"));

if (failures > 0) {
  console.error(`scriptToInputProps.test.mjs: ${failures} falha(s)`);
  process.exit(1);
}
console.log("scriptToInputProps.test.mjs: todos os testes passaram");
