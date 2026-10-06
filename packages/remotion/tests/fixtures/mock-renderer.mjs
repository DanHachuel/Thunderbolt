/** Mock do @remotion/renderer para os testes do wrapper (sem node_modules). */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

export async function selectComposition({ compositionId, inputProps }) {
  const width = Number(inputProps && inputProps.width) || 1920;
  const height = Number(inputProps && inputProps.height) || 1080;
  const fps = Number(inputProps && inputProps.fps) || 30;
  const scenes = Array.isArray(inputProps && inputProps.scenes) ? inputProps.scenes : [];
  const frames = scenes.reduce((acc, scene) => acc + Math.round((Number(scene.durationInSeconds) || 0) * fps), 0);
  const durationInFrames = Math.max(30, frames + fps);
  return {
    id: compositionId,
    width,
    height,
    fps,
    durationInFrames,
    durationInMilliseconds: (durationInFrames / fps) * 1000,
  };
}

export async function renderMedia({ composition, outputLocation, onProgress }) {
  if (typeof onProgress === "function") {
    onProgress({ progress: 0.5 });
    onProgress({ progress: 1 });
  }
  mkdirSync(dirname(outputLocation), { recursive: true });
  writeFileSync(outputLocation, `mock-mp4:${composition.id}:${composition.durationInFrames}`);
}
