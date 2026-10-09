import React from 'react';
import { Img, useCurrentFrame, interpolate } from 'remotion';

export const AnimatedImage: React.FC<{ src?: string; width: number; height: number }> = ({ src, width, height }) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 15], [0, 1], { extrapolateRight: 'clamp' });
  if (src) {
    return <Img src={src} style={{ width, height, objectFit: 'cover', opacity }} />;
  }
  const hue = (frame * 2) % 360;
  return (
    <div style={{
      width, height,
      background: `linear-gradient(135deg, hsl(${hue}, 60%, 30%), hsl(${(hue + 60) % 360}, 50%, 15%))`,
      opacity,
    }} />
  );
};
