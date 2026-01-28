import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'


// code used from confid page on Vite -> https://vite.dev/config/
// if needed, just do /api/block instead of above link
export default defineConfig({
    plugins: [react()],
    server: {
        proxy: {
            '/api': {
                target: 'http://127.0.0.1:5000',
                changeOrigin: true,
                secure: false,
            },
        },
    },
})
