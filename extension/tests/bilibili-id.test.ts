import { describe, expect, it } from "vitest";

import {
  parseBvid,
  parseCid,
  readInitialState,
  resolveCid,
} from "../src/content/bilibili-id";

describe("Bilibili identifiers", () => {
  it("parses canonical and embedded BV links", () => {
    expect(parseBvid("https://www.bilibili.com/video/BV1Q541167Qg?p=2")).toBe(
      "BV1Q541167Qg",
    );
    expect(parseBvid("/video/BV1mK4y1C7Bz")).toBe("BV1mK4y1C7Bz");
    expect(parseBvid("https://example.com/no-video")).toBeNull();
  });

  it("accepts positive safe CIDs", () => {
    expect(parseCid("123")).toBe(123);
    expect(parseCid(1)).toBe(1);
    expect(parseCid(0)).toBeNull();
    expect(parseCid("x")).toBeNull();
  });

  it("resolves the live URL page to its current CID", () => {
    const state = {
      cid: 11,
      videoData: {
        cid: 11,
        pages: [
          { page: 1, cid: 11 },
          { page: 2, cid: 12 },
        ],
      },
    };
    expect(resolveCid("https://www.bilibili.com/video/BV1Q541167Qg?p=2", state)).toBe(
      12,
    );
    expect(resolveCid("https://www.bilibili.com/video/BV1Q541167Qg", state)).toBe(11);
    expect(resolveCid("https://www.bilibili.com/video/BV1Q541167Qg?p=3", state)).toBeNull();
  });

  it("reads serialized initial state from the page DOM without executing it", () => {
    document.head.innerHTML = `<script>window.__INITIAL_STATE__={"cid":11,"videoData":{"title":"brace } in string","pages":[{"page":2,"cid":12}]}};(function(){})()</script>`;
    expect(readInitialState()).toEqual({
      cid: 11,
      videoData: {
        title: "brace } in string",
        pages: [{ page: 2, cid: 12 }],
      },
    });
  });
});
