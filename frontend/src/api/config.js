// In development, Vite proxies /api → localhost:8000
// In production, set VITE_API_URL to your Render backend URL
// On native (Capacitor), there's no proxy so we must use the full URL
import { Capacitor } from '@capacitor/core';

const isNative = Capacitor.isNativePlatform();

export const API_BASE = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api`
  : isNative
    ? 'https://stock-insights-api.onrender.com/api'
    : '/api';
