/**
 * Testes do wrapper render.mjs (spec 11.3): parsing de argumentos, formato
 * do stdout (OUTPUT=...), stderr (PROGRESS=...) e falhas com ERROR=.
 * Corre com os mocks de tests/fixtures/ — não precisa de node_modules.
 */
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const renderScript = path.resolve(here, "..", "render.mjs");
const mockBundler = pathToFileURL(path.resolve(here, "fixtures", "mock-bundler.mjs")).href;
const mockRenderer = pathToFileURL(path.resolve(here, "fixtures", "mock-renderer.mjs")).href;
const node = process.execPath;

let failures = 0;

function check(label, condition) {
  if (condition) {
    console.log(`PASS ${label}`);
  } else {
    failures += 1;
    console.error(`FAIL ${label}`);
  }
}

function runRender(args, extraEnv = {}) {
  return spawnSync(node, [renderScript, ...args], {
    encoding: "utf8",
    env: {
      ...process.env,
      REMOTION_BUNDLER_MODULE: mockBundler,
      REMOTION_RENDERER_MODULE: mockRenderer,
      ...extraEnv,
    },
  });
}

const workDir = mkdtempSync(path.join(tmpdir(), "thunderbolt-remotion-test-"));
mkdirSync(workDir, { recursive: true });
const cacheDir = path.join(workDir, "cache");
const inputPropsPath = path.join(workDir, "input-props.json");
const scriptPath = path.join(workDir, "script.md");
const outputPath = path.join(workDir, "video.mp4");

writeFileSync(
  inputPropsPath,
  JSON.stringify({
    videoId: "test-video",
    title: "Teste",
    language: "pt",
    fps: 30,
    width: 1920,
    height: 1080,
    audioUrl: "",
    scenes: [{ id: "hook", type: "hook", durationInSeconds: 4, narration: "oi", visual: { type: "text_overlay", text: "oi" } }],
    metadata: {},
  }),
);

writeFileSync(
  scriptPath,
  [
    "# Título do vídeo",
    "",
    "## GANCHO",
    "NARRAÇÃO: Uma abertura rápida para validar a conversão.",
    "VISUAL: background: gradient",
    "",
    "## CENA 1",
    "NARRAÇÃO: A primeira cena com alguma locução de exemplo.",
    "",
    "## ENCERRAMENTO",
    "NARRAÇÃO: Fecho curto.",
    "",
  ].join("\n"),
);

// 1) Render normal com --input-props: OUTPUT= no stdout, exit 0.
const renderResult = runRender([
  "--input-props",
  inputPropsPath,
  "--output",
  outputPath,
  "--composition",
  "LongFormVideo",
  "--cache-dir",
  cacheDir,
  "--thunderbolt-role=remotion-render",
]);
check("render devolve exit 0", renderResult.status === 0);
check(
  "stdout termina com OUTPUT=<path>",
  String(renderResult.stdout).trim().endsWith(`OUTPUT=${outputPath}`),
);
check("stderr emite PROGRESS=", /PROGRESS=\d+/.test(String(renderResult.stderr)));
check("MP4 mock foi escrito", readFileSync(outputPath, "utf8").startsWith("mock-mp4:"));
check("bundle cache criado", readFileSync(path.join(cacheDir, "bundle", "index.html"), "utf8").length > 0);

// 2) Bundle em cache: segunda execução reutiliza (LOG=Bundle em cache).
const cachedResult = runRender([
  "--input-props",
  inputPropsPath,
  "--output",
  outputPath,
  "--composition",
  "LongFormVideo",
  "--cache-dir",
  cacheDir,
]);
check("segundo render exit 0", cachedResult.status === 0);
check("bundle em cache reutilizado", /Bundle em cache reutilizado/.test(String(cachedResult.stderr)));

// 3) --prepare-only: JSON do inputProps no stdout, sem render.
const prepareResult = runRender(["--prepare-only", "--script-file", scriptPath]);
check("prepare-only exit 0", prepareResult.status === 0);
let prepared = null;
try {
  prepared = JSON.parse(String(prepareResult.stdout));
} catch {
  prepared = null;
}
check("prepare-only devolve JSON válido", prepared !== null && Array.isArray(prepared.scenes));
check("prepare-only mapeia 3 cenas", prepared && prepared.scenes.length === 3);
check(
  "prepare-only ordena tipos hook/cena/outro",
  prepared && prepared.scenes[0].type === "hook" && prepared.scenes[2].type === "outro",
);

// 4) --script-file directo no render (conversão inline).
const scriptResult = runRender([
  "--script-file",
  scriptPath,
  "--output",
  outputPath,
  "--cache-dir",
  path.join(workDir, "cache2"),
]);
check("render via --script-file exit 0", scriptResult.status === 0);
check("render via --script-file emite OUTPUT=", /OUTPUT=/.test(String(scriptResult.stdout)));

// 5) Sem --output: erro explícito e exit não-zero.
const noOutputResult = runRender(["--input-props", inputPropsPath]);
check("sem --output falha", noOutputResult.status !== 0);
check("sem --output emite ERROR=", /ERROR=/.test(String(noOutputResult.stderr)));

// 6) Composição inferida por dimensões (1080x1920 → ShortVideo).
const verticalPropsPath = path.join(workDir, "vertical-props.json");
const baseProps = JSON.parse(readFileSync(inputPropsPath, "utf8"));
writeFileSync(verticalPropsPath, JSON.stringify({ ...baseProps, width: 1080, height: 1920 }));
const verticalResult = runRender([
  "--input-props",
  verticalPropsPath,
  "--output",
  path.join(workDir, "vertical.mp4"),
  "--cache-dir",
  path.join(workDir, "cache3"),
]);
check("composição vertical infere ShortVideo", /Composição ShortVideo/.test(String(verticalResult.stderr)));

rmSync(workDir, { recursive: true, force: true });
if (failures > 0) {
  console.error(`render.test.mjs: ${failures} falha(s)`);
  process.exit(1);
}
console.log("render.test.mjs: todos os testes passaram");
