import React from 'react';
import { AbsoluteFill, Sequence, useCurrentFrame, interpolate } from 'remotion';
import { AnimatedImage } from './components/AnimatedImage';
import { NarrationAudio } from './components/NarrationAudio';
import { SceneTransition } from './components/SceneTransition';
import { SubscribeCTA } from './components/SubscribeCTA';

type Scene = {
  id: string;
  scene_type: string;
  voiceover_text: string;
  image_prompt: string;
  durationInSeconds: number;
  imageUrl?: string;
  audioUrl?: string;
};

export const InspirationalVideo: React.FC<{
  title: string;
  scenes: Scene[];
}> = ({ title, scenes }) => {
  const frame = useCurrentFrame();
  const fps = 30;
  let offset = 0;
  return (
    <AbsoluteFill style={{ background: '#0a0a0a', fontFamily: 'Georgia, serif' }}>
      {scenes.map((scene, index) => {
        const start = offset;
        const duration = Math.max(30, Math.round(scene.durationInSeconds * fps));
        offset += duration;
        const isLast = index === scenes.length - 1;
        return (
          <Sequence key={scene.id || index} from={start} durationInFrames={duration + (isLast ? 15 : 0)}>
            <AbsoluteFill>
              <AnimatedImage src={scene.imageUrl} width={1920} height={1080} />
              <div style={{
                position: 'absolute', inset: 0,
                background: 'linear-gradient(to bottom, rgba(0,0,0,0.3), rgba(0,0,0,0.7))',
                display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'center',
                padding: '80px 120px',
              }}>
                {index === 0 && (
                  <h1 style={{ fontSize: 72, color: '#fff', textAlign: 'center', marginBottom: 40, textShadow: '0 4px 20px rgba(0,0,0,0.8)' }}>{title}</h1>
                )}
                <p style={{ fontSize: 42, color: '#e0e0e0', textAlign: 'center', lineHeight: 1.6, maxWidth: 1400, textShadow: '0 2px 10px rgba(0,0,0,0.9)' }}>
                  {scene.voiceover_text}
                </p>
              </div>
              <NarrationAudio src={scene.audioUrl} />
              {!isLast && <SceneTransition />}
            </AbsoluteFill>
          </Sequence>
        );
      })}
      {scenes.length > 0 && (
        <Sequence from={offset} durationInFrames={60}>
          <AbsoluteFill style={{ background: '#0a0a0a', alignItems: 'center', justifyContent: 'center' }}>
            <SubscribeCTA />
          </AbsoluteFill>
        </Sequence>
      )}
    </AbsoluteFill>
  );
};
