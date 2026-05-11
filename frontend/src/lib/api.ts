import type { Chat, ChatDetail, Message, ModelInfo } from "./types";

const BASE = "/api";

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  listModels: () => jsonFetch<ModelInfo[]>("/models"),
  listChats: () => jsonFetch<Chat[]>("/chats"),
  getChat: (id: string) => jsonFetch<ChatDetail>(`/chats/${id}`),
  createChat: (data: { model: string; title?: string; system_prompt?: string | null }) =>
    jsonFetch<Chat>("/chats", { method: "POST", body: JSON.stringify(data) }),
  updateChat: (
    id: string,
    data: { title?: string; model?: string; system_prompt?: string | null },
  ) => jsonFetch<Chat>(`/chats/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteChat: (id: string) =>
    jsonFetch<void>(`/chats/${id}`, { method: "DELETE" }),
};

// --- SSE streaming -----------------------------------------------------------

export interface StreamCallbacks {
  onMeta?: (data: {
    user_message: Message;
    assistant_message_id: string;
    model: string;
  }) => void;
  onDelta?: (data: { content?: string; reasoning?: string }) => void;
  onTitle?: (title: string) => void;
  onDone?: (data: { assistant_message: Message; finish_reason: string | null }) => void;
  onError?: (message: string) => void;
}

export async function streamMessage(
  chatId: string,
  payload: { content: string; model?: string; system_prompt?: string | null },
  callbacks: StreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE}/chats/${chatId}/messages`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(payload),
    signal,
  });
  if (!res.ok || !res.body) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    callbacks.onError?.(detail);
    throw new Error(detail);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let done = false;

  while (!done) {
    const result = await reader.read();
    done = result.done;
    const value = result.value;
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // Process complete SSE events (terminated by \n\n).
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);

      let event = "message";
      const dataLines: string[] = [];
      for (const line of raw.split("\n")) {
        if (line.startsWith("event:")) {
          event = line.slice("event:".length).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice("data:".length).trim());
        }
      }
      if (!dataLines.length) continue;
      let payload_: unknown;
      try {
        payload_ = JSON.parse(dataLines.join("\n"));
      } catch {
        continue;
      }
      dispatchEvent(event, payload_, callbacks);
    }
  }
}

function dispatchEvent(event: string, data: unknown, cb: StreamCallbacks) {
  if (typeof data !== "object" || data === null) return;
  const obj = data as Record<string, unknown>;
  switch (event) {
    case "meta":
      cb.onMeta?.(obj as never);
      break;
    case "delta":
      cb.onDelta?.(obj as never);
      break;
    case "title":
      if (typeof obj.title === "string") cb.onTitle?.(obj.title);
      break;
    case "done":
      cb.onDone?.(obj as never);
      break;
    case "error":
      if (typeof obj.message === "string") cb.onError?.(obj.message);
      break;
  }
}
