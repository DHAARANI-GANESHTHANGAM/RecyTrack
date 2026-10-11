/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the API runs on :8000 (uvicorn). Proxying keeps every call
// same-origin, so the backend needs no CORS configuration.
const API = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": API,
      "/health": API,
      "/docs": API,
      "/openapi.json": API,
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/__tests__/setup.ts"],
    css: false,
  },
});
