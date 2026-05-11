import clsx from "clsx";
import { useEffect, useRef } from "react";
import { Globe, Image as ImageIcon, Paperclip, Send, StopCircle, X } from "lucide-react";
import type { DesignVariantId } from "../lib/types";
import type { QuickAction } from "../lib/personalization";

interface ComposerProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onStop?: () => void;
  busy: boolean;
  placeholder?: string;
  design: DesignVariantId;
  quickActions: QuickAction[];
  attachments: string[];
  onAttachmentsChange: (next: string[]) => void;
  supportsVision: boolean;
  onAttachmentError?: (message: string) => void;
  webSearch: boolean;
  onWebSearchChange: (v: boolean) => void;
  searchAvailable: boolean;
}

const ACCEPTED_TYPES = "image/png,image/jpeg,image/webp,image/gif";
const MAX_ATTACHMENTS = 4;
const MAX_FILE_BYTES = 5 * 1024 * 1024; // 5 MB per image

async function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error("read failed"));
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== "string") {
        reject(new Error("unexpected reader result"));
        return;
      }
      resolve(result);
    };
    reader.readAsDataURL(file);
  });
}

export function Composer({
  value,
  onChange,
  onSubmit,
  onStop,
  busy,
  placeholder = "Напиши сообщение… (Enter — отправить, Shift+Enter — новая строка)",
  design,
  quickActions,
  attachments,
  onAttachmentsChange,
  supportsVision,
  onAttachmentError,
  webSearch,
  onWebSearchChange,
  searchAvailable,
}: ComposerProps) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const isUpdate = design === "update2";
  const isZero = design === "zeroSugar";

  // Autosize textarea
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "0px";
    const h = Math.min(el.scrollHeight, Math.floor(window.innerHeight * 0.4));
    el.style.height = `${h}px`;
  }, [value]);

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (!busy && (value.trim() || attachments.length)) onSubmit();
    }
  }

  async function handleFilesPicked(fileList: FileList | null) {
    if (!fileList || fileList.length === 0) return;
    const files = Array.from(fileList);
    const remaining = MAX_ATTACHMENTS - attachments.length;
    if (remaining <= 0) {
      onAttachmentError?.(`Можно прикрепить максимум ${MAX_ATTACHMENTS} изображений.`);
      return;
    }
    const accepted: File[] = [];
    for (const file of files.slice(0, remaining)) {
      if (!file.type.startsWith("image/")) {
        onAttachmentError?.(`Файл ${file.name}: поддерживаются только изображения.`);
        continue;
      }
      if (file.size > MAX_FILE_BYTES) {
        onAttachmentError?.(`Файл ${file.name} слишком большой (>5 МБ).`);
        continue;
      }
      accepted.push(file);
    }
    if (!accepted.length) return;
    try {
      const dataUrls = await Promise.all(accepted.map(fileToDataUrl));
      onAttachmentsChange([...attachments, ...dataUrls]);
    } catch {
      onAttachmentError?.("Не удалось прочитать выбранные файлы.");
    }
  }

  function removeAttachment(index: number) {
    onAttachmentsChange(attachments.filter((_, i) => i !== index));
  }

  const canSend = !busy && (value.trim().length > 0 || attachments.length > 0);
  const attachDisabled = busy || !supportsVision || attachments.length >= MAX_ATTACHMENTS;
  const attachTitle = !supportsVision
    ? "Текущая модель не поддерживает изображения"
    : attachments.length >= MAX_ATTACHMENTS
      ? `Не больше ${MAX_ATTACHMENTS} изображений`
      : "Прикрепить изображение";

  return (
    <div
      className={clsx(
        "w-full px-4 py-3",
        isUpdate && "pb-5",
        isZero && "border-t border-border-muted bg-bg",
      )}
    >
      <div
        className={clsx(
          "mx-auto mb-2 flex max-w-3xl flex-wrap justify-center gap-1.5",
          isUpdate && "max-w-5xl justify-start",
          isZero && "max-w-4xl justify-start font-mono",
        )}
      >
        {quickActions.map((action) => (
          <button
            key={action.id}
            type="button"
            onClick={() => onChange(action.apply(value))}
            className={clsx(
              "rounded-full border border-border-muted px-3 py-1 text-[11px] text-text-muted transition-colors hover:border-border hover:text-text",
              isUpdate && "bg-white/50 backdrop-blur",
              isZero && "rounded-none uppercase tracking-[0.18em]",
            )}
          >
            {action.label}
          </button>
        ))}
      </div>

      {attachments.length > 0 && (
        <div
          className={clsx(
            "mx-auto mb-2 flex max-w-3xl flex-wrap gap-2",
            isUpdate && "max-w-5xl",
            isZero && "max-w-4xl",
          )}
        >
          {attachments.map((url, index) => (
            <div
              key={`${index}-${url.slice(0, 32)}`}
              className={clsx(
                "group relative h-16 w-16 overflow-hidden rounded-lg border border-border-muted bg-surface-2",
                isZero && "rounded-none",
              )}
            >
              <img
                src={url}
                alt={`Прикреплённое изображение ${index + 1}`}
                className="h-full w-full object-cover"
              />
              <button
                type="button"
                onClick={() => removeAttachment(index)}
                className="absolute right-0 top-0 inline-flex h-5 w-5 items-center justify-center rounded-bl-md bg-bg/80 text-text-muted opacity-0 transition-opacity hover:text-text group-hover:opacity-100 focus:opacity-100"
                aria-label={`Убрать изображение ${index + 1}`}
                title="Убрать"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      <div
        className={clsx(
          "mx-auto flex items-end gap-2 border transition-colors duration-150",
          isUpdate
            ? "themed-surface-strong max-w-5xl rounded-2xl p-3 shadow-[0_10px_40px_-22px_rgba(15,23,42,0.35)] backdrop-blur-xl focus-within:border-[color:var(--accent)] focus-within:shadow-[0_14px_44px_-22px_rgba(79,70,229,0.35)]"
            : isZero
              ? "max-w-4xl rounded-none border-border bg-bg p-1 focus-within:border-text"
              : "max-w-3xl rounded-xl border-border bg-surface-2 p-2 shadow-raised focus-within:border-accent",
        )}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_TYPES}
          multiple
          className="hidden"
          onChange={(e) => {
            void handleFilesPicked(e.target.files);
            e.target.value = "";
          }}
        />
        {searchAvailable && (
          <button
            type="button"
            onClick={() => onWebSearchChange(!webSearch)}
            aria-label={webSearch ? "Отключить веб-поиск" : "Включить веб-поиск"}
            title={webSearch ? "Веб-поиск включён (нажмите, чтобы выключить)" : "Искать в интернете"}
            className={clsx(
              "inline-flex h-10 w-10 shrink-0 items-center justify-center transition-colors",
              isUpdate ? "rounded-2xl" : isZero ? "rounded-none" : "rounded-lg",
              webSearch
                ? isZero
                  ? "border border-text bg-text text-bg"
                  : "border border-accent bg-accent/15 text-accent"
                : "border border-transparent text-text-muted hover:bg-surface-3 hover:text-text",
            )}
          >
            <Globe className="h-4 w-4" />
          </button>
        )}
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={attachDisabled}
          aria-label="Прикрепить изображение"
          title={attachTitle}
          className={clsx(
            "inline-flex h-10 w-10 shrink-0 items-center justify-center transition-colors",
            isUpdate ? "rounded-2xl" : isZero ? "rounded-none" : "rounded-lg",
            "border border-transparent text-text-muted hover:bg-surface-3 hover:text-text",
            "disabled:cursor-not-allowed disabled:text-text-subtle disabled:hover:bg-transparent",
          )}
        >
          <Paperclip className="h-4 w-4" />
        </button>
        <textarea
          ref={ref}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          rows={1}
          className={clsx(
            "min-h-10 flex-1 resize-none bg-transparent px-2 py-2 outline-none",
            "text-[15px] leading-relaxed placeholder:text-text-subtle",
            "text-text caret-accent",
            isZero && "font-mono text-sm",
          )}
        />
        {busy && onStop ? (
          <button
            type="button"
            onClick={onStop}
            className={clsx(
              "inline-flex h-10 w-10 shrink-0 items-center justify-center bg-danger/15 text-danger transition-colors hover:bg-danger/25",
              isUpdate ? "rounded-2xl" : isZero ? "rounded-none" : "rounded-lg",
            )}
            aria-label="Остановить генерацию"
            title="Остановить"
          >
            <StopCircle className="w-5 h-5" />
          </button>
        ) : (
          <button
            type="button"
            onClick={onSubmit}
            disabled={!canSend}
            className={clsx(
              "inline-flex h-10 w-10 shrink-0 items-center justify-center",
              isUpdate ? "rounded-2xl" : isZero ? "rounded-none" : "rounded-lg",
              isZero ? "bg-text text-bg hover:bg-text-muted" : "bg-accent text-white hover:bg-accent-hover",
              "disabled:bg-surface-3 disabled:text-text-subtle disabled:cursor-not-allowed",
              "transition-colors duration-150",
            )}
            aria-label="Отправить"
            title="Отправить (Enter)"
          >
            <Send className="w-4 h-4" />
          </button>
        )}
      </div>
      <div
        className={clsx(
          "mx-auto mt-2 max-w-3xl text-center text-[11px] text-text-subtle",
          isUpdate && "max-w-5xl text-left",
          isZero && "max-w-4xl text-left font-mono uppercase tracking-[0.18em]",
        )}
      >
        {supportsVision ? (
          <span className="inline-flex items-center gap-1.5">
            <ImageIcon className="h-3 w-3" />
            {isZero
              ? "VISION ON · ATTACH IMAGES"
              : "Можно прикрепить изображения · модель поддерживает зрение."}
          </span>
        ) : isZero ? (
          "VERIFY OUTPUT :: HUMAN RESPONSIBILITY"
        ) : (
          "ИИ может ошибаться. Проверяй важные ответы."
        )}
      </div>
    </div>
  );
}
