import { beforeEach, describe, expect, it, vi } from "vitest";

import { RouteObserver } from "../src/content/route-observer";

beforeEach(() => {
  document.body.innerHTML = "<main></main>";
});

describe("RouteObserver", () => {
  it("emits only when target changes", async () => {
    let cid = 1;
    const emit = vi.fn();
    const stop = new RouteObserver(
      () => ({ bvid: "BV1Q541167Qg", cid }),
      emit,
    ).start();
    history.pushState({}, "", "/video/BV1Q541167Qg");
    await Promise.resolve();
    history.replaceState({}, "", "/video/BV1Q541167Qg?p=1");
    await Promise.resolve();
    cid = 2;
    history.pushState({}, "", "/video/BV1Q541167Qg?p=2");
    await Promise.resolve();
    expect(emit).toHaveBeenCalledTimes(2);
    stop();
  });
});
