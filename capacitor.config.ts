import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'app.videoqualitychecker.castcast',
  appName: 'VideoQualityCheckerApp',
  webDir: 'dist',
  server: {
    androidScheme: 'http',
  },
};

export default config;
