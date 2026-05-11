import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Sparkles } from "lucide-react";
import clsx from "clsx";
import type { ModelInfo } from "../lib/types";
import { ModelAvatar } from "./ModelAvatar";

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

  if (!selected) {
    return (
      <div className="inline-flex items-center gap-2 rounded-full border border-border-muted bg-surface-2/80 px-3 py-1.5 text-xs font-semibold text-text-subtle">
        <Sparkles className="h-3.5 w-3.5" />
        Модель загружается
      </div>
    );
  }

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={clsx(
          "inline-flex items-center gap-2 rounded-full border py-1 pl-1 pr-3 text-xs font-semibold",
          "border-accent bg-accent-soft text-accent hover:border-accent-hover hover:text-accent-hover",
          "transition-colors duration-150",
        )}
      >
        <ModelAvatar modelId={selected.id} size="sm" />
        <span className="text-text-subtle">Модель</span>
        <span className="font-medium">{selected.label}</span>
        <ChevronDown
          className={clsx("h-3.5 w-3.5 transition-transform", open && "rotate-180")}
        />
      </button>
      {open && (
        <div
          role="listbox"
          className="absolute right-0 mt-2 w-72 z-30 rounded-xl border border-border bg-surface-1 shadow-floating animate-fadein overflow-hidden backdrop-blur-xl"
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
                  "w-full text-left px-3 py-2.5 flex items-start gap-3 transition-colors",
                  isActive ? "bg-surface-3" : "hover:bg-surface-3",
                )}
              >
                <ModelAvatar modelId={m.id} size="md" />
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
