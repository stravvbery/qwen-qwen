import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { Check, ChevronDown, Palette } from "lucide-react";
import { THEMES, type ThemeId } from "../lib/themes";

interface ThemePickerProps {
  value: ThemeId;
  onChange: (id: ThemeId) => void;
}

export function ThemePicker({ value, onChange }: ThemePickerProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const current = THEMES.find((t) => t.id === value) ?? THEMES[0];

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={clsx(
          "inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold",
          "border-border-muted bg-surface-2/80 text-text-muted hover:border-border hover:text-text",
          "transition-colors duration-150",
        )}
        title={current.description}
      >
        <span
          className="h-3.5 w-3.5 rounded-full ring-1 ring-black/10"
          style={{ backgroundImage: current.swatch }}
          aria-hidden
        />
        <Palette className="h-3.5 w-3.5" />
        <span className="hidden sm:inline">{current.label}</span>
        <ChevronDown
          className={clsx("h-3.5 w-3.5 transition-transform", open && "rotate-180")}
        />
      </button>
      {open && (
        <div
          role="listbox"
          className="themed-surface-solid absolute right-0 mt-2 w-56 z-30 rounded-xl border shadow-floating animate-fadein overflow-hidden"
        >
          {THEMES.map((t) => {
            const isActive = t.id === value;
            return (
              <button
                key={t.id}
                type="button"
                role="option"
                aria-selected={isActive}
                onClick={() => {
                  onChange(t.id);
                  setOpen(false);
                }}
                className={clsx(
                  "w-full text-left px-3 py-2.5 flex items-start gap-2.5 transition-colors",
                  isActive ? "bg-surface-3" : "hover:bg-surface-3",
                )}
              >
                <span
                  className="mt-0.5 h-5 w-5 shrink-0 rounded-full ring-1 ring-black/10"
                  style={{ backgroundImage: t.swatch }}
                  aria-hidden
                />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-text">{t.label}</div>
                  <div className="mt-0.5 text-xs text-text-subtle">{t.description}</div>
                </div>
                <Check
                  className={clsx(
                    "w-4 h-4 mt-0.5 shrink-0",
                    isActive ? "text-[color:var(--accent)]" : "text-transparent",
                  )}
                />
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
