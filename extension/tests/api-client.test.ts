import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClient, ApiError } from "../src/background/api-client";

const tokens = {
  getToken: vi.fn<() => Promise<string>>(),
  clear: vi.fn(() => Promise.resolve()),
};

beforeEach(() => {
  tokens.getToken.mockReset();
  tokens.getToken.mockResolvedValue("token");
  tokens.clear.mockClear();
});

describe("ApiClient", () => {
  it("deduplicates same target and isolates distinct targets", async () => {
    const fetcher = vi.fn((url: string) =>
      Promise.resolve(new Response(JSON.stringify({ bvid: url }), { status: 200 })),
    ) as unknown as typeof fetch;
    const client = new ApiClient("https://api.test", tokens, fetcher);
    const same = await Promise.all([
      client.getAnalysis("BV1Q541167Qg", 1),
      client.getAnalysis("BV1Q541167Qg", 1),
    ]);
    await client.getAnalysis("BV1mK4y1C7Bz", 2);
    expect(same[0]).toEqual(same[1]);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("re-registers once and retries the revoked request", async () => {
    tokens.getToken
      .mockResolvedValueOnce("revoked-token")
      .mockResolvedValueOnce("replacement-token");
    const authorizations: string[] = [];
    let requestCount = 0;
    const fetcher = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      authorizations.push(new Headers(init?.headers).get("Authorization") ?? "");
      requestCount += 1;
      return Promise.resolve(
        requestCount === 1
          ? new Response("revoked", { status: 401 })
          : new Response(JSON.stringify({ ok: true }), { status: 200 }),
      );
    }) as unknown as typeof fetch;
    const client = new ApiClient("https://api.test", tokens, fetcher);
    await expect(client.getAnalysis("BV1Q541167Qg", 1)).resolves.toEqual({ ok: true });
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(tokens.getToken).toHaveBeenCalledTimes(2);
    expect(tokens.clear).toHaveBeenCalledTimes(1);
    expect(authorizations).toEqual([
      "Bearer revoked-token",
      "Bearer replacement-token",
    ]);
  });

  it("surfaces a second unauthorized response", async () => {
    const fetcher = vi.fn(() =>
      Promise.resolve(new Response("revoked", { status: 401 })),
    ) as unknown as typeof fetch;
    const client = new ApiClient("https://api.test", tokens, fetcher);
    await expect(client.getAnalysis("BV1Q541167Qg", 1)).rejects.toBeInstanceOf(
      ApiError,
    );
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(tokens.clear).toHaveBeenCalledTimes(2);
  });
});
