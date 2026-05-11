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
          <section className="relative overflow-hidden rounded-3xl border border-white/60 bg-white/75 p-8 shadow-[0_20px_60px_-30px_rgba(15,23,42,0.35)] backdrop-blur-xl">
            <div className="absolute -right-24 -top-24 h-64 w-64 rounded-full bg-indigo-300/35 blur-3xl" />
            <div className="absolute -bottom-28 left-12 h-72 w-72 rounded-full bg-sky-200/40 blur-3xl" />
            <div className="relative">
              <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-indigo-200/70 bg-white/80 px-3.5 py-1.5 text-[11px] font-semibold uppercase tracking-[0.22em] text-indigo-700">
                <Rocket className="h-3.5 w-3.5" />
                Update 2.0
              </div>
              <h1 className="max-w-2xl text-4xl font-semibold leading-[1.05] tracking-[-0.025em] text-slate-950 sm:text-5xl">
                Чистый чат — без визуального шума,
                <span className="bg-gradient-to-r from-indigo-600 via-violet-500 to-cyan-500 bg-clip-text text-transparent">
                  {" "}с фокусом на вводе.
                </span>
              </h1>
              <p className="mt-4 max-w-xl text-[15px] leading-7 text-slate-600">
                Командная панель, prompt-карточки, режимы ответа и быстрые
                действия собраны в одно место. Без лишних блёсток, только
                осмысленные детали.
              </p>
              <div className="mt-7 grid gap-3 sm:grid-cols-3">
                {[
                  ["Дизайн", activeDesign.label],
                  ["Режим", activeMode.label],
                  ["Промптов", `${PROMPT_SUGGESTIONS.length}+`],
                ].map(([label, value]) => (
                  <div
                    key={label}
                    className="rounded-2xl border border-white/70 bg-white/70 p-4 shadow-[0_1px_0_rgba(255,255,255,0.7)_inset,0_6px_18px_-12px_rgba(15,23,42,0.25)] transition-transform hover:-translate-y-0.5"
                  >
                    <div className="text-[10px] font-semibold uppercase tracking-[0.22em] text-slate-400">
                      {label}
                    </div>
                    <div className="mt-1.5 text-sm font-semibold text-slate-900">{value}</div>
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section className="relative overflow-hidden rounded-3xl border border-slate-800/80 bg-gradient-to-br from-slate-950 via-indigo-950 to-slate-900 p-5 text-white shadow-[0_20px_60px_-30px_rgba(15,23,42,0.5)]">
            <div className="absolute -right-16 -top-16 h-44 w-44 rounded-full bg-indigo-500/20 blur-3xl" />
            <div className="relative mb-4 flex items-center justify-between">
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-[0.22em] text-indigo-300">
                  Prompt deck
                </div>
                <div className="mt-1 text-sm text-white/55">
                  4 идеи для нового чата
                </div>
              </div>
            </div>
            <div className="relative">
              <PromptGrid prompts={visiblePrompts} onPick={onPick} design={design} />
            </div>
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
              ? "rounded-2xl border border-white/10 bg-white/[0.05] p-4 text-white hover:-translate-y-0.5 hover:border-indigo-300/40 hover:bg-white/[0.1]"
              : design === "zeroSugar"
                ? "rounded-none border border-border-muted bg-transparent px-3 py-3 font-mono text-xs uppercase leading-relaxed text-text hover:bg-surface-2"
                : "rounded-lg border border-border-muted bg-surface-2 px-4 py-3 text-text hover:border-border hover:bg-surface-3",
          )}
        >
          <span
            className={clsx(
              "mb-2 inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[0.2em]",
              design === "update2" ? "text-indigo-200" : "text-text-subtle",
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
