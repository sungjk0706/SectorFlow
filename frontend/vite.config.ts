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
            // EE3의 listeners()는 컨텍스트 없이 원본 fn만 반환하므로,
            // fn(err) 호출 시 this=undefined → onError에서 this.listeners() 크래시 발생.
            // 따라서 fn.apply(proxy, args)로 컨텍스트와 전체 인자를 복원한다.
            // 또한 proxy.onError는 "커스텀 핸들러가 없으면 throw"가 목적이므로
            // 우리가 커스텀 핸들러를 추가한 상황에서는 스킵한다.
            const proxyErrorListeners = proxy.listeners('error')
            proxy.removeAllListeners('error')
            proxy.on('error', (err: NodeJS.ErrnoException, ...rest: unknown[]) => {
              if (err?.code === 'ECONNRESET') return
              for (const fn of proxyErrorListeners) {
                if (fn === (proxy as unknown as { onError: (...a: unknown[]) => void }).onError) continue
                fn.apply(proxy, [err, ...rest])
              }
            })
          })
          // socket-level error: proxyReqWs에서 Vite가 socket에 추가하는 error 핸들러를 교체
          proxy.on('proxyReqWs', (_proxyReq, _req, socket) => {
            setImmediate(() => {
              const socketErrorListeners = socket.listeners('error')
              socket.removeAllListeners('error')
              socket.on('error', (err: NodeJS.ErrnoException) => {
                if (err?.code === 'ECONNRESET') return
                for (const fn of socketErrorListeners) {
                  fn.call(socket, err)
                }
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
