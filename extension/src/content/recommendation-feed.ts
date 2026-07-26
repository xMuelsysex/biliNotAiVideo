import { createBadge, labelText } from "../ui/badge";
import { parseBvid } from "./bilibili-id";

export type BatchItem = {
  bvid: string;
  cid: number;
  label: string | null;
  confidence: number;
};

export interface FeedApi {
  batchLookup(bvids: string[]): Promise<{ items: BatchItem[] }>;
}

export class RecommendationFeed {
  private readonly pending = new Map<string, Set<HTMLElement>>();
  private readonly cache = new Map<string, BatchItem | null>();
  private timer: ReturnType<typeof setTimeout> | undefined;

  constructor(private readonly api: FeedApi) {}

  observe(card: HTMLElement): void {
    const link = card.querySelector<HTMLAnchorElement>("a[href]");
    const bvid = link ? parseBvid(link.href) : null;
    const previous = card.dataset.biliAiBvid;
    if (!bvid) {
      this.resetCard(card, previous);
      return;
    }
    if (previous === bvid) return;
    this.resetCard(card, previous);
    card.dataset.biliAiBvid = bvid;
    const cached = this.cache.get(bvid);
    if (cached !== undefined) {
      if (cached) this.render(card, cached);
      return;
    }
    const cards = this.pending.get(bvid) ?? new Set<HTMLElement>();
    cards.add(card);
    this.pending.set(bvid, cards);
    clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.flush(), 400);
  }

  async flush(): Promise<void> {
    const bvids = [...this.pending.keys()];
    for (let offset = 0; offset < bvids.length; offset += 30) {
      const batch = bvids.slice(offset, offset + 30);
      const response = await this.api.batchLookup(batch);
      const found = new Map(response.items.map((item) => [item.bvid, item]));
      for (const bvid of batch) {
        const item = found.get(bvid) ?? null;
        this.cache.set(bvid, item);
        for (const card of this.pending.get(bvid) ?? []) {
          if (item) this.render(card, item);
        }
        this.pending.delete(bvid);
      }
    }
  }

  private resetCard(card: HTMLElement, previous: string | undefined): void {
    card.querySelector(".bili-ai-badge")?.remove();
    if (previous) {
      this.pending.get(previous)?.delete(card);
      if (this.pending.get(previous)?.size === 0) this.pending.delete(previous);
    }
    delete card.dataset.biliAiBvid;
  }

  private render(card: HTMLElement, item: BatchItem): void {
    card.querySelector(".bili-ai-badge")?.remove();
    card.append(createBadge(labelText(item.label, item.confidence)));
  }
}

interface IntersectionObserverLike {
  observe(target: Element): void;
  disconnect(): void;
}

type IntersectionFactory = (
  callback: IntersectionObserverCallback,
) => IntersectionObserverLike;

export class RecommendationCardTracker {
  private readonly observed = new WeakSet<Element>();
  private readonly visible = new Set<HTMLElement>();
  private intersection: IntersectionObserverLike | undefined;
  private mutation: MutationObserver | undefined;

  constructor(
    private readonly feed: RecommendationFeed,
    private readonly root: Document = document,
    private readonly createIntersection: IntersectionFactory = (callback) =>
      new IntersectionObserver(callback),
  ) {}

  start(): () => void {
    this.intersection = this.createIntersection((entries) => {
      for (const entry of entries) {
        if (!(entry.target instanceof HTMLElement)) continue;
        if (entry.isIntersecting) {
          this.visible.add(entry.target);
          this.feed.observe(entry.target);
        } else {
          this.visible.delete(entry.target);
        }
      }
    });
    const scan = () => {
      for (const card of this.root.querySelectorAll<HTMLElement>(
        ".bili-video-card, [data-video-card]",
      )) {
        if (this.observed.has(card)) continue;
        this.observed.add(card);
        this.intersection?.observe(card);
      }
    };
    const refresh = () => {
      scan();
      for (const card of this.visible) {
        if (card.isConnected) this.feed.observe(card);
        else this.visible.delete(card);
      }
    };
    this.mutation = new MutationObserver(refresh);
    this.mutation.observe(this.root.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["href"],
    });
    scan();
    return () => {
      this.mutation?.disconnect();
      this.intersection?.disconnect();
    };
  }
}
