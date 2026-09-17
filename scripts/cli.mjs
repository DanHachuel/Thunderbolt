#!/usr/bin/env node
import { spawn, spawnSync } from "node:child_process";
import http from "node:http";
import net from "node:net";
import { existsSync, mkdirSync, readFileSync, copyFileSync, readdirSync } from "node:fs";
import { homedir, platform } from "node:os";
import { join, resolve } from "node:path";
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
const settingsPath = join(storageDir, "state", "settings.json");
const pythonEnvironment = { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1", PYTHONLEGACYWINDOWSSTDIO: "1", CLICK_NO_WIN_CONSOLE: "1" };

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
  const code = `import importlib.util,sys; sys.exit(0 if importlib.util.find_spec(${JSON.stringify(moduleName)}) else 1)`;
  return spawnSync(python, ["-c", code], { stdio: "ignore", env: pythonEnvironment }).status === 0;
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
  return Array.isArray(channels) && channels.some((channel) => channel && channel.automation_on === true);
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
  if (missing.length || !ffmpeg) {
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
  run(python, ["-m", "hermes_ui.automation_worker", ...args.filter((arg) => arg !== "worker" && arg !== "--worker")], "worker de automação", runtimeEnv);
}

if (args[0] === "pipeline-worker" || args.includes("--pipeline-worker")) {
  run(python, ["-m", "hermes_ui.pipeline_worker", ...args.filter((arg) => arg !== "pipeline-worker" && arg !== "--pipeline-worker")], "worker do pipeline de vídeos", runtimeEnv);
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
  process.exitCode = 1;
});
proxy.listen(publicPort, "127.0.0.1", () => {
  console.log(`Thunderbolt: interface disponível em http://localhost:${publicPort}/`);
});
// Os workers são geridos pelo launcher para que um clique em Start na UI
// também active o processamento, mesmo sem automação de canal configurada.
// Cada worker só existe enquanto a respectiva fila tiver trabalho pendente.
let worker = null;
let pipelineWorker = null;
const restartExitCode = 75;
let shuttingDown = false;
let child;
let workerRestartTimer = null;
let pipelineRestartTimer = null;
let workerMonitorTimer = null;
let streamlitRestartTimer = null;

function startAutomationWorker() {
  if (shuttingDown || worker || !hasScheduledAutomation()) return;
  worker = spawn(python, ["-m", "hermes_ui.automation_worker"], {
    cwd: root,
    stdio: "inherit",
    env: runtimeEnv,
    windowsHide: false,
  });
  worker.on("error", (error) => console.error(`Thunderbolt worker: ${error.message}`));
  worker.on("exit", (code, signal) => {
    worker = null;
    if (shuttingDown) return;
    console.error(`Thunderbolt worker: terminou (código ${code ?? "-"}, sinal ${signal ?? "-"}).`);
    if (hasScheduledAutomation()) {
      workerRestartTimer = setTimeout(() => {
        workerRestartTimer = null;
        startAutomationWorker();
      }, 5000);
    }
  });
}

function stopPipelineWorker() {
  if (pipelineRestartTimer) {
    clearTimeout(pipelineRestartTimer);
    pipelineRestartTimer = null;
  }
  if (pipelineWorker && !pipelineWorker.killed) pipelineWorker.kill();
  pipelineWorker = null;
}

function startPipelineWorker() {
  if (shuttingDown || pipelineWorker) return;
  pipelineWorker = spawn(python, ["-m", "hermes_ui.pipeline_worker"], {
    cwd: root,
    stdio: "inherit",
    env: runtimeEnv,
    windowsHide: false,
  });
  pipelineWorker.on("error", (error) => console.error(`Thunderbolt pipeline worker: ${error.message}`));
  pipelineWorker.on("exit", (code, signal) => {
    pipelineWorker = null;
    if (shuttingDown) return;
    console.error(`Thunderbolt pipeline worker: terminou (código ${code ?? "-"}, sinal ${signal ?? "-"}).`);
    pipelineRestartTimer = setTimeout(() => {
      pipelineRestartTimer = null;
      startPipelineWorker();
    }, 5000);
  });
}

function monitorWorkers() {
  if (shuttingDown) return;
  startPipelineWorker();
  startAutomationWorker();
}

function startStreamlit() {
  if (shuttingDown || child) return;
  child = spawn(python, [streamlitBootstrap, "run", main, "--server.port", String(backendPort), "--server.address", "127.0.0.1"], {
    cwd: root,
    stdio: "inherit",
    env: { ...runtimeEnv, PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1", PYTHONLEGACYWINDOWSSTDIO: "1", CLICK_NO_WIN_CONSOLE: "1", THUNDERBOLT_LAUNCHER_RESTART: "1" },
    windowsHide: false,
  });
  child.on("error", (error) => {
    console.error(`Thunderbolt: não foi possível iniciar o Streamlit: ${error.message}`);
  });
  child.on("exit", (code, signal) => {
    child = null;
    if (shuttingDown) {
      stopWorker();
      process.exit(code ?? (signal ? 1 : 0));
    }
    if (code === restartExitCode) {
      const executable = platform() === "win32" ? "npx.cmd" : "npx";
      const replacement = spawn(executable, ["--yes", "--prefer-online", "@danhachuel/thunderbolt"], {
        cwd: userHome,
        env: process.env,
        detached: true,
        stdio: "ignore",
        windowsHide: false,
      });
      replacement.unref();
      stopWorker();
      process.exit(0);
    }
    // Uma falha do Streamlit não pode terminar o launcher: os workers podem
    // estar a gerar vídeos e devem continuar vivos enquanto a interface é
    // recuperada. Isto também cobre encerramentos espontâneos no Windows,
    // onde o processo filho pode terminar sem entregar um código útil.
    console.error(`Thunderbolt: Streamlit terminou inesperadamente (código ${code ?? "-"}, sinal ${signal ?? "-"}); a tentar recuperar.`);
    if (!streamlitRestartTimer) {
      streamlitRestartTimer = setTimeout(() => {
        streamlitRestartTimer = null;
        startStreamlit();
      }, 3000);
    }
  });
}

startStreamlit();

const stopWorker = () => {
  shuttingDown = true;
  for (const socket of proxySockets) socket.destroy();
  proxy.close();
  if (streamlitRestartTimer) clearTimeout(streamlitRestartTimer);
  if (workerRestartTimer) clearTimeout(workerRestartTimer);
  if (workerMonitorTimer) clearInterval(workerMonitorTimer);
  if (worker && !worker.killed) worker.kill();
  stopPipelineWorker();
};
// No Windows, Ctrl+C/SIGINT pode ser propagado ao launcher e ao Streamlit ao
// mesmo tempo. Ignorar o sinal preserva a automação; não escrever no terminal
// evita um ciclo de mensagens quando a consola repete o evento.
process.on("SIGINT", () => {});
process.on("SIGTERM", stopWorker);
monitorWorkers();
// O pipeline worker permanece disponível para recolher imediatamente tarefas
// colocadas em `doing` pelo botão Start, mesmo quando a fila estava vazia.
workerMonitorTimer = setInterval(monitorWorkers, 2000);
