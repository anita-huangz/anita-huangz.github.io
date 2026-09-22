import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    // In development the client is on 5173 and the BFF on 8080. Proxying
    // means the code never needs a base URL, and production -- where both are
    // the same origin behind Express -- takes the identical path.
    proxy: { "/api": { target: "http://127.0.0.1:8080", changeOrigin: true } },
  },
  build: { outDir: "dist", sourcemap: true },
});
