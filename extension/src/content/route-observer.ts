export type Target = { bvid: string; cid: number };

export class RouteObserver {
  private lastKey = "";
  private mutationObserver: MutationObserver | undefined;

  constructor(
    private readonly resolve: () => Target | null,
    private readonly emit: (target: Target) => void,
    private readonly windowObject: Window = window,
  ) {}

  start(): () => void {
    const check = () => {
      const target = this.resolve();
      if (!target) return;
      const key = `${target.bvid}:${target.cid}`;
      if (key === this.lastKey) return;
      this.lastKey = key;
      this.emit(target);
    };
    const history = this.windowObject.history;
    const push = history.pushState.bind(history);
    const replace = history.replaceState.bind(history);
    history.pushState = (...args) => {
      push(...args);
      queueMicrotask(check);
    };
    history.replaceState = (...args) => {
      replace(...args);
      queueMicrotask(check);
    };
    this.windowObject.addEventListener("popstate", check);
    this.mutationObserver = new MutationObserver(check);
    this.mutationObserver.observe(this.windowObject.document.body, {
      childList: true,
      subtree: true,
    });
    check();
    return () => {
      history.pushState = push;
      history.replaceState = replace;
      this.windowObject.removeEventListener("popstate", check);
      this.mutationObserver?.disconnect();
    };
  }
}
