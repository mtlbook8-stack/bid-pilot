import { FormEvent, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  FolderKanban,
  FileStack,
  Inbox,
  AlertCircle,
  Sparkles,
  Send,
  Lightbulb,
} from "lucide-react";
import { PageShell } from "@/components/layout/PageShell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { LoadingSkeleton } from "@/components/common/LoadingSkeleton";
import { BidCard } from "@/components/bids/BidCard";
import { EmptyState } from "@/components/common/EmptyState";
import { apiClient } from "@/api/client";
import type { DashboardAnswer, DashboardStats } from "@/types";

/**
 * DashboardPage — the daily-glance view (build doc workflow step 3). Shows the
 * portfolio stat tiles, a trade breakdown, recent bids, and a DashboardAnalyst
 * (Agent 12) natural-language ask box that answers portfolio questions with
 * structured data points and suggested actions.
 */
export function DashboardPage() {
  const statsQuery = useQuery({
    queryKey: ["stats"],
    queryFn: () => apiClient.getDashboardStats(),
  });

  return (
    <PageShell
      title="Dashboard"
      description="Your bid portfolio at a glance."
    >
      <div className="space-y-6">
        <AskBox />

        {statsQuery.isLoading ? (
          <LoadingSkeleton lines={4} variant="card" />
        ) : statsQuery.isError || !statsQuery.data ? (
          <EmptyState
            icon={AlertCircle}
            title="Couldn't load stats"
            description="The dashboard data failed to load. Try refreshing."
          />
        ) : (
          <>
            <StatTiles stats={statsQuery.data} />
            <TradeBreakdown
              data={statsQuery.data.bids_by_trade}
            />
            <div>
              <h2 className="mb-3 text-base font-semibold">Recent bids</h2>
              {statsQuery.data.recent_bids.length === 0 ? (
                <EmptyState
                  title="No bids yet"
                  description="Bids will appear here as they arrive by email."
                />
              ) : (
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {statsQuery.data.recent_bids.map((bid) => (
                    <BidCard key={bid.id} bid={bid} />
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </PageShell>
  );
}

function StatTiles({ stats }: { stats: DashboardStats }) {
  const tiles = [
    { label: "Projects", value: stats.total_projects, icon: FolderKanban },
    { label: "Total bids", value: stats.total_bids, icon: FileStack },
    { label: "Bids this week", value: stats.bids_this_week, icon: Inbox },
    {
      label: "Needs review",
      value: stats.needs_review,
      icon: AlertCircle,
      emphasis: stats.needs_review > 0,
    },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {tiles.map(({ label, value, icon: Icon, emphasis }) => (
        <Card key={label}>
          <CardContent className="flex items-center gap-3 p-4">
            <div
              className={
                emphasis
                  ? "flex size-9 items-center justify-center rounded-md bg-amber-100 text-amber-700"
                  : "flex size-9 items-center justify-center rounded-md bg-primary/10 text-primary"
              }
            >
              <Icon className="size-4" />
            </div>
            <div>
              <p className="text-2xl font-semibold tabular-nums">{value}</p>
              <p className="text-xs text-muted-foreground">{label}</p>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function TradeBreakdown({
  data,
}: {
  data: Array<{ trade: string; count: number }>;
}) {
  if (data.length === 0) return null;
  const max = Math.max(...data.map((d) => d.count), 1);
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Bids by trade</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {data.map((d) => (
          <div key={d.trade} className="flex items-center gap-3">
            <span className="w-40 shrink-0 truncate text-sm">{d.trade}</span>
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary"
                style={{ width: `${(d.count / max) * 100}%` }}
              />
            </div>
            <span className="w-8 text-right text-sm tabular-nums text-muted-foreground">
              {d.count}
            </span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

/** Natural-language portfolio ask box backed by DashboardAnalyst (Agent 12). */
function AskBox() {
  const [question, setQuestion] = useState("");
  const ask = useMutation<DashboardAnswer, Error, string>({
    mutationFn: (q) => apiClient.askDashboard(q),
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const q = question.trim();
    if (!q || ask.isPending) return;
    ask.mutate(q);
  };

  return (
    <Card className="border-primary/20 bg-primary/[0.03]">
      <CardContent className="p-4">
        <form onSubmit={submit} className="flex items-center gap-2">
          <Sparkles className="size-4 shrink-0 text-primary" />
          <Input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask about your portfolio — e.g. “How many bids came in this week?”"
            className="border-0 bg-transparent shadow-none focus-visible:ring-0"
            aria-label="Ask the dashboard analyst"
          />
          <Button
            type="submit"
            size="icon"
            disabled={ask.isPending || question.trim().length === 0}
            aria-label="Ask"
          >
            <Send className="size-4" />
          </Button>
        </form>

        {ask.isPending && (
          <div className="mt-3">
            <LoadingSkeleton lines={2} />
          </div>
        )}

        {ask.isError && (
          <p className="mt-3 text-sm text-destructive">
            {ask.error.message || "Couldn't answer that. Try rephrasing."}
          </p>
        )}

        {ask.data && <AnswerBlock answer={ask.data} />}
      </CardContent>
    </Card>
  );
}

function AnswerBlock({ answer }: { answer: DashboardAnswer }) {
  return (
    <div className="mt-3 space-y-3 border-t pt-3">
      <p className="text-sm leading-relaxed">{answer.answer}</p>

      {answer.data_points.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {answer.data_points.map((dp, i) => (
            <div
              key={i}
              className="rounded-md border bg-card px-3 py-1.5 text-sm"
            >
              <span className="text-muted-foreground">{dp.label}: </span>
              <span className="font-semibold tabular-nums">{dp.value}</span>
            </div>
          ))}
        </div>
      )}

      {answer.suggested_actions && answer.suggested_actions.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <Lightbulb className="size-4 text-amber-500" />
          {answer.suggested_actions.map((a, i) => (
            <Badge key={i} variant="warning">
              {a}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}
