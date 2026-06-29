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
        configure: (proxy) => {
          // Vite가 configure 이후에 자체 error/proxyReqWs 리스너를 추가하므로
          // setImmediate로 Vite 리스너 추가 이후에 교체 실행
          setImmediate(() => {
            // proxy-level error: Vite의 핸들러 보존 후 ECONNRESET 필터링 버전으로 교체
            const proxyErrorListeners = proxy.listeners('error')
            proxy.removeAllListeners('error')
            proxy.on('error', (err: NodeJS.ErrnoException) => {
              if (err?.code === 'ECONNRESET') return
              proxyErrorListeners.forEach(fn => fn(err))
            })
          })
          // socket-level error: proxyReqWs에서 Vite가 socket에 추가하는 error 핸들러를 교체
          proxy.on('proxyReqWs', (_proxyReq, _req, socket) => {
            setImmediate(() => {
              const socketErrorListeners = socket.listeners('error')
              socket.removeAllListeners('error')
              socket.on('error', (err: NodeJS.ErrnoException) => {
                if (err?.code === 'ECONNRESET') return
                socketErrorListeners.forEach(fn => fn(err))
              })
            })
          })
        },
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true, // 빌드 시 dist 폴더 자동 청소
  },
})
