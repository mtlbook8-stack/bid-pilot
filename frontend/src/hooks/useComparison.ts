import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSSE } from "./useSSE";
import { apiClient } from "@/api/client";
import type {
  ChatMessage,
  ChatStreamEvent,
  ComparisonSession,
  ComparisonTable,
} from "@/types";

/**
 * useComparison — owns all state for a single comparison session page: the
 * loaded session (table + history), the live chat transcript, and the streaming
 * send-message flow over SSE (build doc 8.3).
 *
 * The comparison table can be mutated mid-conversation: the orchestrator may
 * push a `table_update` event when a sub-agent edits it, so this hook keeps a
 * local `table` that overrides the initially loaded one once an update arrives.
 */
export interface UseComparisonResult {
  session: ComparisonSession | undefined;
  table: ComparisonTable | null;
  messages: ChatMessage[];
  /** True while an assistant reply is streaming in. */
  streaming: boolean;
  /** The specialist agent that handled (or is handling) the latest turn. */
  lastHandledBy: string | null;
  /** Initial load state for the session fetch. */
  loading: boolean;
  error: Error | null;
  /** Send a user message and stream the assistant reply. */
  sendMessage: (text: string) => void;
  /** Manually refetch the session document. */
  refetch: () => void;
}

export function useComparison(
  projectId: string,
  sessionId: string
): UseComparisonResult {
  // Load the session document (table + persisted history).
  const sessionQuery = useQuery({
    queryKey: ["session", projectId, sessionId],
    queryFn: () => apiClient.getSession(projectId, sessionId),
    enabled: Boolean(projectId && sessionId),
  });

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [table, setTable] = useState<ComparisonTable | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [lastHandledBy, setLastHandledBy] = useState<string | null>(null);

  // Index of the in-flight assistant message we're appending deltas to.
  const assistantIndexRef = useRef<number | null>(null);

  // Seed local state from the loaded session exactly once it arrives / changes.
  useEffect(() => {
    if (sessionQuery.data) {
      setMessages(sessionQuery.data.conversationHistory);
      setTable(sessionQuery.data.table);
    }
  }, [sessionQuery.data]);

  // The backend (comparison_service.chat) emits, per turn: a `routed` frame
  // naming the specialist, then a single `message` frame carrying the FULL
  // assistant reply (no token deltas), then `done`. An `error` frame carries
  // the AppError envelope. We fold each into the placeholder assistant turn.
  const handleEvent = useCallback((evt: ChatStreamEvent) => {
    // IMPORTANT: capture the ref value synchronously before scheduling any
    // state update. When `message` and `done` arrive in the same TCP chunk
    // they are processed in the same synchronous pass — the `done` branch sets
    // assistantIndexRef.current = null immediately, so reading the ref *inside*
    // a setMessages updater (which runs asynchronously on the next React flush)
    // would always see null and silently drop the message.
    const idx = assistantIndexRef.current;

    switch (evt.event) {
      case "routed":
        setLastHandledBy(evt.agent);
        setMessages((prev) => {
          if (idx === null) return prev;
          const next = [...prev];
          next[idx] = { ...next[idx], handledBy: evt.agent };
          return next;
        });
        break;
      case "message":
        if (evt.handledBy) setLastHandledBy(evt.handledBy);
        setMessages((prev) => {
          if (idx === null) return prev;
          const next = [...prev];
          next[idx] = {
            ...next[idx],
            content: evt.content,
            handledBy: evt.handledBy ?? next[idx].handledBy,
          };
          return next;
        });
        break;
      case "done":
        setStreaming(false);
        assistantIndexRef.current = null;
        break;
      case "error":
        setMessages((prev) => {
          if (idx === null) return prev;
          const next = [...prev];
          next[idx] = {
            ...next[idx],
            content:
              next[idx].content ||
              `Sorry — something went wrong handling that (${evt.message}).`,
          };
          return next;
        });
        setStreaming(false);
        assistantIndexRef.current = null;
        break;
    }
  }, []);

  const { start } = useSSE<ChatStreamEvent>({
    onEvent: handleEvent,
    onError: () => {
      setStreaming(false);
      assistantIndexRef.current = null;
    },
    onDone: () => {
      setStreaming(false);
      assistantIndexRef.current = null;
    },
  });

  const sendMessage = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || streaming) return;

      const now = new Date().toISOString();
      const userMsg: ChatMessage = {
        role: "user",
        content: trimmed,
        handledBy: null,
        createdAt: now,
      };
      const placeholder: ChatMessage = {
        role: "assistant",
        content: "",
        handledBy: null,
        createdAt: now,
      };

      setMessages((prev) => {
        const next = [...prev, userMsg, placeholder];
        // The assistant placeholder is the last element after this update.
        assistantIndexRef.current = next.length - 1;
        return next;
      });
      setStreaming(true);
      setLastHandledBy(null);

      void start(apiClient.getChatUrl(projectId, sessionId), {
        message: trimmed,
      });
    },
    [projectId, sessionId, start, streaming]
  );

  return {
    session: sessionQuery.data,
    table,
    messages,
    streaming,
    lastHandledBy,
    loading: sessionQuery.isLoading,
    error: sessionQuery.error as Error | null,
    sendMessage,
    refetch: sessionQuery.refetch,
  };
}
