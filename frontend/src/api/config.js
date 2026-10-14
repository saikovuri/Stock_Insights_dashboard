// In development, Vite proxies /api → localhost:8000
// In production, set VITE_API_URL to the backend URL (home laptop via Tailscale Funnel)
// On native (Capacitor), there's no proxy so we must use the full URL
import { Capacitor } from '@capacitor/core';

const isNative = Capacitor.isNativePlatform();

export const API_BASE = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api`
  : isNative
    ? 'https://stockpilot.tail112222.ts.nets.net/api'
    : '/api';
