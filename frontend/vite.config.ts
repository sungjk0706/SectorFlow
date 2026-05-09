import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [],
  server: {
    host: 'localhost',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true, // WebSocket 지원 활성화
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true, // 빌드 시 dist 폴더 자동 청소
  },
})
