const DEFAULT_API_ORIGIN = "http://localhost:8000";

export function normalizeApiOrigin(value: string | undefined): string {
  const origin = new URL(value ?? DEFAULT_API_ORIGIN);

  if (origin.protocol !== "http:" && origin.protocol !== "https:") {
    throw new Error("VITE_API_ORIGIN must use http or https");
  }

  return origin.origin;
}

export function createManifest(apiOrigin: string | undefined) {
  const normalizedApiOrigin = normalizeApiOrigin(apiOrigin);

  return {
    manifest_version: 3 as const,
    name: "Bilibili AI Video Identification",
    description: "Displays shared AI-content evidence labels on Bilibili videos.",
    version: "0.1.0",
    permissions: ["storage"],
    background: { service_worker: "src/background/service-worker.ts", type: "module" },
    content_scripts: [
      {
        matches: ["https://www.bilibili.com/*"],
        js: ["src/content/entry.ts"],
        css: ["src/ui/styles.css"],
      },
    ],
    host_permissions: [
      "https://www.bilibili.com/*",
      `${normalizedApiOrigin}/*`,
    ],
  };
}
