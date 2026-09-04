import { defineConfig } from "vite";

export default defineConfig({
  server: {
    proxy: {
      "/ask": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
});
