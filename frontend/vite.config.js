import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8000" } },
  build: {
    rollupOptions: {
      // 秘書画面(index.html)と、リール制作スタジオ(reel.html)
      input: { main: resolve(__dirname, "index.html"), reel: resolve(__dirname, "reel.html") },
    },
  },
});
