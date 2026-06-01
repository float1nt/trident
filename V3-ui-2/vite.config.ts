import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5175,
    proxy: {
      // 认证与业务 API：streamtrident analysis 测试栈（start-test.sh → TRIDENT_API_HOST_PORT=9090）
      "/api/auth": {
        target: "http://127.0.0.1:9090",
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\/api/, ""),
      },
      "/api": {
        target: "http://127.0.0.1:9090",
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\/api/, ""),
      },
    },
  },
});
