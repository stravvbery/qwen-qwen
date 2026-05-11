import clsx from "clsx";
import { useState } from "react";
import { Brain, ChevronDown, User, Sparkles } from "lucide-react";
import type { DesignVariantId, Message } from "../lib/types";
import { Markdown } from "./Markdown";

interface MessageBubbleProps {
  message: Message;
  isStreaming?: boolean;
  design: DesignVariantId;
}

export function MessageBubble({ message, isStreaming, design }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const [reasoningOpen, setReasoningOpen] = useState(false);
  const hasReasoning = !!message.reasoning && message.reasoning.trim().length > 0;
  const isUpdate = design === "update2";
  const isZero = design === "zeroSugar";

  return (
    <div
      className={clsx(
        "flex w-full animate-fadein",
        isUser ? "justify-end" : "justify-start",
        isZero && "border-b border-border-muted py-3",
      )}
    >
      <div
        className={clsx(
          isUpdate
            ? "flex max-w-[min(58rem,_94%)] gap-4"
            : isZero
              ? "grid w-full max-w-none grid-cols-[96px_1fr] gap-4"
              : "flex max-w-[min(46rem,_92%)] gap-3",
          isUser ? "flex-row-reverse" : "flex-row",
        )}
      >
        <div
          className={clsx(
            "flex shrink-0 items-center justify-center",
            isUpdate
              ? "h-11 w-11 rounded-2xl bg-white/70 text-slate-900 shadow-sm"
              : isZero
                ? "h-auto w-24 items-start justify-start rounded-none pt-1 font-mono text-[10px] uppercase tracking-[0.2em] text-text-subtle"
                : "h-8 w-8 rounded-full",
            !isUpdate && !isZero && (isUser ? "bg-accent-soft text-accent" : "bg-surface-3 text-text-muted"),
          )}
          aria-hidden
        >
          {isZero ? (
            isUser ? "USER" : "AI"
          ) : isUser ? (
            <User className="h-4 w-4" />
          ) : (
            <Sparkles className="h-4 w-4" />
          )}
        </div>

        <div className="min-w-0 flex-1">
          {hasReasoning && !isUser && (
            <div className="mb-2">
              <button
                type="button"
                onClick={() => setReasoningOpen((v) => !v)}
                className="inline-flex items-center gap-1.5 text-xs text-text-muted hover:text-text transition-colors"
              >
                <Brain className="w-3.5 h-3.5" />
                <span>Размышления</span>
                <ChevronDown
                  className={clsx(
                    "w-3.5 h-3.5 transition-transform",
                    reasoningOpen && "rotate-180",
                  )}
                />
              </button>
              {reasoningOpen && (
                <div className="mt-2 rounded-lg border border-border-muted bg-surface-1 px-4 py-3 text-sm text-text-muted whitespace-pre-wrap font-mono">
                  {message.reasoning}
                </div>
              )}
            </div>
          )}

          <div
            className={clsx(
              "text-[15px] leading-relaxed",
              isUpdate
                ? clsx(
                    "rounded-[1.5rem] border px-5 py-4 shadow-[0_18px_60px_-34px_rgba(15,23,42,0.95)] backdrop-blur-xl",
                    isUser
                      ? "border-fuchsia-200/80 bg-fuchsia-500/15 text-text"
                      : "border-white/50 bg-white/65 text-text",
                  )
                : isZero
                  ? "border-l border-border-muted px-4 py-1 font-mono text-sm"
                  : clsx(
                      "rounded-lg px-4 py-3",
                      isUser
                        ? "bg-accent-soft text-text"
                        : "border border-border-muted bg-surface-2 text-text",
                    ),
            )}
          >
            {isUser ? (
              <div className="whitespace-pre-wrap break-words">{message.content}</div>
            ) : message.content ? (
              <Markdown>{message.content}</Markdown>
            ) : isStreaming ? (
              <span className="inline-block w-2 h-4 bg-text-muted animate-blink align-middle" />
            ) : (
              <span className="text-text-subtle italic">(пустой ответ)</span>
            )}
            {!isUser && isStreaming && message.content && (
              <span className="inline-block w-2 h-4 bg-text-muted animate-blink align-middle ml-0.5" />
            )}
          </div>

          {message.model && !isUser && (
            <div
              className={clsx(
                "mt-1.5 text-[11px] text-text-subtle",
                isZero && "font-mono uppercase tracking-[0.18em]",
              )}
            >
              {message.model.replace("accounts/fireworks/models/", "")}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
