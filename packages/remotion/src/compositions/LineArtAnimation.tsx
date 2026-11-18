/**
 * LineArtAnimation — skill «line-art-animation» (1.1.00).
 *
 * A skill ensina que tudo é desenhado com uma caneta fina em papel, construído
 * ao vivo em SVG a partir de TypeScript, e que a animação NUNCA é um seno
 * livre: `gait()` resolve o andar/correr, `pendulum()`/`spring()` o que está
 * pendurado, e `palette()` dá o ciclo dia/noite. Os quatro ficheiros de `lib/`
 * foram vendidos do repo da skill (MIT) para `./lib/` e são usados aqui tal e
 * qual — a composição só traduz o ciclo de frames do Remotion para o tempo
 * contínuo que essa matemática espera.
 *
 * Contrato de props (espelha os outras composições do pacote):
 *   title             — nota curta desenhada no canto do cartão
 *   figures           — quem atravessa o cartão, em que pista e com que andar
 *   dayLengthSeconds  — duração de um ciclo completo dia→noite
 *   lanterns          — candeeiros pendurados (pêndulo)
 */
import React, { useMemo } from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { gait, type GaitKind } from "./lineart/lib/gait";
import { pendulum, clamp } from "./lineart/lib/motion";
import { palette, rgb, nightTint, type Palette, type RGB } from "./lineart/lib/daynight";

export interface LineArtFigure {
  kind: GaitKind;
  /** 0 = fundo, 1 = primeiro plano (escala e velocidade). */
  lane: number;
  /** segundos até entrar no cartão. */
  delay: number;
  /** cor da roupa (achata para a noite sozinha). */
  coat: string;
  hat: boolean;
  scarf: boolean;
}

export interface LineArtLantern {
  /** posição x no cartão (unidades do viewBox). */
  x: number;
  /** altura do fio. */
  drop: number;
}

export interface LineArtProps {
  title: string;
  figures: LineArtFigure[];
  lanterns: LineArtLantern[];
  dayLengthSeconds: number;
}

const W = 960;
const H = 540;
const GROUND = 430;
/** Espaço de figura da skill: pés em y = 120, a olhar para +x. */
const FIG_SCALE = 1.5;

const f = (n: number): string => n.toFixed(2);

/** Polilinha aberta com dois comprimentos de traço — um membro da skill. */
const limbPath = (a: readonly number[], b: readonly number[], c: readonly number[]): string =>
  `M${f(a[0])} ${f(a[1])} L${f(b[0])} ${f(b[1])} L${f(c[0])} ${f(c[1])}`;

const shoePath = (ankle: readonly number[], pitch: number): string => {
  const x = ankle[0];
  const y = ankle[1];
  return `M${f(x - 3)} ${f(y + 2)} L${f(x + 4.2 + pitch * 2)} ${f(y + 2)} L${f(x + 3.6 + pitch * 2)} ${f(y + 6)} L${f(x - 2)} ${f(y + 6)}Z`;
};

interface WalkerPose {
  hip: readonly number[];
  feet: Array<{ ankle: readonly number[]; knee: readonly number[]; pitch: number }>;
  front: 0 | 1;
  bob: number;
}

/**
 * Pose determinística no frame `frame`. A skill usa um ciclo acumulado
 * (`phase += dt/period`); aqui o fase é derivado do tempo para que o mesmo
 * frame dê sempre o mesmo desenho (obrigatório para render de vídeo).
 */
function walkerPose(kind: GaitKind, timeSeconds: number, elapsed: number): WalkerPose {
  const walk = gait({ kind });
  const phase = elapsed / walk.period;
  const pose = walk.pose(phase, 1);
  return {
    hip: pose.hip,
    feet: pose.feet.map((foot) => ({ ankle: foot.ankle, knee: foot.knee, pitch: foot.pitch })),
    front: pose.front,
    bob: pose.bob,
  };
}

/** Ângulo do candeeiro: pêndulo integrado do frame 0 até ao actual. */
function lanternAngle(frame: number, fps: number, seed: number): number {
  const p = pendulum(14, 1.8);
  const dt = 1 / fps;
  for (let i = 0; i <= frame; i += 1) {
    p.step(Math.sin((i * dt + seed) * 1.7) * 0.6, dt);
  }
  return p.a;
}

const Figure: React.FC<{
  figure: LineArtFigure;
  frame: number;
  fps: number;
  P: Palette;
}> = ({ figure, frame, fps, P }) => {
  const t = frame / fps;
  const local = t - figure.delay;
  const lane = clamp(figure.lane, 0, 1);
  const scale = 0.85 + lane * 1.15;
  const groundY = GROUND + lane * 90;

  const gaitKind = figure.kind;
  const g = gait({ kind: gaitKind });
  const elapsed = Math.max(0, local);
  // atravessa o cartão e volta a entrar (a skill fá-lo cycling x)
  const travelX = g.speed * FIG_SCALE * elapsed * (0.6 + lane * 0.6);
  const x = ((-80 + travelX) % (W + 200)) - 80;

  const pose = useMemo(() => walkerPose(gaitKind, t, elapsed), [gaitKind, t, elapsed]);

  const ink = rgb(P.ink);
  const coat = nightTint(figure.coat, P);
  /**
   * Espaço de figura da skill: pés em y = 120, a olhar para +x, ancada no
   * quadril x = 40. O grupo é colocado com `place()` da skill — translate para
   * os pés e scale — e TUDO o resto é desenhado nas coordenadas da figura, sem
   * inversões (inverter o y foi o que deixou as figuras de cabeça para baixo e
   * minúsculas no primeiro render).
   */
  const s = scale;
  const transform = `translate(${f(x - 40 * s)} ${f(groundY - 120 * s)}) scale(${f(s)})`;
  const hipY = pose.hip[1];
  const frontFoot = pose.feet[pose.front];

  return (
    <g transform={transform} stroke={ink} fill="none">
      {/* pernas — a da leading fica por cima do casaco */}
      {pose.feet.map((foot, i) => (
        <g key={i}>
          <path
            d={limbPath(pose.hip, foot.knee, foot.ankle)}
            strokeWidth={f(1.35 * (i === pose.front ? 1.15 : 0.9))}
            strokeLinecap="round"
          />
          <path d={shoePath(foot.ankle, foot.pitch)} fill={ink} stroke="none" />
        </g>
      ))}
      {/* casaco desenhado à volta do joelho da frente, para a baina abrir e
          fechar com o passo (regra da skill) */}
      <path
        d={`M${f(34)} ${f(hipY + 2)} Q${f(40)} ${f(hipY - 4)} ${f(46)} ${f(hipY + 2)} L${f(Math.max(frontFoot.knee[0] + 2.4, 46.4))} ${f(70 + pose.bob)} Q${f(Math.max(frontFoot.knee[0], 46.4))} ${f(82 + pose.bob * 0.5)} ${f(Math.max(frontFoot.knee[0], frontFoot.ankle[0] - 4))} ${f(92)} L${f(30.6)} ${f(93)} L${f(33.2)} ${f(70 + pose.bob)}Z`}
        fill={coat}
        strokeWidth={1.35}
      />
      {/* cabeça, chapéu e cachecol */}
      <ellipse cx={42.6} cy={f(31.6 + pose.bob)} rx={3.6} ry={4.6} fill={rgb(P.paper)} strokeWidth={1.35} />
      {figure.hat ? (
        <path
          d={`M${f(36.2)} ${f(28 + pose.bob)} L${f(49.2)} ${f(28 + pose.bob)} Q${f(47)} ${f(23.6 + pose.bob)} ${f(46.6)} ${f(20.6 + pose.bob)} Q${f(42.6)} ${f(17.6 + pose.bob)} ${f(38.8)} ${f(20.6 + pose.bob)} Q${f(38.4)} ${f(23.6 + pose.bob)} ${f(36.2)} ${f(28 + pose.bob)}Z`}
          fill={ink}
          strokeWidth={1.35}
        />
      ) : null}
      {figure.scarf ? (
        <path
          d={`M${f(38)} ${f(36.2 + pose.bob)} Q${f(42.6)} ${f(40 + pose.bob)} ${f(46.6)} ${f(36 + pose.bob)} L${f(47)} ${f(39.2 + pose.bob)} Q${f(42.6)} ${f(42.6 + pose.bob)} ${f(37.8)} ${f(39 + pose.bob)}Z`}
          fill={nightTint("#b3412d", P)}
          strokeWidth={1.1}
        />
      ) : null}
    </g>
  );
};

export const LineArtAnimation: React.FC<LineArtProps> = ({
  title,
  figures,
  lanterns,
  dayLengthSeconds,
}) => {
  const frame = useCurrentFrame();
  const fps = 30;
  const t = frame / fps;
  // τ ∈ [0,1): 0 meia-noite · 0.25 madrugada · 0.5 meio-dia · 0.75 crepúsculo.
  const tau = dayLengthSeconds > 0 ? (t / dayLengthSeconds) % 1 : 0.5;
  const P = useMemo(() => palette(tau), [tau]);
  const ink = rgb(P.ink);
  const paper = rgb(P.paper);
  const skyTop = rgb(P.top);
  const skyBottom = rgb(P.bottom);

  return (
    <AbsoluteFill style={{ backgroundColor: paper, color: ink }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height="100%"
        role="img"
        aria-label={title || "Line art animation"}
        style={{ display: "block" }}
      >
        <defs>
          <linearGradient id="tb-lineart-sky" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={skyTop} />
            <stop offset="100%" stopColor={skyBottom} />
          </linearGradient>
        </defs>

        {/* céu + horizonte */}
        <rect x={0} y={0} width={W} height={GROUND} fill="url(#tb-lineart-sky)" />
        <rect x={0} y={GROUND} width={W} height={H - GROUND} fill={paper} />

        {/* estrelas/lua quando a noite avança */}
        {P.night > 0.05
          ? Array.from({ length: 14 }, (_, i) => {
              const sx = ((i * 137.5) % W) as number;
              const sy = ((i * 61.3) % (GROUND - 120)) as number;
              return (
                <circle
                  key={i}
                  cx={f(sx)}
                  cy={f(sy)}
                  r={f(0.6 + (i % 3) * 0.4)}
                  fill={ink}
                  opacity={f(P.night * 0.8)}
                />
              );
            })
          : null}

        {/* candeeiros pendurados — pendulo integrado, nunca um seno livre */}
        {lanterns.map((lantern, i) => {
          const angle = lanternAngle(frame, fps, i * 1.3);
          const deg = (angle * 180) / Math.PI;
          const lampOn = P.lamp;
          return (
            <g key={i} transform={`translate(${f(lantern.x)} ${f(GROUND - 120)})`}>
              <path d={`M0 0 L0 ${f(lantern.drop)}`} stroke={ink} strokeWidth={1.35} fill="none" />
              <g transform={`rotate(${f(deg)} 0 ${f(lantern.drop)})`}>
                <path
                  d={`M${f(-5)} ${f(lantern.drop + 6)} L${f(5)} ${f(lantern.drop + 6)} L${f(3.4)} ${f(lantern.drop + 20)} L${f(-3.4)} ${f(lantern.drop + 20)}Z`}
                  fill={lampOn > 0.05 ? nightTint("#e8b24a", P) : "none"}
                  stroke={ink}
                  strokeWidth={1.35}
                />
                {lampOn > 0.05 ? (
                  <circle cx={0} cy={f(lantern.drop + 13)} r={f(14 + lampOn * 10)} fill="#e8b24a" opacity={f(lampOn * 0.22)} />
                ) : null}
              </g>
            </g>
          );
        })}

        {/* passeio */}
        <path d={`M0 ${f(GROUND)} L${W} ${f(GROUND)}`} stroke={ink} strokeWidth={1.35} fill="none" />

        {/* figuras, da pista de trás para a da frente */}
        {[...figures]
          .sort((a, b) => a.lane - b.lane)
          .map((figure, i) => (
            <Figure key={i} figure={figure} frame={frame} fps={fps} P={P} />
          ))}

        {title ? (
          <text x={24} y={H - 24} fontSize={15} fill={ink} opacity={0.75} fontFamily="Georgia, serif">
            {title}
          </text>
        ) : null}
      </svg>
    </AbsoluteFill>
  );
};

export type { RGB };