import type { AnalysisResponse } from "../background/api-client";
import { labelText } from "./badge";

export function renderDetailPanel(response: AnalysisResponse): HTMLElement {
  const panel = document.createElement("section");
  panel.className = "bili-ai-detail";
  panel.dataset.bvid = response.bvid;
  panel.dataset.attemptStatus = response.attempt_status;
  panel.dataset.resultStatus = response.result_status;
  const result = response.result;
  const title = result
    ? labelText(result.label, result.confidence)
    : response.attempt_status === "failed"
      ? "分析失败"
      : response.attempt_status === "none"
        ? "等待分析"
        : "分析中";
  panel.innerHTML = `<strong>${title}</strong>`;
  if (response.declaration?.state === "declared_ai") {
    panel.append(document.createTextNode(" · 已声明 AI"));
  }
  if (result) {
    panel.append(document.createTextNode(` · ${Math.round(result.confidence * 100)}% 置信度`));
  }
  if (response.analyzed_at) {
    panel.append(document.createTextNode(` · 分析于 ${response.analyzed_at}`));
  }
  if (response.rule_version) {
    panel.append(document.createTextNode(` · 规则 ${response.rule_version}`));
  }
  if (response.result_status === "stale") {
    panel.append(document.createTextNode(" · 结果待刷新"));
  }
  return panel;
}
