const LABELS: Record<string, string> = {
  none: "暂无明显 AI 迹象",
  light: "轻度疑似 AI",
  medium: "中度疑似 AI",
  high: "高度疑似 AI",
};

export function labelText(label: string | null, confidence: number): string {
  if (confidence < 0.4 || label === null) return "证据不足";
  return LABELS[label] ?? "证据不足";
}

export function createBadge(text: string): HTMLElement {
  const badge = document.createElement("span");
  badge.className = "bili-ai-badge";
  badge.textContent = text;
  return badge;
}
