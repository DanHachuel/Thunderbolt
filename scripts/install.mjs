#!/usr/bin/env node
import { existsSync, mkdirSync, readFileSync, rmSync, renameSync, cpSync, copyFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { homedir, platform } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";

const root = resolve(fileURLToPath(new URL(".", import.meta.url)), "..");
const args = process.argv.slice(2);

function getUserHome() {
  if (platform() !== "win32") return homedir();
  const driveHome = process.env.HOMEDRIVE && process.env.HOMEPATH ? `${process.env.HOMEDRIVE}${process.env.HOMEPATH}` : null;
  const candidates = [process.env.USERPROFILE, driveHome, homedir()].filter(Boolean);
  const slash = String.fromCharCode(92);
  for (const candidate of candidates) {
    const normalized = candidate.replaceAll("/", slash);
    const lower = normalized.toLowerCase();
    const userMarker = `${slash}users${slash}`;
    const suffixes = [
      `${slash}appdata${slash}local${slash}hermes`,
      `${slash}appdata${slash}local${slash}hermes-ui`,
      `${slash}appdata${slash}roaming${slash}mobaxterm${slash}home`,
    ];
    const suffix = suffixes.find((value) => lower.endsWith(value));
    if (suffix && lower.includes(userMarker)) return normalized.slice(0, -suffix.length);
    if (lower.includes(userMarker)) return normalized;
  }
  return candidates[0] || homedir();
}

const home = getUserHome();
const explicitThunderboltHome = process.env.THUNDERBOLT_HOME || "";
const defaultThunderboltHome = platform() === "win32"
  ? join(process.env.LOCALAPPDATA || join(home, "AppData", "Local"), "THUNDERBOLT")
  : join(home, ".thunderbolt");
const thunderboltHome = resolve(explicitThunderboltHome || defaultThunderboltHome);
const venvPath = process.env.THUNDERBOLT_VENV || process.env.HERMES_VENV || join(thunderboltHome, ".venv");
const pythonBin = platform() === "win32" ? join(venvPath, "Scripts", "python.exe") : join(venvPath, "bin", "python");
const defaultMpt = process.env.MONEYPRINTER_PATH || join(thunderboltHome, "MoneyPrinterTurbo");
const dependencyStatePath = join(thunderboltHome, "storage", "state", "install-state.json");
const forceDeps = args.includes("--force-deps");
const refreshMoneyPrinter = args.includes("--refresh-moneyprinter");
const pythonEnvironment = { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1", PYTHONLEGACYWINDOWSSTDIO: "1", CLICK_NO_WIN_CONSOLE: "1" };

function legacyRoots() {
  const userProfile = process.env.USERPROFILE || home;
  const localAppData = process.env.LOCALAPPDATA || join(userProfile, "AppData", "Local");
  const roots = [
    join(home, "Hermes-UI"),
    join(localAppData, "hermes"),
    join(localAppData, "Hermes-UI"),
    join(userProfile, ".content-hermes"),
    join(userProfile, "hermes"),
  ];
  return [...new Set(roots.map((candidate) => resolve(candidate)))].filter((candidate) => candidate !== thunderboltHome);
}

function commandExists(command) {
  const result = spawnSync(platform() === "win32" ? "where" : "which", [command], { stdio: "ignore" });
  return result.status === 0;
}

function run(command, commandArgs, options = {}) {
  console.log(`\n> ${command} ${commandArgs.join(" ")}`);
  const result = spawnSync(command, commandArgs, { stdio: "inherit", env: pythonEnvironment, ...options, env: { ...pythonEnvironment, ...(options.env || {}) } });
  if (result.status !== 0) process.exit(result.status || 1);
}

function probePython(command, commandArgs = []) {
  const result = spawnSync(command, [...commandArgs, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"], { encoding: "utf8", env: pythonEnvironment });
  if (result.status !== 0) return null;
  const versionText = result.stdout.trim();
  const version = versionText.split(".").map(Number);
  if (version[0] > 3 || (version[0] === 3 && version[1] >= 11)) return { command, args: commandArgs, version: versionText };
  return null;
}

function findPython() {
  const candidates = [];
  if (existsSync(pythonBin)) candidates.push({ command: pythonBin, args: [] });
  if (process.env.THUNDERBOLT_PYTHON || process.env.HERMES_PYTHON) {
    candidates.push({ command: process.env.THUNDERBOLT_PYTHON || process.env.HERMES_PYTHON, args: [] });
  }
  candidates.push(...(platform() === "win32"
    ? [{ command: "py", args: ["-3.11"] }, { command: "py", args: [] }, { command: "python", args: [] }, { command: "python3", args: [] }]
    : [{ command: "python3.11", args: [] }, { command: "python3", args: [] }, { command: "python", args: [] }]));
  for (const candidate of candidates) {
    const found = probePython(candidate.command, candidate.args);
    if (found) return found;
  }
  return null;
}

function ensureDirs() {
  const storageRoot = join(thunderboltHome, "storage");
  const directories = [
    thunderboltHome,
    storageRoot,
    join(storageRoot, "state"),
    join(storageRoot, "blueprints"),
    join(storageRoot, "blueprints", "canais"),
    join(storageRoot, "blueprints", "nichos"),
    join(storageRoot, "blueprints", "importados"),
    join(storageRoot, "blueprints", "brandings"),
    join(storageRoot, "blueprints", "thumbnails"),
    join(storageRoot, "tiktok"),
    join(storageRoot, "tiktok", "prompts_master"),
    join(storageRoot, "metadata_cleaner"),
    join(storageRoot, "metadata_cleaner", "originals"),
    join(storageRoot, "metadata_cleaner", "outputs"),
    join(storageRoot, "artifacts"),
    join(storageRoot, "skills"),
    join(storageRoot, "music"),
    join(storageRoot, "voice_previews"),
    join(storageRoot, "data"),
    join(storageRoot, "data", "niches"),
  ];
  for (const directory of directories) mkdirSync(directory, { recursive: true });
  copySeedBlueprints(storageRoot);
  copySeedPromptMasters(storageRoot);
}

function copySeedBlueprints(storageRoot) {
  const seedRoot = join(root, "seed", "blueprints");
  const destination = join(storageRoot, "blueprints", "importados");
  if (!existsSync(seedRoot)) return;
  for (const filename of readdirSync(seedRoot)) {
    if (!filename.endsWith(".json")) continue;
    const source = join(seedRoot, filename);
    const target = join(destination, filename);
    if (!existsSync(target)) copyFileSync(source, target);
  }
  const thumbnailSeedRoot = join(seedRoot, "thumbnails");
  const thumbnailDestination = join(storageRoot, "blueprints", "thumbnails");
  if (existsSync(thumbnailSeedRoot)) {
    for (const thumbnailFilename of readdirSync(thumbnailSeedRoot)) {
      if (!thumbnailFilename.endsWith(".md")) continue;
      const source = join(thumbnailSeedRoot, thumbnailFilename);
      const target = join(thumbnailDestination, thumbnailFilename);
      if (!existsSync(target)) copyFileSync(source, target);
    }
  }
  const pairSource = join(seedRoot, "thumbnail_blueprint_pairs.json");
  const pairTarget = join(storageRoot, "blueprints", "thumbnail_blueprint_pairs.json");
  if (existsSync(pairSource)) {
    try {
      const seededPairs = JSON.parse(readFileSync(pairSource, "utf8"));
      const currentPairs = existsSync(pairTarget) ? JSON.parse(readFileSync(pairTarget, "utf8")) : {};
      if (seededPairs && currentPairs && typeof seededPairs === "object" && typeof currentPairs === "object") {
        writeFileSync(pairTarget, JSON.stringify({ ...seededPairs, ...currentPairs }, null, 2) + "\n", "utf8");
      }
    } catch {
      if (!existsSync(pairTarget)) copyFileSync(pairSource, pairTarget);
    }
  }
}

function copySeedPromptMasters(storageRoot) {
  const seedRoot = join(root, "seed", "prompt_masters");
  const destination = join(storageRoot, "tiktok", "prompts_master");
  if (!existsSync(seedRoot)) return;
  mkdirSync(destination, { recursive: true });
  for (const filename of readdirSync(seedRoot)) {
    if (!filename.endsWith(".md")) continue;
    const source = join(seedRoot, filename);
    const target = join(destination, filename);
    if (!existsSync(target)) copyFileSync(source, target);
  }
}

function copyMissingTree(source, target) {
  if (!existsSync(source)) return 0;
  let copied = 0;
  let sourceStat;
  try { sourceStat = statSync(source); } catch { return 0; }
  if (sourceStat.isDirectory()) {
    mkdirSync(target, { recursive: true });
    for (const entry of readdirSync(source, { withFileTypes: true })) {
      copied += copyMissingTree(join(source, entry.name), join(target, entry.name));
    }
    return copied;
  }
  if (existsSync(target)) return 0;
  mkdirSync(dirname(target), { recursive: true });
  copyFileSync(source, target);
  return 1;
}

function legacyNpxPackageRoots() {
  const roots = new Set();
  const cacheHashes = [resolve(root, "../../..")];
  const cacheRoot = resolve(root, "../../../..");
  if (existsSync(cacheRoot)) {
    try {
      for (const entry of readdirSync(cacheRoot, { withFileTypes: true })) {
        if (entry.isDirectory()) cacheHashes.push(join(cacheRoot, entry.name));
      }
    } catch { /* cache inacessível: a instalação normal continua */ }
  }
  for (const hashRoot of cacheHashes) {
    const candidate = resolve(hashRoot, "node_modules", "@danhachuel", "thunderbolt");
    if (candidate === root || roots.has(candidate)) continue;
    const recoverableStateFiles = ["ai_influencers.db", "tasks.json", "channels.json", "batches.json", "queues.json"];
    if (recoverableStateFiles.some((filename) => existsSync(join(candidate, "storage", "state", filename)))) roots.add(candidate);
  }
  return [...roots].sort((left, right) => {
    const newestStateTime = (candidate) => Math.max(...["ai_influencers.db", "tasks.json", "channels.json", "batches.json", "queues.json"].map((filename) => {
      try { return statSync(join(candidate, "storage", "state", filename)).mtimeMs; }
      catch { return 0; }
    }));
    return newestStateTime(right) - newestStateTime(left);
  });
}

function migrateLegacyNpxStorage() {
  const targetStorage = join(thunderboltHome, "storage");
  const migrationMarker = join(targetStorage, "state", "npx-storage-migration-v1.json");
  if (existsSync(migrationMarker)) return;
  const candidates = legacyNpxPackageRoots();
  let mergedFiles = 0;
  for (const candidate of candidates) {
    copyMissingTree(join(candidate, "storage"), targetStorage);
    mergedFiles += mergeLegacyStorage(candidate);
  }
  if (mergedFiles > 0) console.log(`Dados locais recuperados do cache npm para ${targetStorage} (${mergedFiles} ficheiro(s) unido(s)).`);
  mkdirSync(dirname(migrationMarker), { recursive: true });
  writeFileSync(migrationMarker, JSON.stringify({ version: 1, migrated_at: new Date().toISOString() }) + "\n", "utf8");
}

function copyOrMove(source, target, label) {
  if (!existsSync(source) || existsSync(target)) return false;
  mkdirSync(dirname(target), { recursive: true });
  try {
    renameSync(source, target);
    console.log(`Migração concluída: ${label} -> ${target}`);
  } catch {
    cpSync(source, target, { recursive: true });
    console.log(`Dados copiados para Thunderbolt: ${label} -> ${target}`);
  }
  return true;
}

function parseJsonFile(path) {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return null;
  }
}

function mergeUniqueArray(target, source) {
  const merged = [...target];
  const knownIds = new Set(merged.filter((item) => item && typeof item === "object" && item.id).map((item) => String(item.id)));
  const knownValues = new Set(merged.map((item) => JSON.stringify(item)));
  for (const item of source) {
    const id = item && typeof item === "object" && item.id ? String(item.id) : "";
    const value = JSON.stringify(item);
    if ((id && knownIds.has(id)) || knownValues.has(value)) continue;
    merged.push(item);
    if (id) knownIds.add(id);
    knownValues.add(value);
  }
  return merged;
}

function mergeJsonStateFile(source, target, filename) {
  if (!existsSync(source) || !existsSync(target)) return false;
  const sourceData = parseJsonFile(source);
  const targetData = parseJsonFile(target);
  if (sourceData === null) return false;
  if (targetData === null) {
    copyFileSync(target, `${target}.corrupt-${Date.now()}`);
    writeFileSync(target, JSON.stringify(sourceData, null, 2) + "\n", "utf8");
    return true;
  }
  let merged = targetData;
  if (Array.isArray(sourceData) && Array.isArray(targetData)) {
    merged = mergeUniqueArray(targetData, sourceData);
  } else if (filename === "queues.json" && sourceData && targetData && typeof sourceData === "object" && typeof targetData === "object") {
    merged = { ...targetData };
    for (const [queueName, sourceItems] of Object.entries(sourceData)) {
      if (!Array.isArray(sourceItems)) continue;
      const targetItems = Array.isArray(merged[queueName]) ? merged[queueName] : [];
      merged[queueName] = mergeUniqueArray(targetItems, sourceItems);
    }
  }
  if (JSON.stringify(merged) === JSON.stringify(targetData)) return false;
  writeFileSync(target, JSON.stringify(merged, null, 2) + "\n", "utf8");
  return true;
}

function mergeLegacyStorage(legacyRoot) {
  const sourceStorage = join(legacyRoot, "storage");
  const targetStorage = join(thunderboltHome, "storage");
  if (!existsSync(sourceStorage)) return 0;
  mkdirSync(targetStorage, { recursive: true });
  copyMissingTree(sourceStorage, targetStorage);
  const sourceState = join(sourceStorage, "state");
  const targetState = join(targetStorage, "state");
  if (!existsSync(sourceState) || !existsSync(targetState)) return 0;
  let mergedCount = 0;
  for (const entry of readdirSync(sourceState, { withFileTypes: true })) {
    if (!entry.isFile() || !entry.name.endsWith(".json")) continue;
    if (mergeJsonStateFile(join(sourceState, entry.name), join(targetState, entry.name), entry.name)) mergedCount += 1;
  }
  return mergedCount;
}

function migrateLegacyInstallation() {
  if (explicitThunderboltHome) return;
  const candidates = legacyRoots();
  let found = false;
  for (const legacy of candidates) {
    if (!existsSync(join(legacy, "storage")) && !existsSync(join(legacy, ".venv")) && !existsSync(join(legacy, "MoneyPrinterTurbo"))) continue;
    found = true;
    console.warn(`Foi encontrada uma instalação antiga em ${legacy}. O Thunderbolt usará ${thunderboltHome}.`);
    const mergedFiles = mergeLegacyStorage(legacy);
    if (mergedFiles > 0) console.log(`Dados de estado recuperados da instalação antiga (${mergedFiles} ficheiro(s) unido(s)).`);
    copyOrMove(join(legacy, ".venv"), join(thunderboltHome, ".venv"), "ambiente Python legado");
    copyOrMove(join(legacy, "MoneyPrinterTurbo"), join(thunderboltHome, "MoneyPrinterTurbo"), "MoneyPrinterTurbo legado");
  }
  if (found) console.log("A instalação antiga foi preservada; o Thunderbolt não elimina tarefas, filas ou artefactos durante a actualização.");
}

function removePath(path) {
  if (!existsSync(path)) return;
  console.log(`A remover componente técnico: ${path}`);
  try {
    rmSync(path, { recursive: true, force: true });
  } catch (error) {
    console.error(`Não foi possível remover ${path}: ${error.message}`);
    console.error("Feche processos Thunderbolt/Node/Python que estejam a usar a pasta e execute novamente.");
    process.exit(1);
  }
}

function containsUserData(path) {
  return [
    join(path, "storage", "blueprints"),
    join(path, "storage", "brandings"),
    join(path, "storage", "state"),
  ].some((candidate) => existsSync(candidate));
}

function cleanInstallationRoots(moneyprinterPath) {
  if (args.includes("--purge-data")) {
    console.warn("ATENÇÃO: --purge-data apaga Blueprints, Brandings, configurações, storage e artefactos locais.");
    removePath(thunderboltHome);
    return;
  }

  if (refreshMoneyPrinter && resolve(moneyprinterPath).startsWith(thunderboltHome)) removePath(moneyprinterPath);
  for (const legacyRoot of legacyRoots()) {
    if (existsSync(legacyRoot) && containsUserData(legacyRoot)) {
      console.warn(`Instalação antiga com dados preservada para revisão manual: ${legacyRoot}`);
    }
  }
}

function installPythonWindows() {
  if (process.env.THUNDERBOLT_SKIP_PYTHON_INSTALL === "1" || process.env.HERMES_SKIP_PYTHON_INSTALL === "1") return null;
  if (!commandExists("winget")) {
    console.error("Python 3.11+ não foi encontrado e o winget também não está disponível.");
    console.error("Instale Python 3.11+ a partir de https://www.python.org/downloads/windows/ ou instale o App Installer da Microsoft para obter o winget.");
    console.error("Depois execute novamente: npx.cmd --yes @danhachuel/thunderbolt install");
    process.exit(1);
  }
  console.log("Python 3.11+ não encontrado. A instalar Python automaticamente através do winget...");
  const result = spawnSync("winget", ["install", "--exact", "--id", "Python.Python.3.11", "--source", "winget", "--scope", "user", "--accept-source-agreements", "--accept-package-agreements", "--silent"], { stdio: "inherit" });
  if (result.status !== 0) process.exit(result.status || 1);
  const found = findPython();
  if (!found) {
    console.error("Python foi instalado, mas o terminal actual ainda não encontrou o comando. Feche e reabra o terminal e repita.");
    process.exit(1);
  }
  return found;
}

function ensurePython() {
  let found = findPython();
  if (found) {
    console.log(`Python compatível encontrado: ${found.command} ${found.args.join(" ")} (${found.version})`);
    return found;
  }
  if (existsSync(venvPath)) removePath(venvPath);
  found = findPython();
  if (!found && platform() === "win32") found = installPythonWindows();
  if (!found) {
    console.error("Python 3.11 ou superior não foi encontrado. Instale Python 3.11+ e execute novamente.");
    process.exit(1);
  }
  return found;
}

function installFfmpegWindows() {
  if (platform() !== "win32" || process.env.THUNDERBOLT_SKIP_FFMPEG_INSTALL === "1") return;
  if (!commandExists("winget")) {
    console.warn("winget não encontrado; o FFmpeg 7.1 não foi instalado automaticamente. Instale-o com: winget install --id BtbN.FFmpeg.GPL.7.1 --version 7.1-20240930 -e");
    return;
  }
  console.log("A instalar FFmpeg 7.1 Péter através do winget...");
  const result = spawnSync("winget", ["install", "--id", "BtbN.FFmpeg.GPL.7.1", "--version", "7.1-20240930", "-e", "--accept-source-agreements", "--accept-package-agreements", "--silent"], { stdio: "inherit", env: pythonEnvironment });
  if (result.status !== 0) {
    console.warn("Não foi possível instalar o FFmpeg 7.1 automaticamente. Execute o comando winget mostrado na aba Configuração API > FFmpeg.");
  }
}

function cloneMoneyPrinter(path) {
  if (existsSync(join(path, ".git")) || existsSync(join(path, "pyproject.toml"))) {
    console.log(`MoneyPrinterTurbo já existe em ${path}; será reutilizado.`);
    return;
  }
  if (!commandExists("git")) {
    console.error("Git não encontrado. Instale Git ou defina MONEYPRINTER_PATH para uma cópia local do MoneyPrinterTurbo.");
    process.exit(1);
  }
  const destination = resolve(path);
  const parent = resolve(destination, "..");
  mkdirSync(parent, { recursive: true });
  run("git", ["clone", "--depth", "1", "https://github.com/harry0703/MoneyPrinterTurbo.git", basename(destination)], { cwd: parent });
}

function fileHash(path) {
  if (!existsSync(path)) return "missing";
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function readDependencyState() {
  if (!existsSync(dependencyStatePath)) return {};
  try { return JSON.parse(readFileSync(dependencyStatePath, "utf8")); } catch { return {}; }
}

function writeDependencyState(updates) {
  mkdirSync(dirname(dependencyStatePath), { recursive: true });
  const state = { ...readDependencyState(), ...updates, updated_at: new Date().toISOString() };
  writeFileSync(dependencyStatePath, JSON.stringify(state, null, 2) + "\n", "utf8");
}

function importsAvailable(modules) {
  if (!existsSync(pythonBin)) return false;
  const code = `import importlib.util,sys; missing=[m for m in ${JSON.stringify(modules)} if importlib.util.find_spec(m) is None]; sys.exit(1 if missing else 0)`;
  return spawnSync(pythonBin, ["-c", code], { stdio: "ignore" }).status === 0;
}

function installRequirementIfNeeded(requirementsPath, stateKey, modules, label) {
  if (!existsSync(requirementsPath)) return;
  const currentHash = fileHash(requirementsPath);
  const state = readDependencyState();
  const importsOk = importsAvailable(modules);
  const hashMatches = state[stateKey] === currentHash;
  const markerPath = join(venvPath, `.${stateKey}.sha256`);
  const markerHash = existsSync(markerPath) ? readFileSync(markerPath, "utf8").trim() : "";
  const persistedHashMatches = hashMatches || markerHash === currentHash;
  if (!forceDeps && importsOk) {
    console.log(`${label}: dependências detectadas e reutilizadas; nenhuma reinstalação necessária.`);
    writeFileSync(markerPath, `${currentHash}\n`, "utf8");
    writeDependencyState({ [stateKey]: currentHash });
    return;
  }
  console.log(`${label}: dependências ausentes, incompletas ou alteradas; a instalar agora.`);
  run(pythonBin, ["-m", "pip", "install", "-r", requirementsPath]);
  writeFileSync(markerPath, `${currentHash}\n`, "utf8");
  writeDependencyState({ [stateKey]: currentHash });
}

function installPlaywrightBrowsers() {
  if (!existsSync(pythonBin)) return;
  console.log("Playwright: a verificar o browser Chromium... ");
  const result = spawnSync(pythonBin, ["-m", "playwright", "install", "chromium"], { stdio: "inherit", env: pythonEnvironment });
  if (result.status !== 0) {
    console.error("Não foi possível instalar o browser Chromium do Playwright.");
    console.error("Execute novamente o instalador depois de confirmar o acesso à Internet.");
    process.exit(result.status || 1);
  }
}

function writeSettings(moneyprinterPath) {
  const stateDir = join(thunderboltHome, "storage", "state");
  mkdirSync(stateDir, { recursive: true });
  const settingsPath = join(stateDir, "settings.json");
  let settings = {};
  if (existsSync(settingsPath)) {
    try { settings = JSON.parse(readFileSync(settingsPath, "utf8")); } catch { settings = {}; }
  }
  settings.moneyprinter_path = moneyprinterPath;
  if (!settings.ffmpeg_path) settings.ffmpeg_path = "ffmpeg";
  if (!settings.ffmpeg_version) settings.ffmpeg_version = "7.1-20240930";
  if (!settings.llm_provider || String(settings.llm_provider).trim().toLowerCase() === "moonshot") {
    settings.llm_provider = "openai";
  }
  settings.port = Number(process.env.THUNDERBOLT_PORT || process.env.HERMES_PORT || settings.port || 3030);
  writeFileSync(settingsPath, JSON.stringify(settings, null, 2) + "\n", "utf8");
}

function installThunderboltDependencies(python) {
  if (!existsSync(pythonBin)) run(python.command, [...python.args, "-m", "venv", venvPath]);
  installRequirementIfNeeded(join(root, "requirements.txt"), "thunderbolt_requirements_sha256", ["streamlit", "requests", "pandas", "toml", "imageio_ffmpeg", "edge_tts", "google.auth", "google_auth_oauthlib", "googleapiclient", "yt_dlp", "deno", "youtube_transcript_api", "huggingface_hub", "playwright"], "Thunderbolt");
  installPlaywrightBrowsers();
}

function installMoneyPrinterDependencies(moneyprinterPath) {
  installRequirementIfNeeded(join(moneyprinterPath, "requirements.txt"), "moneyprinter_requirements_sha256", ["fastapi", "moviepy", "PIL", "numpy", "requests"], "MoneyPrinterTurbo");
}

function main() {
  const skipMpt = args.includes("--skip-moneyprinter");
  const skipDeps = args.includes("--skip-python-deps");
  const moneyprinterPath = process.env.MONEYPRINTER_PATH || defaultMpt;
  migrateLegacyInstallation();
  cleanInstallationRoots(moneyprinterPath);
  ensureDirs();
  migrateLegacyNpxStorage();
  const python = skipDeps ? null : ensurePython();
  if (!skipMpt) cloneMoneyPrinter(moneyprinterPath);
  if (!skipDeps) installThunderboltDependencies(python);
  if (!skipDeps && !skipMpt) installMoneyPrinterDependencies(moneyprinterPath);
  if (!skipDeps) installFfmpegWindows();
  writeSettings(moneyprinterPath);
  console.log("\nInstalação do Thunderbolt concluída.");
  console.log(`Pasta Thunderbolt: ${thunderboltHome}`);
  console.log(`Ambiente Python: ${venvPath}`);
  console.log(`Motor de vídeo: ${moneyprinterPath}`);
  console.log("Execute `npx.cmd --yes @danhachuel/thunderbolt` no Windows ou `npx --yes @danhachuel/thunderbolt` noutros sistemas.");
}

main();
