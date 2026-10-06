import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

interface TextOverlayProps {
  text?: string;
  textScale?: number;
  position?: "lower_third" | "center";
}

/**
 * Texto em tela (títulos, citações, dados) com animação de entrada/saída.
 * No Shorts (textPosition="center") o texto é maior e centralizado.
 */
export const TextOverlay: React.FC<TextOverlayProps> = ({
  text,
  textScale = 1,
  position = "lower_third",
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const value = String(text || "").trim();
  if (!value) {
    return null;
  }
  const entrance = spring({ frame, fps, config: { damping: 18, mass: 0.9 } });
  const exit = interpolate(
    frame,
    [Math.max(0, durationInFrames - 10), Math.max(1, durationInFrames - 2)],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  const opacity = entrance * exit;
  const translateY = (1 - entrance) * 28 * textScale;
  const fontSize = Math.round(46 * textScale);
  const alignItems = position === "center" ? "center" : "flex-end";
  const justifyContent = position === "center" ? "center" : "flex-start";
  const padding = position === "center" ? "12%" : "6% 8%";
  return (
    <AbsoluteFill alignItems={alignItems} justifyContent={justifyContent} padding={padding}>
      <div
        style={{
          opacity,
          transform: `translateY(${translateY}px)`,
          fontSize,
          fontWeight: 700,
          fontFamily: "Georgia, 'Times New Roman', serif",
          color: "#ffffff",
          textAlign: "center",
          textShadow: "0 3px 14px rgba(0,0,0,0.65)",
          lineHeight: 1.25,
          maxWidth: "84%",
          backgroundColor: "rgba(0,0,0,0.28)",
          borderRadius: 18,
          padding: `${Math.round(18 * textScale)}px ${Math.round(30 * textScale)}px`,
          letterSpacing: "0.2px",
        }}
      >
        {value}
      </div>
    </AbsoluteFill>
  );
};

// AbsoluteFill local com props de layout (remotion só exporta o componente puro).
const AbsoluteFill: React.FC<{
  children: React.ReactNode;
  alignItems: string;
  justifyContent: string;
  padding: string;
}> = ({ children, alignItems, justifyContent, padding }) => (
  <div
    style={{
      position: "absolute",
      inset: 0,
      display: "flex",
      alignItems,
      justifyContent,
      padding,
      boxSizing: "border-box",
    }}
  >
    {children}
  </div>
);
