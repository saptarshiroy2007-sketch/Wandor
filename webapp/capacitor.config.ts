import { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.wandor.app',
  appName: 'Wandor',
  webDir: 'dist',
  // During dev you can point this at your Vite dev server for live-reload on device:
  // server: { url: 'http://192.168.x.x:5173', cleartext: true },
};

export default config;
