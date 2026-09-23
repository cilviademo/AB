import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Tauri serves the dev server on a fixed port and expects a relative base.
export default defineConfig({
  plugins: [react()],
  base: "./",
  clearScreen: false,
  server: { port: 5184, strictPort: true },
  build: { target: "es2022", outDir: "dist", emptyOutDir: true },
  worker: { format: "es" },
  test: { include: ["static-engine/test/**/*.test.ts", "src/**/*.test.ts"], environment: "node" },
});
