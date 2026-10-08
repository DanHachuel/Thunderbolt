import React from 'react';
import { useCurrentFrame, interpolate, Easing } from 'remotion';

export const SceneTransition: React.FC<{ durationInFrames?: number }> = ({ durationInFrames = 15 }) => {
  const frame = useCurrentFrame();
  const progress = interpolate(frame, [0, durationInFrames], [0, 1], {
    easing: Easing.inOut(Easing.cubic),
    extrapolateRight: 'clamp',
  });
  if (progress >= 1) return null;
  return (
    <div style={{
      position: 'absolute',
      inset: 0,
      background: `rgba(0,0,0,${progress})`,
      zIndex: 10,
    }} />
  );
};
