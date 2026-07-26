import { beforeEach, describe, expect, it, vi } from "vitest";

import { VideoPageController } from "../src/content/video-page";

const response = (attempt_status: "none" | "queued" | "failed", current = false) => ({
  bvid: "BV1Q541167Qg",
  cid: 1,
  result_status: current ? ("current" as const) : ("missing" as const),
  attempt_status,
  declaration: null,
  result: current ? { score: 50, label: "light", confidence: 0.8, stale: false } : null,
  evidence: [],
  analyzed_at: current ? "2026-07-20T00:00:00Z" : null,
  rule_version: current ? "v1" : null,
  retry_after: null,
  error_code: null,
});

beforeEach(() => {
  document.body.innerHTML = "<h1></h1>";
});

describe("VideoPageController", () => {
  it("creates missing analysis once and stops after completion", async () => {
    const getAnalysis = vi
      .fn()
      .mockResolvedValueOnce(response("none"))
      .mockResolvedValueOnce(response("none", true));
    const createAnalysis = vi.fn(() => Promise.resolve(response("queued")));
    const controller = new VideoPageController(
      { getAnalysis, createAnalysis },
      () => document.querySelector("h1"),
      () => Promise.resolve(),
    );
    await controller.show({ bvid: "BV1Q541167Qg", cid: 1 });
    expect(createAnalysis).toHaveBeenCalledTimes(1);
    expect(getAnalysis).toHaveBeenCalledTimes(2);
    expect(document.querySelectorAll(".bili-ai-detail")).toHaveLength(1);
  });

  it("stops on terminal failure", async () => {
    const getAnalysis = vi.fn(() => Promise.resolve(response("failed")));
    const createAnalysis = vi.fn();
    await new VideoPageController(
      { getAnalysis, createAnalysis },
      () => document.querySelector("h1"),
      () => Promise.resolve(),
    ).show({ bvid: "BV1Q541167Qg", cid: 1 });
    expect(createAnalysis).not.toHaveBeenCalled();
    expect(getAnalysis).toHaveBeenCalledTimes(1);
  });

  it("bounds long-running polling to the worker timeout window", async () => {
    const getAnalysis = vi.fn(() => Promise.resolve(response("queued")));
    const createAnalysis = vi.fn();
    await new VideoPageController(
      { getAnalysis, createAnalysis },
      () => document.querySelector("h1"),
      () => Promise.resolve(),
    ).show({ bvid: "BV1Q541167Qg", cid: 1 });
    expect(createAnalysis).not.toHaveBeenCalled();
    expect(getAnalysis).toHaveBeenCalledTimes(63);
  });

  it("stops before querying after the absolute deadline", async () => {
    let now = 0;
    let sleeps = 0;
    const getAnalysis = vi.fn(() => Promise.resolve(response("queued")));
    const createAnalysis = vi.fn();
    await new VideoPageController(
      { getAnalysis, createAnalysis },
      () => document.querySelector("h1"),
      () => {
        sleeps += 1;
        if (sleeps > 1) now = 900_000;
        return Promise.resolve();
      },
      () => now,
    ).show({ bvid: "BV1Q541167Qg", cid: 1 });
    expect(getAnalysis).toHaveBeenCalledTimes(1);
  });
});
