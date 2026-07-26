import { expect, test, chromium, type BrowserContext, type Route } from "@playwright/test";
import { resolve } from "node:path";

const extensionRoot = resolve(import.meta.dirname, "../..");

const missing = {
  bvid: "BV1Q541167Qg",
  cid: 1,
  result_status: "missing",
  attempt_status: "none",
  declaration: null,
  result: null,
  evidence: [],
  analyzed_at: null,
  rule_version: null,
  retry_after: null,
  error_code: null,
};
const queued = { ...missing, attempt_status: "queued" };
const analyzing = { ...missing, attempt_status: "analyzing" };
const completed = {
  ...missing,
  result_status: "current",
  attempt_status: "none",
  declaration: { state: "declared_ai", stale: false, source: "description" },
  result: { score: 88, label: "high", confidence: 0.91, stale: false },
  evidence: [{ description: "visible AI artifact" }],
  analyzed_at: "2026-07-20T12:00:00Z",
  rule_version: "v1",
};

async function launchExtension(): Promise<BrowserContext> {
  return chromium.launchPersistentContext("", {
    channel: "chromium",
    headless: true,
    args: [
      `--disable-extensions-except=${extensionRoot}/dist`,
      `--load-extension=${extensionRoot}/dist`,
    ],
  });
}

async function fulfillJson(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function extensionWorker(context: BrowserContext) {
  return context.serviceWorkers()[0] ?? context.waitForEvent("serviceworker");
}

test("loaded MV3 extension moves detail page through all states", async () => {
  const context = await launchExtension();
  try {
    const responses = [missing, analyzing, completed];
    let getIndex = 0;
    await context.route("http://localhost:8000/**", async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (path === "/api/v1/installations") {
        await fulfillJson(route, { token: "fixture-token" }, 201);
        return;
      }
      if (path === "/api/v1/analyses" && request.method() === "POST") {
        await fulfillJson(route, queued, 202);
        return;
      }
      if (path === "/api/v1/analyses/BV1Q541167Qg") {
        await fulfillJson(route, responses[Math.min(getIndex++, responses.length - 1)]);
        return;
      }
      await fulfillJson(route, { detail: "unexpected request" }, 500);
    });
    await context.route("https://www.bilibili.com/video/BV1Q541167Qg", (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/html",
        body: `<script>window.__INITIAL_STATE__={"cid":1,"videoData":{"cid":1,"pages":[{"page":1,"cid":1}]}}</script><main><h1>Fixture video</h1></main>`,
      }),
    );
    const page = context.pages()[0] ?? (await context.newPage());
    await page.goto("https://www.bilibili.com/video/BV1Q541167Qg");

    const detail = page.locator(".bili-ai-detail");
    await expect(detail).toHaveAttribute("data-attempt-status", "queued", {
      timeout: 8_000,
    });
    await expect(detail).toHaveAttribute("data-attempt-status", "analyzing", {
      timeout: 8_000,
    });
    await expect(detail).toContainText("高度疑似 AI", { timeout: 15_000 });
    await expect(detail).toHaveAttribute("data-result-status", "current");
    await expect(detail).toContainText("已声明 AI");
    await expect(detail).toContainText("规则 v1");

    const worker = await extensionWorker(context);
    expect(worker.url()).toMatch(/^chrome-extension:\/\//);
    const storedToken = await worker.evaluate(async () => {
      const value = await chrome.storage.local.get("installationToken");
      return value.installationToken;
    });
    expect(storedToken).toBe("fixture-token");
  } finally {
    await context.close();
  }
});

test("loaded MV3 extension batches only visible feed cards", async () => {
  const context = await launchExtension();
  try {
    const requests: string[][] = [];
    await context.route("http://localhost:8000/**", async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (path === "/api/v1/installations") {
        await fulfillJson(route, { token: "fixture-token" }, 201);
        return;
      }
      if (path === "/api/v1/analyses/batch") {
        const payload = request.postDataJSON() as { bvids: string[] };
        requests.push(payload.bvids);
        await fulfillJson(route, {
          items: [
            {
              bvid: "BV1Q541167Qg",
              cid: 1,
              score: 88,
              label: "high",
              confidence: 0.91,
              analyzed_at: "2026-07-20T12:00:00Z",
              rule_version: "v1",
            },
          ],
        });
        return;
      }
      await fulfillJson(route, { detail: "unexpected request" }, 500);
    });
    await context.route("https://www.bilibili.com/", (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/html",
        body: `<main>
          <article class="bili-video-card" data-video-card>
            <a href="https://www.bilibili.com/video/BV1Q541167Qg">cached</a>
          </article>
          <article class="bili-video-card" data-video-card style="display:none">
            <a href="https://www.bilibili.com/video/BV1mK4y1C7Bz">hidden</a>
          </article>
        </main>`,
      }),
    );
    const page = context.pages()[0] ?? (await context.newPage());
    await page.goto("https://www.bilibili.com/");

    const cards = page.locator(".bili-video-card");
    await expect(cards.nth(0).locator(".bili-ai-badge")).toHaveText("高度疑似 AI", {
      timeout: 8_000,
    });
    await expect(cards.nth(1).locator(".bili-ai-badge")).toHaveCount(0);
    expect(requests).toEqual([["BV1Q541167Qg"]]);

    await cards.nth(0).locator("a").evaluate((link) => {
      link.setAttribute("href", "https://www.bilibili.com/video/BV1mK4y1C7Bz");
    });
    await expect.poll(() => requests).toEqual([
      ["BV1Q541167Qg"],
      ["BV1mK4y1C7Bz"],
    ]);
    await expect(cards.nth(0).locator(".bili-ai-badge")).toHaveCount(0);
    expect(await extensionWorker(context)).toBeDefined();
  } finally {
    await context.close();
  }
});
