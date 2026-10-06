/**
 * scriptToInputProps — converte o roteiro Markdown da LLM no JSON inputProps
 * consumido pelas composições Remotion (Tarefa 2 da especificação).
 *
 * Nota de implementação: a especificação pede scriptToInputProps.ts; a
 * conversão corre FORA do bundle (o wrapper render.mjs invoca-a antes de
 * bundle()/renderMedia()), e um subprocesso Node não executa TypeScript sem
 * passo de build. O módulo vive portanto em .mjs (ESM puro, sem dependências)
 * e os tipos partilhados estão em src/types.ts para as composições TSX.
 *
 * Regras de conversão (spec 2.2):
 * - Cada secção (## GANCHO, ## CENA N, ## Encerramento / HOOK, SCENE N,
 *   OUTRO) vira um objecto em scenes.
 * - Duração = DURAÇÃO explícita, ou estimada por palavras (wpm); quando o
 *   Python passa totalAudioSeconds (duração real do áudio TTS), as durações
 *   estimadas são reescaladas proporcionalmente para o total real.
 * - VISUAL, NARRAÇÃO/NARRATION, SFX e ON-SCREEN TEXT mapeiam para as
 *   propriedades da cena; o id do frontmatter e os metadados são preservados.
 * - O resultado é 100% serializável (round-trip JSON em render.mjs).
 */

const DEFAULT_FPS = 30;
const DEFAULT_WPM = 150;
const MIN_SCENE_SECONDS = 2;

const HOOK_HEADINGS = ["gancho", "hook", "abertura", "introdução", "introducao", "introduction", "opening"];
const OUTRO_HEADINGS = [
  "encerramento",
  "outro",
  "conclusão",
  "conclusao",
  "conclusion",
  "fecho",
  "closing",
  "final",
];

function normalizeHeading(raw) {
  return String(raw || "")
    .replace(/[#*_`]/g, "")
    .trim()
    .toLowerCase();
}

function classifyHeading(heading) {
  const normalized = normalizeHeading(heading);
  if (HOOK_HEADINGS.includes(normalized)) return { type: "hook", id: "hook" };
  const sceneMatch = normalized.match(/^(?:cena|scene|parte|part|segmento|segment)\s*#?\s*(\d+)?/);
  if (sceneMatch) {
    const number = sceneMatch[1] ? String(Number(sceneMatch[1])) : null;
    return { type: "scene", id: number ? `scene-${number}` : null, number };
  }
  if (OUTRO_HEADINGS.includes(normalized)) return { type: "outro", id: "outro" };
  return null;
}

function parseLabelled(line) {
  const match = String(line).match(/^\s*(?:[-*]\s*)?\*{0,2}([^*::]{2,40}?)\*{0,2}\s*[:：]\s*(.*)$/);
  if (!match) return null;
  return { label: normalizeHeading(match[1]), value: String(match[2] || "").trim() };
}

function labelKind(label) {
  if (["narração", "narracao", "narration", "locução", "locucao", "voz off", "voice over", "voiceover", "narrador"].includes(label)) {
    return "narration";
  }
  if (["visual", "imagem", "image", "b-roll", "broll", "indicação visual", "indicacao visual", "visual indication"].includes(label)) {
    return "visual";
  }
  if (["sfx", "som", "sound", "efeito sonoro", "efeito", "sound effect"].includes(label)) return "sfx";
  if (
    ["on-screen text", "onscreen text", "texto na tela", "texto em tela", "texto no ecrã", "texto em ecrã", "text on screen", "título", "titulo", "título em tela", "titulo em tela"].includes(label)
  ) {
    return "text";
  }
  if (["duração", "duracao", "duration", "duração (s)", "segundos"].includes(label)) return "duration";
  if (["data", "dados", "visualization", "visualização", "visualizacao", "gráfico", "grafico"].includes(label)) return "data";
  return null;
}

function parseBackground(value) {
  const match = String(value).match(/(?:background|fundo)\s*[:：]\s*([^\n]+)/i);
  if (!match) return "";
  return match[1].split(/[;,]/)[0].trim();
}

function words(text) {
  return String(text || "")
    .split(/\s+/)
    .filter(Boolean).length;
}

function estimateSeconds(narration, wpm) {
  const count = words(narration);
  if (!count) return MIN_SCENE_SECONDS + 1;
  return Math.max(MIN_SCENE_SECONDS, (count / Math.max(60, wpm)) * 60);
}

function parseDurationValue(value) {
  const match = String(value).match(/(\d+(?:[.,]\d+)?)\s*(s|seg|segundos?|seconds?)?\b/i);
  if (!match) return null;
  const seconds = Number(match[1].replace(",", "."));
  return Number.isFinite(seconds) && seconds > 0 ? seconds : null;
}

function parseDataValue(value) {
  // Formato aceite: "barras: Etiqueta 12; Outra 8" ou "contador: 1250 seguidores"
  try {
    const text = String(value || "").trim();
    const counter = text.match(/^(?:contador|counter)\s*[:：]\s*(\d+(?:[.,]\d+)?)\s*(.*)$/i);
    if (counter) {
      return { kind: "counter", value: Number(counter[1].replace(",", ".")), title: counter[2] || undefined };
    }
    const items = [];
    const itemPattern = /([^,;]+?)\s+(\d+(?:[.,]\d+)?)/g;
    let match = itemPattern.exec(text);
    let guard = 0;
    while (match && guard < 12) {
      items.push({ label: match[1].trim(), value: Number(match[2].replace(",", ".")) });
      match = itemPattern.exec(text);
      guard += 1;
    }
    if (items.length) {
      return { kind: "bar", items };
    }
  } catch {
    return undefined;
  }
  return undefined;
}

function splitScenes(markdown) {
  const lines = String(markdown || "").split(/\r?\n/);
  const sections = [];
  let current = null;
  for (const line of lines) {
    const headingMatch = line.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      const classified = classifyHeading(headingMatch[2]);
      if (classified || (headingMatch[1].length <= 2 && normalizeHeading(headingMatch[2]))) {
        if (classified) {
          current = {
            heading: String(headingMatch[2]).trim(),
            type: classified.type,
            id: classified.id,
            number: classified.number,
            body: [],
          };
          sections.push(current);
          continue;
        }
      }
    }
    if (current) {
      current.body.push(line);
    } else if (sections.length === 0) {
      // Preamble antes da primeira secção reconhecida (frontmatter/título).
      sections.push({ heading: "", type: "preamble", id: null, body: [line] });
    } else {
      sections[0].body.push(line);
    }
  }
  return sections;
}

function extractFrontmatter(markdown) {
  const meta = {};
  const idMatch = String(markdown).match(/^\s*(?:---[\s\S]*?\n---\s*\n?)?[\s\S]*?\bid\s*[:：]\s*"?([\w-]+)"?/m);
  if (idMatch) meta.videoId = idMatch[1];
  const titleMatch = String(markdown).match(/^\s*#\s+(.+)$/m);
  if (titleMatch) meta.title = titleMatch[1].replace(/[#*`]/g, "").trim();
  return meta;
}

export function scriptToInputProps(scriptMarkdown, config = {}) {
  const markdown = String(scriptMarkdown || "");
  const frontmatter = extractFrontmatter(markdown);
  const fps = Number(config.fps) > 0 ? Number(config.fps) : DEFAULT_FPS;
  const vertical = Number(config.height) > Number(config.width);
  const width = Number(config.width) > 0 ? Number(config.width) : vertical ? 1080 : 1920;
  const height = Number(config.height) > 0 ? Number(config.height) : vertical ? 1920 : 1080;
  const wpm = Number(config.wpm) > 0 ? Number(config.wpm) : DEFAULT_WPM;

  const sections = splitScenes(markdown).filter((section) => section.type !== "preamble");
  const useFallback = sections.length === 0;
  const effective = useFallback
    ? [{ heading: "", type: "hook", id: "hook", body: markdown.split(/\r?\n/) }]
    : sections;

  const scenes = effective.map((section, index) => {
    const narrationParts = [];
    let visualText = "";
    let background = "";
    let sfx = "";
    let onScreenText = "";
    let explicitDuration = null;
    let data;

    for (const line of section.body) {
      const labelled = parseLabelled(line);
      if (labelled) {
        const kind = labelKind(labelled.label);
        if (kind === "narration") {
          narrationParts.push(labelled.value);
          continue;
        }
        if (kind === "visual") {
          background = parseBackground(labelled.value) || labelled.value.split(/[.;]/)[0].trim();
          visualText = labelled.value;
          continue;
        }
        if (kind === "sfx") {
          sfx = labelled.value;
          continue;
        }
        if (kind === "text") {
          onScreenText = labelled.value;
          continue;
        }
        if (kind === "duration") {
          explicitDuration = parseDurationValue(labelled.value);
          continue;
        }
        if (kind === "data") {
          data = parseDataValue(labelled.value);
          continue;
        }
      }
      const plain = String(line).trim();
      if (plain && !plain.match(/^(#{1,6})\s/) && !plain.match(/^(-{3,}|\*{3,})$/)) {
        narrationParts.push(plain);
      }
    }

    const narration = narrationParts.join(" ").replace(/\s+/g, " ").trim();
    const estimated = explicitDuration ?? estimateSeconds(narration, wpm);
    const fallbackId = section.id || `scene-${index + 1}`;
    const visual = {
      type: "text_overlay",
      text: onScreenText || narration.split(/[.!?]/)[0] || "",
      background: background || visualText.split(/[.:;]/)[0].trim().toLowerCase() || "",
    };
    const scene = {
      id: fallbackId,
      type: section.type || "scene",
      durationInSeconds: Number(estimated.toFixed(3)),
      narration,
      visual,
    };
    if (section.heading) scene.title = section.heading;
    if (sfx) scene.sfx = sfx;
    if (data) scene.data = data;
    return scene;
  });

  // Recalcular quando o áudio real está disponível: reescala as durações
  // estimadas proporcionalmente para a duração total real do MP3 (spec 2.2).
  const totalAudioSeconds = Number(config.totalAudioSeconds);
  if (Number.isFinite(totalAudioSeconds) && totalAudioSeconds > 0 && scenes.length) {
    const estimatedTotal = scenes.reduce((acc, scene) => acc + scene.durationInSeconds, 0);
    if (estimatedTotal > 0) {
      const factor = totalAudioSeconds / estimatedTotal;
      for (const scene of scenes) {
        scene.durationInSeconds = Number(Math.max(0.8, scene.durationInSeconds * factor).toFixed(3));
      }
    }
  }

  return {
    videoId: String(config.videoId || frontmatter.videoId || "thunderbolt-video"),
    title: String(config.title || frontmatter.title || ""),
    language: String(config.language || "en"),
    fps,
    width,
    height,
    audioUrl: String(config.audioUrl || ""),
    scenes,
    metadata: {
      channel: String((config.metadata && config.metadata.channel) || ""),
      style: String((config.metadata && config.metadata.style) || ""),
      music: String((config.metadata && config.metadata.music) || ""),
    },
  };
}
