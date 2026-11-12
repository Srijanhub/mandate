import React, { Component, Suspense, lazy, useEffect, useState } from 'react';
import { useTheme } from '../../theme/ThemeProvider';

const LazyPhotonKnotCanvas = lazy(() => import('./PhotonKnotCanvas'));

function isWebGLSupported(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    const canvas = document.createElement('canvas');
    return Boolean(
      window.WebGLRenderingContext &&
        (canvas.getContext('webgl2') || canvas.getContext('webgl')),
    );
  } catch {
    return false;
  }
}

class CanvasErrorBoundary extends Component<
  { fallback: React.ReactNode; children: React.ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };
  static getDerivedStateFromError(): { hasError: boolean } {
    return { hasError: true };
  }
  render() {
    if (this.state.hasError) return this.props.fallback;
    return this.props.children;
  }
}

export const PhotonKnotFallback: React.FC<{ size?: 'hero' | 'auth' | 'mini' }> = ({ size = 'hero' }) => {
  const px = size === 'mini' ? 68 : size === 'auth' ? 280 : 340;
  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        display: 'grid',
        placeItems: 'center',
      }}
      aria-label="Mandate Photon Knot Identity"
    >
      <svg
        width={px}
        height={px}
        viewBox="0 0 240 240"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        style={{ maxWidth: '88%', maxHeight: '88%' }}
      >
        <ellipse
          cx="120"
          cy="120"
          rx="94"
          ry="44"
          transform="rotate(-24 120 120)"
          stroke="var(--accent-brass)"
          strokeWidth="1.2"
          strokeOpacity="0.72"
        />
        <ellipse
          cx="120"
          cy="120"
          rx="84"
          ry="38"
          transform="rotate(34 120 120)"
          stroke="var(--accent-titanium)"
          strokeWidth="1"
          strokeOpacity="0.48"
        />
        <path
          d="M120 44C158 44 184 74 176 112C168 150 132 192 92 178C52 164 58 110 88 86C118 62 178 86 170 132C162 178 98 188 74 148C50 108 82 44 120 44Z"
          stroke="var(--text-primary)"
          strokeWidth="5.5"
          strokeOpacity="0.28"
          strokeLinecap="round"
        />
        <path
          d="M120 44C158 44 184 74 176 112C168 150 132 192 92 178C52 164 58 110 88 86C118 62 178 86 170 132C162 178 98 188 74 148C50 108 82 44 120 44Z"
          stroke="var(--accent-titanium)"
          strokeWidth="1.8"
          strokeOpacity="0.85"
          strokeLinecap="round"
        />
        <circle cx="120" cy="120" r="9" fill="var(--accent-brass)" fillOpacity="0.9" />
      </svg>
    </div>
  );
};

export const PhotonKnot: React.FC<{
  variant?: 'hero' | 'auth' | 'mini';
  interactive?: boolean;
  className?: string;
  style?: React.CSSProperties;
}> = ({ variant = 'hero', interactive = true, className, style }) => {
  const { resolved, prefersReducedMotion } = useTheme();
  const [webglReady, setWebglReady] = useState(false);

  useEffect(() => {
    setWebglReady(isWebGLSupported());
  }, []);

  const scale = variant === 'mini' ? 0.9 : variant === 'auth' ? 0.96 : 1.05;
  const fallback = <PhotonKnotFallback size={variant} />;

  return (
    <div
      className={className}
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
        minHeight: variant === 'mini' ? '72px' : variant === 'auth' ? '320px' : '400px',
        ...style,
      }}
    >
      {webglReady ? (
        <CanvasErrorBoundary fallback={fallback}>
          <Suspense fallback={fallback}>
            <LazyPhotonKnotCanvas
              theme={resolved}
              reducedMotion={prefersReducedMotion}
              interactive={interactive}
              scale={scale}
            />
          </Suspense>
        </CanvasErrorBoundary>
      ) : (
        fallback
      )}
    </div>
  );
};
