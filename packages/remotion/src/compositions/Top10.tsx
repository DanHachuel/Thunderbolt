import React from 'react';
import { AbsoluteFill, Sequence, useCurrentFrame, interpolate, spring } from 'remotion';
import { AnimatedImage } from './components/AnimatedImage';
import { NarrationAudio } from './components/NarrationAudio';
import { SceneTransition } from './components/SceneTransition';
import { SubscribeCTA } from './components/SubscribeCTA';

type IntroOutro = { voiceoverText: string; imagePrompt: string; durationInSeconds: number; imageUrl?: string; audioUrl?: string };
type RankItem = { rank: number; voiceoverText: string; imagePrompt: string; lowerThirdText: string; durationInSeconds: number; imageUrl?: string; audioUrl?: string };

export const Top10: React.FC<{
  title: string;
  intro: IntroOutro;
  ranking: RankItem[];
  outro: IntroOutro;
}> = ({ title, intro, ranking, outro }) => {
  const fps = 30;
  let offset = Math.round((intro.durationInSeconds || 5) * fps);
  const introDur = offset;
  return (
    <AbsoluteFill style={{ background: '#0d0d0d', fontFamily: 'Impact, Arial Black, sans-serif' }}>
      <Sequence from={0} durationInFrames={introDur}>
        <AbsoluteFill>
          <AnimatedImage src={intro.imageUrl} width={1920} height={1080} />
          <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <h1 style={{ fontSize: 96, color: '#FFD700', textAlign: 'center', textShadow: '0 4px 30px rgba(0,0,0,1)' }}>{title}</h1>
          </div>
          <NarrationAudio src={intro.audioUrl} />
        </AbsoluteFill>
      </Sequence>
      {ranking.map((item, index) => {
        const start = offset;
        const duration = Math.max(30, Math.round(item.durationInSeconds * fps)) + 12; // +0.4s fade
        offset += duration;
        return (
          <Sequence key={item.rank} from={start} durationInFrames={duration}>
            <AbsoluteFill>
              <AnimatedImage src={item.imageUrl} width={1920} height={1080} />
              <div style={{
                position: 'absolute', bottom: 60, left: 60,
                background: 'linear-gradient(90deg, rgba(0,0,0,0.9), transparent)',
                padding: '30px 80px 30px 40px',
                borderRadius: '0 20px 20px 0',
              }}>
                <div style={{ fontSize: 80, color: '#FFD700', fontWeight: 900, lineHeight: 1 }}>#{item.rank}</div>
                <div style={{ fontSize: 42, color: '#fff', fontWeight: 700, marginTop: 10 }}>{item.lowerThirdText}</div>
              </div>
              <NarrationAudio src={item.audioUrl} />
              <SceneTransition />
            </AbsoluteFill>
          </Sequence>
        );
      })}
      <Sequence from={offset} durationInFrames={Math.round((outro.durationInSeconds || 4) * fps) + 30}>
        <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
          <SubscribeCTA />
        </AbsoluteFill>
        <NarrationAudio src={outro.audioUrl} />
      </Sequence>
    </AbsoluteFill>
  );
};
