import { useEffect, useRef } from "react";
import type { Message } from "../lib/types";
import { MessageBubble } from "./MessageBubble";

interface ChatViewProps {
  messages: Message[];
  streamingId: string | null;
  error: string | null;
}

export function ChatView({ messages, streamingId, error }: ChatViewProps) {
  const ref = useRef<HTMLDivElement>(null);
  const last = messages[messages.length - 1];
  const lastContent = last?.content ?? "";
  const lastReasoning = last?.reasoning ?? "";

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages.length, lastContent, lastReasoning]);

  return (
    <div ref={ref} className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-3xl w-full px-4 py-6 flex flex-col gap-6">
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} isStreaming={m.id === streamingId} />
        ))}
        {error && (
          <div className="rounded-lg border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
            {error}
          </div>
        )}
      </div>
    </div>
  );
}
