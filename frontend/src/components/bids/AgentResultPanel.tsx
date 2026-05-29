import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfidenceBadge } from "@/components/common/ConfidenceBadge";
import { formatDate } from "@/lib/utils";
import type { AgentResult } from "@/types";

/**
 * AgentResultPanel — renders the per-agent decision trail attached to a bid
 * (bid.agentResults, keyed by agent name). Each agent's confidence, reasoning,
 * and raw structured output are shown so a reviewer can audit why the pipeline
 * classified/matched/categorized the bid as it did.
 */
export function AgentResultPanel({
  results,
}: {
  results: Record<string, AgentResult>;
}) {
  const entries = Object.entries(results);

  if (entries.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No agent results recorded yet.
      </p>
    );
  }

  // Render in pipeline order where known, otherwise alphabetical.
  const order = ["QuoteValidator", "ProjectMatcher", "JobCategorizer"];
  const sorted = [...entries].sort(([a], [b]) => {
    const ia = order.indexOf(a);
    const ib = order.indexOf(b);
    if (ia !== -1 && ib !== -1) return ia - ib;
    if (ia !== -1) return -1;
    if (ib !== -1) return 1;
    return a.localeCompare(b);
  });

  return (
    <div className="space-y-3">
      {sorted.map(([name, result]) => (
        <Card key={name}>
          <CardHeader className="flex-row items-center justify-between space-y-0 py-3">
            <CardTitle className="text-sm">{result.agentName || name}</CardTitle>
            <ConfidenceBadge value={result.confidence} />
          </CardHeader>
          <CardContent className="space-y-3 pt-0">
            {result.reasoning && (
              <p className="text-sm text-muted-foreground">{result.reasoning}</p>
            )}
            <details className="group">
              <summary className="cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground">
                Raw output
              </summary>
              <pre className="mt-2 max-h-64 overflow-auto rounded-md bg-muted p-3 text-xs">
                {JSON.stringify(result.rawOutput, null, 2)}
              </pre>
            </details>
            <p className="text-xs text-muted-foreground">
              {formatDate(result.createdAt)}
            </p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
