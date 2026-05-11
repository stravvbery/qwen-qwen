import clsx from "clsx";
import { useEffect, useRef } from "react";
import { Send, StopCircle } from "lucide-react";

interface ComposerProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onStop?: () => void;
  busy: boolean;
  placeholder?: string;
}

export function Composer({
  value,
  onChange,
  onSubmit,
  onStop,
  busy,
  placeholder = "Напиши сообщение… (Enter — отправить, Shift+Enter — новая строка)",
}: ComposerProps) {
  const ref = useRef<HTMLTextAreaElement>(null);

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
    <div className="w-full px-4 py-3">
      <div
        className={clsx(
          "mx-auto max-w-3xl flex items-end gap-2 p-2 rounded-xl border",
          "bg-surface-2 border-border focus-within:border-accent",
          "shadow-raised transition-colors duration-150",
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
            "flex-1 resize-none bg-transparent outline-none px-2 py-2",
            "text-[15px] leading-relaxed placeholder:text-text-subtle",
          )}
        />
        {busy && onStop ? (
          <button
            type="button"
            onClick={onStop}
            className="shrink-0 inline-flex items-center justify-center w-10 h-10 rounded-lg bg-danger/15 text-danger hover:bg-danger/25 transition-colors"
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
              "shrink-0 inline-flex items-center justify-center w-10 h-10 rounded-lg",
              "bg-accent text-white hover:bg-accent-hover",
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
      <div className="mx-auto max-w-3xl mt-2 text-center text-[11px] text-text-subtle">
        ИИ может ошибаться. Проверяй важные ответы.
      </div>
    </div>
  );
}
