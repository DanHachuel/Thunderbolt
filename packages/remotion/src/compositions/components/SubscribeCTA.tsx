import React from 'react';
import { useCurrentFrame, interpolate, spring } from 'remotion';

export const SubscribeCTA: React.FC<{ text?: string }> = ({ text = 'Like & Subscribe' }) => {
  const frame = useCurrentFrame();
  const scale = spring({ frame, fps: 30, config: { damping: 12 } });
  return (
    <div style={{
      position: 'absolute',
      bottom: 100,
      left: '50%',
      transform: `translateX(-50%) scale(${scale})`,
      padding: '20px 60px',
      background: 'linear-gradient(90deg, #FF0000, #FF6B00)',
      borderRadius: 40,
      fontSize: 48,
      fontWeight: 900,
      color: '#fff',
      textAlign: 'center',
      zIndex: 5,
    }}>
      {text}
    </div>
  );
};
