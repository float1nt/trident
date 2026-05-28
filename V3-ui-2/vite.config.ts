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
      // 认证（backend-service）
      "/api/auth": {
        target: "http://127.0.0.1:8090",
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\/api/, ""),
      },
      // 总览、风险、采集配置（streamtrident trident-api，compose 默认 8090）
      // 采集配置当前前端 Mock，待 trident-api 就绪后取消 Mock 即可走此代理
      "/api": {
        target: "http://127.0.0.1:8090",
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\/api/, ""),
      },
    },
  },
});
