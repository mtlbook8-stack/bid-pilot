import { TableCell, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import type { FeatureRow as FeatureRowType, Sentiment } from "@/types";

/**
 * FeatureRow — one non-cost differentiator (schedule, warranty, exclusions, …)
 * compared across vendors. Each cell is tinted by its sentiment so favorable
 * terms (green) and unfavorable/missing ones (red/grey) are obvious without
 * reading every word. The source quote is exposed on hover for verification.
 */
const SENTIMENT_CLASS: Record<Sentiment, string> = {
  favorable: "bg-emerald-50 text-emerald-900",
  neutral: "bg-transparent text-foreground",
  unfavorable: "bg-rose-50 text-rose-900",
  not_specified: "bg-muted/40 text-muted-foreground italic",
};

const SENTIMENT_DOT: Record<Sentiment, string> = {
  favorable: "bg-emerald-500",
  neutral: "bg-slate-300",
  unfavorable: "bg-rose-500",
  not_specified: "bg-slate-200",
};

export function FeatureRow({
  row,
  vendorOrder,
}: {
  row: FeatureRowType;
  vendorOrder: string[];
}) {
  const byBid = new Map(row.cells.map((c) => [c.bid_id, c]));

  return (
    <TableRow className="align-top">
      <TableCell className="sticky left-0 z-10 bg-card font-medium">
        {row.label}
      </TableCell>

      {vendorOrder.map((bidId) => {
        const cell = byBid.get(bidId);
        if (!cell) {
          return (
            <TableCell
              key={bidId}
              className="text-center text-sm text-muted-foreground"
            >
              —
            </TableCell>
          );
        }
        return (
          <TableCell
            key={bidId}
            className={cn("text-sm", SENTIMENT_CLASS[cell.sentiment])}
          >
            <div className="flex items-start gap-2">
              <span
                className={cn(
                  "mt-1.5 size-2 shrink-0 rounded-full",
                  SENTIMENT_DOT[cell.sentiment]
                )}
                aria-hidden
              />
              <span title={cell.source_quote || undefined}>
                {cell.sentiment === "not_specified" && !cell.value
                  ? "Not specified"
                  : cell.value}
              </span>
            </div>
          </TableCell>
        );
      })}
    </TableRow>
  );
}
