import clsx from "clsx";
import { BrainCircuit } from "lucide-react";
import type { ResponseModeId } from "../lib/types";
import { RESPONSE_MODES } from "../lib/personalization";

interface ResponseModePickerProps {
  value: ResponseModeId;
  onChange: (id: ResponseModeId) => void;
  compact?: boolean;
}

export function ResponseModePicker({
  value,
  onChange,
  compact = false,
}: ResponseModePickerProps) {
  return (
    <div className="flex flex-wrap items-center gap-1.5" aria-label="Режим ответа">
      {RESPONSE_MODES.map((mode) => {
        const isActive = mode.id === value;
        return (
          <button
            key={mode.id}
            type="button"
            onClick={() => onChange(mode.id)}
            className={clsx(
              "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold transition-all duration-200",
              isActive
                ? "border-accent bg-accent-soft text-accent"
                : "border-border-muted bg-surface-2/80 text-text-muted hover:border-border hover:text-text",
            )}
            title={mode.description}
          >
            <BrainCircuit className="h-3.5 w-3.5" />
            {compact ? mode.shortLabel : mode.label}
          </button>
        );
      })}
    </div>
  );
}
