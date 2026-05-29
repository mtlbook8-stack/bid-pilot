import { FormEvent, useEffect, useRef, useState } from "react";
import { Send, Sparkles } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ChatMessageBubble } from "./ChatMessage";
import type { ChatMessage } from "@/types";

/**
 * ChatPanel — the conversational half of the comparison page. Streams a
 * transcript of the multi-agent conversation, auto-scrolls as replies arrive,
 * and offers a few suggested prompts to seed the interaction. The last
 * assistant turn is flagged as `streaming` so its typing indicator animates
 * while deltas land (build doc 8.3).
 */
const SUGGESTIONS = [
  "Who is cheapest overall and why?",
  "What does the lowest bid exclude?",
  "Compare the warranties.",
  "Help me decide between these vendors.",
];

export function ChatPanel({
  messages,
  streaming,
  onSend,
}: {
  messages: ChatMessage[];
  streaming: boolean;
  onSend: (text: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  // Keep the latest turn in view as the transcript grows / streams.
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const text = draft.trim();
    if (!text || streaming) return;
    onSend(text);
    setDraft("");
  };

  const lastAssistantIndex = (() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "assistant") return i;
    }
    return -1;
  })();

  return (
    <div className="flex h-full flex-col rounded-lg border bg-card">
      <div className="flex items-center gap-2 border-b px-4 py-3">
        <Sparkles className="size-4 text-primary" />
        <h2 className="text-sm font-semibold">Ask the comparison agents</h2>
      </div>

      <div
        ref={scrollRef}
        className="flex-1 space-y-3 overflow-y-auto p-4"
        aria-live="polite"
      >
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
            <p className="max-w-xs text-sm text-muted-foreground">
              Ask about pricing, exclusions, warranties, or which vendor to pick.
              A router sends each question to the right specialist agent.
            </p>
            <div className="flex flex-wrap justify-center gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => onSend(s)}
                  disabled={streaming}
                  className="rounded-full border bg-background px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground disabled:opacity-50"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((message, i) => (
            <ChatMessageBubble
              key={`${message.role}-${i}-${message.created_at}`}
              message={message}
              streaming={streaming && i === lastAssistantIndex}
            />
          ))
        )}
      </div>

      <form onSubmit={submit} className="flex items-center gap-2 border-t p-3">
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={streaming ? "Waiting for reply…" : "Ask a question…"}
          disabled={streaming}
          aria-label="Message the comparison agents"
        />
        <Button
          type="submit"
          size="icon"
          disabled={streaming || draft.trim().length === 0}
          aria-label="Send"
        >
          <Send className="size-4" />
        </Button>
      </form>
    </div>
  );
}
