import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Vite 配置：开发服务器端口 5173，将 /api 代理到后端 8766
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8766',
        changeOrigin: true,
      },
    },
  },
})
