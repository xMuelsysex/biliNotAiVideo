import type { AnalysisResponse } from "../background/api-client";
import { renderDetailPanel } from "../ui/detail-panel";
import type { Target } from "./route-observer";

export interface VideoApi {
  getAnalysis(bvid: string, cid: number): Promise<AnalysisResponse>;
  createAnalysis(bvid: string, cid: number): Promise<AnalysisResponse>;
}

const MAX_POLL_MS = 900_000;
const POLL_DELAYS = [
  2_000,
  4_000,
  8_000,
  ...Array.from({ length: 59 }, () => 15_000),
];

export class VideoPageController {
  private generation = 0;

  constructor(
    private readonly api: VideoApi,
    private readonly title: () => HTMLElement | null,
    private readonly sleep: (milliseconds: number) => Promise<void> = (milliseconds) =>
      new Promise((resolve) => setTimeout(resolve, milliseconds)),
    private readonly now: () => number = Date.now,
  ) {}

  async show(target: Target): Promise<void> {
    const generation = ++this.generation;
    await this.sleep(2_000);
    if (generation !== this.generation || document.hidden) return;
    let response = await this.api.getAnalysis(target.bvid, target.cid);
    this.render(response);
    if (response.result_status !== "current" && response.attempt_status === "none") {
      response = await this.api.createAnalysis(target.bvid, target.cid);
      this.render(response);
    }
    const pollDeadline = this.now() + MAX_POLL_MS;
    for (const delay of POLL_DELAYS) {
      if (response.result_status === "current" || response.attempt_status === "failed") return;
      const remaining = pollDeadline - this.now();
      if (remaining <= 0) return;
      await this.sleep(Math.min(delay + Math.floor(Math.random() * 250), remaining));
      if (this.now() >= pollDeadline) return;
      if (generation !== this.generation || document.hidden) return;
      response = await this.api.getAnalysis(target.bvid, target.cid);
      this.render(response);
    }
  }

  cancel(): void {
    this.generation += 1;
  }

  private render(response: AnalysisResponse): void {
    const container = this.title();
    if (!container) return;
    container.querySelector(".bili-ai-detail")?.remove();
    container.append(renderDetailPanel(response));
  }
}
