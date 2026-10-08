import React from 'react';
import { AbsoluteFill, Sequence, useCurrentFrame, interpolate, spring } from 'remotion';
import { NarrationAudio } from './components/NarrationAudio';
import { ProgressBar } from './components/ProgressBar';
import { SubscribeCTA } from './components/SubscribeCTA';

type Question = {
  question: string;
  answer1: string;
  answer2: string;
  answer3: string;
  answer4: string;
  correct_answer: number;
  durationInSeconds: number;
  revealDelaySeconds: number;
  audioUrl?: string;
};

const ANSWER_COLORS = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#FFA07A'];

export const Quiz: React.FC<{
  topic: string;
  intro_voiceover: string;
  like_and_subscribe_voiceover: string;
  questions: Question[];
  introAudioUrl?: string;
  outroAudioUrl?: string;
}> = ({ topic, intro_voiceover, like_and_subscribe_voiceover, questions, introAudioUrl, outroAudioUrl }) => {
  const fps = 30;
  let offset = 90; // 3s intro
  return (
    <AbsoluteFill style={{ background: 'linear-gradient(180deg, #1a1a2e, #16213e)', fontFamily: 'Arial, sans-serif' }}>
      <ProgressBar />
      <Sequence from={0} durationInFrames={90}>
        <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
          <h1 style={{ fontSize: 64, color: '#fff', textAlign: 'center', padding: 40 }}>{topic}</h1>
          <p style={{ fontSize: 36, color: '#aaa', marginTop: 20 }}>{intro_voiceover}</p>
        </AbsoluteFill>
        <NarrationAudio src={introAudioUrl} />
      </Sequence>
      {questions.map((q, index) => {
        const start = offset;
        const qDur = Math.round(q.durationInSeconds * fps);
        const revealDur = Math.round(q.revealDelaySeconds * fps);
        const totalDur = qDur + revealDur;
        offset += totalDur;
        return (
          <Sequence key={index} from={start} durationInFrames={totalDur}>
            <AbsoluteFill style={{ padding: 40, justifyContent: 'center' }}>
              <h2 style={{ fontSize: 48, color: '#fff', textAlign: 'center', marginBottom: 60, minHeight: 200 }}>{q.question}</h2>
              {[q.answer1, q.answer2, q.answer3, q.answer4].map((answer, aIndex) => (
                <div key={aIndex} style={{
                  padding: '24px 40px',
                  margin: '12px 20px',
                  background: aIndex + 1 === q.correct_answer ? '#2ecc71' : ANSWER_COLORS[aIndex],
                  borderRadius: 20,
                  fontSize: 36,
                  fontWeight: 700,
                  color: '#fff',
                  textAlign: 'center',
                  minWidth: 400,
                }}>
                  {answer}
                </div>
              ))}
              <NarrationAudio src={q.audioUrl} />
            </AbsoluteFill>
          </Sequence>
        );
      })}
      <Sequence from={offset} durationInFrames={90}>
        <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
          <SubscribeCTA text={like_and_subscribe_voiceover} />
        </AbsoluteFill>
        <NarrationAudio src={outroAudioUrl} />
      </Sequence>
    </AbsoluteFill>
  );
};
