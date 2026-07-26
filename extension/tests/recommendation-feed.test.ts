import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  RecommendationCardTracker,
  RecommendationFeed,
} from "../src/content/recommendation-feed";

function card(bvid: string): HTMLElement {
  const element = document.createElement("article");
  element.className = "bili-video-card";
  element.innerHTML = `<a href="https://www.bilibili.com/video/${bvid}"></a>`;
  return element;
}

beforeEach(() => {
  document.body.innerHTML = "";
  vi.useFakeTimers();
});

describe("RecommendationFeed", () => {
  it("deduplicates BVs, splits 31 identifiers and skips absent results", async () => {
    const batchLookup = vi.fn((bvids: string[]) =>
      Promise.resolve({
        items: bvids
          .slice(0, 1)
          .map((bvid) => ({ bvid, cid: 1, label: "high", confidence: 0.9 })),
      }),
    );
    const feed = new RecommendationFeed({ batchLookup });
    const alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
    const cards = Array.from({ length: 31 }, (_, index) =>
      card(`BV1Q541167${alphabet[0]}${alphabet[index]}`),
    );
    for (const element of cards) feed.observe(element);
    feed.observe(cards[0]!);
    await feed.flush();
    expect(batchLookup).toHaveBeenCalledTimes(2);
    expect(batchLookup.mock.calls[0]?.[0]).toHaveLength(30);
    expect(cards[0]?.querySelectorAll(".bili-ai-badge")).toHaveLength(1);
    expect(cards[1]?.querySelector(".bili-ai-badge")).toBeNull();
  });

  it("queries only cards that enter the viewport", async () => {
    const batchLookup = vi.fn((bvids: string[]) =>
      Promise.resolve({
        items: bvids.map((bvid) => ({
          bvid,
          cid: 1,
          label: "high",
          confidence: 0.9,
        })),
      }),
    );
    const feed = new RecommendationFeed({ batchLookup });
    const first = card("BV1Q541167Qg");
    const second = card("BV1mK4y1C7Bz");
    document.body.append(first, second);
    let callback: IntersectionObserverCallback | undefined;
    const observed: Element[] = [];
    const tracker = new RecommendationCardTracker(feed, document, (handler) => {
      callback = handler;
      return {
        observe: (target) => observed.push(target),
        disconnect: vi.fn(),
      };
    });
    tracker.start();
    expect(observed).toEqual([first, second]);
    await feed.flush();
    expect(batchLookup).not.toHaveBeenCalled();

    callback?.(
      [
        { target: first, isIntersecting: true } as unknown as IntersectionObserverEntry,
        { target: second, isIntersecting: false } as unknown as IntersectionObserverEntry,
      ],
      {} as IntersectionObserver,
    );
    await feed.flush();
    expect(batchLookup).toHaveBeenCalledWith(["BV1Q541167Qg"]);
    expect(first.querySelector(".bili-ai-badge")).not.toBeNull();
    expect(second.querySelector(".bili-ai-badge")).toBeNull();

    const link = first.querySelector("a");
    if (!link) throw new Error("fixture link missing");
    link.href = "https://www.bilibili.com/video/BV1mK4y1C7Bz";
    await Promise.resolve();
    await feed.flush();
    expect(batchLookup).toHaveBeenLastCalledWith(["BV1mK4y1C7Bz"]);
    expect(first.dataset.biliAiBvid).toBe("BV1mK4y1C7Bz");
  });

  it("removes stale badges when a card is reused", async () => {
    const batchLookup = vi.fn((bvids: string[]) =>
      Promise.resolve({
        items: bvids.map((bvid) => ({
          bvid,
          cid: 1,
          label: "high",
          confidence: 0.9,
        })),
      }),
    );
    const feed = new RecommendationFeed({ batchLookup });
    const element = card("BV1Q541167Qg");
    feed.observe(element);
    await feed.flush();
    expect(element.querySelector(".bili-ai-badge")).not.toBeNull();

    const link = element.querySelector("a");
    if (!link) throw new Error("fixture link missing");
    link.href = "https://www.bilibili.com/video/BV1mK4y1C7Bz";
    feed.observe(element);
    expect(element.querySelector(".bili-ai-badge")).toBeNull();
    await feed.flush();
    expect(batchLookup).toHaveBeenLastCalledWith(["BV1mK4y1C7Bz"]);
    expect(element.dataset.biliAiBvid).toBe("BV1mK4y1C7Bz");
  });
});
