import React from "react";
import { Audio } from "remotion";

/**
 * Toca a narração TTS sincronizada com a timeline da composição.
 * O áudio é gerado pelo pipeline Python (edge-tts/Azure/ElevenLabs) antes do
 * render e chega como caminho absoluto no inputProps.audioUrl.
 * Remotion resolve caminhos absolutos locais durante o render server-side.
 */
export const NarrationAudio: React.FC<{ audioUrl?: string }> = ({ audioUrl }) => {
  if (!audioUrl) {
    // defaultProps traz audioUrl vazio (preview no studio); sem ficheiro não
    // existe áudio para tocar, mas a composição continua válida.
    return null;
  }
  return <Audio src={audioUrl} />;
};
