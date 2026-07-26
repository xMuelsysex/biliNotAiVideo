const BV_PATTERN = /BV[1-9A-HJ-NP-Za-km-z]{10}/;

export function parseBvid(value: string): string | null {
  try {
    const url = new URL(value, "https://www.bilibili.com");
    return url.pathname.match(BV_PATTERN)?.[0] ?? null;
  } catch {
    return value.match(BV_PATTERN)?.[0] ?? null;
  }
}

export function parseCid(value: unknown): number | null {
  const number = typeof value === "string" && value.trim() ? Number(value) : value;
  return typeof number === "number" && Number.isSafeInteger(number) && number > 0
    ? number
    : null;
}

type PageState = {
  cid?: unknown;
  page?: unknown;
};

type InitialState = {
  cid?: unknown;
  videoData?: {
    cid?: unknown;
    pages?: PageState[];
  };
};

export function readInitialState(root: Document = document): unknown {
  const marker = "window.__INITIAL_STATE__=";
  for (const script of root.scripts) {
    const text = script.textContent ?? "";
    const markerIndex = text.indexOf(marker);
    if (markerIndex < 0) continue;
    const start = text.indexOf("{", markerIndex + marker.length);
    if (start < 0) continue;
    let depth = 0;
    let inString = false;
    let escaped = false;
    for (let index = start; index < text.length; index += 1) {
      const character = text[index];
      if (inString) {
        if (escaped) escaped = false;
        else if (character === "\\") escaped = true;
        else if (character === '"') inString = false;
        continue;
      }
      if (character === '"') {
        inString = true;
        continue;
      }
      if (character === "{" || character === "[") depth += 1;
      if (character === "}" || character === "]") depth -= 1;
      if (depth === 0) {
        try {
          return JSON.parse(text.slice(start, index + 1)) as unknown;
        } catch {
          break;
        }
      }
    }
  }
  return null;
}

export function resolveCid(href: string, value: unknown): number | null {
  const state =
    typeof value === "object" && value !== null ? (value as InitialState) : undefined;
  const page = parseCid(new URL(href, "https://www.bilibili.com").searchParams.get("p"));
  if (page !== null) {
    const matched = state?.videoData?.pages?.find(
      (item) => parseCid(item.page) === page,
    );
    return parseCid(matched?.cid);
  }
  return parseCid(state?.videoData?.cid) ?? parseCid(state?.cid);
}
