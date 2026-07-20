import { describe, expect, it } from "vitest";

import { createManifest, normalizeApiOrigin } from "../manifest.config";

describe("extension manifest", () => {
  it("requests only storage permission", () => {
    const manifest = createManifest("https://api.example.test");

    expect(manifest.manifest_version).toBe(3);
    expect(manifest.permissions).toEqual(["storage"]);
  });

  it("limits host access to Bilibili and the configured API origin", () => {
    const manifest = createManifest("https://api.example.test/path");

    expect(manifest.host_permissions).toEqual([
      "https://www.bilibili.com/*",
      "https://api.example.test/*",
    ]);
  });

  it("uses the local API origin by default", () => {
    expect(normalizeApiOrigin(undefined)).toBe("http://localhost:8000");
  });

  it("rejects non-http API origins", () => {
    expect(() => normalizeApiOrigin("file:///tmp/api")).toThrow(
      "VITE_API_ORIGIN must use http or https",
    );
  });
});
