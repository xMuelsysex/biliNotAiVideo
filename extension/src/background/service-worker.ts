import { ApiClient, ApiError, type RuntimeResponse } from "./api-client";
import { TokenStore } from "./token-store";

type Message =
  | { type: "getAnalysis" | "createAnalysis"; bvid: string; cid: number }
  | { type: "batchLookup"; bvids: string[] };

function parseMessage(value: unknown): Message {
  if (typeof value !== "object" || value === null || !("type" in value)) {
    throw new Error("invalid message");
  }
  const message = value as Record<string, unknown>;
  if (
    (message.type === "getAnalysis" || message.type === "createAnalysis") &&
    typeof message.bvid === "string" &&
    typeof message.cid === "number"
  ) {
    return { type: message.type, bvid: message.bvid, cid: message.cid };
  }
  if (
    message.type === "batchLookup" &&
    Array.isArray(message.bvids) &&
    message.bvids.every((item) => typeof item === "string")
  ) {
    return { type: message.type, bvids: message.bvids.filter((item) => typeof item === "string") };
  }
  throw new Error("invalid message");
}

const apiOrigin = import.meta.env.VITE_API_ORIGIN ?? "http://localhost:8000";
const storage = chrome.storage.local;
const registration = {
  register(): Promise<{ token: string }> {
    return fetch(`${apiOrigin}/api/v1/installations`, { method: "POST" }).then(
      async (response) => {
        if (!response.ok) throw new Error(`registration failed: ${response.status}`);
        return (await response.json()) as { token: string };
      },
    );
  },
};
const api = new ApiClient(apiOrigin, new TokenStore(storage, registration));

chrome.runtime.onMessage.addListener((rawMessage, _sender, sendResponse) => {
  let request: Promise<unknown>;
  try {
    const message = parseMessage(rawMessage);
    switch (message.type) {
      case "getAnalysis":
        request = api.getAnalysis(message.bvid, message.cid);
        break;
      case "createAnalysis":
        request = api.createAnalysis(message.bvid, message.cid);
        break;
      case "batchLookup":
        request = api.batchLookup(message.bvids);
        break;
    }
  } catch (error) {
    const response: RuntimeResponse<never> = {
      ok: false,
      error: { message: error instanceof Error ? error.message : "invalid message" },
    };
    sendResponse(response);
    return false;
  }
  request.then(
    (data) => sendResponse({ ok: true, data } satisfies RuntimeResponse<unknown>),
    (error: unknown) =>
      sendResponse({
        ok: false,
        error: {
          message: error instanceof Error ? error.message : "request failed",
          ...(error instanceof ApiError ? { status: error.status } : {}),
        },
      } satisfies RuntimeResponse<never>),
  );
  return true;
});
