import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';

export type ThemePref = 'light' | 'dark' | 'system';

interface ThemeCtx {
  pref: ThemePref;
  resolved: 'light' | 'dark';
  setPref: (p: ThemePref) => void;
  toggle: () => void;
  reduceMotion: boolean;
  setReduceMotion: (v: boolean) => void;
}

const Ctx = createContext<ThemeCtx | null>(null);
const KEY = 'aq-theme';
const media = () => window.matchMedia('(prefers-color-scheme: dark)');

function readPref(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'light' || v === 'dark' || v === 'system' ? v : 'system';
  } catch {
    return 'system';
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [pref, setPref] = useState<ThemePref>(readPref);
  const [systemDark, setSystemDark] = useState(() => media().matches);
  const [reduceMotion, setReduceMotion] = useState(() => {
    try {
      return localStorage.getItem('aq-reduce-motion') === '1';
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem('aq-reduce-motion', reduceMotion ? '1' : '0');
    } catch {
      // ignore
    }
  }, [reduceMotion]);

  useEffect(() => {
    const m = media();
    const on = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    m.addEventListener('change', on);
    return () => m.removeEventListener('change', on);
  }, []);

  const resolved: 'light' | 'dark' = pref === 'system' ? (systemDark ? 'dark' : 'light') : pref;

  useEffect(() => {
    document.documentElement.classList.toggle('dark', resolved === 'dark');
    try {
      localStorage.setItem(KEY, pref);
    } catch {
      // Storage unavailable: theme still applies for this session.
    }
  }, [pref, resolved]);

  return (
    <Ctx.Provider
      value={{
        pref,
        resolved,
        setPref,
        toggle: () => setPref(resolved === 'dark' ? 'light' : 'dark'),
        reduceMotion,
        setReduceMotion,
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useTheme() {
  const c = useContext(Ctx);
  if (!c) throw new Error('useTheme must be used within ThemeProvider');
  return c;
}
