import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

const at = (path: string) => fileURLToPath(new URL(path, import.meta.url))

export default defineConfig({
  root: at('../landing/'),
  base: './',
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': at('./src/') } },
  build: {
    outDir: at('../landing/dist/'),
    emptyOutDir: true,
    rolldownOptions: {
      input: { main: at('../landing/index.html'), en: at('../landing/en/index.html') },
    },
  },
})
