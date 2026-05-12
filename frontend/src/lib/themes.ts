export type ThemeId = "aurora" | "forest" | "sunset" | "midnight" | "mono";

export interface ThemeDef {
  id: ThemeId;
  label: string;
  description: string;
  swatch: string;
}

export const THEMES: ThemeDef[] = [
  {
    id: "aurora",
    label: "Aurora",
    description: "Индиго, виолет и циан — современный 2.0 по умолчанию.",
    swatch: "linear-gradient(135deg, #6366f1, #8b5cf6 55%, #22d3ee)",
  },
  {
    id: "forest",
    label: "Forest",
    description: "Изумруд и бирюза, спокойная зелёная палитра.",
    swatch: "linear-gradient(135deg, #10b981, #14b8a6 55%, #5eead4)",
  },
  {
    id: "sunset",
    label: "Sunset",
    description: "Тёплый закат: амбер, коралл, рассветный розовый.",
    swatch: "linear-gradient(135deg, #f59e0b, #f97316 55%, #e11d48)",
  },
  {
    id: "midnight",
    label: "Midnight",
    description: "Тёмная версия 2.0 — тот же layout, но ночной indigo.",
    swatch: "linear-gradient(135deg, #1e1b4b, #312e81 55%, #155e75)",
  },
  {
    id: "mono",
    label: "Mono",
    description: "Сланцевая монохромная палитра без акцентного цвета.",
    swatch: "linear-gradient(135deg, #475569, #64748b 55%, #cbd5e1)",
  },
];

export const DEFAULT_THEME: ThemeId = "aurora";

const THEME_STORAGE_KEY = "grebeshok-chat:theme-update2";

export function readStoredTheme(): ThemeId {
  if (typeof window === "undefined") return DEFAULT_THEME;
  try {
    const value = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (!value) return DEFAULT_THEME;
    return (THEMES.find((t) => t.id === value)?.id ?? DEFAULT_THEME) as ThemeId;
  } catch {
    return DEFAULT_THEME;
  }
}

export function persistTheme(id: ThemeId): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, id);
  } catch {
    /* ignore */
  }
}
