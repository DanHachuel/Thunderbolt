import React from "react";
import { Composition } from "remotion";
import { LongFormVideo } from "./compositions/LongFormVideo";
import { ShortVideo } from "./compositions/ShortVideo";
import { InspirationalVideo } from "./compositions/InspirationalVideo";
import { Quiz } from "./compositions/Quiz";
import { SocialReel } from "./compositions/SocialReel";
import { Top10 } from "./compositions/Top10";
import { WouldYouRather } from "./compositions/WouldYouRather";
import { Cartoon3DShort, CARTOON_3D_FRAMES } from "./compositions/Cartoon3DShort";
import { LineArtAnimation } from "./compositions/LineArtAnimation";
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

// 0.9.75: calculateMetadata dos blueprints Remotion espelha EXACTAMENTE o
// layout dos componentes (mesmas fórmulas de Sequences) — intro/outro fixos de
// 90 frames incluídos — para que a duração total nunca corte o áudio nem
// acrescente frames mortos. A fonte de verdade é o componente, não uma
// estimativa de texto.
const inspirationalFrames = (props: { scenes: { durationInSeconds: number }[] }): number =>
  Math.max(30, props.scenes.reduce((acc, s) => acc + Math.max(30, Math.round((s.durationInSeconds ?? 3) * 30)), 0));

const quizFrames = (props: {
  questions: { durationInSeconds: number; revealDelaySeconds: number }[];
}): number =>
  Math.max(
    30,
    90 +
      props.questions.reduce(
        (acc, q) => acc + Math.round((q.durationInSeconds ?? 6) * 30) + Math.round((q.revealDelaySeconds ?? 3) * 30),
        0,
      ) +
      90,
  );

const socialReelFrames = (props: { scenes: { durationInSeconds: number; scene_type: string }[] }): number =>
  Math.max(
    30,
    props.scenes.reduce((acc, s) => {
      const extra = s.scene_type === "hook" ? 9 : s.scene_type === "cta" ? 15 : 0;
      return acc + Math.max(30, Math.round((s.durationInSeconds ?? 3) * 30)) + extra;
    }, 0),
  );

const top10Frames = (props: {
  intro: { durationInSeconds: number } | null;
  ranking: { durationInSeconds: number }[];
  outro: { durationInSeconds: number } | null;
}): number =>
  Math.max(
    30,
    Math.round(((props.intro?.durationInSeconds as number) || 5) * 30) +
      props.ranking.reduce((acc, item) => acc + Math.max(30, Math.round((item.durationInSeconds ?? 3) * 30)) + 12, 0) +
      Math.round(((props.outro?.durationInSeconds as number) || 4) * 30) +
      30,
  );

const wouldYouRatherFrames = (props: {
  questions: { durationInSeconds: number; thinkingDelaySeconds: number; revealDurationSeconds: number }[];
}): number =>
  Math.max(
    30,
    90 +
      props.questions.reduce(
        (acc, q) =>
          acc +
          Math.round((q.thinkingDelaySeconds ?? 3) * 30) +
          Math.round((q.durationInSeconds ?? 3) * 30) +
          Math.round((q.revealDurationSeconds ?? 3) * 30),
        0,
      ) +
      90,
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
    <Composition
      id="InspirationalVideo"
      component={InspirationalVideo}
      durationInFrames={1800}
      fps={30}
      width={1920}
      height={1080}
      defaultProps={{ title: "", scenes: [] }}
      calculateMetadata={async ({ props }) => ({
        durationInFrames: inspirationalFrames(props as { scenes: { durationInSeconds: number }[] }),
      })}
    />
    <Composition
      id="Quiz"
      component={Quiz}
      durationInFrames={1800}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={{
        topic: "",
        intro_voiceover: "",
        like_and_subscribe_voiceover: "",
        questions: [],
      }}
      calculateMetadata={async ({ props }) => ({
        durationInFrames: quizFrames(
          props as { questions: { durationInSeconds: number; revealDelaySeconds: number }[] },
        ),
      })}
    />
    <Composition
      id="SocialReel"
      component={SocialReel}
      durationInFrames={1800}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={{ title: "", scenes: [] }}
      calculateMetadata={async ({ props }) => ({
        durationInFrames: socialReelFrames(
          props as { scenes: { durationInSeconds: number; scene_type: string }[] },
        ),
      })}
    />
    <Composition
      id="Top10"
      component={Top10}
      durationInFrames={5400}
      fps={30}
      width={1920}
      height={1080}
      defaultProps={{ title: "", intro: null, ranking: [], outro: null }}
      calculateMetadata={async ({ props }) => ({
        durationInFrames: top10Frames(
          props as {
            intro: { durationInSeconds: number } | null;
            ranking: { durationInSeconds: number }[];
            outro: { durationInSeconds: number } | null;
          },
        ),
      })}
    />
    <Composition
      id="WouldYouRather"
      component={WouldYouRather}
      durationInFrames={2700}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={{
        or_text: "OR",
        questions: [],
        like_and_subscribe_voiceover_text: "",
      }}
      calculateMetadata={async ({ props }) => ({
        durationInFrames: wouldYouRatherFrames(
          props as {
            questions: { durationInSeconds: number; thinkingDelaySeconds: number; revealDurationSeconds: number }[];
          },
        ),
      })}
    />
    {/* 1.1.00 - skill «cartoon-3d-short» (seed/remotion_skills/cartoon-3d-skills):
        a timeline de `src/videos/cartoon-3d/story.ts` (vendorizada do template da
        skill) dita os shots, as câmaras e a física da ponde. A duração é o
        TOTAL da própria timeline (2025 f = 67,5 s), não uma estimativa. */}
    <Composition
      id="Cartoon3DShort"
      component={Cartoon3DShort}
      durationInFrames={CARTOON_3D_FRAMES}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={{ title: "", narration: "" }}
    />
    {/* 1.1.00 - skill «line-art-animation» (seed/remotion_skills/line-art-animation-skills):
        figuras desenhadas com a biblioteca vendida em
        src/compositions/lineart/lib/ (gait, motion, daynight) — nunca senos livres. */}
    <Composition
      id="LineArtAnimation"
      component={LineArtAnimation}
      durationInFrames={600}
      fps={30}
      width={960}
      height={540}
      defaultProps={{
        title: "",
        figures: [
          { kind: "walk", lane: 0.2, delay: 0, coat: "#b3412d", hat: true, scarf: true },
          { kind: "shuffle", lane: 0.55, delay: 1.5, coat: "#3f6f4a", hat: false, scarf: false },
          { kind: "run", lane: 0.95, delay: 3, coat: "#4a4f7a", hat: false, scarf: true },
        ],
        lanterns: [
          { x: 180, drop: 90 },
          { x: 760, drop: 120 },
        ],
        dayLengthSeconds: 20,
      }}
      calculateMetadata={async ({ props }) => ({
        durationInFrames: Math.max(
          30,
          Math.round(
            ((props as { dayLengthSeconds?: number }).dayLengthSeconds || 20) * 30,
          ),
        ),
      })}
    />
  </>
);
