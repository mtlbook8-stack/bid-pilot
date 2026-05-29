import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileStack, AlertCircle } from "lucide-react";
import { PageShell } from "@/components/layout/PageShell";
import { CardGridSkeleton } from "@/components/common/LoadingSkeleton";
import { EmptyState } from "@/components/common/EmptyState";
import { BidCard } from "@/components/bids/BidCard";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { apiClient } from "@/api/client";
import type { BidStatus } from "@/types";

/**
 * AllBidsPage — a searchable, status-filterable grid of every bid in the system.
 * Filtering is client-side over the fetched list (the dataset is small per the
 * build doc's scale notes), keeping the UI responsive without extra round-trips.
 */
const STATUS_FILTERS: Array<{ label: string; value: BidStatus | "all" }> = [
  { label: "All", value: "all" },
  { label: "Ready", value: "Categorized" },
  { label: "In progress", value: "Validating" },
  { label: "Failed", value: "Failed" },
];

const IN_PROGRESS: BidStatus[] = [
  "Parsed",
  "Validating",
  "Validated",
  "MatchingProject",
  "ProjectMatched",
  "CategorizingJob",
];

export function AllBidsPage() {
  const query = useQuery({
    queryKey: ["bids"],
    queryFn: () => apiClient.listBids(),
  });

  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<BidStatus | "all">("all");

  const filtered = useMemo(() => {
    const list = query.data ?? [];
    const term = search.trim().toLowerCase();
    return list.filter((bid) => {
      if (status === "Validating") {
        if (!IN_PROGRESS.includes(bid.status)) return false;
      } else if (status !== "all" && bid.status !== status) {
        return false;
      }
      if (!term) return true;
      return (
        (bid.vendor_name ?? "").toLowerCase().includes(term) ||
        bid.email_subject.toLowerCase().includes(term) ||
        (bid.trade_category ?? "").toLowerCase().includes(term) ||
        (bid.scope_summary ?? "").toLowerCase().includes(term)
      );
    });
  }, [query.data, search, status]);

  return (
    <PageShell title="All bids" description="Every bid ingested across all projects.">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search vendor, subject, trade, scope…"
          className="sm:max-w-sm"
          aria-label="Search bids"
        />
        <div className="flex gap-1">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              onClick={() => setStatus(f.value)}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                status === f.value
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {query.isLoading ? (
        <CardGridSkeleton />
      ) : query.isError ? (
        <EmptyState
          icon={AlertCircle}
          title="Couldn't load bids"
          description="The bid list failed to load. Try refreshing."
        />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={FileStack}
          title={query.data?.length ? "No matching bids" : "No bids yet"}
          description={
            query.data?.length
              ? "Try a different search or status filter."
              : "Bids will appear here as they arrive by email."
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((bid) => (
            <BidCard key={bid.id} bid={bid} />
          ))}
        </div>
      )}
    </PageShell>
  );
}
