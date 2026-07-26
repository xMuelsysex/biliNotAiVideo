import {
  ApiError,
  type AnalysisResponse,
  type RuntimeResponse,
} from "../background/api-client";
import { parseBvid, readInitialState, resolveCid } from "./bilibili-id";
import {
  RecommendationCardTracker,
  RecommendationFeed,
  type BatchItem,
} from "./recommendation-feed";
import { RouteObserver, type Target } from "./route-observer";
import { VideoPageController } from "./video-page";

const send = async <T>(message: unknown): Promise<T> => {
  const response = await chrome.runtime.sendMessage<RuntimeResponse<T>>(message);
  if (!response.ok) {
    throw new ApiError(response.error.status ?? 0, response.error.message);
  }
  return response.data;
};
const api = {
  getAnalysis: (bvid: string, cid: number) =>
    send<AnalysisResponse>({ type: "getAnalysis", bvid, cid }),
  createAnalysis: (bvid: string, cid: number) =>
    send<AnalysisResponse>({ type: "createAnalysis", bvid, cid }),
  batchLookup: (bvids: string[]) =>
    send<{ items: BatchItem[] }>({ type: "batchLookup", bvids }),
};

const videoPage = new VideoPageController(api, () =>
  document.querySelector<HTMLElement>("h1, .video-title, [data-title]")
);
let currentTarget: Target | null = null;
const showTarget = (target: Target) => {
  currentTarget = target;
  void videoPage.show(target).catch((error: unknown) => {
    console.error("Bilibili AI analysis failed", error);
  });
};
new RouteObserver(
  () => {
    const bvid = parseBvid(location.href);
    const cid = resolveCid(location.href, readInitialState());
    return bvid && cid ? { bvid, cid } : null;
  },
  showTarget,
).start();
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && currentTarget) showTarget(currentTarget);
});

const feed = new RecommendationFeed(api);
new RecommendationCardTracker(feed).start();
