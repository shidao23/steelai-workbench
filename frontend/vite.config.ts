import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// WO-31 §2：前端独立构建，产物 `dist/` 由薄 API 同源提供（见 steelai/web_api/app.py）。
// 开发模式把 /api 代理到本机 8760，避免把凭据或跨源放行写进代码。
export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 4096,
    rollupOptions: {
      output: {
        manualChunks: {
          plotly: ['plotly.js-dist-min'],
        },
      },
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8760',
        changeOrigin: false,
      },
    },
  },
})
