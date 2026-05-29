import { Bot, User } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { ChatMessage as ChatMessageType } from "@/types";

/**
 * ChatMessageBubble — one turn in the comparison conversation.
 *
 * User turns align right with the primary colour; assistant turns align left
 * with a bot avatar and, crucially, a small badge naming which specialist agent
 * handled the reply (message.handledBy — e.g. CostComparator, FeatureAnalyst),
 * so the user understands which expert answered (build doc 8.3). A streaming
 * assistant turn with no text yet shows an animated typing indicator.
 */
const AGENT_LABELS: Record<string, string> = {
  cost_comparator: "Cost analysis",
  feature_analyst: "Feature analysis",
  data_query: "Data query",
  unit_normalizer: "Unit normalizer",
  session_summarizer: "Session summary",
  decision_explainer: "Decision advisor",
  table_update: "Table update",
  clarification: "Clarifying",
};

function agentLabel(handledBy: string): string {
  return AGENT_LABELS[handledBy] ?? handledBy;
}

export function ChatMessageBubble({
  message,
  streaming = false,
}: {
  message: ChatMessageType;
  /** True when this is the assistant turn currently receiving deltas. */
  streaming?: boolean;
}) {
  const isUser = message.role === "user";
  const isEmptyAssistant = !isUser && message.content.length === 0;

  return (
    <div
      className={cn(
        "flex w-full animate-fade-in gap-2",
        isUser ? "justify-end" : "justify-start"
      )}
    >
      {!isUser && (
        <span className="mt-1 flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
          <Bot className="size-4" />
        </span>
      )}

      <div
        className={cn(
          "max-w-[80%] rounded-lg px-3 py-2 text-sm",
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted text-foreground"
        )}
      >
        {!isUser && message.handledBy && (
          <Badge variant="secondary" className="mb-1.5 text-[10px]">
            {agentLabel(message.handledBy)}
          </Badge>
        )}
        {isEmptyAssistant && streaming ? (
          <TypingDots />
        ) : (
          <p className="whitespace-pre-wrap leading-relaxed">{message.content}</p>
        )}
      </div>

      {isUser && (
        <span className="mt-1 flex size-7 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
          <User className="size-4" />
        </span>
      )}
    </div>
  );
}

function TypingDots() {
  return (
    <span className="flex items-center gap-1 py-1" aria-label="Assistant is typing">
      {[0, 150, 300].map((delay) => (
        <span
          key={delay}
          className="size-1.5 animate-bounce rounded-full bg-muted-foreground/60"
          style={{ animationDelay: `${delay}ms` }}
        />
      ))}
    </span>
  );
}
