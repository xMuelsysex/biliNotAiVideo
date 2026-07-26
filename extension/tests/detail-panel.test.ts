import { describe, expect, it } from "vitest";

import { renderDetailPanel } from "../src/ui/detail-panel";

const base = {
  bvid: "BV1Q541167Qg",
  cid: 1,
  result_status: "current" as const,
  attempt_status: "none" as const,
  declaration: { state: "declared_ai", stale: false },
  result: { score: 80, label: "high", confidence: 0.9, stale: false },
  evidence: [],
  analyzed_at: "2026-07-20T12:00:00Z",
  rule_version: "v1",
  retry_after: null,
  error_code: null,
};

describe("detail panel", () => {
  it("renders declaration, label, time and rule version", () => {
    expect(renderDetailPanel(base).textContent).toContain("高度疑似 AI");
    expect(renderDetailPanel(base).textContent).toContain("已声明 AI");
    expect(renderDetailPanel(base).textContent).toContain("2026-07-20");
    expect(renderDetailPanel(base).textContent).toContain("v1");
  });

  it("renders insufficient evidence below confidence threshold", () => {
    const panel = renderDetailPanel({
      ...base,
      result: { ...base.result, confidence: 0.39 },
    });
    expect(panel.textContent).toContain("证据不足");
  });
});
