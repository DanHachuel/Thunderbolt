export function estimateAudioFrames(text: string, wps = 2.5, fps = 30): number {
  const words = (text || "").trim().split(/\s+/).filter(Boolean).length;
  const seconds = Math.max(1, words / wps);
  return Math.round(seconds * fps);
}
