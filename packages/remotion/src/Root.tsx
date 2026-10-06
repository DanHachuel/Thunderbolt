import React from "react";
import { Composition } from "remotion";
import { LongFormVideo } from "./compositions/LongFormVideo";
import { ShortVideo } from "./compositions/ShortVideo";
import type { InputProps } from "./types";

const DEFAULT_PROPS: InputProps = {
  videoId: "default",
  title: "",
  language: "en",
  fps: 30,
  width: 1920,
  height: 1080,
  audioUrl: "",
  scenes: [],
  metadata: {},
};

const durationFromScenes = (props: InputProps, compositionFps: number): number =>
  props.scenes.reduce(
    (acc, scene) => acc + Math.max(1, Math.round(scene.durationInSeconds * compositionFps)),
    Math.round(compositionFps),
  );

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="LongFormVideo"
      component={LongFormVideo}
      durationInFrames={1800}
      fps={30}
      width={1920}
      height={1080}
      defaultProps={DEFAULT_PROPS}
      calculateMetadata={async ({ props }) => ({
        durationInFrames: durationFromScenes(props as InputProps, 30),
      })}
    />
    <Composition
      id="ShortVideo"
      component={ShortVideo}
      durationInFrames={1800}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={DEFAULT_PROPS}
      calculateMetadata={async ({ props }) => ({
        durationInFrames: durationFromScenes(props as InputProps, 30),
      })}
    />
  </>
);
