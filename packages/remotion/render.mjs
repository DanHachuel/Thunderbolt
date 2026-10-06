#!/usr/bin/env node
/**
 * render.mjs — wrapper Node.js invocado pelo hermes_ui/remotion_provider.py
 * via subprocesso (o mesmo padrão do MoneyPrinterTurbo via uv).
 *
 * Protocolo (spec 4.1):
 *   stdout: "OUTPUT=<path>" (uma linha, caminho do MP4 final)
 *   stderr: "PROGRESS=<percent>" (uma linha por actualização) e "LOG=..."
 *   exit 0 em sucesso; não-zero em erro (ERROR=<mensagem> no stderr).
 *
 * Argumentos:
 *   --input-props <path.json>   inputProps final (produzido por --prepare-only)
 *   --script-file <path.md>     roteiro Markdown (converte via scriptToInputProps)
 *   --config <path.json>        config extra do vídeo (opcional, com --script-file)
 *   --composition <id>          LongFormVideo | ShortVideo (opcional; infere)
 *   --output <path.mp4>         destino do vídeo
 *   --cache-dir <dir>           cache do bundle (storage/remotion-cache/bundle)
 *   --chromium <path>           Chromium do Playwright (browserExecutable)
 *   --ffmpeg <path>             FFmpeg do imageio-ffmpeg (validação/paridade)
 *   --prepare-only              converte roteiro→inputProps, imprime JSON e sai
 *   --thunderbolt-role <value>  marcador do single-instance guard
 *                               (--thunderbolt-role=remotion-render é excluído)
 *
 * Cache do bundle (spec 4.2): bundle() corre uma vez e é cacheado em
 * <cache-dir>/bundle; invalida quando o hash de packages/remotion/package.json
 * muda. O serveUrl vive em cache durante a execução.
 *
 * Migração futura (spec 4.4): a arquitectura mantém inputProps/composições/
 * adaptador inalterados para migrar para @remotion/lambda — só este wrapper
 * trocaria bundle()+renderMedia() por renderMediaOnLambda().
 *
 * Testabilidade: os módulos @remotion/bundler e @remotion/renderer são
 * importados LAZIAMENTE (só no caminho de render), permitindo às dependências
 * serem sobrepostas por REMOTION_BUNDLER_MODULE / REMOTION_RENDERER_MODULE —
 * os testes do wrapper correm sem node_modules instalado.
 */
import { createHash } from "node:crypto";
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";

import { scriptToInputProps } from "./src/adapters/scriptToInputProps.mjs";

function parseArgs(argv) {
  const parsed = {};
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i];
    if (!flag.startsWith("--")) continue;
    if (flag.includes("=")) {
      const [name, ...rest] = flag.split("=");
      parsed[name] = rest.join("=");
      continue;
    }
    const next = argv[i + 1];
    if (next !== undefined && !next.startsWith("--")) {
      parsed[flag] = next;
      i += 1;
    } else {
      parsed[flag] = "true";
    }
  }
  return parsed;
}

function log(line) {
  process.stderr.write(`LOG=${line}\n`);
}

function progress(value) {
  const pct = Math.max(0, Math.min(100, Math.round(Number(value) || 0)));
  process.stderr.write(`PROGRESS=${pct}\n`);
}

function fail(message, code = 1) {
  process.stderr.write(`ERROR=${message}\n`);
  process.exit(code);
}

function readJsonFile(file, label) {
  try {
    return JSON.parse(readFileSync(file, "utf8"));
  } catch (error) {
    fail(`Não foi possível ler ${label} (${file}): ${error.message}`);
    return {};
  }
}

function sha256Of(file) {
  try {
    return createHash("sha256").update(readFileSync(file)).digest("hex");
  } catch {
    return null;
  }
}

function directoryHasBundle(dir) {
  try {
    return existsSync(path.join(dir, "index.html")) && statSync(path.join(dir, "index.html")).size > 0;
  } catch {
    return false;
  }
}

async function loadRemotionModules() {
  const bundlerModule = process.env.REMOTION_BUNDLER_MODULE || "@remotion/bundler";
  const rendererModule = process.env.REMOTION_RENDERER_MODULE || "@remotion/renderer";
  const { bundle } = await import(bundlerModule);
  const { selectComposition, renderMedia } = await import(rendererModule);
  return { bundle, selectComposition, renderMedia };
}

const options = parseArgs(process.argv.slice(2));
const here = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));

// ── Modo --prepare-only: roteiro Markdown → inputProps (sem render) ─────────
if (options["--prepare-only"]) {
  if (!options["--script-file"]) fail("--prepare-only exige --script-file <path.md>");
  const config = options["--config"] ? readJsonFile(options["--config"], "config") : {};
  let markdown;
  try {
    markdown = readFileSync(options["--script-file"], "utf8");
  } catch (error) {
    fail(`Não foi possível ler o roteiro (${options["--script-file"]}): ${error.message}`);
  }
  const inputProps = scriptToInputProps(markdown, config);
  process.stdout.write(JSON.stringify(inputProps));
  process.exit(0);
}

// ── inputProps: ficheiro final ou conversão do roteiro ──────────────────────
let inputProps;
if (options["--input-props"]) {
  inputProps = readJsonFile(options["--input-props"], "inputProps");
} else if (options["--script-file"]) {
  const config = options["--config"] ? readJsonFile(options["--config"], "config") : {};
  let markdown;
  try {
    markdown = readFileSync(options["--script-file"], "utf8");
  } catch (error) {
    fail(`Não foi possível ler o roteiro (${options["--script-file"]}): ${error.message}`);
  }
  inputProps = scriptToInputProps(markdown, config);
} else {
  fail("Forneça --input-props <path.json> ou --script-file <path.md>");
}

// Serializabilidade garantida (spec 2.2): sem funções, ciclos ou undefined.
inputProps = JSON.parse(JSON.stringify(inputProps));

const compositionId =
  options["--composition"] ||
  (Number(inputProps.height) > Number(inputProps.width) ? "ShortVideo" : "LongFormVideo");
const output = options["--output"] || fail("--output <path.mp4> é obrigatório");
const cacheDir = options["--cache-dir"] || path.join(here, ".remotion-cache");
const chromium = options["--chromium"] || process.env.THUNDERBOLT_CHROMIUM || "";
const ffmpeg = options["--ffmpeg"] || process.env.THUNDERBOLT_FFMPEG || "";

if (chromium) log(`Chromium: ${chromium}`);
if (ffmpeg) {
  // @remotion/renderer v4 traz o próprio compositor pré-compilado; o FFmpeg do
  // imageio-ffmpeg é aceites para paridade/validação e fica exposto por env.
  if (!existsSync(ffmpeg)) fail(`O caminho do FFmpeg não existe: ${ffmpeg}`);
  process.env.FFMPEG_BINARY = ffmpeg;
  log(`FFmpeg (imageio-ffmpeg): ${ffmpeg}`);
}

// ── Bundle com cache (spec 4.2) ─────────────────────────────────────────────
const packageJsonPath = path.join(here, "package.json");
const packageHash = sha256Of(packageJsonPath);
const bundleDir = path.join(cacheDir, "bundle");
const manifestPath = path.join(cacheDir, "bundle-manifest.json");
let serveUrl = null;
if (packageHash && existsSync(manifestPath) && directoryHasBundle(bundleDir)) {
  try {
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
    if (manifest.hash === packageHash) {
      serveUrl = bundleDir;
      log("Bundle em cache reutilizado.");
    }
  } catch {
    serveUrl = null;
  }
}

const { bundle, selectComposition, renderMedia } = await loadRemotionModules();

if (!serveUrl) {
  log("A compilar o bundle Remotion…");
  rmSync(bundleDir, { recursive: true, force: true });
  mkdirSync(cacheDir, { recursive: true });
  const builtDir = await bundle(path.join(here, "src", "index.ts"), {
    onProgress: (value) => progress((Number(value) || 0) * 30),
  });
  // O bundle() devolve um directório temporário; é materializado no cache
  // para sobreviver entre execuções e ser invalidado pelo hash.
  cpSync(builtDir, bundleDir, { recursive: true });
  writeFileSync(manifestPath, JSON.stringify({ hash: packageHash, createdAt: new Date().toISOString() }));
  serveUrl = bundleDir;
  log(`Bundle pronto: ${bundleDir}`);
}

// ── Render (spec 4.3) ────────────────────────────────────────────────────────
const concurrency = Math.max(1, os.cpus().length - 1);
const composition = await selectComposition({
  serveUrl,
  compositionId,
  inputProps,
  ...(chromium ? { browserExecutable: chromium } : {}),
});
log(`Composição ${compositionId}: ${composition.width}x${composition.height} @ ${composition.fps}fps, ${composition.durationInFrames} frames.`);
progress(32);

await renderMedia({
  composition,
  serveUrl,
  codec: "h264",
  outputLocation: output,
  inputProps,
  concurrency,
  ...(chromium ? { browserExecutable: chromium } : {}),
  onProgress: (value) => {
    const ratio = typeof value === "number" ? value : Number(value && value.progress) || 0;
    progress(32 + ratio * 66);
  },
});

if (!existsSync(output) || statSync(output).size <= 0) {
  fail(`O render terminou mas o MP4 não existe ou está vazio: ${output}`);
}
progress(100);
process.stdout.write(`OUTPUT=${output}\n`);
process.exit(0);
