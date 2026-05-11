import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, streamMessage } from "./lib/api";
import type { Chat, ChatDetail, Message, ModelInfo } from "./lib/types";
import { Sidebar } from "./components/Sidebar";
import { ChatView } from "./components/ChatView";
import { Composer } from "./components/Composer";
import { ModelPicker } from "./components/ModelPicker";
import { EmptyState } from "./components/EmptyState";

export default function App() {
  const navigate = useNavigate();
  const params = useParams();
  const activeId = params.id ?? null;

  const [chats, setChats] = useState<Chat[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [currentChat, setCurrentChat] = useState<ChatDetail | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamingId, setStreamingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Initial load
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [m, c] = await Promise.all([api.listModels(), api.listChats()]);
        if (cancelled) return;
        setModels(m);
        setChats(c);
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
    let cancelled = false;
    (async () => {
      try {
        setError(null);
        const detail = await api.getChat(activeId);
        if (cancelled) return;
        setCurrentChat(detail);
        setMessages(detail.messages);
        setSelectedModel(detail.model);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Не удалось открыть чат");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeId]);

  const onNewChat = useCallback(() => {
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

  const onSubmit = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;

    setError(null);
    setStreaming(true);

    let chatId = activeId;
    let createdNew = false;

    try {
      if (!chatId) {
        const chat = await api.createChat({ model: selectedModel });
        chatId = chat.id;
        createdNew = true;
        setChats((prev) => [chat, ...prev]);
        setCurrentChat({ ...chat, messages: [] });
        setMessages([]);
        navigate(`/c/${chat.id}`, { replace: true });
      }

      setInput("");

      const controller = new AbortController();
      abortRef.current = controller;

      await streamMessage(
        chatId!,
        { content: text, model: selectedModel },
        {
          onMeta: ({ user_message, assistant_message_id, model }) => {
            setMessages((prev) => [
              ...prev,
              user_message,
              {
                id: assistant_message_id,
                chat_id: chatId!,
                role: "assistant",
                content: "",
                reasoning: "",
                model,
                created_at: new Date().toISOString(),
              },
            ]);
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
          onError: (message) => {
            setError(message);
            setStreamingId(null);
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
      abortRef.current = null;
    }
  }, [activeId, input, messages.length, navigate, selectedModel, streaming]);

  const onStop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const isEmpty = !currentChat || messages.length === 0;
  const headerTitle = currentChat?.title ?? "Новый чат";

  const modelById = useMemo(() => new Map(models.map((m) => [m.id, m])), [models]);
  const headerModelId = currentChat?.model ?? selectedModel;

  return (
    <div className="h-full w-full flex bg-bg text-text">
      <Sidebar
        chats={chats}
        activeId={activeId}
        onSelect={onSelectChat}
        onNew={onNewChat}
        onDelete={onDeleteChat}
      />
      <main className="flex-1 min-w-0 flex flex-col h-full">
        <header className="h-14 px-4 flex items-center justify-between border-b border-border-muted bg-surface-1/50 backdrop-blur">
          <div className="min-w-0 flex items-center gap-3">
            <div className="truncate text-sm font-medium text-text">
              {headerTitle}
            </div>
            {currentChat && modelById.get(headerModelId) && (
              <span className="text-[11px] uppercase tracking-wide text-text-subtle">
                {modelById.get(headerModelId)!.label}
              </span>
            )}
          </div>
          <ModelPicker
            models={models}
            value={selectedModel}
            onChange={onModelChange}
          />
        </header>

        {isEmpty ? (
          <EmptyState onPick={(p) => setInput(p)} />
        ) : (
          <ChatView
            messages={messages}
            streamingId={streamingId}
            error={error}
          />
        )}

        <div className="border-t border-border-muted bg-surface-1/40 backdrop-blur">
          <Composer
            value={input}
            onChange={setInput}
            onSubmit={onSubmit}
            onStop={onStop}
            busy={streaming}
          />
        </div>
      </main>
    </div>
  );
}
