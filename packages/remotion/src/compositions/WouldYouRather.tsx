import React from 'react';
import { AbsoluteFill, Sequence, useCurrentFrame, interpolate, spring } from 'remotion';
import { AnimatedImage } from './components/AnimatedImage';
import { NarrationAudio } from './components/NarrationAudio';
import { ProgressBar } from './components/ProgressBar';
import { SubscribeCTA } from './components/SubscribeCTA';

type Question = {
  id: string;
  option1_text: string;
  option1_image_prompt: string;
  option2_text: string;
  option2_image_prompt: string;
  option1_result: number;
  voiceover_text: string;
  durationInSeconds: number;
  thinkingDelaySeconds: number;
  revealDurationSeconds: number;
  option1_imageUrl?: string;
  option2_imageUrl?: string;
  audioUrl?: string;
};

export const WouldYouRather: React.FC<{
  or_text: string;
  like_and_subscribe_voiceover_text: string;
  questions: Question[];
  outroAudioUrl?: string;
}> = ({ or_text, like_and_subscribe_voiceover_text, questions, outroAudioUrl }) => {
  const fps = 30;
  let offset = 90; // 3s intro
  return (
    <AbsoluteFill style={{ background: '#0f0f1a', fontFamily: 'Arial, sans-serif' }}>
      <ProgressBar />
      <Sequence from={0} durationInFrames={90}>
        <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
          <h1 style={{ fontSize: 56, color: '#fff', textAlign: 'center' }}>Would You Rather?</h1>
        </AbsoluteFill>
      </Sequence>
      {questions.map((q, index) => {
        const start = offset;
        const thinkDur = Math.round(q.thinkingDelaySeconds * fps);
        const qDur = Math.round(q.durationInSeconds * fps);
        const revealDur = Math.round(q.revealDurationSeconds * fps);
        const totalDur = thinkDur + qDur + revealDur;
        offset += totalDur;
        return (
          <Sequence key={q.id || index} from={start} durationInFrames={totalDur}>
            <AbsoluteFill>
              <div style={{ display: 'flex', height: '100%' }}>
                <div style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
                  <AnimatedImage src={q.option1_imageUrl} width={540} height={1920} />
                  <div style={{ position: 'absolute', bottom: 300, left: 0, right: 0, textAlign: 'center', padding: 20 }}>
                    <span style={{ fontSize: 36, color: '#fff', fontWeight: 700, textShadow: '0 2px 10px #000' }}>{q.option1_text}</span>
                  </div>
                </div>
                <div style={{
                  width: 80, display: 'flex', alignItems: 'center', justifyContent: 'center',
                  background: '#1a1a2e',
                }}>
                  <span style={{ fontSize: 40, color: '#FFD700', fontWeight: 900 }}>{or_text}</span>
                </div>
                <div style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
                  <AnimatedImage src={q.option2_imageUrl} width={540} height={1920} />
                  <div style={{ position: 'absolute', bottom: 300, left: 0, right: 0, textAlign: 'center', padding: 20 }}>
                    <span style={{ fontSize: 36, color: '#fff', fontWeight: 700, textShadow: '0 2px 10px #000' }}>{q.option2_text}</span>
                  </div>
                </div>
              </div>
              <div style={{ position: 'absolute', bottom: 200, left: 40, right: 40, height: 40, background: 'rgba(255,255,255,0.2)', borderRadius: 20, overflow: 'hidden', zIndex: 10 }}>
                <div style={{ width: `${q.option1_result}%`, height: '100%', background: 'linear-gradient(90deg, #FF6B6B, #FF4444)', borderRadius: 20 }} />
              </div>
              <NarrationAudio src={q.audioUrl} />
            </AbsoluteFill>
          </Sequence>
        );
      })}
      <Sequence from={offset} durationInFrames={90}>
        <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
          <SubscribeCTA text={like_and_subscribe_voiceover_text} />
        </AbsoluteFill>
        <NarrationAudio src={outroAudioUrl} />
      </Sequence>
    </AbsoluteFill>
  );
};
