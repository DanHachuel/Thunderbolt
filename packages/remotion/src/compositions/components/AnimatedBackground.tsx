import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { HandDrawnCanvas } from "./HandDrawnCanvas";

interface AnimatedBackgroundProps {
  variant?: string;
  seed?: string;
}

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

/**
 * Fundos animados seleccionados por `variant` (scene.visual.background):
 * - hand_drawn_* → motor HandDrawnCanvas (skill hand-drawn-canvas-animation)
 * - gradient | particles | grid | solid → fundos programáticos determinísticos
 */
export const AnimatedBackground: React.FC<AnimatedBackgroundProps> = ({ variant, seed }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const value = String(variant || "").trim().toLowerCase();
  if (value.startsWith("hand_drawn")) {
    const look = value.replace("hand_drawn", "").replace(/^_*/, "") || "paperInk";
    return <HandDrawnCanvas seed={seed || "thunderbolt"} look={look} />;
  }
  if (value === "gradient" || value === "gradiente") {
    const hue = (frame / Math.max(1, durationInFrames)) * 60;
    return (
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: `linear-gradient(${135 + frame * 0.4}deg, hsl(${210 + hue} 42% 16%), hsl(${260 + hue} 38% 10%))`,
        }}
      />
    );
  }
  if (value === "particles" || value === "particulas" || value === "partículas") {
    const random = mulberry32(hashString(seed || "particles"));
    const dots = Array.from({ length: 26 }, () => ({
      x: random(),
      y: random(),
      radius: 2 + random() * 4,
      speed: 0.2 + random() * 0.9,
    }));
    return (
      <div style={{ position: "absolute", inset: 0, backgroundColor: "#0c1018", overflow: "hidden" }}>
        {dots.map((dot, index) => {
          const y = (dot.y - ((frame / fps) * dot.speed)) % 1;
          return (
            <div
              key={index}
              style={{
                position: "absolute",
                left: `${dot.x * 100}%`,
                top: `${((y + 1) % 1) * 100}%`,
                width: dot.radius * 2,
                height: dot.radius * 2,
                borderRadius: "50%",
                backgroundColor: `rgba(120,160,255,${0.25 + (index % 5) * 0.1})`,
              }}
            />
          );
        })}
      </div>
    );
  }
  if (value === "grid" || value === "grelha") {
    const offset = interpolate(frame, [0, Math.round(fps * 8)], [0, 80], {
      extrapolateRight: "clamp",
    });
    return (
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundColor: "#101418",
          backgroundImage:
            "linear-gradient(rgba(255,255,255,0.07) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.07) 1px, transparent 1px)",
          backgroundSize: "80px 80px",
          backgroundPosition: `${offset}px ${offset * 0.5}px`,
        }}
      />
    );
  }
  if (value === "solid" || value === "sólido" || value === "solido") {
    return <div style={{ position: "absolute", inset: 0, backgroundColor: "#14161c" }} />;
  }
  // Fundo predefinido: gradiente escuro determinístico.
  const drift = interpolate(frame, [0, durationInFrames], [0, 40], { extrapolateRight: "clamp" });
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        background: `linear-gradient(${140 + drift}deg, #10131a, #1b2130)`,
      }}
    />
  );
};
