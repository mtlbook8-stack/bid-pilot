import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
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
import { BidStatusBadge } from "@/components/bids/BidStatusBadge";
import { EmptyState } from "@/components/common/EmptyState";
import { apiClient } from "@/api/client";
import { formatCurrency } from "@/lib/utils";
import type {
  DashboardAnswer,
  DashboardRecentBid,
  DashboardStats,
} from "@/types";

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
            <StatusBreakdown data={statsQuery.data.bidsByStatus} />
            <div>
              <h2 className="mb-3 text-base font-semibold">Recent bids</h2>
              {statsQuery.data.recentBids.length === 0 ? (
                <EmptyState
                  title="No bids yet"
                  description="Bids will appear here as they arrive by email."
                />
              ) : (
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {statsQuery.data.recentBids.map((bid) => (
                    <RecentBidCard key={bid.id} bid={bid} />
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
    { label: "Projects", value: stats.totalProjects, icon: FolderKanban },
    { label: "Total bids", value: stats.totalBids, icon: FileStack },
    { label: "Comparisons", value: stats.totalSessions, icon: Inbox },
    {
      label: "Needs review",
      value: stats.needsReview,
      icon: AlertCircle,
      emphasis: stats.needsReview > 0,
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

/** Bids broken down by pipeline status (stats.bidsByStatus, a status→count map). */
function StatusBreakdown({ data }: { data: Record<string, number> }) {
  const entries = Object.entries(data);
  if (entries.length === 0) return null;
  const max = Math.max(...entries.map(([, count]) => count), 1);
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Bids by status</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {entries.map(([status, count]) => (
          <div key={status} className="flex items-center gap-3">
            <span className="w-40 shrink-0 truncate text-sm">{status}</span>
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary"
                style={{ width: `${(count / max) * 100}%` }}
              />
            </div>
            <span className="w-8 text-right text-sm tabular-nums text-muted-foreground">
              {count}
            </span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

/** Compact card for the reduced recent-bid shape embedded in DashboardStats. */
function RecentBidCard({ bid }: { bid: DashboardRecentBid }) {
  return (
    <Link
      to={`/bids/${encodeURIComponent(bid.id)}`}
      className="block rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <Card className="h-full transition-shadow hover:shadow-md">
        <CardContent className="flex h-full flex-col gap-2 p-4">
          <div className="flex items-start justify-between gap-2">
            <span className="truncate font-medium">
              {bid.vendorName ?? "Unknown vendor"}
            </span>
            <BidStatusBadge status={bid.status} />
          </div>
          <p className="truncate text-xs text-muted-foreground">{bid.subject}</p>
          <div className="mt-auto flex items-center justify-between pt-1">
            {bid.tradeCategory && (
              <Badge variant="outline">{bid.tradeCategory}</Badge>
            )}
            <span className="text-sm font-semibold tabular-nums">
              {formatCurrency(bid.totalPrice)}
            </span>
          </div>
        </CardContent>
      </Card>
    </Link>
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
