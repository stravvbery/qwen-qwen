import clsx from "clsx";
import { Rocket, Sparkles, Wand2, Zap } from "lucide-react";
import { useMemo } from "react";
import type { DesignVariantId, ResponseModeId } from "../lib/types";
import {
  DESIGN_VARIANTS,
  PROMPT_SUGGESTIONS,
  RESPONSE_MODES,
} from "../lib/personalization";

interface EmptyStateProps {
  onPick?: (prompt: string) => void;
  design: DesignVariantId;
  mode: ResponseModeId;
  promptSeed: number;
}

const CARD_COUNT = 4;

export function EmptyState({ onPick, design, mode, promptSeed }: EmptyStateProps) {
  const activeDesign = DESIGN_VARIANTS.find((item) => item.id === design) ?? DESIGN_VARIANTS[0];
  const activeMode = RESPONSE_MODES.find((item) => item.id === mode) ?? RESPONSE_MODES[0];
  const offset = useMemo(
    () => Math.abs(promptSeed) % PROMPT_SUGGESTIONS.length,
    [promptSeed],
  );
  const visiblePrompts = useMemo(
    () =>
      Array.from({ length: CARD_COUNT }, (_, index) => {
        const promptIndex = (offset + index) % PROMPT_SUGGESTIONS.length;
        return PROMPT_SUGGESTIONS[promptIndex];
      }),
    [offset],
  );

  if (design === "update2") {
    return (
      <div className="flex-1 overflow-y-auto px-4 py-8">
        <div className="mx-auto grid max-w-6xl gap-5 lg:grid-cols-[1.1fr_0.9fr]">
          <section className="relative overflow-hidden rounded-[2.5rem] border border-white/30 bg-white/65 p-8 shadow-[0_30px_120px_-55px_rgba(15,23,42,1)] backdrop-blur-2xl">
            <div className="absolute -right-24 -top-24 h-64 w-64 rounded-full bg-fuchsia-400/30 blur-3xl" />
            <div className="absolute -bottom-28 left-12 h-72 w-72 rounded-full bg-cyan-300/30 blur-3xl" />
            <div className="relative">
              <div className="mb-8 inline-flex items-center gap-2 rounded-full border border-white/50 bg-white/70 px-4 py-2 text-xs font-bold uppercase tracking-[0.22em] text-slate-700">
                <Rocket className="h-4 w-4 text-fuchsia-500" />
                Update 2.0 live deck
              </div>
              <h1 className="max-w-2xl text-5xl font-black leading-[0.95] tracking-[-0.06em] text-slate-950 sm:text-7xl">
                Чат, который больше не выглядит как обычный чат.
              </h1>
              <p className="mt-5 max-w-xl text-base leading-7 text-slate-600">
                Командная панель, живые prompt-карточки, режимы ответа и быстрые
                действия собраны в один яркий cockpit для Fireworks-моделей.
              </p>
              <div className="mt-8 grid gap-3 sm:grid-cols-3">
                {[
                  ["Дизайн", activeDesign.label],
                  ["Режим", activeMode.label],
                  ["Промптов", `${PROMPT_SUGGESTIONS.length}+`],
                ].map(([label, value]) => (
                  <div
                    key={label}
                    className="rounded-3xl border border-white/40 bg-white/60 p-4 shadow-sm"
                  >
                    <div className="text-[10px] font-bold uppercase tracking-[0.22em] text-slate-400">
                      {label}
                    </div>
                    <div className="mt-2 text-sm font-bold text-slate-950">{value}</div>
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section className="rounded-[2rem] border border-white/30 bg-slate-950 p-5 text-white shadow-[0_30px_120px_-50px_rgba(15,23,42,1)]">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <div className="text-xs font-bold uppercase tracking-[0.22em] text-fuchsia-300">
                  Prompt deck
                </div>
                <div className="mt-1 text-sm text-white/55">
                  4 идеи для нового чата
                </div>
              </div>
            </div>
            <PromptGrid prompts={visiblePrompts} onPick={onPick} design={design} />
          </section>
        </div>
      </div>
    );
  }

  if (design === "zeroSugar") {
    return (
      <div className="flex-1 overflow-y-auto p-4 font-mono">
        <div className="mx-auto grid max-w-5xl border border-border-muted md:grid-cols-[280px_1fr]">
          <section className="border-b border-border-muted p-4 md:border-b-0 md:border-r">
            <div className="text-[10px] uppercase tracking-[0.24em] text-text-subtle">
              GREBESHOK CHAT / ZERO SUGAR
            </div>
            <h1 className="mt-8 text-3xl font-semibold uppercase tracking-[-0.05em]">
              input first.
              <br />
              decoration never.
            </h1>
            <div className="mt-8 space-y-3 text-xs text-text-muted">
              <div>DESIGN: {activeDesign.shortLabel}</div>
              <div>MODE: {activeMode.shortLabel}</div>
              <div>POOL: {PROMPT_SUGGESTIONS.length} PROMPTS</div>
              <div>REFRESH OR NEW CHAT: NEW IDEAS</div>
            </div>
          </section>
          <section className="p-3">
            <PromptGrid prompts={visiblePrompts} onPick={onPick} design={design} />
          </section>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col items-center justify-center px-6 text-center">
      <div className="w-14 h-14 rounded-2xl bg-accent-soft text-accent flex items-center justify-center mb-5 shadow-raised">
        <Sparkles className="w-7 h-7" />
      </div>
      <h1 className="text-2xl font-semibold text-text">Чат с нейросетью</h1>
      <p className="mt-2 text-sm text-text-muted max-w-md">
        Личный чат-интерфейс на Fireworks API. Выбирай модель сверху и
        начинай разговор — история сохраняется автоматически.
      </p>
      <div className="mt-6 flex items-center gap-2 text-xs text-text-muted">
        <Zap className="h-3.5 w-3.5 text-accent" />
        {activeMode.label} · {PROMPT_SUGGESTIONS.length} быстрых идей
      </div>
      <div className="mt-8 w-full max-w-2xl">
        <PromptGrid prompts={visiblePrompts} onPick={onPick} design={design} />
      </div>
    </div>
  );
}

function PromptGrid({
  prompts,
  onPick,
  design,
}: {
  prompts: string[];
  onPick?: (prompt: string) => void;
  design: DesignVariantId;
}) {
  return (
    <div
      className={clsx(
        "grid gap-2",
        design === "update2" ? "grid-cols-1" : "sm:grid-cols-2",
      )}
    >
      {prompts.map((prompt, index) => (
        <button
          key={`${prompt}-${index}`}
          type="button"
          onClick={() => onPick?.(prompt)}
          className={clsx(
            "group text-left text-sm transition-all duration-200",
            design === "update2"
              ? "rounded-3xl border border-white/10 bg-white/[0.06] p-4 text-white hover:-translate-y-0.5 hover:bg-white/[0.12]"
              : design === "zeroSugar"
                ? "rounded-none border border-border-muted bg-transparent px-3 py-3 font-mono text-xs uppercase leading-relaxed text-text hover:bg-surface-2"
                : "rounded-lg border border-border-muted bg-surface-2 px-4 py-3 text-text hover:border-border hover:bg-surface-3",
          )}
        >
          <span
            className={clsx(
              "mb-2 inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-[0.2em]",
              design === "update2" ? "text-cyan-200" : "text-text-subtle",
            )}
          >
            {design === "update2" ? <Wand2 className="h-3 w-3" /> : null}
            0{index + 1}
          </span>
          <span className="block">{prompt}</span>
        </button>
      ))}
    </div>
  );
}
