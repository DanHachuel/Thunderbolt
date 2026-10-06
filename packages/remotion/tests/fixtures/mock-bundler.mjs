/** Mock do @remotion/bundler para os testes do wrapper (sem node_modules). */
import { mkdirSync, writeFileSync } from "node:fs";

export async function bundle(entryPoint, options = {}) {
  const dir = `${process.env.MOCK_BUNDLE_DIR || "./.mock-bundle"}`;
  mkdirSync(dir, { recursive: true });
  writeFileSync(`${dir}/index.html`, `<html><body>mock bundle for ${entryPoint}</body></html>`);
  if (options && typeof options.onProgress === "function") {
    options.onProgress(1);
  }
  return dir;
}
