import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// Django serves the API, provider callbacks, pay pages and OAuth. The proxy
// keeps the browser's Host header (acme.localhost) so tenancy works in dev.
const backend = 'http://127.0.0.1:8010'
const proxied = ['/api', '/p/', '/cb/', '/oauth/', '/admin', '/static']

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    port: 5174,
    strictPort: true,
    allowedHosts: ['.localhost'],
    // lets widget/dev/harness.html load the widget source in dev
    fs: { allow: ['..'] },
    proxy: Object.fromEntries(proxied.map((p) => [p, { target: backend, changeOrigin: false }])),
  },
})
