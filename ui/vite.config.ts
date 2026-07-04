import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Vite 配置：基路径使用相对路径，便于 Electron 在生产态通过 file:// 加载打包产物
export default defineConfig({
  base: './',
  plugins: [react()],
  build: {
    outDir: 'dist',
  },
});
