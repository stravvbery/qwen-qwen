import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { ArrowDown, Globe, Loader2 } from "lucide-react";
import type { DesignVariantId, Message } from "../lib/types";
import type { ToolStatusEvent } from "../lib/api";
import { MessageBubble } from "./MessageBubble";

interface ChatViewProps {
  messages: Message[];
  streamingId: string | null;
  error: string | null;
  design: DesignVariantId;
  toolStatus?: ToolStatusEvent | null;
}

// How close to the bottom (in pixels) we treat as "at bottom". Anything within
// this distance keeps the auto-follow behavior; further up unsticks it.
const STICK_THRESHOLD = 80;

function toolLabel(tool: string): string {
  switch (tool) {
    case "web_search": return "Поиск в интернете";
    case "read_webpage": return "Чтение страницы";
    default: return tool;
  }
}

export function ChatView({ messages, streamingId, error, design, toolStatus }: ChatViewProps) {
  const ref = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const [showJump, setShowJump] = useState(false);

  const count = messages.length;
  const last = messages[count - 1];
  const lastContent = last?.content ?? "";
  const lastReasoning = last?.reasoning ?? "";

  // Track user scroll position so streaming deltas only follow the bottom when
  // the user has not scrolled away.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    function handle() {
      const node = ref.current;
      if (!node) return;
      const distance = node.scrollHeight - node.scrollTop - node.clientHeight;
      const atBottom = distance < STICK_THRESHOLD;
      stickRef.current = atBottom;
      setShowJump(!atBottom);
    }
    el.addEventListener("scroll", handle, { passive: true });
    return () => el.removeEventListener("scroll", handle);
  }, []);

  // On a brand-new message (length change), jump to bottom and re-stick.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    stickRef.current = true;
    setShowJump(false);
    el.scrollTo({ top: el.scrollHeight });
  }, [count]);

  // While streaming deltas come in, only follow if the user is still pinned to
  // the bottom — otherwise stay where the user scrolled to.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (!stickRef.current) return;
    el.scrollTo({ top: el.scrollHeight });
  }, [lastContent, lastReasoning]);

  function jumpToBottom() {
    const el = ref.current;
    if (!el) return;
    stickRef.current = true;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    setShowJump(false);
  }

  return (
    <div className="relative flex-1 min-h-0">
      <div
        ref={ref}
        className={clsx(
          "h-full overflow-y-auto overscroll-contain",
          design === "update2" && "px-4",
          design === "zeroSugar" &&
            "bg-[linear-gradient(var(--border-muted)_1px,transparent_1px)] bg-[size:100%_44px]",
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
          {toolStatus && (
            <div
              className={clsx(
                "flex items-center gap-2 rounded-lg border px-4 py-3 text-sm",
                design === "update2"
                  ? "themed-surface border-[color:var(--accent)]/30 text-[color:var(--accent)]"
                  : design === "zeroSugar"
                    ? "rounded-none border-text/20 bg-bg font-mono text-text-muted uppercase tracking-[0.12em]"
                    : "border-accent/30 bg-accent/5 text-accent",
              )}
            >
              {toolStatus.status === "running" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Globe className="h-4 w-4" />
              )}
              <span>
                {toolLabel(toolStatus.tool)}
                {toolStatus.status === "running" && "…"}
                {toolStatus.status === "done" && " — готово"}
              </span>
            </div>
          )}
          {error && (
            <div className="rounded-lg border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
              {error}
            </div>
          )}
        </div>
      </div>
      {showJump && (
        <button
          type="button"
          onClick={jumpToBottom}
          aria-label="К последнему сообщению"
          className={clsx(
            "absolute bottom-3 left-1/2 z-10 -translate-x-1/2 inline-flex items-center gap-1.5",
            "rounded-full border border-border bg-surface-2/95 px-3 py-1.5 text-[11px] text-text-muted",
            "shadow-floating backdrop-blur transition-colors hover:text-text",
            design === "update2" &&
              "border-white/60 bg-white/85 text-slate-700 hover:text-slate-900",
            design === "zeroSugar" && "rounded-none uppercase tracking-[0.18em]",
          )}
        >
          <ArrowDown className="h-3.5 w-3.5" />
          К последнему
        </button>
      )}
    </div>
  );
}
