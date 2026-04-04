// In development, Vite proxies /api → localhost:8000
// In production, set VITE_API_URL to your Render backend URL
export const API_BASE = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api`
  : '/api';
