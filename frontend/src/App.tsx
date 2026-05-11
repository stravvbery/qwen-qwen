import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import clsx from "clsx";
import { api, streamMessage, type SearchStatus, type ToolStatusEvent } from "./lib/api";
import type { Chat, ChatDetail, Message, ModelInfo } from "./lib/types";
import { Sidebar } from "./components/Sidebar";
import { ChatView } from "./components/ChatView";
import { Composer } from "./components/Composer";
import { ModelPicker } from "./components/ModelPicker";
import { EmptyState } from "./components/EmptyState";
import { DesignPicker } from "./components/DesignPicker";
import { ResponseModePicker } from "./components/ResponseModePicker";
import { ThemePicker } from "./components/ThemePicker";
import {
  DESIGN_VARIANTS,
  QUICK_ACTIONS,
  RESPONSE_MODES,
  getModeByPrompt,
} from "./lib/personalization";
import { persistTheme, readStoredTheme, type ThemeId } from "./lib/themes";
import type { DesignVariantId, ResponseModeId } from "./lib/types";

export default function App() {
  const navigate = useNavigate();
  const params = useParams();
  const activeId = params.id ?? null;

  const [chats, setChats] = useState<Chat[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [currentChat, setCurrentChat] = useState<ChatDetail | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [selectedDesign, setSelectedDesign] = useState<DesignVariantId>("legacy");
  const [selectedMode, setSelectedMode] = useState<ResponseModeId>("normal");
  const [theme, setTheme] = useState<ThemeId>(() => readStoredTheme());

  const onThemeChange = useCallback((id: ThemeId) => {
    setTheme(id);
    persistTheme(id);
  }, []);
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<string[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [streamingId, setStreamingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [promptSeed, setPromptSeed] = useState(() => Math.floor(Math.random() * 10000));
  const [webSearch, setWebSearch] = useState(false);
  const [searchAvailable, setSearchAvailable] = useState(false);
  const [toolStatus, setToolStatus] = useState<ToolStatusEvent | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const currentChatId = currentChat?.id ?? null;

  // Initial load
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [m, c, ss] = await Promise.all([
          api.listModels(),
          api.listChats(),
          api.searchStatus().catch(() => ({ enabled: false }) as SearchStatus),
        ]);
        if (cancelled) return;
        setModels(m);
        setChats(c);
        setSearchAvailable(ss.enabled);
        if (m.length && !selectedModel) setSelectedModel(m[0].id);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Не удалось загрузить данные");
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load chat when activeId changes
  useEffect(() => {
    if (!activeId) {
      setCurrentChat(null);
      setMessages([]);
      return;
    }
    if (streaming && currentChatId === activeId) return;
    let cancelled = false;
    (async () => {
      try {
        setError(null);
        const detail = await api.getChat(activeId);
        if (cancelled) return;
        setCurrentChat(detail);
        setMessages(detail.messages);
        setSelectedModel(detail.model);
        setSelectedMode(getModeByPrompt(detail.system_prompt).id);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Не удалось открыть чат");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeId, currentChatId, streaming]);

  const onNewChat = useCallback(() => {
    setPromptSeed((seed) => seed + 1);
    navigate("/");
  }, [navigate]);

  const onSelectChat = useCallback(
    (id: string) => {
      navigate(`/c/${id}`);
    },
    [navigate],
  );

  const onDeleteChat = useCallback(
    async (id: string) => {
      try {
        await api.deleteChat(id);
        setChats((prev) => prev.filter((c) => c.id !== id));
        if (activeId === id) navigate("/");
      } catch (e) {
        setError(e instanceof Error ? e.message : "Не удалось удалить чат");
      }
    },
    [activeId, navigate],
  );

  const onModelChange = useCallback(
    async (id: string) => {
      setSelectedModel(id);
      if (currentChat && currentChat.model !== id) {
        try {
          const updated = await api.updateChat(currentChat.id, { model: id });
          setCurrentChat((prev) => (prev ? { ...prev, model: updated.model } : prev));
          setChats((prev) =>
            prev.map((c) => (c.id === updated.id ? { ...c, model: updated.model } : c)),
          );
        } catch {
          /* ignore — UI reflects locally */
        }
      }
    },
    [currentChat],
  );

  const selectedModeConfig = useMemo(
    () => RESPONSE_MODES.find((mode) => mode.id === selectedMode) ?? RESPONSE_MODES[0],
    [selectedMode],
  );

  const selectedDesignConfig = useMemo(
    () =>
      DESIGN_VARIANTS.find((design) => design.id === selectedDesign) ?? DESIGN_VARIANTS[0],
    [selectedDesign],
  );

  const onModeChange = useCallback(
    async (id: ResponseModeId) => {
      const mode = RESPONSE_MODES.find((item) => item.id === id) ?? RESPONSE_MODES[0];
      setSelectedMode(mode.id);
      if (currentChat) {
        try {
          const updated = await api.updateChat(currentChat.id, {
            system_prompt: mode.systemPrompt,
          });
          setCurrentChat((prev) =>
            prev ? { ...prev, system_prompt: updated.system_prompt } : prev,
          );
          setChats((prev) =>
            prev.map((chat) =>
              chat.id === updated.id
                ? { ...chat, system_prompt: updated.system_prompt }
                : chat,
            ),
          );
        } catch {
          /* ignore — selected mode still applies to the next send */
        }
      }
    },
    [currentChat],
  );

  const onSubmit = useCallback(async () => {
    const text = input.trim();
    if (streaming) return;
    if (!text && attachments.length === 0) return;

    setError(null);
    setStreaming(true);

    let chatId = activeId;
    let createdNew = false;
    const localUserId = `local-user-${Date.now()}`;
    const localAssistantId = `local-assistant-${Date.now()}`;
    const now = new Date().toISOString();
    const outgoingAttachments = attachments;
    const optimisticMessages: Message[] = [
      {
        id: localUserId,
        chat_id: chatId ?? "pending",
        role: "user",
        content: text,
        model: selectedModel,
        attachments: outgoingAttachments.length ? outgoingAttachments : null,
        created_at: now,
      },
      {
        id: localAssistantId,
        chat_id: chatId ?? "pending",
        role: "assistant",
        content: "",
        reasoning: "",
        model: selectedModel,
        created_at: now,
      },
    ];

    try {
      if (!chatId) {
        const chat = await api.createChat({
          model: selectedModel,
          system_prompt: selectedModeConfig.systemPrompt,
        });
        chatId = chat.id;
        createdNew = true;
        setChats((prev) => [chat, ...prev]);
        setCurrentChat({ ...chat, messages: [] });
        navigate(`/c/${chat.id}`, { replace: true });
      }

      setInput("");
      setAttachments([]);
      setMessages((prev) => [
        ...prev,
        ...optimisticMessages.map((message) => ({ ...message, chat_id: chatId! })),
      ]);
      setStreamingId(localAssistantId);

      const controller = new AbortController();
      abortRef.current = controller;

      setToolStatus(null);

      await streamMessage(
        chatId!,
        {
          content: text || "",
          model: selectedModel,
          system_prompt: selectedModeConfig.systemPrompt,
          attachments: outgoingAttachments.length ? outgoingAttachments : null,
          web_search: webSearch || undefined,
        },
        {
          onMeta: ({ user_message, assistant_message_id, model }) => {
            setMessages((prev) =>
              prev.map((message) => {
                if (message.id === localUserId) return user_message;
                if (message.id === localAssistantId) {
                  return {
                    ...message,
                    id: assistant_message_id,
                    chat_id: chatId!,
                    model,
                  };
                }
                return message;
              }),
            );
            setStreamingId(assistant_message_id);
          },
          onDelta: ({ content, reasoning }) => {
            setMessages((prev) => {
              if (!prev.length) return prev;
              const next = [...prev];
              const last = { ...next[next.length - 1] };
              if (content) last.content += content;
              if (reasoning) last.reasoning = (last.reasoning ?? "") + reasoning;
              next[next.length - 1] = last;
              return next;
            });
          },
          onTitle: (title) => {
            if (chatId) {
              setChats((prev) =>
                prev.map((c) => (c.id === chatId ? { ...c, title } : c)),
              );
              setCurrentChat((prev) => (prev ? { ...prev, title } : prev));
            }
          },
          onDone: ({ assistant_message }) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistant_message.id
                  ? { ...m, ...assistant_message }
                  : m,
              ),
            );
            setStreamingId(null);
            if (chatId) {
              setChats((prev) => {
                const idx = prev.findIndex((c) => c.id === chatId);
                if (idx === -1) return prev;
                const updated = {
                  ...prev[idx],
                  updated_at: new Date().toISOString(),
                };
                const next = [updated, ...prev.slice(0, idx), ...prev.slice(idx + 1)];
                return next;
              });
            }
          },
          onToolStatus: (data) => {
            setToolStatus(data);
          },
          onError: (message) => {
            setError(message);
            setStreamingId(null);
            setToolStatus(null);
          },
        },
        controller.signal,
      );
    } catch (e) {
      if ((e as Error).name === "AbortError") {
        setError(null);
      } else {
        setError(e instanceof Error ? e.message : "Ошибка отправки сообщения");
      }
      if (createdNew && chatId && !messages.length) {
        // leave the empty chat in the list — user may want to retry
      }
    } finally {
      setStreaming(false);
      setStreamingId(null);
      setToolStatus(null);
      abortRef.current = null;
    }
  }, [
    activeId,
    attachments,
    input,
    messages.length,
    navigate,
    selectedModeConfig.systemPrompt,
    selectedModel,
    streaming,
    webSearch,
  ]);

  const onStop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const isEmpty = !currentChat || messages.length === 0;
  const headerTitle = currentChat?.title ?? "Новый чат";

  const modelById = useMemo(() => new Map(models.map((m) => [m.id, m])), [models]);
  const headerModelId = currentChat?.model ?? selectedModel;
  const activeModelInfo = modelById.get(selectedModel) ?? null;
  const supportsVision = !!activeModelInfo?.supports_vision;
  const isUpdate = selectedDesign === "update2";
  const isZero = selectedDesign === "zeroSugar";

  // If the user picks a non-vision model after attaching images, drop them so
  // we don't accidentally send a payload the model can't read.
  useEffect(() => {
    if (!supportsVision && attachments.length) setAttachments([]);
  }, [supportsVision, attachments.length]);

  return (
    <div
      className={clsx(
        `design-${selectedDesign}`,
        isUpdate && `theme-${theme}`,
        "h-full w-full overflow-hidden bg-bg text-text",
      )}
    >
      {isUpdate && (
        <div className="pointer-events-none fixed inset-0 overflow-hidden aurora-bg" />
      )}
      <div
        className={clsx(
          "relative flex h-full w-full",
          isUpdate && "themed-app-bg",
          isZero && "font-mono",
        )}
      >
        <Sidebar
          chats={chats}
          activeId={activeId}
          onSelect={onSelectChat}
          onNew={onNewChat}
          onDelete={onDeleteChat}
          design={selectedDesign}
        />
        <main
          className={clsx("flex h-full min-h-0 min-w-0 flex-1 flex-col", isUpdate && "p-4")}
        >
          <header
          className={clsx(
            "relative z-30 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-border-muted",
            isUpdate
              ? "themed-surface mb-4 min-h-[3.75rem] rounded-2xl border px-5 py-2.5 shadow-[0_8px_30px_-18px_rgba(15,23,42,0.35)] backdrop-blur-xl"
              : isZero
                ? "h-auto bg-bg px-3 py-2"
                : "min-h-14 bg-surface-1/50 px-4 py-2 backdrop-blur",
          )}
          >
            <div className="flex min-w-0 max-w-full flex-1 flex-col gap-0.5 sm:max-w-[40%]">
              <div className="truncate text-sm font-medium text-text">
                {headerTitle}
              </div>
              <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] uppercase tracking-wide text-text-subtle">
                {currentChat && modelById.get(headerModelId) && (
                  <span className="truncate">
                    {modelById.get(headerModelId)!.label}
                  </span>
                )}
                <span className="text-text-subtle/60">·</span>
                <span>
                  {selectedDesignConfig.shortLabel} · {selectedModeConfig.shortLabel}
                </span>
              </div>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2">
              <ModelPicker
                models={models}
                value={selectedModel}
                onChange={onModelChange}
              />
              <DesignPicker value={selectedDesign} onChange={setSelectedDesign} />
              {isUpdate && <ThemePicker value={theme} onChange={onThemeChange} />}
              <ResponseModePicker
                value={selectedMode}
                onChange={onModeChange}
                compact={isUpdate || isZero}
              />
            </div>
          </header>

          {isEmpty ? (
            <EmptyState
              onPick={(p) => setInput(p)}
              design={selectedDesign}
              mode={selectedMode}
              promptSeed={promptSeed}
            />
          ) : (
            <ChatView
              messages={messages}
              streamingId={streamingId}
              error={error}
              design={selectedDesign}
              toolStatus={toolStatus}
            />
          )}

          <div className="relative z-10 shrink-0 border-t border-border-muted bg-surface-1/40 backdrop-blur">
            <Composer
              value={input}
              onChange={setInput}
              onSubmit={onSubmit}
              onStop={onStop}
              design={selectedDesign}
              quickActions={QUICK_ACTIONS}
              busy={streaming}
              attachments={attachments}
              onAttachmentsChange={setAttachments}
              supportsVision={supportsVision}
              onAttachmentError={setError}
              webSearch={webSearch}
              onWebSearchChange={setWebSearch}
              searchAvailable={searchAvailable}
            />
          </div>
        </main>
      </div>
    </div>
  );
}
