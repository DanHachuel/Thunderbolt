import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import type { SceneData } from "../../types";

interface DataVisualizationProps {
  data?: SceneData;
  textScale?: number;
}

/**
 * Gráficos e contadores animados (barras, contadores) consumidos de
 * scene.data. Cada item entra com spring; o valor anima até ao alvo.
 */
export const DataVisualization: React.FC<DataVisualizationProps> = ({ data, textScale = 1 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (!data) {
    return null;
  }
  const items = Array.isArray(data.items) ? data.items.slice(0, 6) : [];
  const maxValue = Math.max(1, ...items.map((item) => Number(item.value) || 0));

  if (data.kind === "counter" || (!items.length && data.value !== undefined)) {
    const entrance = spring({ frame, fps, config: { damping: 20 } });
    const target = Number(data.value) || 0;
    const current = Math.round(target * entrance);
    return (
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 8,
        }}
      >
        <div
          style={{
            fontSize: Math.round(120 * textScale),
            fontWeight: 800,
            fontFamily: "Georgia, 'Times New Roman', serif",
            color: "#ffffff",
            textShadow: "0 4px 24px rgba(0,0,0,0.6)",
          }}
        >
          {current.toLocaleString()}
          {data.suffix || ""}
        </div>
        {data.title ? (
          <div
            style={{
              fontSize: Math.round(30 * textScale),
              color: "rgba(255,255,255,0.82)",
              fontFamily: "Georgia, 'Times New Roman', serif",
            }}
          >
            {data.title}
          </div>
        ) : null}
      </div>
    );
  }

  if (!items.length) {
    return null;
  }
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: Math.round(18 * textScale),
        padding: "0 12%",
      }}
    >
      {data.title ? (
        <div
          style={{
            fontSize: Math.round(34 * textScale),
            fontWeight: 700,
            color: "#ffffff",
            fontFamily: "Georgia, 'Times New Roman', serif",
            marginBottom: Math.round(10 * textScale),
          }}
        >
          {data.title}
        </div>
      ) : null}
      {items.map((item, index) => {
        const entrance = spring({
          frame: frame - index * 4,
          fps,
          config: { damping: 20 },
        });
        const width = ((Number(item.value) || 0) / maxValue) * 100 * entrance;
        return (
          <div
            key={`${item.label}-${index}`}
            style={{
              width: "100%",
              display: "flex",
              alignItems: "center",
              gap: Math.round(16 * textScale),
              opacity: entrance,
            }}
          >
            <div
              style={{
                width: "34%",
                textAlign: "right",
                fontSize: Math.round(24 * textScale),
                color: "rgba(255,255,255,0.86)",
                fontFamily: "Georgia, 'Times New Roman', serif",
              }}
            >
              {item.label}
            </div>
            <div style={{ flex: 1, backgroundColor: "rgba(255,255,255,0.12)", borderRadius: 10, padding: 4 }}>
              <div
                style={{
                  width: `${width}%`,
                  height: Math.round(26 * textScale),
                  borderRadius: 8,
                  background: "linear-gradient(90deg, #4d7cfe, #7db3ff)",
                }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
};
