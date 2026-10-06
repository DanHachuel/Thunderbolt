/**
 * Tipos partilhados entre o adaptador (scriptToInputProps) e as composições.
 * O inputProps é 100% serializável (sem funções, sem referências circulares,
 * sem undefined) para passar directamente a selectComposition()/renderMedia().
 */

export interface SceneVisual {
  type: string;
  text: string;
  background?: string;
}

export interface SceneData {
  kind?: "bar" | "counter";
  title?: string;
  items?: Array<{ label: string; value: number }>;
  value?: number;
  suffix?: string;
}

export interface Scene {
  id: string;
  type: "hook" | "scene" | "outro" | string;
  title?: string;
  durationInSeconds: number;
  narration: string;
  visual: SceneVisual;
  sfx?: string;
  data?: SceneData;
}

export interface ScriptMetadata {
  channel?: string;
  style?: string;
  music?: string;
  [key: string]: unknown;
}

export interface InputProps {
  videoId: string;
  title: string;
  language: string;
  fps: number;
  width: number;
  height: number;
  audioUrl: string;
  scenes: Scene[];
  metadata: ScriptMetadata;
}

export interface CompositionLayout {
  width: number;
  height: number;
  /** Escala tipográfica (Shorts usa textos maiores e legendas centralizadas). */
  textScale: number;
  textPosition: "lower_third" | "center";
  defaultTransition: "fade" | "slide" | "zoom";
  transitionFrames: number;
}
