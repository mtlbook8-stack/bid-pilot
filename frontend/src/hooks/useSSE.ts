import { useCallback, useRef, useState } from "react";
import { apiClient } from "@/api/client";

/**
 * useSSE — a generic Server-Sent-Events consumer built on the fetch streaming
 * API rather than the native EventSource.
 *
 * Why fetch and not EventSource: EventSource cannot set an Authorization header,
 * but every BidPilot SSE endpoint sits behind Entra auth. The fetch+ReadableStream
 * approach lets us attach the bearer token and use POST bodies (needed for the
 * chat endpoint, which sends the user's message). The hook parses the standard
 * `data: <json>\n\n` SSE frame format and hands each decoded event to onEvent.
 *
 * The generic parameter T is the union of event payloads the endpoint emits
 * (e.g. PollEvent, ChatStreamEvent), so callers get fully typed events.
 */
export interface UseSSEOptions<T> {
  /** Called for every parsed event frame. */
  onEvent: (event: T) => void;
  /** Called once when the stream closes cleanly. */
  onDone?: () => void;
  /** Called on transport/parse error. */
  onError?: (error: Error) => void;
}

export interface UseSSEResult {
  /** Open a connection. `body` is JSON-serialised for POST endpoints. */
  start: (url: string, body?: unknown) => Promise<void>;
  /** Abort the current stream. */
  stop: () => void;
  /** True while a stream is open. */
  active: boolean;
}

export function useSSE<T>({
  onEvent,
  onDone,
  onError,
}: UseSSEOptions<T>): UseSSEResult {
  const [active, setActive] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);

  const stop = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setActive(false);
  }, []);

  const start = useCallback(
    async (url: string, body?: unknown) => {
      // Tear down any previous stream before opening a new one.
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      setActive(true);

      try {
        const auth = await apiClient.authHeaders();
        const res = await fetch(url, {
          method: body !== undefined ? "POST" : "GET",
          signal: controller.signal,
          headers: {
            Accept: "text/event-stream",
            ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
            ...auth,
          },
          body: body !== undefined ? JSON.stringify(body) : undefined,
        });

        if (!res.ok || !res.body) {
          throw new Error(`SSE connection failed (${res.status})`);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        // Read until the server closes the stream or we abort.
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          // SSE frames are separated by a blank line. Process complete frames.
          let sep: number;
          while ((sep = buffer.indexOf("\n\n")) !== -1) {
            const frame = buffer.slice(0, sep);
            buffer = buffer.slice(sep + 2);
            this_parseFrame(frame, onEvent);
          }
        }

        setActive(false);
        controllerRef.current = null;
        onDone?.();
      } catch (err) {
        // AbortError is an intentional stop() — not an error to surface.
        if (err instanceof DOMException && err.name === "AbortError") {
          setActive(false);
          return;
        }
        setActive(false);
        controllerRef.current = null;
        onError?.(err instanceof Error ? err : new Error(String(err)));
      }
    },
    [onEvent, onDone, onError]
  );

  return { start, stop, active };
}

/**
 * Parse a single SSE frame: collect all `data:` lines, JSON-decode the payload,
 * and forward it. Comment lines (`:`) and other fields are ignored. Kept as a
 * module function (prefixed to avoid shadowing) so the hook body stays lean.
 */
function this_parseFrame<T>(frame: string, onEvent: (event: T) => void): void {
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }
  if (dataLines.length === 0) return;
  const payload = dataLines.join("\n");
  try {
    onEvent(JSON.parse(payload) as T);
  } catch {
    // Malformed frame — skip it rather than killing the whole stream.
  }
}
