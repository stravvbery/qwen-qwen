import clsx from "clsx";

interface ModelAvatarProps {
  modelId?: string | null;
  size?: "sm" | "md" | "lg";
  className?: string;
}

interface AvatarSpec {
  initial: string;
  /** Tailwind gradient classes for the avatar background. */
  gradient: string;
  /** Optional ring/glow accent. */
  ring: string;
}

const DEFAULT_SPEC: AvatarSpec = {
  initial: "AI",
  gradient: "from-slate-500 via-slate-600 to-slate-700",
  ring: "shadow-[0_0_0_1px_rgba(148,163,184,0.4),0_8px_24px_-12px_rgba(15,23,42,0.6)]",
};

// Curated per-model styling: a distinct two-stop gradient + initial. Designed
// to read well on both light (update2) and dark (legacy / zeroSugar) shells.
const SPECS: Record<string, AvatarSpec> = {
  // DeepSeek — deep blue / indigo "trench" gradient.
  "deepseek-v4-pro": {
    initial: "D",
    gradient: "from-sky-500 via-indigo-600 to-blue-900",
    ring: "shadow-[0_0_0_1px_rgba(99,102,241,0.45),0_10px_30px_-12px_rgba(30,64,175,0.65)]",
  },
  // Kimi (Moonshot) — moonlight silver/violet halo.
  "kimi-k2p6": {
    initial: "K",
    gradient: "from-slate-200 via-violet-300 to-violet-700",
    ring: "shadow-[0_0_0_1px_rgba(196,181,253,0.45),0_10px_30px_-12px_rgba(124,58,237,0.6)]",
  },
  // Qwen — warm Alibaba-style orange.
  "qwen3p6-plus": {
    initial: "Q",
    gradient: "from-amber-300 via-orange-500 to-rose-600",
    ring: "shadow-[0_0_0_1px_rgba(251,146,60,0.5),0_10px_30px_-12px_rgba(234,88,12,0.65)]",
  },
  // MiniMax — crimson punch.
  "minimax-m2p7": {
    initial: "M",
    gradient: "from-pink-500 via-rose-600 to-red-900",
    ring: "shadow-[0_0_0_1px_rgba(244,63,94,0.5),0_10px_30px_-12px_rgba(190,18,60,0.65)]",
  },
  // GLM (Zhipu) — cool emerald/teal.
  "glm-5p1": {
    initial: "G",
    gradient: "from-emerald-300 via-teal-500 to-cyan-800",
    ring: "shadow-[0_0_0_1px_rgba(45,212,191,0.5),0_10px_30px_-12px_rgba(15,118,110,0.6)]",
  },
  // Claude Opus — Anthropic warm terracotta.
  "cat/claude-opus-4-7": {
    initial: "C",
    gradient: "from-orange-300 via-amber-600 to-yellow-900",
    ring: "shadow-[0_0_0_1px_rgba(217,119,6,0.5),0_10px_30px_-12px_rgba(146,64,14,0.65)]",
  },
  // GPT-5.5 — OpenAI green.
  "cat/gpt-5.5": {
    initial: "G",
    gradient: "from-emerald-400 via-green-600 to-teal-800",
    ring: "shadow-[0_0_0_1px_rgba(16,185,129,0.5),0_10px_30px_-12px_rgba(5,150,105,0.6)]",
  },
  // Gemini 3.1 Pro pool — Google blue.
  "pool/gemini-3-1-pro": {
    initial: "G",
    gradient: "from-blue-300 via-blue-500 to-indigo-700",
    ring: "shadow-[0_0_0_1px_rgba(59,130,246,0.5),0_10px_30px_-12px_rgba(37,99,235,0.65)]",
  },
};

function specFor(modelId?: string | null): AvatarSpec {
  if (!modelId) return DEFAULT_SPEC;
  // Try exact match first (freetheai models use full id as key),
  // then strip the Fireworks prefix for legacy models.
  return (
    SPECS[modelId] ??
    SPECS[modelId.replace("accounts/fireworks/models/", "")] ??
    DEFAULT_SPEC
  );
}

const SIZE_CLASSES = {
  sm: "h-6 w-6 text-[10px]",
  md: "h-8 w-8 text-xs",
  lg: "h-11 w-11 text-sm",
};

export function ModelAvatar({ modelId, size = "md", className }: ModelAvatarProps) {
  const spec = specFor(modelId);
  return (
    <span
      role="img"
      aria-label={modelId ?? "Модель"}
      className={clsx(
        "relative inline-flex shrink-0 items-center justify-center rounded-2xl font-semibold text-white",
        "bg-gradient-to-br",
        spec.gradient,
        spec.ring,
        SIZE_CLASSES[size],
        className,
      )}
    >
      <span className="relative drop-shadow-[0_1px_1px_rgba(0,0,0,0.35)]">
        {spec.initial}
      </span>
      <span
        aria-hidden
        className="pointer-events-none absolute inset-0 rounded-2xl bg-gradient-to-br from-white/30 via-transparent to-transparent opacity-70"
      />
    </span>
  );
}
