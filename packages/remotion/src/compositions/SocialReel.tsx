import React from 'react';
import { AbsoluteFill, Sequence, useCurrentFrame, interpolate } from 'remotion';
import { AnimatedImage } from './components/AnimatedImage';
import { NarrationAudio } from './components/NarrationAudio';
import { SceneTransition } from './components/SceneTransition';
import { ProgressBar } from './components/ProgressBar';

type Scene = {
  id: string;
  scene_type: string;
  voiceOverText: string;
  imagePrompt: string;
  durationInSeconds: number;
  imageUrl?: string;
  audioUrl?: string;
};

export const SocialReel: React.FC<{ title: string; scenes: Scene[] }> = ({ title, scenes }) => {
  const fps = 30;
  let offset = 0;
  return (
    <AbsoluteFill style={{ background: '#000', fontFamily: 'Helvetica, Arial, sans-serif' }}>
      <ProgressBar />
      {scenes.map((scene, index) => {
        const start = offset;
        const extra = scene.scene_type === 'hook' ? 9 : scene.scene_type === 'cta' ? 15 : 0;
        const duration = Math.max(30, Math.round(scene.durationInSeconds * fps)) + extra;
        offset += duration;
        const isHook = scene.scene_type === 'hook';
        const isCta = scene.scene_type === 'cta';
        return (
          <Sequence key={scene.id || index} from={start} durationInFrames={duration}>
            <AbsoluteFill>
              <AnimatedImage src={scene.imageUrl} width={1080} height={1920} />
              <div style={{
                position: 'absolute', inset: 0,
                background: isCta ? 'rgba(0,0,0,0.6)' : 'linear-gradient(to bottom, transparent 30%, rgba(0,0,0,0.7))',
                display: 'flex', flexDirection: 'column',
                justifyContent: isCta ? 'center' : 'flex-end',
                alignItems: 'center',
                padding: 60,
              }}>
                {isHook && (
                  <h1 style={{ fontSize: 56, color: '#fff', textAlign: 'center', marginBottom: 30, textShadow: '0 2px 15px rgba(0,0,0,0.9)' }}>{title}</h1>
                )}
                <p style={{ fontSize: 36, color: '#fff', textAlign: 'center', lineHeight: 1.5, maxWidth: 900, textShadow: '0 2px 10px rgba(0,0,0,0.9)', fontWeight: isHook ? 700 : 400 }}>
                  {scene.voiceOverText}
                </p>
              </div>
              <NarrationAudio src={scene.audioUrl} />
              {!isCta && index < scenes.length - 1 && <SceneTransition />}
            </AbsoluteFill>
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
