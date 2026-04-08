import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.stockinsights.app',
  appName: 'Stock Insights',
  webDir: 'dist',
  server: {
    // Points to your production backend
    // During development, you can change this to your local IP:
    // url: 'http://192.168.x.x:5173',
    androidScheme: 'https',
  },
  plugins: {
    StatusBar: {
      style: 'Dark',
      backgroundColor: '#0a0f1c',
    },
    SplashScreen: {
      launchAutoHide: true,
      launchShowDuration: 1500,
      backgroundColor: '#0a0f1c',
      showSpinner: false,
    },
  },
};

export default config;
