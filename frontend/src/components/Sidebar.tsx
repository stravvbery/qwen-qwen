import clsx from "clsx";
import { MessageSquarePlus, Trash2, MessageCircle, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { Chat, DesignVariantId } from "../lib/types";
import { formatRelative } from "../lib/format";

interface SidebarProps {
  chats: Chat[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  design: DesignVariantId;
  mobileOpen?: boolean;
  onMobileClose?: () => void;
}

export function Sidebar({
  chats,
  activeId,
  onSelect,
  onNew,
  onDelete,
  design,
  mobileOpen = false,
  onMobileClose,
}: SidebarProps) {
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const isUpdate = design === "update2";
  const isZero = design === "zeroSugar";

  useEffect(() => {
    if (!confirmId) return;
    const t = setTimeout(() => setConfirmId(null), 3000);
    return () => clearTimeout(t);
  }, [confirmId]);

  return (
    <>
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm md:hidden"
          onClick={onMobileClose}
        />
      )}
      <aside
        className={clsx(
          "flex shrink-0 flex-col transition-transform duration-200 ease-out",
          "fixed inset-y-0 left-0 z-50 md:relative md:z-auto md:translate-x-0",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
          isUpdate
            ? "themed-surface md:m-4 md:mr-0 md:h-[calc(100%-2rem)] w-72 md:rounded-2xl border shadow-[0_10px_40px_-22px_rgba(15,23,42,0.35)] backdrop-blur-xl h-full bg-[var(--bg)] md:bg-transparent"
            : isZero
              ? "h-full w-64 border-r border-border-muted bg-bg font-mono"
              : "h-full w-72 border-r border-border-muted bg-surface-1",
        )}
      >
      <div
        className={clsx(
          "border-b border-border-muted",
          isUpdate ? "p-4" : isZero ? "p-2" : "p-3",
        )}
      >
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onMobileClose}
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-text-muted hover:bg-surface-3 hover:text-text transition-colors md:hidden"
            aria-label="Закрыть меню"
          >
            <X className="h-5 w-5" />
          </button>
          <button
            type="button"
            onClick={onNew}
            className={clsx(
              "inline-flex w-full items-center justify-center gap-2 font-medium transition-colors duration-150",
            isUpdate
              ? "themed-accent-bg rounded-xl px-4 py-2.5 text-sm text-white shadow-[0_8px_24px_-14px_rgba(79,70,229,0.55)] transition-[filter] hover:brightness-110"
              : isZero
                ? "rounded-none border border-border px-2 py-2 text-xs uppercase tracking-[0.2em] text-text hover:bg-surface-2"
                : "rounded-md bg-accent px-3 py-2 text-sm text-white shadow-raised hover:bg-accent-hover",
          )}
        >
            <MessageSquarePlus className="w-4 h-4" />
            Новый чат
          </button>
        </div>
      </div>

      <nav className={clsx("flex-1 overflow-y-auto", isUpdate ? "px-3 py-3" : "px-2 py-2")}>
        {chats.length === 0 ? (
          <div className="px-3 py-8 text-center text-sm text-text-muted">
            <MessageCircle className="w-6 h-6 mx-auto mb-2 text-text-subtle" />
            Чатов пока нет
          </div>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {chats.map((chat) => {
              const isActive = chat.id === activeId;
              const isConfirm = confirmId === chat.id;
              return (
                <li key={chat.id}>
                  <div
                    className={clsx(
                      "group flex cursor-pointer items-center gap-2 transition-colors duration-150",
                      isUpdate
                        ? "rounded-2xl px-3 py-3"
                        : isZero
                          ? "rounded-none border-b border-border-muted px-2 py-2"
                          : "rounded-md px-3 py-2",
                      isActive
                        ? isUpdate
                          ? "themed-accent-bg-soft text-white shadow-[0_8px_24px_-16px_rgba(15,23,42,0.45)]"
                          : "bg-surface-3"
                        : isUpdate
                          ? "hover:bg-white/85"
                          : "hover:bg-surface-3",
                    )}
                    onClick={() => onSelect(chat.id)}
                  >
                    <div className="min-w-0 flex-1">
                      <div
                        className={clsx(
                          "truncate text-sm font-medium",
                          isActive && isUpdate ? "text-white" : "text-text",
                        )}
                      >
                        {chat.title || "Без названия"}
                      </div>
                      <div
                        className={clsx(
                          "mt-0.5 text-xs",
                          isActive && isUpdate ? "text-white/60" : "text-text-subtle",
                        )}
                      >
                        {formatRelative(chat.updated_at)}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        if (isConfirm) {
                          onDelete(chat.id);
                          setConfirmId(null);
                        } else {
                          setConfirmId(chat.id);
                        }
                      }}
                      className={clsx(
                        "shrink-0 p-1.5 rounded-md transition-colors",
                        isConfirm
                          ? "bg-danger/15 text-danger"
                          : "text-text-subtle opacity-0 group-hover:opacity-100 hover:text-danger hover:bg-surface-3",
                      )}
                      aria-label={isConfirm ? "Подтвердить удаление" : "Удалить чат"}
                      title={isConfirm ? "Кликни ещё раз для удаления" : "Удалить"}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </nav>

      <div
        className={clsx(
          "border-t border-border-muted text-[11px] text-text-subtle",
          isUpdate ? "px-5 py-4" : "px-4 py-3",
        )}
      >
        {isZero ? "FW/AI :: ONLINE" : "Powered by Fireworks AI"}
      </div>
    </aside>
    </>
  );
}
