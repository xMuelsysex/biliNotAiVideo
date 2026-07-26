export type AnalysisResponse = {
  bvid: string;
  cid: number;
  result_status: "missing" | "current" | "stale";
  attempt_status: "none" | "queued" | "fetching" | "analyzing" | "failed";
  declaration: { state: string; stale: boolean; source?: string | null } | null;
  result: { score: number; label: string | null; confidence: number; stale: boolean } | null;
  evidence: Array<Record<string, unknown>>;
  analyzed_at: string | null;
  rule_version: string | null;
  retry_after: string | null;
  error_code: string | null;
};

export type RuntimeResponse<T> =
  | { ok: true; data: T }
  | { ok: false; error: { message: string; status?: number } };

export interface TokenProvider {
  getToken(): Promise<string>;
  clear(): Promise<void>;
}

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

export class ApiClient {
  private readonly inFlight = new Map<string, Promise<unknown>>();

  constructor(
    private readonly origin: string,
    private readonly tokens: TokenProvider,
    private readonly fetcher: typeof fetch = globalThis.fetch.bind(globalThis),
  ) {}

  getAnalysis(bvid: string, cid: number): Promise<AnalysisResponse> {
    return this.request("GET", `/api/v1/analyses/${bvid}?cid=${cid}`);
  }

  createAnalysis(bvid: string, cid: number): Promise<AnalysisResponse> {
    return this.request("POST", "/api/v1/analyses", { bvid, cid });
  }

  batchLookup(bvids: string[]): Promise<{ items: AnalysisResponse[] }> {
    return this.request("POST", "/api/v1/analyses/batch", { bvids });
  }

  private request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const key = `${method}:${path}:${body ? JSON.stringify(body) : ""}`;
    const existing = this.inFlight.get(key);
    if (existing) return existing as Promise<T>;
    const request = this.execute<T>(method, path, body).finally(() => {
      this.inFlight.delete(key);
    });
    this.inFlight.set(key, request);
    return request;
  }

  private async execute<T>(method: string, path: string, body?: unknown): Promise<T> {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const token = await this.tokens.getToken();
      const response = await this.fetcher(`${this.origin}${path}`, {
        method,
        headers: {
          Authorization: `Bearer ${token}`,
          ...(body ? { "Content-Type": "application/json" } : {}),
        },
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
      if (response.status === 401) {
        await this.tokens.clear();
        if (attempt === 0) continue;
        throw new ApiError(401, "installation token revoked");
      }
      if (!response.ok) throw new ApiError(response.status, await response.text());
      return (await response.json()) as T;
    }
    throw new Error("unreachable");
  }
}
