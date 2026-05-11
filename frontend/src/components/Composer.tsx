import clsx from "clsx";
import { useEffect, useRef } from "react";
import { Send, StopCircle } from "lucide-react";
import type { DesignVariantId } from "../lib/types";
import type { QuickAction } from "../lib/personalization";

interface ComposerProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onStop?: () => void;
  busy: boolean;
  placeholder?: string;
  design: DesignVariantId;
  quickActions: QuickAction[];
}

export function Composer({
  value,
  onChange,
  onSubmit,
  onStop,
  busy,
  placeholder = "Напиши сообщение… (Enter — отправить, Shift+Enter — новая строка)",
  design,
  quickActions,
}: ComposerProps) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const isUpdate = design === "update2";
  const isZero = design === "zeroSugar";

  // Autosize textarea
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "0px";
    const h = Math.min(el.scrollHeight, Math.floor(window.innerHeight * 0.4));
    el.style.height = `${h}px`;
  }, [value]);

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (!busy && value.trim()) onSubmit();
    }
  }

  return (
    <div
      className={clsx(
        "w-full px-4 py-3",
        isUpdate && "pb-5",
        isZero && "border-t border-border-muted bg-bg",
      )}
    >
      <div
        className={clsx(
          "mx-auto mb-2 flex max-w-3xl flex-wrap justify-center gap-1.5",
          isUpdate && "max-w-5xl justify-start",
          isZero && "max-w-4xl justify-start font-mono",
        )}
      >
        {quickActions.map((action) => (
          <button
            key={action.id}
            type="button"
            onClick={() => onChange(action.apply(value))}
            className={clsx(
              "rounded-full border border-border-muted px-3 py-1 text-[11px] text-text-muted transition-colors hover:border-border hover:text-text",
              isUpdate && "bg-white/50 backdrop-blur",
              isZero && "rounded-none uppercase tracking-[0.18em]",
            )}
          >
            {action.label}
          </button>
        ))}
      </div>
      <div
        className={clsx(
          "mx-auto flex items-end gap-2 border transition-colors duration-150",
          isUpdate
            ? "max-w-5xl rounded-[1.75rem] border-white/40 bg-white/70 p-3 shadow-[0_24px_80px_-36px_rgba(15,23,42,0.95)] backdrop-blur-2xl focus-within:border-fuchsia-300"
            : isZero
              ? "max-w-4xl rounded-none border-border bg-bg p-1 focus-within:border-text"
              : "max-w-3xl rounded-xl border-border bg-surface-2 p-2 shadow-raised focus-within:border-accent",
        )}
      >
        <textarea
          ref={ref}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          rows={1}
          className={clsx(
            "flex-1 resize-none bg-transparent px-2 py-2 outline-none",
            "text-[15px] leading-relaxed placeholder:text-text-subtle",
            isZero && "font-mono text-sm",
          )}
        />
        {busy && onStop ? (
          <button
            type="button"
            onClick={onStop}
            className={clsx(
              "inline-flex h-10 w-10 shrink-0 items-center justify-center bg-danger/15 text-danger transition-colors hover:bg-danger/25",
              isUpdate ? "rounded-2xl" : isZero ? "rounded-none" : "rounded-lg",
            )}
            aria-label="Остановить генерацию"
            title="Остановить"
          >
            <StopCircle className="w-5 h-5" />
          </button>
        ) : (
          <button
            type="button"
            onClick={onSubmit}
            disabled={busy || !value.trim()}
            className={clsx(
              "inline-flex h-10 w-10 shrink-0 items-center justify-center",
              isUpdate ? "rounded-2xl" : isZero ? "rounded-none" : "rounded-lg",
              isZero ? "bg-text text-bg hover:bg-text-muted" : "bg-accent text-white hover:bg-accent-hover",
              "disabled:bg-surface-3 disabled:text-text-subtle disabled:cursor-not-allowed",
              "transition-colors duration-150",
            )}
            aria-label="Отправить"
            title="Отправить (Enter)"
          >
            <Send className="w-4 h-4" />
          </button>
        )}
      </div>
      <div
        className={clsx(
          "mx-auto mt-2 max-w-3xl text-center text-[11px] text-text-subtle",
          isUpdate && "max-w-5xl text-left",
          isZero && "max-w-4xl text-left font-mono uppercase tracking-[0.18em]",
        )}
      >
        {isZero ? "VERIFY OUTPUT :: HUMAN RESPONSIBILITY" : "ИИ может ошибаться. Проверяй важные ответы."}
      </div>
    </div>
  );
}
