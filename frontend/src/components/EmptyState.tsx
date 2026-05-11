import { Sparkles } from "lucide-react";

interface EmptyStateProps {
  onPick?: (prompt: string) => void;
}

const SUGGESTIONS = [
  "Объясни идею стоической философии в трёх предложениях.",
  "Напиши Python-функцию, которая считает простые числа решетом Эратосфена.",
  "Дай 5 идей для домашнего хобби в выходные.",
  "Помоги структурировать план на неделю.",
];

export function EmptyState({ onPick }: EmptyStateProps) {
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
      <div className="mt-8 grid sm:grid-cols-2 gap-2 w-full max-w-2xl">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onPick?.(s)}
            className="text-left text-sm px-4 py-3 rounded-lg border border-border-muted bg-surface-2 hover:bg-surface-3 hover:border-border transition-colors text-text"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
