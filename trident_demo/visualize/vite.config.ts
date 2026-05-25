import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { stressDataApiPlugin } from './vite.stressDataPlugin'

export default defineConfig({
  plugins: [react(), stressDataApiPlugin()],
  server: {
    host: '0.0.0.0',
    port: 5184,
    strictPort: true,
    fs: {
      allow: ['..', '../..'],
    },
  },
})
