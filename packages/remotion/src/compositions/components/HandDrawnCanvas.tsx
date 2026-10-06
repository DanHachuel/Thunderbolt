import React, { useEffect, useRef } from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";

/**
 * HandDrawnCanvas — motor de fundo desenhado à mão dentro do Remotion,
 * derivado da skill hand-drawn-canvas-animation (alesha-pro/tools).
 *
 * Invariantes da skill aplicados aqui:
 * - Randomness com seed (mulberry32): as marcas de cada pose nascem UMA vez
 *   por desenho, com ids semânticos estáveis; um desenho mantido mantém as
 *   mesmas marcas (nada de "boil" uniforme por frame).
 * - Whole-pose drawings: cada pose é um conjunto inteiro de traços; a pose
 *   avança em exposures (twos: 2 frames de filme por desenho).
 * - Timebase: o filme corre a filmFps (24) DENTRO da composição (fps 30).
 *   filmFrame = min(NDRAW-1, floor(frame * filmFps / compositionFps)) — a
 *   fórmula documentada pela skill para composições Remotion.
 * - Cinco looks com palettes próprias: paperInk, risoPop, screenSea,
 *   pencilMinimal, doodlePastel.
 */

const LOOKS = {
  paperInk: { paper: "#f4efe4", ink: "#181410", accent: "#181410", strokeScale: 1 },
  risoPop: { paper: "#f7f1e3", ink: "#e8443a", accent: "#2b54d8", strokeScale: 1 },
  screenSea: { paper: "#eef4f2", ink: "#0d3b3b", accent: "#0d3b3b", strokeScale: 1.15 },
  pencilMinimal: { paper: "#f6f5f1", ink: "#4a4a46", accent: "#8a8a84", strokeScale: 0.65 },
  doodlePastel: { paper: "#f3ead9", ink: "#2f2a26", accent: "#e0662f", strokeScale: 1 },
};

export type HandDrawnLook = keyof typeof LOOKS;

function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hashString(value: string): number {
  let hash = 2166136261;
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

interface Pose {
  strokes: Array<{ points: Array<[number, number]>; width: number }>;
}

/** Cada pose é desenhada UMA vez a partir do seed — marcas estáveis por desenho. */
function buildPose(seedKey: string, look: HandDrawnLook, posesPerFilm: number, index: number): Pose {
  const random = mulberry32(hashString(`${seedKey}::pose::${index}`));
  const strokes: Pose["strokes"] = [];
  const count = 7 + Math.floor(random() * 5);
  for (let s = 0; s < count; s += 1) {
    const points: Array<[number, number]> = [];
    const segments = 4;
    const baseX = 0.12 + random() * 0.76;
    const baseY = 0.14 + random() * 0.72;
    let angle = random() * Math.PI * 2;
    let x = baseX;
    let y = baseY;
    for (let p = 0; p <= segments; p += 1) {
      angle += (random() - 0.5) * 1.4;
      const step = 0.04 + random() * 0.08;
      x = Math.min(0.94, Math.max(0.06, x + Math.cos(angle) * step));
      y = Math.min(0.92, Math.max(0.08, y + Math.sin(angle) * step));
      points.push([x, y]);
    }
    strokes.push({
      points,
      width: (1.6 + random() * 3.4) * LOOKS[look].strokeScale,
    });
  }
  return { strokes };
}

export const HandDrawnCanvas: React.FC<{
  seed?: string;
  look?: HandDrawnLook | string;
  filmFps?: number;
  exposure?: number;
  filmFramesPerPose?: number;
}> = ({ seed = "thunderbolt", look = "paperInk", filmFps = 24, exposure = 2, filmFramesPerPose = 36 }) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const activeLook = (look && look in LOOKS ? (look as HandDrawnLook) : "paperInk") as HandDrawnLook;
  const palette = LOOKS[activeLook];

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    canvas.width = width;
    canvas.height = height;

    // Timebase da skill: filme a filmFps dentro da composição a fps.
    const filmFrame = Math.min(filmFramesPerPose * 64, Math.floor((frame * filmFps) / fps));
    // Exposição intencional (twos): as marcas mantêm-se pelo exposure inteiro.
    const heldFrame = filmFrame - (filmFrame % Math.max(1, exposure));
    const poseIndex = Math.floor(heldFrame / filmFramesPerPose);
    const poseProgress = (heldFrame % filmFramesPerPose) / filmFramesPerPose;
    const pose = buildPose(seed, activeLook, 1, poseIndex);

    // Papel.
    ctx.fillStyle = palette.paper;
    ctx.fillRect(0, 0, width, height);
    // Grão leve do papel (determinístico por frame composto).
    const grainRandom = mulberry32(hashString(`${seed}::grain::${Math.floor(frame / 2)}`));
    ctx.globalAlpha = 0.05;
    for (let g = 0; g < 140; g += 1) {
      ctx.fillStyle = palette.ink;
      ctx.fillRect(grainRandom() * width, grainRandom() * height, 1.4, 1.4);
    }
    ctx.globalAlpha = 1;

    // Draw-on: os traços da pose revelam-se ao longo da pose (progresso),
    // mas mantêm-se fixos durante cada exposure (heldFrame quantizado).
    const reveal = Math.min(1, poseProgress * 1.6);
    pose.strokes.forEach((stroke, strokeIndex) => {
      const strokeReveal = Math.min(1, Math.max(0, reveal * pose.strokes.length - strokeIndex));
      if (strokeReveal <= 0) return;
      const visible = Math.max(2, Math.floor(stroke.points.length * strokeReveal));
      ctx.strokeStyle = strokeIndex % 5 === 3 ? palette.accent : palette.ink;
      ctx.lineWidth = stroke.width * (width / 1920) * 1.4;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.beginPath();
      stroke.points.slice(0, visible).forEach(([px, py], pointIndex) => {
        const x = px * width;
        const y = py * height;
        if (pointIndex === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
    });
  }, [frame, fps, width, height, seed, activeLook, filmFps, exposure, filmFramesPerPose, palette]);

  return <canvas ref={canvasRef} style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }} />;
};
