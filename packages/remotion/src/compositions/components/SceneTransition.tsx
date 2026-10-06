import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";

interface SceneTransitionProps {
  type?: "fade" | "slide" | "zoom";
  transitionFrames?: number;
  children: React.ReactNode;
}

/**
 * Transições entre cenas (fade, slide, zoom) aplicadas ao conteúdo de cada
 * Sequence. No Shorts as transições são mais rápidas (cortes mais ágeis).
 */
export const SceneTransition: React.FC<SceneTransitionProps> = ({
  type = "fade",
  transitionFrames = 8,
  children,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const tail = Math.max(1, Math.min(transitionFrames, Math.floor(durationInFrames / 2)));
  const intro = interpolate(frame, [0, tail], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const outro = interpolate(frame, [durationInFrames - tail, durationInFrames], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const progress = Math.min(intro, outro);
  const style: React.CSSProperties = { position: "absolute", inset: 0 };
  if (type === "slide") {
    const offset = (1 - progress) * 12;
    style.opacity = progress;
    style.transform = `translateY(${offset}%)`;
  } else if (type === "zoom") {
    const scale = interpolate(progress, [0, 1], [1.12, 1]);
    style.opacity = progress;
    style.transform = `scale(${scale})`;
  } else {
    style.opacity = progress;
  }
  return <div style={style}>{children}</div>;
};
