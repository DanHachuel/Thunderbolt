import React from 'react';
import { useCurrentFrame, useVideoConfig, interpolate } from 'remotion';

export const ProgressBar: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const progress = interpolate(frame, [0, durationInFrames], [0, 100], { extrapolateRight: 'clamp' });
  return (
    <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 8, background: 'rgba(255,255,255,0.2)' }}>
      <div style={{ width: `${progress}%`, height: '100%', background: '#FF4444' }} />
    </div>
  );
};
