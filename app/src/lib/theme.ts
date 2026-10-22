import { useEffect, useState } from 'react';
import { useMediaQuery } from './useMediaQuery';

export type ThemePref = 'system' | 'light' | 'dark';

/** Same key as the pre-paint script in index.html. */
const KEY = 'sn-theme';
const ORDER: ThemePref[] = ['system', 'light', 'dark'];

function readPref(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    if (v === 'light' || v === 'dark') return v;
  } catch {
    // storage blocked: fall back to the OS setting
  }
  return 'system';
}

/** Theme preference, persisted; resolves "system" against prefers-color-scheme and sets <html data-theme>. */
export function useTheme() {
  const [pref, setPref] = useState<ThemePref>(readPref);
  const systemLight = useMediaQuery('(prefers-color-scheme: light)');
  const resolved = pref === 'system' ? (systemLight ? 'light' : 'dark') : pref;

  useEffect(() => {
    document.documentElement.dataset.theme = resolved;
  }, [resolved]);

  useEffect(() => {
    try {
      if (pref === 'system') localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, pref);
    } catch {
      // not persisted; the choice still applies for this visit
    }
  }, [pref]);

  const next = ORDER[(ORDER.indexOf(pref) + 1) % ORDER.length];
  return { pref, resolved, next, cycle: () => setPref(next) };
}
