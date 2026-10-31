#!/usr/bin/env node
import { spawn, spawnSync } from "node:child_process";
import http from "node:http";
import net from "node:net";
import { existsSync, mkdirSync, readFileSync, copyFileSync, readdirSync, appendFileSync, writeFileSync, rmSync, statSync, createReadStream } from "node:fs";
import { homedir, platform } from "node:os";
import { join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(fileURLToPath(new URL(".", import.meta.url)), "..");
const args = process.argv.slice(2);
const packageVersion = (() => {
  try { return JSON.parse(readFileSync(join(root, "package.json"), "utf8")).version || "dev"; }
  catch { return "dev"; }
})();

function getUserHome() {
  if (platform() !== "win32") return homedir();
  const driveHome = process.env.HOMEDRIVE && process.env.HOMEPATH ? `${process.env.HOMEDRIVE}${process.env.HOMEPATH}` : null;
  return process.env.USERPROFILE || driveHome || homedir();
}

const userHome = getUserHome();
const defaultThunderboltHome = platform() === "win32"
  ? join(process.env.LOCALAPPDATA || join(userHome, "AppData", "Local"), "THUNDERBOLT")
  : join(userHome, ".thunderbolt");
const thunderboltHome = resolve(process.env.THUNDERBOLT_HOME || defaultThunderboltHome);
const venvDir = process.env.THUNDERBOLT_VENV || process.env.HERMES_VENV || join(thunderboltHome, ".venv");
const venvPython = platform() === "win32" ? join(venvDir, "Scripts", "python.exe") : join(venvDir, "bin", "python");
const python = process.env.THUNDERBOLT_PYTHON || process.env.HERMES_PYTHON || (existsSync(venvPython) ? venvPython : (platform() === "win32" ? "python" : "python3"));
const main = resolve(root, "app", "main.py");
const streamlitBootstrap = resolve(root, "scripts", "streamlit_bootstrap.py");
const storageDir = process.env.THUNDERBOLT_STORAGE_DIR || join(thunderboltHome, "storage");
const diagnosticsDir = join(storageDir, "state");
const launcherDiagnosticsPath = join(diagnosticsDir, "launcher_diagnostics.jsonl");
const settingsPath = join(storageDir, "state", "settings.json");
// Single-instance guard: o lock por ficheiro sobrevive a overrides de porta
// (THUNDERBOLT_PORT/HERMES_PORT) que derrotavam o bind 3030 como lock.
const launcherLockPath = join(diagnosticsDir, "launcher.lock");
const killTreeHelper = resolve(root, "scripts", "kill_tree.py");
const pythonEnvironment = { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1", PYTHONLEGACYWINDOWSSTDIO: "1", CLICK_NO_WIN_CONSOLE: "1" };

function diagnostic(event, payload = {}) {
  try {
    mkdirSync(diagnosticsDir, { recursive: true });
    appendFileSync(launcherDiagnosticsPath, `${JSON.stringify({ timestamp: new Date().toISOString(), event, ...payload })}\n`, "utf8");
  } catch { /* logging never changes launcher behaviour */ }
}

function runKillTreeHelper(modeArgs) {
  // O venv do Thunderbolt tem sempre psutil (os workers dependem dele); o
  // Python de sistema pode não ter, por isso é tentado primeiro o venv.
  // O helper devolve exit 1 quando há sobreviventes (o JSON continua válido),
  // por isso o resultado é aceite sempre que o stdout é JSON parseable —
  // exigir status 0 fazia o guard registar falsos "indisponível" e tentar de
  // novo com um interpretador sem psutil.
  const candidates = [venvPython, python].filter(Boolean).filter((candidate, index, all) => all.indexOf(candidate) === index);
  let lastFailure = null;
  for (const candidate of candidates) {
    if (!existsSync(candidate) && candidate !== "python" && candidate !== "python3") continue;
    let result = null;
    try {
      result = spawnSync(candidate, [killTreeHelper, ...modeArgs], { encoding: "utf8", env: pythonEnvironment, timeout: 60000 });
    } catch { /* tenta o próximo interpretador */ }
    if (!result) continue;
    if (result.stdout) {
      try { return JSON.parse(result.stdout); } catch { /* saída não-JSON */ }
    }
    lastFailure = { interpreter: candidate, status: result.status, stderr: String(result.stderr || result.error || "").slice(-300) };
  }
  return { helper_failure: lastFailure };
}

function stopPreviousThunderboltStacks() {
  // Single-instance guard: no Windows uma morte abrupta do launcher deixa os
  // filhos órfãos vivos, e um segundo arranque (npx) criava uma segunda stack
  // completa que disputava os locks do storage — a causa-raiz do ciclo
  // "servidor encerra sozinho". Antes de arrancar a nova stack, termina-se
  // toda a árvore Thunderbolt anterior (o helper psutil exclui este launcher
  // e a cadeia de processos que o iniciou). Se sobrar algum sobrevivente
  // (processos a terminar devagar), a limpeza é repetida uma vez.
  let summary = runKillTreeHelper(["--cleanup", String(process.pid)]);
  if (summary && summary.helper_failure) {
    diagnostic("single_instance_guard_error", { error: "kill_tree.py indisponível; a limpeza da instância anterior não correu", ...summary.helper_failure });
    return;
  }
  if (!summary) {
    diagnostic("single_instance_guard_error", { error: "kill_tree.py indisponível; a limpeza da instância anterior não correu" });
    return;
  }
  if (Array.isArray(summary.survivors) && summary.survivors.length > 0) {
    summary = runKillTreeHelper(["--cleanup", String(process.pid)]) || summary;
  }
  if (Array.isArray(summary.killed) && summary.killed.length > 0) {
    diagnostic("previous_instance_stopped", { killed: summary.killed, survivors: summary.survivors || [] });
    console.log(`Thunderbolt: terminada a instância anterior (${summary.killed.length} processo(s)).`);
  }
}

function claimLauncherLock() {
  try {
    mkdirSync(diagnosticsDir, { recursive: true });
    writeFileSync(launcherLockPath, JSON.stringify({ pid: process.pid, started_at: new Date().toISOString() }), "utf8");
  } catch { /* o lock é defesa extra; falhar a escrevê-lo não bloqueia o arranque */ }
}

function launcherExiting(reason) {
  // Telemetria de saída: sem isto, mortes abruptas/externas eram
  // indistinguíveis de exits silenciosos nos diagnósticos.
  diagnostic("launcher_exiting", { reason, pid: process.pid, uptime_seconds: Math.round(process.uptime()) });
  try { rmSync(launcherLockPath, { force: true }); } catch { /* best effort */ }
}

function run(command, commandArgs, label = "comando", environment = process.env) {
  console.log(`Thunderbolt: a iniciar ${label}...`);
  const result = spawnSync(command, commandArgs, {
    stdio: "inherit",
    env: { ...pythonEnvironment, ...environment, PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1", PYTHONLEGACYWINDOWSSTDIO: "1", CLICK_NO_WIN_CONSOLE: "1" },
    cwd: root,
    windowsHide: false,
  });
  if (result.error) {
    console.error(`Thunderbolt: não foi possível iniciar ${label}: ${result.error.message}`);
    process.exit(1);
  }
  if (result.signal) {
    console.error(`Thunderbolt: ${label} terminou pelo sinal ${result.signal}.`);
    process.exit(1);
  }
  process.exit(result.status ?? 1);
}

function pythonVersion() {
  return spawnSync(python, ["-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"], { encoding: "utf8", env: pythonEnvironment });
}

function moduleAvailable(moduleName) {
  // 1.0.20: IMPORT REAL em vez de importlib.util.find_spec — o find_spec dava
  // falso positivo com pacote parcial/corrompido: o check passava, o worker
  // morria no boot com ImportError e o launcher entrava no loop infinito de
  // «a reiniciar em 5s». O import real executa o pacote: se falha, falha.
  const code = [
    "import importlib, sys",
    `name = ${JSON.stringify(moduleName)}`,
    "try:",
    "    importlib.import_module(name)",
    "    sys.exit(0)",
    "except Exception:",
    "    sys.exit(1)",
  ].join("\n");
  return spawnSync(python, ["-c", code], { stdio: "ignore", env: pythonEnvironment }).status === 0;
}

const requiredWorkerModules = ["psutil", "serpapi", "playwright", "patchright"];

// 1.0.42 — Camoufox é OBRIGATÓRIO (o stealth do upload directo YouTube
// depende dele) e passa a usar a MESMA checagem do botão «Testar instalação
// do browser» da UI: `hermes_ui.browser_manager.camoufox_environment_ready`
// (import REAL do módulo — lição 1.0.20 — + integridade do binário). O aviso
// falso de «dependências opcionais ausentes (camoufox)» morreu: quando o
// módulo está lá, o boot fica calado; quando falta, é ERRO REAL com o
// comando do instalador — nunca um aviso de opcional.
function camoufoxWorkerReady() {
  try {
    const probe = spawnSync(
      python,
      [
        "-c",
        "import json;from hermes_ui.browser_manager import camoufox_environment_ready;print(json.dumps(camoufox_environment_ready()))",
      ],
      { encoding: "utf8", env: { ...pythonEnvironment, PYTHONPATH: root }, timeout: 90000 },
    );
    if (probe.status === 0 && String(probe.stdout || "").trim()) {
      const environment = JSON.parse(String(probe.stdout).trim());
      return { ready: Boolean(environment.module), message: String(environment.message || "") };
    }
  } catch {
    // probe Python indisponível: cai no import simples abaixo
  }
  return { ready: moduleAvailable("camoufox"), message: "" };
}

function checkWorkerDependencies(label) {
  const missing = requiredWorkerModules.filter((moduleName) => !moduleAvailable(moduleName));
  // 1.0.42: o Camoufox sai da lista de opcionais — obrigatório, pela mesma
  // checagem central que a UI usa (fim da discórdia terminal × interface).
  const camoufox = camoufoxWorkerReady();
  if (!camoufox.ready) missing.push("camoufox");
  if (!missing.length) return true;
  console.error(`Thunderbolt: ${label} não iniciado; imports obrigatórios ausentes: ${missing.join(", ")}.`);
  if (camoufox.message) console.error(`Thunderbolt: ${camoufox.message}`);
  console.error("Execute: npx.cmd --yes --prefer-online @danhachuel/thunderbolt install");
  console.error("Depois confirme com: npx.cmd --yes --prefer-online @danhachuel/thunderbolt --check");
  return false;
}

function configuredMoneyPrinterPath() {
  if (!existsSync(settingsPath)) return join(thunderboltHome, "MoneyPrinterTurbo");
  try {
    const settings = JSON.parse(readFileSync(settingsPath, "utf8"));
    return settings.moneyprinter_path || join(thunderboltHome, "MoneyPrinterTurbo");
  } catch {
    return join(thunderboltHome, "MoneyPrinterTurbo");
  }
}

function readStateJson(filename, fallback = []) {
  try { return JSON.parse(readFileSync(join(storageDir, "state", filename), "utf8")); }
  catch { return fallback; }
}

function hasScheduledAutomation() {
  const channels = readStateJson("channels.json", []);
  if (Array.isArray(channels) && channels.some((channel) => channel && channel.automation_on === true)) return true;
  const tasks = readStateJson("tasks.json", []);
  return Array.isArray(tasks) && tasks.some((task) => (
    task && task.automation_worker === true && ["to_do", "doing"].includes(String(task.state || task.status || "").toLowerCase())
  ));
}

function hasPendingPipelineWork() {
  const tasks = readStateJson("tasks.json", []);
  // A UI Start coloca a tarefa em `doing`; `to_do` também é consumido pelo
  // pipeline worker. Estes estados não dependem de automação de canal activa.
  return Array.isArray(tasks) && tasks.some((task) => ["to_do", "doing"].includes(String(task?.state || task?.status || "").toLowerCase()));
}

function ensureRuntimeStorage() {
  const storageRoot = storageDir;
  const directories = [
    storageRoot,
    join(storageRoot, "state"),
    join(storageRoot, "blueprints"),
    join(storageRoot, "blueprints", "canais"),
    join(storageRoot, "blueprints", "nichos"),
    join(storageRoot, "blueprints", "importados"),
    join(storageRoot, "blueprints", "brandings"),
    join(storageRoot, "blueprints", "thumbnails"),
    join(storageRoot, "metadata_cleaner"),
    join(storageRoot, "metadata_cleaner", "originals"),
    join(storageRoot, "metadata_cleaner", "outputs"),
    join(storageRoot, "skills"),
    join(storageRoot, "music"),
    join(storageRoot, "voice_previews"),
    join(storageRoot, "data"),
    join(storageRoot, "data", "niches"),
  ];
  for (const directory of directories) mkdirSync(directory, { recursive: true });
  const seedRoot = resolve(root, "seed", "blueprints");
  const destination = join(storageRoot, "blueprints", "importados");
  if (existsSync(seedRoot)) {
    for (const filename of readdirSync(seedRoot)) {
      if (!filename.endsWith(".json")) continue;
      const target = join(destination, filename);
      if (!existsSync(target)) copyFileSync(join(seedRoot, filename), target);
    }
    const thumbnailSeedRoot = join(seedRoot, "thumbnails");
    const thumbnailDestination = join(storageRoot, "blueprints", "thumbnails");
    if (existsSync(thumbnailSeedRoot)) {
      for (const filename of readdirSync(thumbnailSeedRoot)) {
        if (filename.endsWith(".md")) {
          const target = join(thumbnailDestination, filename);
          if (!existsSync(target)) copyFileSync(join(thumbnailSeedRoot, filename), target);
        }
      }
    }
    const pairSeed = join(seedRoot, "thumbnail_blueprint_pairs.json");
    const pairTarget = join(storageRoot, "blueprints", "thumbnail_blueprint_pairs.json");
    if (existsSync(pairSeed) && !existsSync(pairTarget)) copyFileSync(pairSeed, pairTarget);
  }
}

function camoufoxInstallDir() {
  // 1.0.22: `python -m camoufox path` imprime o DIRECTÓRIO de instalação do
  // browser (documentado em camoufox.com/python/installation) — a peça que o
  // pip install nunca traz.
  const probe = spawnSync(python, ["-m", "camoufox", "path"], { encoding: "utf8", env: pythonEnvironment });
  if (!probe || probe.status !== 0) return "";
  return String(probe.stdout || "").split("\n").map((line) => line.trim()).find(Boolean) || "";
}

function directoryHasContent(directory, depth = 3) {
  // 1.0.22: integridade REAL — ficheiros com bytes dentro do directório (um
  // cache apagado à mão deixa pasta vazia que o «Installed: yes» aceitava).
  try {
    for (const entry of readdirSync(directory)) {
      const entryPath = join(directory, entry);
      let stats;
      try { stats = statSync(entryPath); } catch { continue; }
      if (stats.isFile()) {
        if (stats.size > 0) return true;
      } else if (stats.isDirectory() && depth > 0 && directoryHasContent(entryPath, depth - 1)) {
        return true;
      }
    }
  } catch { return false; }
  return false;
}

function camoufoxBinaryDownloaded() {
  // 1.0.21: espelha install.mjs/browser_manager — sem o binário a automação
  // de browsers morre no arranque com um erro genérico de driver.
  // 1.0.22: integridade em duas camadas — directório `camoufox path` com
  // bytes; fallback para «Installed: yes» do `camoufox version`.
  const directory = camoufoxInstallDir();
  if (directory) {
    return existsSync(directory) && directoryHasContent(directory);
  }
  const probe = spawnSync(python, ["-m", "camoufox", "version"], { encoding: "utf8", env: pythonEnvironment });
  if (!probe || probe.status !== 0) return false;
  return /^\s*Installed\s*[:=]?\s*(?:yes|true)\s*$/im.test(String(probe.stdout || ""));
}

function check() {
  const version = pythonVersion();
  if (version.status !== 0) {
    console.error(`Python não encontrado. Execute: npx.cmd --yes @danhachuel/thunderbolt install`);
    process.exit(1);
  }
  const requiredModules = ["streamlit", "requests", "pandas", "toml", "imageio_ffmpeg", "edge_tts", "sklearn", "mlxtend", "plotly", "seaborn", "kagglehub", "composio", "playwright"];
  const missing = requiredModules.filter((moduleName) => !moduleAvailable(moduleName));
  const ffmpeg = moduleAvailable("imageio_ffmpeg");
  const mptPath = configuredMoneyPrinterPath();
  const mptReady = existsSync(join(mptPath, "requirements.txt")) || existsSync(join(mptPath, "pyproject.toml"));
  console.log(`Thunderbolt: ${thunderboltHome}`);
  console.log(`Python: ${version.stdout.trim()}`);
  console.log(`Dependências da aplicação: ${missing.length ? `em falta (${missing.join(", ")})` : "OK"}`);
  console.log(`FFmpeg: ${ffmpeg ? "OK via imageio-ffmpeg" : "em falta"}`);
  console.log(`Motor de vídeo: ${mptReady ? `OK (${mptPath})` : `não encontrado (${mptPath})`}`);
  // 1.0.21: o binário do Camoufox é a peça que o `pip install` NÃO traz —
  // sem ele a automação de browsers morre no arranque com um erro genérico
  // de driver. Aviso claro, não falha o check (o resto pode estar OK).
  if (camoufoxBinaryDownloaded()) {
    console.log("Camoufox: binário do browser OK.");
  } else {
    console.error("Camoufox: binário do browser ausente. Execute o instalador novamente.");
  }
  // 1.0.31/1.0.44: os uploaders (social-auto-upload/sau_cli) são OBRIGATÓRIOS
  // — o check INFORMA e FALHA se estiverem em falta (instalação incompleta;
  // o instalador padrão já os repara/aborta, regra do AGENTS.md).
  const uploadersReady = moduleAvailable("uploader") && moduleAvailable("sau_cli");
  if (uploadersReady) {
    console.log("Uploaders (social-auto-upload/sau_cli): OK.");
  } else {
    console.error("Uploaders (social-auto-upload/sau_cli): em falta — dependências obrigatórias do upload automático.");
  }
  if (missing.length || !ffmpeg || !uploadersReady) {
    console.error("Instalação incompleta. Execute `npx.cmd --yes @danhachuel/thunderbolt install`; dependências já válidas serão reutilizadas.");
    process.exit(1);
  }
}

if (args[0] === "install" || args[0] === "--install") {
  const installer = resolve(root, "scripts", "install.mjs");
  if (!existsSync(installer)) {
    console.error(`Thunderbolt: instalador não encontrado: ${installer}`);
    process.exit(1);
  }
  run(process.execPath, [installer, ...args.slice(1)], "a instalação");
}
if (args[0] === "doctor" || args.includes("--check")) {
  check();
  process.exit(0);
}

// REMOVIDO: relançamento em janela separada — o launcher corre directamente
// no terminal onde foi chamado, como sempre correu. Ctrl+C único encerra.

if (!existsSync(main)) {
  console.error(`Entrada não encontrada: ${main}`);
  process.exit(1);
}
ensureRuntimeStorage();
const runtimeEnv = {
  ...process.env,
  PYTHONIOENCODING: "utf-8",
  PYTHONUTF8: "1",
  PYTHONLEGACYWINDOWSSTDIO: "1",
  CLICK_NO_WIN_CONSOLE: "1",
  THUNDERBOLT_STORAGE_DIR: storageDir,
  STREAMLIT_BROWSER_GATHER_USAGE_STATS: "false",
  STREAMLIT_SERVER_HEADLESS: "true",
};

if (args[0] === "worker" || args.includes("--worker")) {
  if (!checkWorkerDependencies("o worker de automação")) process.exit(1);
  run(python, ["-m", "hermes_ui.automation_worker", ...args.filter((arg) => arg !== "worker" && arg !== "--worker")], "worker de automação", runtimeEnv);
}

if (args[0] === "pipeline-worker" || args.includes("--pipeline-worker")) {
  if (!checkWorkerDependencies("o worker do pipeline de vídeos")) process.exit(1);
  run(python, ["-m", "hermes_ui.pipeline_worker", ...args.filter((arg) => arg !== "pipeline-worker" && arg !== "--pipeline-worker")], "worker do pipeline de vídeos", runtimeEnv);
}

if (args[0] === "thumbnail-worker" || args.includes("--thumbnail-worker")) {
  if (!checkWorkerDependencies("o worker de thumbnails")) process.exit(1);
  run(python, ["-m", "hermes_ui.thumbnail_worker", ...args.filter((arg) => arg !== "thumbnail-worker" && arg !== "--thumbnail-worker")], "worker de thumbnails", runtimeEnv);
}

if (args[0] === "image-worker" || args.includes("--image-worker")) {
  if (!checkWorkerDependencies("o worker de imagens de produção")) process.exit(1);
  run(python, ["-m", "hermes_ui.image_worker", ...args.filter((arg) => arg !== "image-worker" && arg !== "--image-worker")], "worker de imagens de produção", runtimeEnv);
}

const port = process.env.THUNDERBOLT_PORT || process.env.HERMES_PORT || "3030";
const publicPort = Number.parseInt(String(port), 10);
const backendPort = await new Promise((resolve, reject) => {
  const reservation = net.createServer();
  reservation.once("error", reject);
  reservation.listen(0, "127.0.0.1", () => {
    const address = reservation.address();
    const selectedPort = address && typeof address === "object" ? address.port : 0;
    reservation.close((error) => error ? reject(error) : resolve(selectedPort));
  });
});
const supportedLanguages = new Set(["en", "zh", "de", "vi", "tr", "pt", "ru", "es", "id", "it"]);
const proxySockets = new Set();
const dynamicChunkRecoveryScript = `<script data-thunderbolt-recovery="${packageVersion}">
(() => {
  const key = "thunderbolt-dynamic-chunk-recovery";
  const recover = () => {
    try {
      const now = Date.now();
      const previous = Number(sessionStorage.getItem(key) || 0);
      if (now - previous < 30000) return;
      sessionStorage.setItem(key, String(now));
      const url = new URL(window.location.href);
      url.searchParams.set("tb_refresh", String(now));
      window.location.replace(url.href);
    } catch (_) {
      window.location.reload();
    }
  };
  window.addEventListener("unhandledrejection", (event) => {
    const message = String(event.reason?.message || event.reason || "");
    if (/Failed to fetch dynamically imported module|Importing a module script failed/i.test(message)) recover();
  });
  window.addEventListener("error", (event) => {
    const message = String(event.message || "");
    if (/dynamically imported module|module script failed/i.test(message)) recover();
  });
})();
</script>`;

// ---------------------------------------------------------------------------
// 1.0.34 — player de vídeo: streaming DIRECTO do disco com Range requests.
//
// CAUSA DO SPINNER INFINITO: o Streamlit 1.65 usa MemoryMediaFileStorage —
// `st.video(caminho)` lê o MP4 INTEIRO para a RAM do servidor a cada render
// (um Backlog com N vídeos feitos = N cópias gigantes em RAM + re-leitura do
// ficheiro a cada rerun, a maioria dentro do lock global do media manager) —
// o script run bloqueia, a memória satura e o browser fica à espera para
// sempre. O marshall_video 1.65 passa URLs http ABSOLUTAS ao browser SEM
// tocar no ficheiro; este endpoint do launcher serve o mesmo vídeo a partir
// do DISCO: toca imediatamente, suporta scrubbing (206 + Content-Range) e
// preserva a invariante 0.9.95 (o servidor nunca carrega o .mp4 para RAM).
// ---------------------------------------------------------------------------

const TB_MEDIA_MIME = {
  ".mp4": "video/mp4",
  ".webm": "video/webm",
  ".mov": "video/quicktime",
  ".m4v": "video/x-m4v",
  ".mp3": "audio/mpeg",
  ".wav": "audio/wav",
  ".m4a": "audio/mp4",
};

function launcherSettings() {
  try { return JSON.parse(readFileSync(settingsPath, "utf8")); } catch { return {}; }
}

function tbMediaRoots() {
  const settings = launcherSettings();
  const mptRoot = resolve(
    String(settings.moneyprinter_path || process.env.MONEYPRINTER_PATH || join(thunderboltHome, "MoneyPrinterTurbo")),
  );
  return {
    // vídeos das montagens locais (text_to_images, web_images, full_ia, remotion)
    videos: join(thunderboltHome, "storage", "videos"),
    // vídeos finais das rotas Pexels/Pixabay (dinâmico: MoneyPrinterTurbo configurável)
    mpt: join(mptRoot, "storage", "tasks"),
  };
}

function resolveTbMediaTarget(pathname) {
  // /tb-media/<root>/<subpath...> — o subpath é RELATIVO dentro da root e a
  // validação corta path traversal ANTES de resolver no disco.
  const parts = pathname.split("/").filter(Boolean);
  if (parts.length < 3) return null;
  const rootName = parts[1];
  const root = tbMediaRoots()[rootName];
  if (!root) return null;
  let subParts;
  try {
    subParts = parts.slice(2).map((segment) => decodeURIComponent(segment));
  } catch {
    return null; // sequência percent mal formada
  }
  if (
    subParts.some(
      (segment) => !segment || segment === "." || segment === ".." || segment.includes("\\") || /^[a-zA-Z]:/.test(segment),
    )
  ) {
    return null;
  }
  const resolvedRoot = resolve(root);
  const target = resolve(join(resolvedRoot, ...subParts));
  // contenção real: o alvo tem de continuar DENTRO da root resolvida
  if (target !== resolvedRoot && !target.startsWith(resolvedRoot + sep)) return null;
  return target;
}

function parseRangeHeader(rangeHeader, fileSize) {
  // "bytes=start-end" | "bytes=start-" | "bytes=-sufixo" — devolve
  // { start, end } inclusivos, ou null quando o pedido é do ficheiro inteiro;
  // { invalid: true } quando o intervalo é impossível (→ 416).
  const match = /^bytes=(\d*)-(\d*)$/.exec(String(rangeHeader || "").trim());
  if (!match) return null;
  const [, rawStart, rawEnd] = match;
  if (rawStart === "" && rawEnd === "") return null;
  let start;
  let end;
  if (rawStart === "") {
    // sufixo: os últimos N bytes (o browser usa isto para achar o moov no fim)
    const suffix = Number.parseInt(rawEnd, 10);
    if (Number.isNaN(suffix) || suffix <= 0) return { invalid: true };
    start = Math.max(0, fileSize - suffix);
    end = fileSize - 1;
  } else {
    start = Number.parseInt(rawStart, 10);
    end = rawEnd === "" ? fileSize - 1 : Number.parseInt(rawEnd, 10);
    if (Number.isNaN(start) || Number.isNaN(end) || start > end || start >= fileSize) return { invalid: true };
    end = Math.min(end, fileSize - 1);
  }
  return { start, end };
}

function serveTbMediaFile(request, response, requestUrl) {
  const target = resolveTbMediaTarget(requestUrl.pathname);
  let stats = null;
  if (target) {
    try { stats = statSync(target); } catch { stats = null; }
  }
  if (!target || !stats || !stats.isFile()) {
    response.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
    response.end("Thunderbolt: media não encontrado.");
    return;
  }
  const extension = target.slice(target.lastIndexOf(".")).toLowerCase();
  const contentType = TB_MEDIA_MIME[extension] || "application/octet-stream";
  const headers = {
    "content-type": contentType,
    "accept-ranges": "bytes",
    // o ficheiro pode ser substituído in-place (re-render da mesma tarefa):
    // o browser não pode cachear bytes antigos
    "cache-control": "no-store, no-cache, must-revalidate, max-age=0",
  };
  if (request.method === "HEAD") {
    response.writeHead(200, { ...headers, "content-length": stats.size });
    response.end();
    return;
  }
  const range = parseRangeHeader(request.headers.range, stats.size);
  if (range && "invalid" in range) {
    response.writeHead(416, { "content-range": `bytes */${stats.size}` });
    response.end();
    return;
  }
  if (range) {
    response.writeHead(206, {
      ...headers,
      "content-range": `bytes ${range.start}-${range.end}/${stats.size}`,
      "content-length": range.end - range.start + 1,
    });
    createReadStream(target, { start: range.start, end: range.end }).pipe(response);
    return;
  }
  response.writeHead(200, { ...headers, "content-length": stats.size });
  createReadStream(target).pipe(response);
}

const proxy = http.createServer((request, response) => {
  const requestUrl = new URL(request.url || "/", `http://localhost:${publicPort}`);
  const pathParts = requestUrl.pathname.split("/").filter(Boolean);
  if (requestUrl.pathname === "/oauth/redirect") {
    requestUrl.pathname = "/";
    requestUrl.searchParams.set("page", "Configuração API");
    response.writeHead(302, {
      Location: `${requestUrl.pathname}${requestUrl.search}`,
      "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
      Pragma: "no-cache",
      Expires: "0",
    });
    response.end();
    return;
  }
  const languagePrefix = pathParts.length === 1 && supportedLanguages.has(pathParts[0]) ? pathParts[0] : "";
  if (languagePrefix) {
    requestUrl.pathname = "/";
    requestUrl.searchParams.set("lang", languagePrefix);
    response.writeHead(302, { Location: `${requestUrl.pathname}?${requestUrl.searchParams.toString()}` });
    response.end();
    return;
  }
  // 1.0.34 — streaming de media do disco (vídeos do player): servido pelo
  // próprio launcher com Range/206, SEM passar pelo Streamlit (o media
  // manager 1.65 carregaria o ficheiro inteiro para a RAM do servidor).
  if (requestUrl.pathname.startsWith("/tb-media/")) {
    serveTbMediaFile(request, response, requestUrl);
    return;
  }
  const upstream = http.request({
    hostname: "127.0.0.1",
    port: backendPort,
    method: request.method,
    path: `${requestUrl.pathname}${requestUrl.search}`,
    headers: { ...request.headers, host: `127.0.0.1:${backendPort}`, "accept-encoding": "identity" },
  }, (upstreamResponse) => {
    const responseHeaders = { ...upstreamResponse.headers };
    const contentType = String(responseHeaders["content-type"] || "").toLowerCase();
    const isHtml = contentType.includes("text/html") && !responseHeaders["content-encoding"];
    const isStaticAsset = requestUrl.pathname.startsWith("/static/");
    // O documento HTML contém o estado da sessão e pode mudar após uma
    // actualização via npx; os bundles estáticos do Streamlit, por outro lado,
    // devem ser reutilizados pelo browser. Desactivar cache em todos os
    // recursos tornava cada aba muito mais pesada e multiplicava downloads.
    if (isHtml) {
      delete responseHeaders.etag;
      delete responseHeaders["last-modified"];
      responseHeaders["cache-control"] = "no-store, no-cache, must-revalidate, max-age=0";
      responseHeaders.pragma = "no-cache";
      responseHeaders.expires = "0";
    }
    if (isStaticAsset) {
      delete responseHeaders.etag;
      delete responseHeaders["last-modified"];
      responseHeaders["cache-control"] = "no-store, no-cache, must-revalidate, max-age=0";
      responseHeaders.pragma = "no-cache";
      responseHeaders.expires = "0";
    }
    if (!isHtml) {
      response.writeHead(upstreamResponse.statusCode || 502, responseHeaders);
      upstreamResponse.pipe(response);
      return;
    }
    const chunks = [];
    let totalBytes = 0;
    upstreamResponse.on("data", (chunk) => {
      chunks.push(chunk);
      totalBytes += chunk.length;
    });
    upstreamResponse.on("end", () => {
      let body = Buffer.concat(chunks, totalBytes).toString("utf8");
      if (body.includes("</body>")) body = body.replace("</body>", `${dynamicChunkRecoveryScript}</body>`);
      delete responseHeaders["content-length"];
      response.writeHead(upstreamResponse.statusCode || 502, responseHeaders);
      response.end(body);
    });
  });
  request.on("aborted", () => upstream.destroy());
  response.on("close", () => {
    if (!response.writableEnded) upstream.destroy();
  });
  upstream.on("error", (error) => {
    if (response.headersSent || response.writableEnded) return;
    response.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
    response.end(`Thunderbolt backend indisponível: ${error.message}`);
  });
  request.pipe(upstream);
});
proxy.on("connection", (socket) => {
  proxySockets.add(socket);
  socket.on("close", () => proxySockets.delete(socket));
});

proxy.on("upgrade", (request, clientSocket, head) => {
  // Cada aba mantém uma sessão WebSocket Streamlit própria. Fechar os dois
  // lados da ponte em qualquer encerramento evita sockets órfãos: estes
  // sockets acumulados faziam várias abas ficarem eternamente a carregar.
  let upstreamSocket;
  let connected = false;
  const closeBridge = () => {
    if (clientSocket && !clientSocket.destroyed) clientSocket.destroy();
    if (upstreamSocket && !upstreamSocket.destroyed) upstreamSocket.destroy();
  };
  clientSocket.setNoDelay(true);
  clientSocket.setKeepAlive(true, 30000);
  clientSocket.setTimeout(15000, closeBridge);
  clientSocket.on("error", closeBridge);
  clientSocket.on("close", () => {
    proxySockets.delete(clientSocket);
    if (upstreamSocket && !upstreamSocket.destroyed) upstreamSocket.destroy();
  });
  proxySockets.add(clientSocket);
  upstreamSocket = net.connect(backendPort, "127.0.0.1", () => {
    connected = true;
    clientSocket.setTimeout(0);
    upstreamSocket.setNoDelay(true);
    upstreamSocket.setKeepAlive(true, 30000);
    // O timeout só protege o handshake inicial. Depois do primeiro byte do
    // Streamlit, a sessão pode ficar legitimamente sem tráfego por mais de
    // 15 segundos; não destruir uma aba ligada evita ciclos de reconexão.
    upstreamSocket.once("data", () => upstreamSocket.setTimeout(0));
    proxySockets.add(upstreamSocket);
    upstreamSocket.on("close", () => proxySockets.delete(upstreamSocket));
    const headers = Object.entries(request.headers)
      .map(([name, value]) => `${name}: ${Array.isArray(value) ? value.join(", ") : value}`)
      .join("\r\n");
    upstreamSocket.write(`GET ${request.url} HTTP/1.1\r\n${headers}\r\n\r\n`);
    if (head.length) upstreamSocket.write(head);
    clientSocket.pipe(upstreamSocket).pipe(clientSocket);
  });
  upstreamSocket.setTimeout(15000, closeBridge);
  upstreamSocket.on("error", closeBridge);
  upstreamSocket.on("close", () => {
    if (connected && !clientSocket.destroyed) clientSocket.destroy();
  });
});

// O backend Streamlit fica em 127.0.0.1; apenas o proxy escuta em todas as
// interfaces para que o encaminhamento seguro do ambiente consiga alcançá-lo.
proxy.on("error", (error) => {
  console.error(`Thunderbolt: não foi possível abrir a interface em ${publicPort}: ${error.message}`);
  // A porta pública funciona como lock de instância do launcher: uma segunda
  // instância não deve continuar a arrancar workers depois do bind falhar.
  // O guard de ficheiro (launcher.lock + kill_tree) é a defesa principal; o
  // bind falhado só acontece se outra aplicação ocupar a porta.
  launcherExiting("crash");
  process.exit(1);
});
// Single-instance guard: nenhum bind, worker ou Streamlit arranca antes de a
// instância anterior estar totalmente terminada. A ordem importa: o bind da
// porta pública (3030) falharia se a stack antiga ainda a mantivesse.
stopPreviousThunderboltStacks();
claimLauncherLock();
proxy.listen(publicPort, "127.0.0.1", () => {
  console.log(`Thunderbolt: interface disponível em http://localhost:${publicPort}/`);
});
// Os workers são geridos pelo launcher para que um clique em Start na UI
// também active o processamento, mesmo sem automação de canal configurada.
// Cada worker só existe enquanto a respectiva fila tiver trabalho pendente.
let worker = null;
let pipelineWorker = null;
let thumbnailWorker = null;
let imageWorker = null;
const restartExitCode = 75;
let shuttingDown = false;
let child;
let workerRestartTimer = null;
let pipelineRestartTimer = null;
let workerMonitorTimer = null;
let streamlitRestartTimer = null;
let shutdownForceTimer = null;
let automationFailureCount = 0;
let automationFailureWindowStartedAt = 0;
let automationStableTimer = null;
let lastAutomationWorkerError = "";
// 0.9.73: o monitor de 2 s re-tentava o worker de automação para sempre
// mesmo depois das 5 falhas — com o lock obsoleto (PID morto recusado pelo
// falso positivo), o terminal enchia de "falhou 5 vezes seguidas" num loop
// infinito. Passa a existir o mesmo travão do worker do pipeline.
let automationAutoRestartDisabled = false;
let pipelineFailureCount = 0;
let pipelineStableTimer = null;
let pipelineAutoRestartDisabled = false;
let streamlitFailureCount = 0;
let streamlitStableTimer = null;
let streamlitAutoRestartDisabled = false;
let workerDependencyFailureReported = false;
let pipelineDependencyFailureReported = false;
let queueWorkersDependencyFailureReported = false;

// 1.0.20: morte por dependências (ImportError/ModuleNotFoundError) NÃO volta
// a arrancar. Antes, os workers de fila reiniciavam incondicionalmente a cada
// 5s para sempre (o check find_spec dava falso positivo com pacote parcial/
// corrompido: o check passava, o worker morria no boot, o launcher repetia) —
// poluindo o terminal e travando a consola do Windows com erros fatais.
const dependencyFailurePattern = /ImportError|ModuleNotFoundError|Fatal Python error/i;
const workerStderrTails = new WeakMap();

function rememberWorkerStderr(child, chunk) {
  const previous = workerStderrTails.get(child) || "";
  workerStderrTails.set(child, (previous + String(chunk)).slice(-4000));
}

function workerDiedFromDependencies(child) {
  if (!child) return false;
  return dependencyFailurePattern.test(workerStderrTails.get(child) || "");
}

function missingModuleFromTail(text) {
  const match = String(text || "").match(/No module named '([^']+)'/i);
  return match ? match[1] : "";
}

function reportFatalDependencyFailure(label, tail) {
  const missing = missingModuleFromTail(tail);
  const hint = missing ? ` (módulo em falta: ${missing})` : "";
  console.error(`\x1b[31m[ERRO FATAL] ${label} falhou por falta de dependências${hint}. Rode 'npx.cmd --yes --prefer-online @danhachuel/thunderbolt install' para corrigir. Loop de reinício cancelado.\x1b[0m`);
}

function scheduleAutomationWorkerRestart() {
  const now = Date.now();
  if (!automationFailureWindowStartedAt || now - automationFailureWindowStartedAt >= 60000) {
    automationFailureWindowStartedAt = now;
    automationFailureCount = 0;
  }
  automationFailureCount += 1;
  if (automationFailureCount >= 5) {
    automationAutoRestartDisabled = true;
    console.error(`O worker de automação falhou 5 vezes seguidas. Última mensagem: ${lastAutomationWorkerError || "sem mensagem de erro capturada"}. Verifique o storage ou reinicie o Thunderbolt manualmente.`);
    return;
  }
  const delay = Math.min(2 ** automationFailureCount, 32) * 1000;
  console.error(`Thunderbolt worker: nova tentativa em ${delay / 1000}s (falha ${automationFailureCount}/5).`);
  workerRestartTimer = setTimeout(() => {
    workerRestartTimer = null;
    startAutomationWorker();
  }, delay);
}

function startAutomationWorker() {
  if (shuttingDown || worker || automationAutoRestartDisabled || !hasScheduledAutomation() || workerDependencyFailureReported) return;
  if (!checkWorkerDependencies("o worker de automação")) {
    workerDependencyFailureReported = true;
    return;
  }
  const startedAt = Date.now();
  lastAutomationWorkerError = "";
  worker = spawn(python, ["-m", "hermes_ui.automation_worker"], {
    cwd: root,
    stdio: ["ignore", "inherit", "pipe"],
    env: runtimeEnv,
    windowsHide: false,
  });
  worker.stderr?.setEncoding("utf8");
  worker.stderr?.on("data", (chunk) => {
    const message = String(chunk).trim();
    if (message) lastAutomationWorkerError = message.slice(-1000);
  });
  worker.on("error", (error) => console.error(`Thunderbolt worker: ${error.message}`));
  worker.on("exit", (code, signal) => {
    const dependencyTail = lastAutomationWorkerError;
    const diedFromDependencies = dependencyFailurePattern.test(dependencyTail);
    worker = null;
    if (shuttingDown) return;
    console.error(`Thunderbolt worker: terminou (código ${code ?? "-"}, sinal ${signal ?? "-"}).`);
    if (diedFromDependencies) {
      reportFatalDependencyFailure("O worker de automação", dependencyTail);
      workerDependencyFailureReported = true;
      return;
    }
    if (automationStableTimer) {
      clearTimeout(automationStableTimer);
      automationStableTimer = null;
    }
    const runtimeMs = Date.now() - startedAt;
    if (code !== 0 && runtimeMs < 5000 && hasScheduledAutomation()) {
      scheduleAutomationWorkerRestart();
    } else if (hasScheduledAutomation()) {
      workerRestartTimer = setTimeout(() => {
        workerRestartTimer = null;
        startAutomationWorker();
      }, 5000);
    }
  });
  automationStableTimer = setTimeout(() => {
    automationFailureCount = 0;
    automationFailureWindowStartedAt = 0;
    automationAutoRestartDisabled = false;
    automationStableTimer = null;
  }, 60000);
}

function stopPipelineWorker() {
  if (pipelineRestartTimer) {
    clearTimeout(pipelineRestartTimer);
    pipelineRestartTimer = null;
  }
  if (pipelineStableTimer) {
    clearTimeout(pipelineStableTimer);
    pipelineStableTimer = null;
  }
  if (pipelineWorker && !pipelineWorker.killed) pipelineWorker.kill();
  pipelineWorker = null;
}

function startPipelineWorker() {
  if (shuttingDown || pipelineWorker || pipelineRestartTimer || pipelineAutoRestartDisabled || pipelineDependencyFailureReported) return;
  if (!checkWorkerDependencies("o worker do pipeline de vídeos")) {
    pipelineDependencyFailureReported = true;
    return;
  }
  const startedAt = Date.now();
  pipelineWorker = spawn(python, ["-m", "hermes_ui.pipeline_worker"], {
    cwd: root,
    // 1.0.20: pipes + log próprio (storage/logs/pipeline_worker.log) — o mesmo
    // padrão stdio-seguro da 1.0.18 para os workers de fila (o «inherit» era o
    // gatilho documentado do «Fatal Python error: init_sys_streams» no
    // Windows) E permite ao launcher detectar morte por ImportError.
    stdio: ["ignore", "pipe", "pipe"],
    env: runtimeEnv,
    windowsHide: false,
  });
  attachQueueWorkerLog(pipelineWorker, "pipeline_worker.log", "pipeline worker");
  pipelineWorker.on("error", (error) => console.error(`Thunderbolt pipeline worker: ${error.message}`));
  pipelineStableTimer = setTimeout(() => {
    pipelineFailureCount = 0;
    pipelineAutoRestartDisabled = false;
    pipelineStableTimer = null;
  }, 60000);
  pipelineWorker.on("exit", (code, signal) => {
    const diedFromDependencies = workerDiedFromDependencies(pipelineWorker);
    const dependencyTail = workerStderrTails.get(pipelineWorker) || "";
    pipelineWorker = null;
    if (shuttingDown) return;
    console.error(`Thunderbolt pipeline worker: terminou (código ${code ?? "-"}, sinal ${signal ?? "-"}).`);
    if (pipelineStableTimer) {
      clearTimeout(pipelineStableTimer);
      pipelineStableTimer = null;
    }
    if (diedFromDependencies) {
      reportFatalDependencyFailure("O worker do pipeline de vídeos", dependencyTail);
      pipelineDependencyFailureReported = true;
      return;
    }
    if (Date.now() - startedAt >= 60000) {
      pipelineFailureCount = 0;
      pipelineAutoRestartDisabled = false;
    }
    pipelineFailureCount += 1;
    if (pipelineFailureCount >= 5) {
      pipelineAutoRestartDisabled = true;
      console.error("O worker de vídeo falhou 5 vezes antes de permanecer estável. A fila foi deixada intacta; reinicie o Thunderbolt após verificar os logs.");
      return;
    }
    const delay = Math.min(2 ** pipelineFailureCount, 32) * 1000;
    console.error(`Thunderbolt pipeline worker: nova tentativa em ${delay / 1000}s (falha ${pipelineFailureCount}/5).`);
    pipelineRestartTimer = setTimeout(() => {
      pipelineRestartTimer = null;
      startPipelineWorker();
    }, delay);
  });
}

function attachQueueWorkerLog(child, filename, label) {
  // 1.0.18: os workers de fila deixam de herdar a consola do launcher. O
  // «stdio: "inherit"» crashava no Windows com «Fatal Python error:
  // init_sys_streams: can't initialize sys standard streams» quando os
  // handles herdados não eram válidos para dois interpretadores a arrancar
  // em simultâneo (thumbnail + image), matando os workers no boot com o
  // loop de «a reiniciar em 5s». Pipes são SEMPRE handles válidos; o output
  // é espelhado na consola e anexado ao log próprio de cada worker.
  const logsDir = join(storageDir, "logs");
  const logPath = join(logsDir, filename);
  try {
    mkdirSync(logsDir, { recursive: true });
    if (existsSync(logPath) && statSync(logPath).size > 5_000_000) writeFileSync(logPath, "");
  } catch { /* logging nunca muda o comportamento do launcher */ }
  const append = (chunk) => {
    try { appendFileSync(logPath, chunk, "utf8"); } catch { /* idem */ }
  };
  child.stdout?.setEncoding("utf8");
  child.stderr?.setEncoding("utf8");
  child.stdout?.on("data", (chunk) => {
    if (!shuttingDown) process.stdout.write(chunk);
    append(chunk);
  });
  child.stderr?.on("data", (chunk) => {
    if (!shuttingDown) process.stderr.write(chunk);
    append(chunk);
    rememberWorkerStderr(child, chunk);
  });
  child.on("exit", (code, signal) => {
    append(`\n--- ${label}: terminou (código ${code ?? "-"}, sinal ${signal ?? "-"}) em ${new Date().toISOString()} ---\n`);
  });
  return logPath;
}

function startQueueWorkers() {
  // 1.0.11: filas paralelas do Motor — thumbnails e imagens de produção são
  // workers independentes com pools próprios (motor.max_parallel_*).
  if (shuttingDown || queueWorkersDependencyFailureReported || thumbnailWorker || imageWorker) return;
  if (!checkWorkerDependencies("os workers de filas do Motor")) {
    queueWorkersDependencyFailureReported = true;
    return;
  }
  thumbnailWorker = spawn(python, ["-m", "hermes_ui.thumbnail_worker"], {
    cwd: root,
    // 1.0.18: pipes + log próprio (storage/logs/thumbnail_worker.log) em
    // vez de herdar a consola — ver attachQueueWorkerLog.
    stdio: ["ignore", "pipe", "pipe"],
    env: runtimeEnv,
    windowsHide: false,
  });
  attachQueueWorkerLog(thumbnailWorker, "thumbnail_worker.log", "thumbnail worker");
  thumbnailWorker.on("error", (error) => console.error(`Thunderbolt thumbnail worker: ${error.message}`));
  thumbnailWorker.on("exit", (code, signal) => {
    const diedFromDependencies = workerDiedFromDependencies(thumbnailWorker);
    const dependencyTail = workerStderrTails.get(thumbnailWorker) || "";
    thumbnailWorker = null;
    if (shuttingDown) return;
    if (diedFromDependencies) {
      reportFatalDependencyFailure("O thumbnail worker", dependencyTail);
      queueWorkersDependencyFailureReported = true;
      return;
    }
    console.error(`Thunderbolt thumbnail worker: terminou (código ${code ?? "-"}, sinal ${signal ?? "-"}); a reiniciar em 5s.`);
    setTimeout(() => {
      if (!shuttingDown) startQueueWorkers();
    }, 5000).unref?.();
  });
  imageWorker = spawn(python, ["-m", "hermes_ui.image_worker"], {
    cwd: root,
    // 1.0.18: pipes + log próprio (storage/logs/image_worker.log).
    stdio: ["ignore", "pipe", "pipe"],
    env: runtimeEnv,
    windowsHide: false,
  });
  attachQueueWorkerLog(imageWorker, "image_worker.log", "image worker");
  imageWorker.on("error", (error) => console.error(`Thunderbolt image worker: ${error.message}`));
  imageWorker.on("exit", (code, signal) => {
    const diedFromDependencies = workerDiedFromDependencies(imageWorker);
    const dependencyTail = workerStderrTails.get(imageWorker) || "";
    imageWorker = null;
    if (shuttingDown) return;
    if (diedFromDependencies) {
      reportFatalDependencyFailure("O image worker", dependencyTail);
      queueWorkersDependencyFailureReported = true;
      return;
    }
    console.error(`Thunderbolt image worker: terminou (código ${code ?? "-"}, sinal ${signal ?? "-"}); a reiniciar em 5s.`);
    setTimeout(() => {
      if (!shuttingDown) startQueueWorkers();
    }, 5000).unref?.();
  });
}

function stopQueueWorkers() {
  if (thumbnailWorker && !thumbnailWorker.killed) thumbnailWorker.kill();
  thumbnailWorker = null;
  if (imageWorker && !imageWorker.killed) imageWorker.kill();
  imageWorker = null;
}

function monitorWorkers() {
  if (shuttingDown) return;
  startPipelineWorker();
  startAutomationWorker();
  startQueueWorkers();
}

function startStreamlit() {
  if (shuttingDown || child || streamlitRestartTimer || streamlitAutoRestartDisabled) return;
  const startedAt = Date.now();
  child = spawn(python, [streamlitBootstrap, "run", main, "--server.port", String(backendPort), "--server.address", "127.0.0.1"], {
    cwd: root,
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...runtimeEnv, PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1", PYTHONLEGACYWINDOWSSTDIO: "1", CLICK_NO_WIN_CONSOLE: "1", THUNDERBOLT_LAUNCHER_RESTART: "1" },
    windowsHide: false,
  });
  child.stdout?.on("data", (chunk) => {
    if (!shuttingDown) process.stdout.write(chunk);
  });  child.stderr?.on("data", (chunk) => {
    if (!shuttingDown) process.stderr.write(chunk);
  });
  child.on("error", (error) => {
    console.error(`Thunderbolt: não foi possível iniciar o Streamlit: ${error.message}`);
  });
  streamlitStableTimer = setTimeout(() => {
    streamlitFailureCount = 0;
    streamlitAutoRestartDisabled = false;
    streamlitStableTimer = null;
  }, 60000);
  child.on("exit", (code, signal) => {
    child = null;
    if (shuttingDown) {
      launcherExiting(shutdownReason || "unknown");
      process.exit(code ?? (signal ? 1 : 0));
    }
    if (code === restartExitCode) {
      // Termina a stack actual ANTES de spawnar a reposição: a ordem anterior
      // (spawn primeiro, exit depois) deixava a árvore antiga a morrer em
      // paralelo com a nova a arrancar, duplicando workers e a disputa pelos
      // locks do storage. A reposição traz o próprio guard como defesa extra.
      shuttingDown = true;
      stopStackComponents();
      proxy.close();
      const executable = platform() === "win32" ? "npx.cmd" : "npx";
      const replacement = spawn(executable, ["--yes", "--prefer-online", "@danhachuel/thunderbolt"], {
        cwd: userHome,
        env: process.env,
        detached: true,
        stdio: "ignore",
        windowsHide: false,
      });
      replacement.unref();
      launcherExiting("update");
      process.exit(0);
    }
    if (streamlitStableTimer) {
      clearTimeout(streamlitStableTimer);
      streamlitStableTimer = null;
    }
    if (Date.now() - startedAt >= 60000) {
      streamlitFailureCount = 0;
      streamlitAutoRestartDisabled = false;
    }
    // Uma falha do Streamlit não pode terminar o launcher: os workers podem
    // estar a gerar vídeos e devem continuar vivos enquanto a interface é
    // recuperada. Isto também cobre encerramentos espontâneos no Windows,
    // onde o processo filho pode terminar sem entregar um código útil.
    console.error(`Thunderbolt: Streamlit terminou inesperadamente (código ${code ?? "-"}, sinal ${signal ?? "-"}); a tentar recuperar.`);
    streamlitFailureCount += 1;
    if (streamlitFailureCount >= 5) {
      streamlitAutoRestartDisabled = true;
      console.error("O Streamlit falhou 5 vezes antes de permanecer estável. O launcher continua activo, mas a interface não será reiniciada até o Thunderbolt ser iniciado novamente.");
      return;
    }
    const delay = Math.min(2 ** streamlitFailureCount, 32) * 1000;
    console.error(`Thunderbolt: nova tentativa do Streamlit em ${delay / 1000}s (falha ${streamlitFailureCount}/5).`);
    streamlitRestartTimer = setTimeout(() => {
      streamlitRestartTimer = null;
      startStreamlit();
    }, delay);
  });
}

// Single-instance guard + lock: nenhum worker/streamlit é arrancado antes de
// a instância anterior estar totalmente terminada (o guard corre antes do
// bind da porta pública, logo esta sequência já encontra a via livre).
startStreamlit();

let shutdownReason = "unknown";

function stopStackComponents() {
  for (const socket of proxySockets) socket.destroy();
  if (streamlitRestartTimer) clearTimeout(streamlitRestartTimer);
  if (workerRestartTimer) clearTimeout(workerRestartTimer);
  if (automationStableTimer) clearTimeout(automationStableTimer);
  if (pipelineStableTimer) clearTimeout(pipelineStableTimer);
  if (streamlitStableTimer) clearTimeout(streamlitStableTimer);
  if (workerMonitorTimer) clearInterval(workerMonitorTimer);
  if (child && !child.killed) child.kill();
  if (worker && !worker.killed) worker.kill();
  stopPipelineWorker();
  stopQueueWorkers();
}

const stopWorker = (reason = "unknown") => {
  if (shuttingDown) return;
  shuttingDown = true;
  shutdownReason = reason;
  stopStackComponents();
  const finishShutdown = () => {
    if (shutdownForceTimer) clearTimeout(shutdownForceTimer);
    shutdownForceTimer = null;
    launcherExiting(shutdownReason);
    process.exit(0);
  };
  proxy.close(finishShutdown);
  shutdownForceTimer = setTimeout(finishShutdown, 5000);
  shutdownForceTimer.unref();
};
// ─────────────────────────────────────────────────────────────────────────
// Windows: absorver SIGINT espúrio
// ─────────────────────────────────────────────────────────────────────────
// O Windows 11 entrega o MESMO SIGINT para Ctrl+C real e para CTRL_C_EVENT
// espúrio gerado quando um navegador é aberto ou um subprocesso .cmd é criado
// em thread secundária (comportamento documentado: Hermes Agent, DeepTutor).
// Não é possível distingui-los. No Windows, absorvemos o sinal e oferecemos
// Ctrl+Break (SIGBREAK) e o arquivo .thunderbolt.stop como alternativa.
// No Linux/macOS, Ctrl+C continua funcionando normalmente.
const STOP_FILE = join(userHome, ".thunderbolt.stop");

if (platform() === "win32") {
  process.on("SIGINT", () => {
    diagnostic("ctrl_c_absorbed_windows", { pid: process.pid, uptime_seconds: Math.round(process.uptime()) });
  });
} else {
  process.on("SIGINT", () => stopWorker("ctrl+c"));
}
// Ctrl+Break (Windows) e SIGTERM (Unix) são paragens legítimas em todas as
// plataformas. O fecho da janela (SIGHUP) também.
process.on("SIGBREAK", () => stopWorker("ctrl+break"));
process.on("SIGHUP", () => stopWorker("console_closed"));
process.on("SIGTERM", () => stopWorker("external_kill"));

// Watcher do arquivo .thunderbolt.stop — encerramento sem depender de sinais.
const stopFileWatcher = setInterval(() => {
  try {
    if (existsSync(STOP_FILE)) {
      diagnostic("stop_file_detected", { pid: process.pid, path: STOP_FILE });
      console.log("Thunderbolt: arquivo .thunderbolt.stop detectado — encerrando...");
      try { rmSync(STOP_FILE, { force: true }); } catch { }
      stopWorker("stop-file");
    }
  } catch { }
}, 3000);
stopFileWatcher.unref();
process.on("uncaughtException", (error) => {
  diagnostic("launcher_uncaught_exception", { error: String((error && (error.stack || error.message)) || error).slice(-500) });
  launcherExiting("crash");
  process.exit(1);
});
process.on("unhandledRejection", (rejection) => {
  diagnostic("launcher_unhandled_rejection", { reason: String(rejection).slice(-500) });
});
monitorWorkers();
// O pipeline worker permanece disponível para recolher imediatamente tarefas
// colocadas em `doing` pelo botão Start, mesmo quando a fila estava vazia.
workerMonitorTimer = setInterval(monitorWorkers, 2000);
