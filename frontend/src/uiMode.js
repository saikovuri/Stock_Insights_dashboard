import { useSyncExternalStore } from 'react';

// Simple / Advanced interface mode, saved per device. Simple hides overlapping or specialist tools; nothing is removed.
const KEY = 'ui_mode';
const listeners = new Set();
let current = null;  // in-memory fallback when storage can't be written

export const SIMPLE = {
  ideas: ['setups', 'wheel', 'record'],
  journal: ['history', 'journal', 'options', 'scorecard', 'paper'],
  // Portfolio Risk tools hidden in Simple (anchor ids)
  risk: ['portfolio-doctor', 'trim-planner', 'earnings-exposure', 'expiry-ladder', 'stress-scenarios', 'correlations', 'sectors'],
  // Stock dashboard cards hidden in Simple, by stock view
  cards: { analysis: ['rs', 'smartmoney', 'peers'], fundamentals: ['ownership', 'financials'] },
};

export function getUiMode() {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved) return saved === 'advanced' ? 'advanced' : 'simple';
  } catch { /* storage blocked */ }
  return current || 'simple';
}

export function setUiMode(mode) {
  current = mode === 'advanced' ? 'advanced' : 'simple';
  try { localStorage.setItem(KEY, current); } catch { /* storage full or blocked: kept for this page only */ }
  listeners.forEach(listener => listener());
}

function subscribe(listener) {
  listeners.add(listener);
  const onStorage = event => { if (event.key === KEY) listener(); };
  window.addEventListener('storage', onStorage);
  return () => { listeners.delete(listener); window.removeEventListener('storage', onStorage); };
}

export function useUiMode() {
  const mode = useSyncExternalStore(subscribe, getUiMode, () => 'simple');
  return { mode, simple: mode === 'simple', setMode: setUiMode };
}

/** True when a command-palette destination is hidden in Simple mode. */
export function hiddenInSimple(go) {
  if (go.ideasTab && !SIMPLE.ideas.includes(go.ideasTab)) return true;
  return Boolean(go.anchor && SIMPLE.risk.includes(go.anchor));
}
