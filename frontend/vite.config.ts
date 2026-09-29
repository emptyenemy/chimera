import path from "path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// Сборка кладётся в ui/web-next: её отдают все три движка окна без правок серверного кода.
// base "./" — пути в бандле относительные, страница открывается и с file://, и по http.
export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  build: {
    outDir: path.resolve(import.meta.dirname, "../ui/web-next"),
    emptyOutDir: true,
  },
})
