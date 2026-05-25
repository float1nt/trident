import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { runDataApiPlugin } from './vite.runDataPlugin'
import { liveStreamApiPlugin } from './vite.liveStreamPlugin'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), runDataApiPlugin(), liveStreamApiPlugin()],
  server: {
    host: '0.0.0.0',
    port: 5174,
    strictPort: true,
    fs: {
      // Allow reading run outputs from project root.
      allow: ['..'],
    },
  },
})
