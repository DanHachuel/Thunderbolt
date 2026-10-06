import React from "react";
import { Sequence, useVideoConfig } from "remotion";
import { NarrationAudio } from "./components/NarrationAudio";
import { TextOverlay } from "./components/TextOverlay";
import { AnimatedBackground } from "./components/AnimatedBackground";
import { SceneTransition } from "./components/SceneTransition";
import { DataVisualization } from "./components/DataVisualization";
import type { InputProps } from "../types";

/**
 * Composição horizontal 1920×1080 para vídeos longos.
 * A duração total vem do calculateMetadata (Root.tsx): soma das cenas.
 */
export const LongFormVideo: React.FC<InputProps> = ({ scenes, audioUrl, videoId }) => {
  const { fps } = useVideoConfig();
  let currentFrame = 0;
  return (
    <div style={{ position: "absolute", inset: 0, backgroundColor: "#0b0d12" }}>
      <NarrationAudio audioUrl={audioUrl} />
      {scenes.map((scene) => {
        const durationInFrames = Math.max(1, Math.round(scene.durationInSeconds * fps));
        const from = currentFrame;
        currentFrame += durationInFrames;
        return (
          <Sequence key={scene.id} from={from} durationInFrames={durationInFrames}>
            <SceneTransition type="fade" transitionFrames={8}>
              <AnimatedBackground variant={scene.visual?.background} seed={`${videoId}:${scene.id}`} />
              <DataVisualization data={scene.data} textScale={1} />
              <TextOverlay text={scene.visual?.text} textScale={1} position="lower_third" />
            </SceneTransition>
          </Sequence>
        );
      })}
    </div>
  );
};
