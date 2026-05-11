import clsx from "clsx";
import { Layers3 } from "lucide-react";
import type { DesignVariantId } from "../lib/types";
import { DESIGN_VARIANTS } from "../lib/personalization";

interface DesignPickerProps {
  value: DesignVariantId;
  onChange: (id: DesignVariantId) => void;
}

export function DesignPicker({ value, onChange }: DesignPickerProps) {
  return (
    <div className="flex flex-wrap items-center gap-1.5" aria-label="Выбор дизайна">
      {DESIGN_VARIANTS.map((variant) => {
        const isActive = variant.id === value;
        return (
          <button
            key={variant.id}
            type="button"
            onClick={() => onChange(variant.id)}
            className={clsx(
              "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold transition-all duration-200",
              isActive
                ? "border-accent bg-accent text-white shadow-[0_0_24px_-8px_var(--accent)]"
                : "border-border-muted bg-surface-2/80 text-text-muted hover:border-border hover:text-text",
            )}
            title={variant.description}
          >
            <Layers3 className="h-3.5 w-3.5" />
            {variant.shortLabel}
          </button>
        );
      })}
    </div>
  );
}
