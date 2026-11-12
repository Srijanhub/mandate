import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';

export type ThemeMode = 'dark' | 'light' | 'system';
export type ResolvedTheme = 'dark' | 'light';

interface ThemeContextValue {
  mode: ThemeMode;
  resolved: ResolvedTheme;
  prefersReducedMotion: boolean;
  setMode: (mode: ThemeMode) => void;
  toggleTheme: () => void;
}

const STORAGE_KEY = 'mandate-theme';

const ThemeContext = createContext<ThemeContextValue | null>(null);

function resolveSystemTheme(): ResolvedTheme {
  if (typeof window === 'undefined' || !window.matchMedia) return 'dark';
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

function readStoredMode(): ThemeMode {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === 'dark' || raw === 'light' || raw === 'system') return raw;
  } catch {
    // Ignore storage errors
  }
  return 'system';
}

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [mode, setModeState] = useState<ThemeMode>(readStoredMode);
  const [systemTheme, setSystemTheme] = useState<ResolvedTheme>(resolveSystemTheme);
  const [prefersReducedMotion, setPrefersReducedMotion] = useState<boolean>(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return false;
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  });

  useEffect(() => {
    const colorMq = window.matchMedia('(prefers-color-scheme: light)');
    const motionMq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const onColor = () => setSystemTheme(colorMq.matches ? 'light' : 'dark');
    const onMotion = () => setPrefersReducedMotion(motionMq.matches);
    colorMq.addEventListener('change', onColor);
    motionMq.addEventListener('change', onMotion);
    return () => {
      colorMq.removeEventListener('change', onColor);
      motionMq.removeEventListener('change', onMotion);
    };
  }, []);

  const resolved: ResolvedTheme = mode === 'system' ? systemTheme : mode;

  useEffect(() => {
    document.documentElement.dataset.theme = resolved;
    document.documentElement.dataset.themeMode = mode;
    try {
      localStorage.setItem(STORAGE_KEY, mode);
    } catch {
      // Ignore storage errors
    }
  }, [mode, resolved]);

  const value = useMemo<ThemeContextValue>(
    () => ({
      mode,
      resolved,
      prefersReducedMotion,
      setMode: (next) => setModeState(next),
      toggleTheme: () => setModeState((prev) => ((prev === 'system' ? systemTheme : prev) === 'dark' ? 'light' : 'dark')),
    }),
    [mode, resolved, prefersReducedMotion, systemTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
};

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used inside ThemeProvider');
  return ctx;
}
