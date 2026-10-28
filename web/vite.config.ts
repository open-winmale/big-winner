import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import unocss from 'unocss/vite';

// 开发期后端地址：默认连常驻真实模式 8787，可用 BIGWINNER_BACKEND 覆盖
// （例如目检 demo 模式：BIGWINNER_BACKEND=http://127.0.0.1:8795 npm run dev）
const backend = process.env.BIGWINNER_BACKEND || 'http://127.0.0.1:8787';

export default defineConfig(({ mode }) => ({
  plugins: [vue(), unocss()],
  // hash 路由 + 相对 base：后端同端口托管（/）或任意子路径都能跑
  base: './',
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: backend, changeOrigin: false },
      '/export': { target: backend, changeOrigin: false },
    },
  },
  build: {
    // 构建产物直接进 Python 包，由 bigwinner.shouxi 的 do_GET 托管（单端口单进程）；
    // pages 模式输出到本地 dist-pages/，由 GitHub Pages workflow 托管
    outDir: fileURLToPath(new URL(
      mode === 'pages' ? './dist-pages' : '../src/bigwinner/shouxi/web_dist',
      import.meta.url)),
    emptyOutDir: true,
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks: {
          echarts: ['echarts'],
          vue: ['vue', 'vue-router', 'pinia'],
        },
      },
    },
  },
}));
