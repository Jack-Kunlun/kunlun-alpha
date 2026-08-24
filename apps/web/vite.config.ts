import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const serverProxyTarget = process.env["KUNLUN_SERVER_PROXY_TARGET"] ?? "http://localhost:3002";
const apiProxy = {
  "/api": {
    target: serverProxyTarget,
    changeOrigin: true,
  },
};

export default defineConfig({
  plugins: [tailwindcss(), react()],
  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },
  server: {
    port: 5173,
    open: false,
    proxy: apiProxy,
  },
  preview: {
    host: "0.0.0.0",
    port: 4173,
    proxy: apiProxy,
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
