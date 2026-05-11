import clsx from "clsx";
import { useState } from "react";
import { Brain, ChevronDown, User, Sparkles } from "lucide-react";
import type { Message } from "../lib/types";
import { Markdown } from "./Markdown";

interface MessageBubbleProps {
  message: Message;
  isStreaming?: boolean;
}

export function MessageBubble({ message, isStreaming }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const [reasoningOpen, setReasoningOpen] = useState(false);
  const hasReasoning = !!message.reasoning && message.reasoning.trim().length > 0;

  return (
    <div
      className={clsx(
        "w-full flex animate-fadein",
        isUser ? "justify-end" : "justify-start",
      )}
    >
      <div
        className={clsx(
          "max-w-[min(46rem,_92%)] flex gap-3",
          isUser ? "flex-row-reverse" : "flex-row",
        )}
      >
        <div
          className={clsx(
            "shrink-0 w-8 h-8 rounded-full flex items-center justify-center",
            isUser
              ? "bg-accent-soft text-accent"
              : "bg-surface-3 text-text-muted",
          )}
          aria-hidden
        >
          {isUser ? <User className="w-4 h-4" /> : <Sparkles className="w-4 h-4" />}
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
              "rounded-lg px-4 py-3 text-[15px] leading-relaxed",
              isUser
                ? "bg-accent-soft text-text"
                : "bg-surface-2 text-text border border-border-muted",
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
            <div className="mt-1.5 text-[11px] text-text-subtle">
              {message.model.replace("accounts/fireworks/models/", "")}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
