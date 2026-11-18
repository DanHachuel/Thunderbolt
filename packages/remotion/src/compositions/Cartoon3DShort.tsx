/**
 * Cartoon3DShort — skill «cartoon-3d-short» (1.1.00).
 *
 * A skill descreve um curto vertical de 55-70 s no estilo «personagens 2D em
 * mundo 3D colorido»: cartões bean-head com contorno a tinta, vila pintada,
 * céu saturado, depth-of-field, câmaras deslizantes, e a PRÓPRIA timeline em
 * `templates/bridge/story.ts` (shots, câmaras, física da ponde, marcha dos 74
 * soldados, crossfades e flash do gancho).
 *
 * Esse `story.ts` foi vendorizado do template da skill para
 * `../videos/cartoon-3d/story.ts` e éaqui usado TAL E QUAL — é a matemática
 * que manda no desenho, não uma reimplementação.
 *
 * NOTA DE ESCOPO (1.1.00): o template original renderiza essa timeline com
 * three.js + @react-three/fiber + @react-three/postprocessing. Essas
 * dependências NÃO foram adicionadas a `packages/remotion/package.json` porque
 * o instalador corre `npm install` simples (`scripts/install.mjs`, sem
 * `--legacy-peer-deps`) e esse conjunto não resolve contra o React 18 do
 * pacote (R3F 9 exige React 19) — a instalação abortaria para todos os
 * utilizadores. Esta composição desenha portanto a MESMA timeline em camadas
 * 2D (SVG/CSS), que renderiza sem nenhuma dependência nova. O pipeline
 * three.js completo fica documentado na skill, em `templates/bridge/`, pronto
 * para quem quiser ligá-lo num projecto com React 19.
 */
import React, { useMemo } from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import {
  COUNT,
  FPS,
  FLASH_AT,
  SHOTS,
  TOTAL,
  XFADE,
  bridgeState,
  camAt,
  dofAt,
  front,
  layersAt,
  marchPhase,
  shotAt,
} from "../videos/cartoon-3d/story";

export interface Cartoon3DProps {
  title: string;
  narration?: string;
}

/** Paleta medida no estudo de referência (references/reports/*.md). */
const LOOK = {
  daySkyTop: "#5e93d9",
  daySkyHorizon: "#9dc3ef",
  goldenSkyTop: "#3f4c7a",
  goldenSkyHorizon: "#ffd08a",
  paper: "#f3eee4",
  ink: "#201628",
  water: "#4d7f9a",
  bank: "#7f9a54",
} as const;

const W = 1080;
const H = 1920;

const f = (n: number): string => n.toFixed(2);

/** Geometria do tabuleiro — a MESMA curva usada para desenhar a ponte, para
 *  que os soldados marcharem OS PÉS no convés e não a flutuar sobre a água. */
const DECK_LEFT = W / 2 - 27 * 15;
const DECK_RIGHT = W / 2 + 27 * 15;
const DECK_BASE_Y = 660;
const DECK_RISE = 190;
const deckYAt = (x: number): number => {
  const t = (x - DECK_LEFT) / (DECK_RIGHT - DECK_LEFT);
  const u = Math.max(0, Math.min(1, t));
  // quadrática com os pontos de controlo do desenho da ponte
  return (1 - u) ** 2 * DECK_BASE_Y + 2 * (1 - u) * u * (DECK_BASE_Y - DECK_RISE) + u ** 2 * DECK_BASE_Y;
};

/** Marcha: 74 soldados em 4 fileiras, fase e z dados pela física da timeline. */
const Marchers: React.FC<{ frame: number; collapsed: boolean }> = ({ frame, collapsed }) => {
  const shot = shotAt(frame);
  const tau = shot.tau(frame / FPS);
  const phase = marchPhase(tau);
  const zFront = front(tau);
  return (
    <g>
      {Array.from({ length: COUNT }, (_, i) => {
        const file = i % 4;
        const row = Math.floor(i / 4);
        const z = zFront - row * 1.3;
        if (z < -27 || z > 26) return null;
        const x = W / 2 + (file - 1.5) * 46 + (row % 2) * 8;
        const depth = (26 - z) / 53;
        const scale = 0.35 + depth * 0.75;
        const bob = collapsed ? 0 : Math.abs(Math.sin((phase + file * 0.25) * Math.PI * 2)) * 8 * scale;
        // pés assentes no convés da ponte nesse x
        const y = deckYAt(x) - bob;
        if (collapsed && z > -6) return null;
        return (
          <g key={i} transform={`translate(${f(x)} ${f(y)}) scale(${f(scale)})`}>
            <ellipse cx={0} cy={-14} rx={7} ry={8} fill={LOOK.ink} />
            <rect x={-6} y={-6} width={12} height={22} rx={4} fill="#3c4a63" stroke={LOOK.ink} strokeWidth={1.2} />
            <rect x={-2.4} y={-64} width={1.6} height={58} fill={LOOK.ink} />
          </g>
        );
      })}
    </g>
  );
};

/** Ponte: tabuleiro com vão em arco e torres; `deckY` da timeline dá a queda. */
const Bridge: React.FC<{ frame: number }> = ({ frame }) => {
  const shot = shotAt(frame);
  const state = bridgeState(shot.id, frame);
  return (
    <g>
      {[-27, 27].map((z) => (
        <rect
          key={z}
          x={W / 2 + z * 15 - 26}
          y={640}
          width={52}
          height={520}
          rx={6}
          fill="#8a6b4a"
          stroke={LOOK.ink}
          strokeWidth={3}
        />
      ))}
      <path
        d={`M${f(W / 2 - 27 * 15)} ${f(660 - state.drop * 120)} Q${f(W / 2)} ${f(660 - 190 - state.drop * 260)} ${f(W / 2 + 27 * 15)} ${f(660 - state.drop * 120)}`}
        stroke={LOOK.ink}
        strokeWidth={10}
        fill="none"
        strokeLinecap="round"
      />
      <path
        d={`M${f(W / 2 - 27 * 15)} ${f(672 - state.drop * 120)} Q${f(W / 2)} ${f(672 - 178 - state.drop * 260)} ${f(W / 2 + 27 * 15)} ${f(672 - state.drop * 120)}`}
        stroke="#a5834f"
        strokeWidth={16}
        fill="none"
        opacity={0.9}
      />
    </g>
  );
};

const ShotLayer: React.FC<{ frame: number; id: number; alpha: number }> = ({ frame, id, alpha }) => {
  const shot = SHOTS[id - 1];
  if (!shot) return null;
  const golden = shot.light === "golden";
  const cam = camAt(id, frame);
  const dof = dofAt(frame);
  const blur = dof ? Math.min(14, Math.max(0, dof.cInf - 8)) : 0;
  // enquadramento: posição da câmara dá paralaxe; fov dá zoom
  const k = Math.max(0.55, Math.min(1.6, 40 / Math.max(12, cam.fov)));
  const px = (cam.pos[0] - cam.look[0]) * 6;
  const py = (cam.pos[2] - cam.look[2]) * 2.2;

  return (
    <g opacity={f(alpha)}>
      <rect x={0} y={0} width={W} height={H} fill={golden ? LOOK.goldenSkyTop : LOOK.daySkyTop} />
      <rect x={0} y={430} width={W} height={260} fill={golden ? LOOK.goldenSkyHorizon : LOOK.daySkyHorizon} />
      {shot.towns ? (
        <g opacity={0.9} filter={blur > 0 ? `blur(${f(blur * 0.6)}px)` : undefined}>
          {Array.from({ length: 9 }, (_, i) => {
            const bx = i * 130 - 20;
            const bh = 150 + ((i * 53) % 110);
            return (
              <g key={i}>
                <rect x={bx} y={690 - bh} width={104} height={bh} fill="#b9a583" stroke={LOOK.ink} strokeWidth={2.4} />
                <path d={`M${f(bx - 8)} ${f(690 - bh)} L${f(bx + 52)} ${f(690 - bh - 46)} L${f(bx + 116)} ${f(690 - bh)}Z`} fill="#8c5a4a" stroke={LOOK.ink} strokeWidth={2.4} />
                <rect x={bx + 34} y={690 - bh + 60} width={30} height={38} fill="#f0d9a8" stroke={LOOK.ink} strokeWidth={1.6} />
              </g>
            );
          })}
        </g>
      ) : null}
      <rect x={0} y={690} width={W} height={H - 690} fill={LOOK.water} />
      <rect x={0} y={1140} width={W} height={H - 1140} fill={LOOK.bank} />
      <g transform={`translate(${f(px)} ${f(py)}) scale(${f(k)})`} style={{ transformOrigin: "center" }}>
        {shot.crowd === "march" ? <Marchers frame={frame} collapsed={false} /> : null}
        {shot.crowd === "fall" ? <Marchers frame={frame} collapsed /> : null}
        <Bridge frame={frame} />
      </g>
    </g>
  );
};

export const Cartoon3DShort: React.FC<Cartoon3DProps> = ({ title }) => {
  const frame = useCurrentFrame();
  const layers = useMemo(() => layersAt(frame), [frame]);
  const flash = useMemo(() => {
    // flash branco de 4 frames no gancho (FLASH_AT)
    const d = frame - FLASH_AT;
    return d >= 0 && d < 4 ? 1 - d / 4 : 0;
  }, [frame]);

  return (
    <AbsoluteFill style={{ backgroundColor: LOOK.paper, margin: 0, padding: 0 }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height="100%" style={{ display: "block" }}>
        {layers.map((layer, i) => (
          <ShotLayer key={`${layer.id}-${i}`} frame={frame} id={layer.id} alpha={layer.alpha} />
        ))}
        {/* contorno a tinta por cima de tudo (a assinatura do estilo) */}
        <rect x={0} y={0} width={W} height={H} fill="none" stroke={LOOK.ink} strokeWidth={6} opacity={0.35} />
        {flash > 0 ? <rect x={0} y={0} width={W} height={H} fill="#ffffff" opacity={f(flash)} /> : null}
        {title ? (
          <text x={W / 2} y={H - 60} fontSize={34} textAnchor="middle" fill={LOOK.paper} opacity={0.9} fontFamily="system-ui, sans-serif">
            {title}
          </text>
        ) : null}
      </svg>
    </AbsoluteFill>
  );
};

export const CARTOON_3D_FRAMES = TOTAL;
export const CARTOON_3D_XFADES = XFADE;