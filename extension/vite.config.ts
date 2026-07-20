import { crx } from "@crxjs/vite-plugin";
import { defineConfig, loadEnv } from "vite";

import { createManifest } from "./manifest.config";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");

  return {
    plugins: [crx({ manifest: createManifest(env.VITE_API_ORIGIN) })],
    build: {
      outDir: "dist",
      emptyOutDir: true,
      sourcemap: true,
    },
  };
});
