// Error tracking is optional: set VITE_SENTRY_DSN in Vercel to enable. The SDK is loaded lazily.
export async function initMonitoring() {
  const dsn = import.meta.env.VITE_SENTRY_DSN;
  if (!dsn) return;
  const Sentry = await import('@sentry/react');
  Sentry.init({
    dsn,
    environment: import.meta.env.MODE,
    sendDefaultPii: false,
    tracesSampleRate: 0,
    // Network blips and browser extensions are not app bugs
    ignoreErrors: ['Failed to fetch', 'NetworkError', 'Load failed', 'ResizeObserver loop'],
    beforeSend(event) {
      if (event.request?.headers) delete event.request.headers.Authorization;
      return event;
    },
  });
}
