import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Sparkles } from "lucide-react";
import clsx from "clsx";
import type { ModelInfo } from "../lib/types";

interface ModelPickerProps {
  models: ModelInfo[];
  value: string;
  onChange: (id: string) => void;
}

export function ModelPicker({ models, value, onChange }: ModelPickerProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const selected = models.find((m) => m.id === value) ?? models[0];

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  if (!selected) return null;

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={clsx(
          "inline-flex items-center gap-2 px-3 py-1.5 rounded-md text-sm",
          "bg-surface-2 hover:bg-surface-3 border border-border text-text",
          "transition-colors duration-150",
        )}
      >
        <Sparkles className="w-4 h-4 text-accent" />
        <span className="font-medium">{selected.label}</span>
        <ChevronDown
          className={clsx("w-4 h-4 transition-transform", open && "rotate-180")}
        />
      </button>
      {open && (
        <div
          role="listbox"
          className="absolute right-0 mt-2 w-72 z-30 rounded-lg border border-border bg-surface-1 shadow-floating animate-fadein overflow-hidden"
        >
          {models.map((m) => {
            const isActive = m.id === value;
            return (
              <button
                key={m.id}
                type="button"
                role="option"
                aria-selected={isActive}
                onClick={() => {
                  onChange(m.id);
                  setOpen(false);
                }}
                className={clsx(
                  "w-full text-left px-3 py-2.5 flex items-start gap-2 transition-colors",
                  isActive ? "bg-surface-3" : "hover:bg-surface-3",
                )}
              >
                <Check
                  className={clsx(
                    "w-4 h-4 mt-0.5 shrink-0",
                    isActive ? "text-accent" : "text-transparent",
                  )}
                />
                <div className="min-w-0">
                  <div className="text-sm font-medium text-text">{m.label}</div>
                  <div className="text-xs text-text-muted mt-0.5">{m.description}</div>
                  {m.context_length ? (
                    <div className="text-[10px] uppercase tracking-wide text-text-subtle mt-1">
                      ctx {Math.round(m.context_length / 1024)}k
                    </div>
                  ) : null}
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
