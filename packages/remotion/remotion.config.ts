/**
 * Configuração do Remotion CLI (preview/studio).
 *
 * IMPORTANTE: o pipeline do Thunderbolt NÃO usa o CLI — o wrapper
 * `render.mjs` chama bundle()/selectComposition()/renderMedia()
 * programaticamente e passa os executáveis do sistema (Chromium do
 * Playwright e FFmpeg do imageio-ffmpeg) pelas opções `browserExecutable`
 * e env `FFMPEG_BINARY`. O remotion.config.ts só cobre uso manual
 * (`npx remotion studio`) dentro de packages/remotion/.
 */
import { Config } from "@remotion/cli/config";

Config.setEntryPoint("./src/index.ts");
Config.setOverwriteOutput(true);
