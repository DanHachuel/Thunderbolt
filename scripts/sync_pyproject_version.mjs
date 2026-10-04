#!/usr/bin/env node
/**
 * Sincroniza a versão do pyproject.toml (thunderbolt-runtime) com a do
 * package.json. Impede que uma publicação npm esqueça o "bump duplo"
 * (REAL-BUG #2: 0.9.47 vs 0.9.46) — o workflow de publicação executa este
 * script antes de empacotar, e pode ser usado manualmente antes de um commit:
 *
 *   node scripts/sync_pyproject_version.mjs          # sincroniza em silêncio
 *   node scripts/sync_pyproject_version.mjs --check  # só verifica (exit 1 se divergir)
 */
import { readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(fileURLToPath(new URL(".", import.meta.url)), "..");
const packagePath = join(root, "package.json");
const pyprojectPath = join(root, "pyproject.toml");
const checkOnly = process.argv.includes("--check");

const packageVersion = JSON.parse(readFileSync(packagePath, "utf8")).version;
const pyproject = readFileSync(pyprojectPath, "utf8");
const versionLine = /^version\s*=\s*"([^"]+)"/m.exec(pyproject);

if (!versionLine) {
  console.error("pyproject.toml não contém uma linha `version = \"...\"` para sincronizar.");
  process.exit(1);
}

if (versionLine[1] === packageVersion) {
  console.log(`Versões já sincronizadas: package.json e pyproject.toml em ${packageVersion}.`);
  process.exit(0);
}

if (checkOnly) {
  console.error(`Divergência de versão: package.json=${packageVersion} mas pyproject.toml=${versionLine[1]}. Execute: node scripts/sync_pyproject_version.mjs`);
  process.exit(1);
}

const updated = pyproject.replace(versionLine[0], `version = "${packageVersion}"`);
writeFileSync(pyprojectPath, updated, "utf8");
console.log(`pyproject.toml sincronizado: ${versionLine[1]} -> ${packageVersion}.`);
