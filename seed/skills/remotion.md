# Skill: Remotion — renderização programática de vídeos

Skill do agente Thunderbolt para a fonte **Remotion** ("Fonte do vídeo").
O Remotion não gera clipes: descreve-se o vídeo como árvore de componentes
React e o motor renderiza cada frame. O roteiro da LLM torna-se dados.

## Quando usar

- Fonte do vídeo = **Remotion** (a UI só habilita quando o ambiente está OK).
- Vídeos orientados a narração com texto em tela, fundos animados e dados.
- Estética "desenhado à mão" via fundos `hand_drawn_<look>` das cenas.

## Componentes do pipeline

| Peça | Papel |
|---|---|
| `packages/remotion/src/adapters/scriptToInputProps.mjs` | Roteiro Markdown → inputProps JSON (cenas, durações, visual) |
| `packages/remotion/src/compositions/` | `LongFormVideo` (1920×1080) e `ShortVideo` (1080×1920) |
| `packages/remotion/render.mjs` | Wrapper Node: bundle (cacheado), selectComposition, renderMedia |
| `hermes_ui/remotion_provider.py` | `get_remotion_status`, `prepare_input_props`, `run_remotion_render` |
| `docs/remotion.md` | Documentação completa (requisitos, paths, limitações) |

## Formato do roteiro reconhecido

```markdown
## GANCHO
NARRAÇÃO: A primeira frase do vídeo.
VISUAL: background: gradient; navio de carga aéreo
SFX: low_industrial_hum
ON-SCREEN TEXT: Index funds promised to democratize investing.

## CENA 1
NARRAÇÃO: …
VISUAL: fundo: hand_drawn_paperInk
DATA: barras: S&P 12; Bonds 8
DURAÇÃO: 35

## ENCERRAMENTO
NARRAÇÃO: …
```

Equivalentes EN (`## HOOK`, `## SCENE N`, `## OUTRO`, `NARRATION`, `VISUAL`,
`SFX`, `ON-SCREEN TEXT`, `DURATION`) são reconhecidos automaticamente.
Durações ausentes são estimadas por palavras (WPM) e reescaladas quando o
MP3 real da narração existe.

## Motor hand-drawn-canvas-animation (incluído)

Derivado da skill pública **hand-drawn-canvas-animation**
(https://github.com/alesha-pro/tools/tree/main/skills/hand-drawn-canvas-animation,
por alesha-pro) — filmes desenhados à mão em Canvas 2D. O Thunderbolt inclui
o motor `HandDrawnCanvas` nas composições com os invariantes da skill:

- **Whole-pose drawings**: cada pose é um conjunto inteiro de traços com
  strokes visíveis e exposição intencional; as chaves e breakdowns existem
  antes de qualquer textura.
- **Randomness com seed**: as marcas nascem UMA vez por desenho (id
  semântico estável) e mantêm-se fixas durante a exposição — sem "boil"
  uniforme por frame; cada frame reproduz após seek.
- **Timebase**: o filme corre a 24 fps dentro da composição (30 fps) —
  `drawFrame(min(NDRAW-1, floor(frame * 24 / fps)))`; com filme e composição
  ambos a 24 fps é simplesmente `drawFrame(frame)`.
- **Cinco looks/paletas**: `paperInk`, `risoPop`, `screenSea`, `pencilMinimal`,
  `doodlePastel` — seleccionáveis como `background: hand_drawn_<look>`.

Quality gates da skill (verificar em stills e no vídeo codificado, não só em
contact sheets): silhueta clara, pesos de linha controlados, contatos
plantados, exposição legível, sem tangências acidentais nem frames em branco.

## Comandos

```bash
# dependências (o instalador do Thunderbolt também o faz)
cd packages/remotion && npm install --no-audit --no-fund

# testes do wrapper e do adaptador (sem node_modules necessário)
node packages/remotion/tests/render.test.mjs
node packages/remotion/tests/scriptToInputProps.test.mjs

# e2e opt-in (requer dependências instaladas)
THUNDERBOLT_REMOTION_E2E=1 python -m pytest tests/test_remotion_e2e.py -v
```

## Regras de ouro

1. Nunca publicar por `npm publish` local — sempre via GitHub Actions.
2. Nunca usar `taskkill /T /F` — o `_stop_process` (psutil) é o único caminho.
3. Nunca descarregar Chromium/FFmpeg novos — reutilizar Playwright e imageio-ffmpeg.
4. O bundle cacheia em `storage/remotion-cache/bundle/`, nunca em `node_modules/`.
5. O guard exclui processos com `--thunderbolt-role=remotion-render`.
