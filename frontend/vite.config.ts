import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// As rotas da API do FastAPI ficam na raiz (/chat, /dashboard, ...), então o dev
// server precisa encaminhá-las para o uvicorn em 127.0.0.1:8000.
const API_ROUTES = [
  '/chat',
  '/dashboard',
  '/rebalanceamento',
  '/snapshots',
  '/posicoes',
  '/extrato',
  '/desempenho',
  '/health',
  '/docs',
  '/openapi.json',
]

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // O build é servido por app/main.py em /static/, então os assets precisam
  // desse prefixo nos links gerados.
  base: '/static/',
  build: {
    outDir: '../static',
    emptyOutDir: true,
    assetsDir: 'assets',
  },
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      API_ROUTES.map((rota) => [
        rota,
        { target: 'http://127.0.0.1:8000', changeOrigin: true },
      ]),
    ),
  },
})
