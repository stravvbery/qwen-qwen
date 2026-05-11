import clsx from "clsx";
import { MessageSquarePlus, Trash2, MessageCircle } from "lucide-react";
import { useEffect, useState } from "react";
import type { Chat } from "../lib/types";
import { formatRelative } from "../lib/format";

interface SidebarProps {
  chats: Chat[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}

export function Sidebar({ chats, activeId, onSelect, onNew, onDelete }: SidebarProps) {
  const [confirmId, setConfirmId] = useState<string | null>(null);

  useEffect(() => {
    if (!confirmId) return;
    const t = setTimeout(() => setConfirmId(null), 3000);
    return () => clearTimeout(t);
  }, [confirmId]);

  return (
    <aside className="flex flex-col w-72 shrink-0 h-full bg-surface-1 border-r border-border-muted">
      <div className="p-3 border-b border-border-muted">
        <button
          type="button"
          onClick={onNew}
          className={clsx(
            "w-full inline-flex items-center justify-center gap-2 px-3 py-2 rounded-md",
            "bg-accent text-white font-medium text-sm shadow-raised",
            "hover:bg-accent-hover transition-colors duration-150",
          )}
        >
          <MessageSquarePlus className="w-4 h-4" />
          Новый чат
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 py-2">
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
                      "group flex items-center gap-2 px-3 py-2 rounded-md cursor-pointer",
                      "transition-colors duration-150",
                      isActive ? "bg-surface-3" : "hover:bg-surface-3",
                    )}
                    onClick={() => onSelect(chat.id)}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm text-text font-medium">
                        {chat.title || "Без названия"}
                      </div>
                      <div className="text-xs text-text-subtle mt-0.5">
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

      <div className="px-4 py-3 border-t border-border-muted text-[11px] text-text-subtle">
        Powered by Fireworks AI
      </div>
    </aside>
  );
}
