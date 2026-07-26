import { describe, expect, it, vi } from "vitest";

import type { LocalStorageArea } from "../src/background/token-store";
import { TokenStore } from "../src/background/token-store";

function storage(initial?: string): LocalStorageArea & { remove: ReturnType<typeof vi.fn> } {
  const values: Record<string, unknown> = initial ? { installationToken: initial } : {};
  const remove = vi.fn((key: string) => {
    delete values[key];
    return Promise.resolve();
  });
  return {
    get: vi.fn(() => Promise.resolve(values)),
    set: vi.fn((items: Record<string, unknown>) => {
      Object.assign(values, items);
      return Promise.resolve();
    }),
    remove,
  };
}

describe("TokenStore", () => {
  it("registers once and reuses storage", async () => {
    const area = storage();
    const register = vi.fn(() => Promise.resolve({ token: "new-token" }));
    const store = new TokenStore(area, { register });
    expect(await Promise.all([store.getToken(), store.getToken()])).toEqual([
      "new-token",
      "new-token",
    ]);
    expect(register).toHaveBeenCalledTimes(1);
    expect(await store.getToken()).toBe("new-token");
  });

  it("uses existing token and supports revoked cleanup", async () => {
    const area = storage("old-token");
    const store = new TokenStore(area, { register: vi.fn() });
    expect(await store.getToken()).toBe("old-token");
    await store.clear();
    expect(area.remove).toHaveBeenCalledWith("installationToken");
  });
});
