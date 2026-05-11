import { useEffect, useRef } from "react";
import clsx from "clsx";
import type { DesignVariantId, Message } from "../lib/types";
import { MessageBubble } from "./MessageBubble";

interface ChatViewProps {
  messages: Message[];
  streamingId: string | null;
  error: string | null;
  design: DesignVariantId;
}

export function ChatView({ messages, streamingId, error, design }: ChatViewProps) {
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
    <div
      ref={ref}
      className={clsx(
        "flex-1 overflow-y-auto",
        design === "update2" && "px-4",
        design === "zeroSugar" && "bg-[linear-gradient(var(--border-muted)_1px,transparent_1px)] bg-[size:100%_44px]",
      )}
    >
      <div
        className={clsx(
          "flex w-full flex-col",
          design === "update2"
            ? "mx-auto max-w-5xl gap-5 px-4 py-8"
            : design === "zeroSugar"
              ? "mx-auto max-w-4xl gap-0 px-4 py-4"
              : "mx-auto max-w-3xl gap-6 px-4 py-6",
        )}
      >
        {messages.map((m) => (
          <MessageBubble
            key={m.id}
            message={m}
            isStreaming={m.id === streamingId}
            design={design}
          />
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
