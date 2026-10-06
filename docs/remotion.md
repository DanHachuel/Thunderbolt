# Remotion — renderização local de vídeos no Thunderbolt

O **Remotion** é um provedor "Fonte do vídeo" do Thunderbolt: recebe o roteiro
Markdown gerado pela LLM, converte-o em `inputProps` (JSON) e renderiza o
vídeo frame a frame com React, localmente, via subprocesso Node.js invocado
pelo `pipeline_worker.py` — o mesmo padrão do MoneyPrinterTurbo/MPT.

Não é um gerador de clipes: o roteiro torna-se uma especificação de
composição (cenas, textos, fundos, dados animados) e o Remotion executa-a.

## Requisitos de sistema (verificados em runtime)

| Requisito | Origem | Verificação |
|---|---|---|
| Node.js 18+ | https://nodejs.org | `node --version` |
| FFmpeg | `imageio-ffmpeg` já instalado pelo Thunderbolt | `imageio_ffmpeg.get_ffmpeg_exe()` |
| Chromium | Playwright já instalado pelo Thunderbolt | `playwright.chromium.executable_path` |
| `@remotion/renderer` | `npm install` em `packages/remotion/` | `import('@remotion/renderer')` |

Nada é descarregado de novo — o Chromium e o FFmpeg existentes são reutilizados.
O estado completo aparece na UI em **Configurações > Configuração API > Remotion**
e a lista de razões mostra exactamente o que falta e como resolver.

## Instalação

O instalador do Thunderbolt corre `npm install` em `packages/remotion/`
automaticamente (salta com `--skip-remotion` ou `--skip-python-deps`):

```
npx.cmd --yes --prefer-online @danhachuel/thunderbolt@<versão> install
```

Manualmente, na raiz do pacote instalado:

```
cd packages/remotion
npm install --no-audit --no-fund
```

## Como funciona

```
pipeline_worker (Python)
  ├─ roteiro Markdown (LLM) ──► prepare_input_props()
  │                              └─ node render.mjs --prepare-only
  │                                 └─ scriptToInputProps (adaptador)
  │                                     └─ inputProps JSON (cenas+durações)
  ├─ narração TTS (edge-tts/Azure/ElevenLabs) ──► MP3 em storage/audio
  └─ run_remotion_render()
        └─ node render.mjs --input-props … --thunderbolt-role=remotion-render
              ├─ bundle() → storage/remotion-cache/bundle (cache por hash)
              ├─ selectComposition() → LongFormVideo | ShortVideo
              └─ renderMedia() → MP4 em storage/videos/<task>-remotion.mp4
                    stdout: OUTPUT=<path>   stderr: PROGRESS=<percent>
```

- **Adaptador `scriptToInputProps`** (packages/remotion/src/adapters/): cada
  secção do roteiro (`## GANCHO`, `## CENA N`, `## ENCERRAMENTO`, ou os
  equivalentes EN) vira uma cena; `NARRAÇÃO`, `VISUAL`, `SFX`,
  `ON-SCREEN TEXT`, `DATA` e `DURAÇÃO` mapeiam para as propriedades da cena.
  As durações são estimadas por palavras (WPM) e **recalculadas
  proporcionalmente** quando o MP3 real da narração existe
  (`totalAudioSeconds`). O resultado é 100% serializável.
- **Composições** (`src/compositions/`): `LongFormVideo` (1920×1080) e
  `ShortVideo` (1080×1920, textos maiores e cortes mais rápidos). A duração
  total vem de `calculateMetadata` — soma das cenas — e o áudio da narração
  toca sincronizado na timeline.
- **Fundos por cena** (`scene.visual.background`): `gradient`, `particles`,
  `grid`, `solid` e a família **`hand_drawn_<look>`** do motor
  HandDrawnCanvas (ver skill abaixo).

## Configuração de paths (FFmpeg, Chromium)

O provider Python resolve os paths (imageio-ffmpeg e Playwright) e passa-os
ao wrapper (`--chromium` → `browserExecutable`; `--ffmpeg` → validação e env
`FFMPEG_BINARY`). O `@remotion/renderer` v4 traz o próprio compositor
pré-compilado; nada precisa de ser configurado manualmente.

## Single-instance guard

O render é marcado no cmdline com `--thunderbolt-role=remotion-render`.
O guard (`scripts/kill_tree.py`) **exclui** processos com esse marcador (e as
respectivas árvores de Chromium/FFmpeg) — um render não é morto quando uma
nova instância do launcher arranca. Toda a comparação de cmdline normaliza
`\` → `/` antes de comparar (lição do incidente 0.9.50).

## Timeout, progresso e cancelamento

- Timeout de 15 minutos (vídeos longos); ao expirar, `_stop_process` (psutil,
  cascata) termina o subprocesso e a falha é atribuída ao Remotion.
- Progresso real do render mapeado para a banda da etapa vídeo (52–79%) com
  heartbeat de 5s (`video_helper_status` mostra a última linha do wrapper).
- Cancelamento pelo utilizador detectado via estado da tarefa (bloqueada/
  cancelada) — mesmo padrão do MPT.

## Limitações

- Render local é limitado pela CPU (concorrência = núcleos − 1); um vídeo de
  10 min pode demorar vários minutos a renderizar.
- O bundle é cacheado em `storage/remotion-cache/bundle/` (nunca em
  `node_modules/` nem em `storage/state/`) e invalida quando o hash do
  `packages/remotion/package.json` muda.
- O e2e (`tests/test_remotion_e2e.py`) é opt-in (`THUNDERBOLT_REMOTION_E2E=1`).
- Windows é o ambiente prioritário; Linux/macOS são secundários.

## Migração futura para @remotion/lambda

A arquitectura isola a nuvem no wrapper `render.mjs`: para migrar, troca-se
`bundle()` + `renderMedia()` por `getRenderProgress()`/`renderMediaOnLambda()`
sem alterar o adaptador, as composições ou o provider Python (spec 4.4).

## Skill: hand-drawn-canvas-animation (motor HandDrawnCanvas)

A integração inclui a skill **hand-drawn-canvas-animation**
(https://github.com/alesha-pro/tools/tree/main/skills/hand-drawn-canvas-animation)
como motor de fundo desenhado à mão dentro das composições
(`src/compositions/components/HandDrawnCanvas.tsx`):

- **Cinco looks** com paletas próprias (variantes `hand_drawn_*` do
  `scene.visual.background`): `paperInk` (tinta), `risoPop` (risograph),
  `screenSea` (serigrafia), `pencilMinimal` (grafite), `doodlePastel`
  (doodle sobre papel pastel).
- **Invariantes da skill aplicados**: aleatoriedade com seed (mulberry32) —
  as marcas nascem uma vez por pose e mantêm-se estáveis durante a exposição
  (nada de "boil" uniforme); whole-pose drawings (pose = conjunto inteiro de
  traços); exposição intencional (twos — 2 frames de filme por desenho).
- **Timebase da skill para Remotion**: o filme corre a 24 fps dentro da
  composição a 30 fps — `filmFrame = min(NDRAW-1, floor(frame * 24 / fps))`,
  a fórmula documentada pela skill para composições Remotion.

A skill completa (assets, exemplos, referências de estilo e paletas) vive no
repositório upstream; o resumo operacional está em `seed/skills/remotion.md`.
