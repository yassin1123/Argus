import path from "node:path";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Vitest is wired up here for the first time (Phase 2 / Week 5 / Day 2 ).
// Existing components don't have tests — this config is the foundation
// future component tests can build on.
export default defineConfig({
  plugins: [react()],
  esbuild: {
    // Use the automatic React 17+ JSX runtime so test files don't need
    // to `import React`. tsconfig has `jsx: preserve` for Next.js to
    // handle, but vitest transforms with esbuild and needs an explicit
    // hint here.
    jsx: "automatic",
  },
  resolve: {
    alias: {
      // Match the "@/..." alias the rest of the frontend uses (tsconfig.json
      // baseUrl is the frontend root). Without this, vitest can't resolve
      // imports like `@/lib/api`.
      "@": path.resolve(__dirname, "."),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    css: false,
    // Don't accidentally pull in .next, node_modules.
    include: ["**/*.test.{ts,tsx}"],
    exclude: ["node_modules", ".next", "dist"],
  },
});
