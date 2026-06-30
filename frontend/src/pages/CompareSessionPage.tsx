import { useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Loader2, AlertCircle, RefreshCw } from "lucide-react";
import { PageShell } from "@/components/layout/PageShell";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/common/EmptyState";
import { LoadingSkeleton } from "@/components/common/LoadingSkeleton";
import { ComparisonTable } from "@/components/comparison/ComparisonTable";
import { ChatPanel } from "@/components/comparison/ChatPanel";
import { SessionSummaryDialog } from "@/components/comparison/SessionSummary";
import { useComparison } from "@/hooks/useComparison";
import { apiClient } from "@/api/client";

/**
 * CompareSessionPage — THE core product surface (build doc 190, highest UX
 * priority). It places the assembled ComparisonTable beside a streaming
 * ChatPanel so the user reads the comparison and interrogates it in one view.
 *
 * Layout: on large screens the table takes the wider left column and the chat
 * docks to a fixed-height right column; on small screens they stack. While the
 * pipeline is still normalizing/comparing (phase !== "ready") we show progress
 * rather than an empty table.
 */
export function CompareSessionPage() {
  const { projectId = "", sessionId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const {
    session,
    table,
    messages,
    streaming,
    loading,
    error,
    sendMessage,
  } = useComparison(projectId, sessionId);

  const [summaryOpen, setSummaryOpen] = useState(false);

  const retry = useMutation({
    mutationFn: () => apiClient.startComparison(projectId, session!.jobId),
    onSuccess: (newSession) => {
      queryClient.setQueryData(["session", projectId, newSession.id], newSession);
      navigate(
        `/projects/${encodeURIComponent(projectId)}/compare/${encodeURIComponent(newSession.id)}`
      );
    },
  });

  if (loading) {
    return (
      <PageShell title="Comparison" fullBleed>
        <div className="p-6">
          <LoadingSkeleton lines={8} variant="card" />
        </div>
      </PageShell>
    );
  }

  if (error || !session) {
    return (
      <PageShell title="Comparison" fullBleed>
        <div className="p-6">
          <EmptyState
            icon={AlertCircle}
            title="Couldn't load this comparison"
            description="The session failed to load or no longer exists."
          />
        </div>
      </PageShell>
    );
  }

  const ready = session.phase === "ready" && table;

  return (
    <PageShell
      fullBleed
      breadcrumb={
        <Link
          to={`/projects/${encodeURIComponent(projectId)}`}
          className="hover:text-foreground"
        >
          ← {session.projectName}
        </Link>
      }
      title={session.jobName}
      description={
        <span className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{session.tradeCategory}</Badge>
          <span>{session.vendorNames.length} vendors</span>
          <span className="text-muted-foreground">·</span>
          <span className="truncate">{session.vendorNames.join(", ")}</span>
        </span>
      }
      actions={
        <Button
          variant="outline"
          onClick={() => setSummaryOpen(true)}
          disabled={!ready}
        >
          <FileText className="size-4" />
          Summary
        </Button>
      }
    >
      {/* Two-pane core layout: table (left) + chat (right). */}
      <div className="grid h-full min-h-0 grid-cols-1 gap-4 overflow-hidden px-4 pb-4 sm:px-6 lg:grid-cols-[minmax(0,1fr)_400px]">
        <div className="min-h-0 overflow-y-auto">
          {ready ? (
            <ComparisonTable table={table} />
          ) : session.phase === "failed" ? (
            <EmptyState
              icon={AlertCircle}
              title="Comparison failed"
              description="The comparison pipeline hit an error assembling this table."
              action={
                <Button
                  onClick={() => retry.mutate()}
                  disabled={retry.isPending}
                >
                  {retry.isPending ? (
                    <Loader2 className="mr-2 size-4 animate-spin" />
                  ) : (
                    <RefreshCw className="mr-2 size-4" />
                  )}
                  {retry.isPending ? "Starting…" : "Retry comparison"}
                </Button>
              }
            />
          ) : (
            <PipelineProgress phase={session.phase} />
          )}
        </div>

        <div className="min-h-0 lg:h-full">
          <ChatPanel
            messages={messages}
            streaming={streaming}
            onSend={sendMessage}
          />
        </div>
      </div>

      <SessionSummaryView
        open={summaryOpen}
        onOpenChange={setSummaryOpen}
        projectId={projectId}
        sessionId={sessionId}
      />
    </PageShell>
  );
}

/** Progress placeholder shown while Agents 5/6/7 assemble the table. */
function PipelineProgress({ phase }: { phase: string }) {
  const label =
    phase === "normalizing"
      ? "Normalizing units across bids…"
      : "Comparing costs and analyzing features…";
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
      <Loader2 className="size-8 animate-spin text-primary" />
      <div>
        <p className="font-medium">{label}</p>
        <p className="mt-1 text-sm text-muted-foreground">
          The agents are reading each bid document. This can take a moment.
        </p>
      </div>
    </div>
  );
}

/** Lazily fetches the session summary only when the dialog opens. */
function SessionSummaryView({
  open,
  onOpenChange,
  projectId,
  sessionId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  sessionId: string;
}) {
  const summaryQuery = useQuery({
    queryKey: ["session-summary", projectId, sessionId],
    queryFn: () => apiClient.getSessionSummary(projectId, sessionId),
    enabled: open,
  });

  return (
    <SessionSummaryDialog
      open={open}
      onOpenChange={onOpenChange}
      summary={summaryQuery.data ?? null}
      loading={summaryQuery.isLoading}
    />
  );
}
