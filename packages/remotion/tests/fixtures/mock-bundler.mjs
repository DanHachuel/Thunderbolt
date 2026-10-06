/** Mock do @remotion/bundler para os testes do wrapper (sem node_modules). */
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export async function bundle(entryPoint, options = {}) {
  // Nunca escreve na raiz do repositório: usa o dir do teste ou um temp.
  const dir = process.env.MOCK_BUNDLE_DIR || mkdtempSync(join(tmpdir(), "thunderbolt-mock-bundle-"));
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "index.html"), `<html><body>mock bundle for ${entryPoint}</body></html>`);
  if (options && typeof options.onProgress === "function") {
    options.onProgress(1);
  }
  return dir;
}
