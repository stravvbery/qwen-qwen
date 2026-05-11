export function formatRelative(iso: string): string {
  const date = new Date(iso);
  const now = Date.now();
  const diffSec = Math.round((now - date.getTime()) / 1000);

  if (diffSec < 60) return "только что";
  const min = Math.floor(diffSec / 60);
  if (min < 60) return `${min} мин назад`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} ч назад`;
  const day = Math.floor(hr / 24);
  if (day < 7) return `${day} д назад`;
  return date.toLocaleDateString("ru-RU", { day: "2-digit", month: "short" });
}
