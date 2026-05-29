import { TableCell, TableRow } from "@/components/ui/table";
import { cn, formatCurrency } from "@/lib/utils";
import type { CostRow as CostRowType } from "@/types";

/**
 * CostRow — one line item across all vendors in the cost comparison table.
 *
 * The cheapest cell on the row (cell.is_lowest) is highlighted green so the
 * lowest price jumps out at a glance — the single most important read in the
 * whole comparison. Per-cell flags (e.g. lump_sum_comparison_limited) render as
 * a small caveat marker, and missing values show an em dash rather than $0 so a
 * vendor who simply didn't bid an item isn't confused with one who bid zero.
 *
 * `outlierBidIds` (computed by ComparisonTable from cost_analysis) marks cells
 * the analysis flagged as significant deviations with an amber ring.
 */
export function CostRow({
  row,
  vendorOrder,
  outlierBidIds,
}: {
  row: CostRowType;
  /** Bid ids in the fixed column order shared by every row. */
  vendorOrder: string[];
  /** Bid ids flagged as outliers on this specific row label. */
  outlierBidIds: Set<string>;
}) {
  // Index cells by bid id so we render columns in the table's canonical order.
  const byBid = new Map(row.cells.map((c) => [c.bid_id, c]));

  return (
    <TableRow>
      <TableCell className="sticky left-0 z-10 bg-card font-medium">
        <div className="flex flex-col">
          <span>{row.label}</span>
          {row.normalized_unit && (
            <span className="text-xs font-normal text-muted-foreground">
              per {row.normalized_unit}
            </span>
          )}
        </div>
      </TableCell>

      {vendorOrder.map((bidId) => {
        const cell = byBid.get(bidId);
        if (!cell) {
          return (
            <TableCell key={bidId} className="text-center text-muted-foreground">
              —
            </TableCell>
          );
        }
        const hasValue = cell.value !== null && cell.value !== undefined;
        const isOutlier = outlierBidIds.has(bidId);
        return (
          <TableCell
            key={bidId}
            className={cn(
              "text-right tabular-nums",
              cell.is_lowest && hasValue && "bg-emerald-50",
              isOutlier && "ring-1 ring-inset ring-amber-300"
            )}
          >
            <div className="flex flex-col items-end gap-0.5">
              <span
                className={cn(
                  "font-medium",
                  cell.is_lowest && hasValue && "text-emerald-700"
                )}
                title={cell.original_text || undefined}
              >
                {hasValue ? formatCurrency(cell.value) : "—"}
              </span>
              {cell.flags.length > 0 && (
                <span
                  className="text-[10px] uppercase tracking-wide text-amber-600"
                  title={cell.flags.join(", ")}
                >
                  {cell.flags.length === 1 ? cell.flags[0] : `${cell.flags.length} flags`}
                </span>
              )}
            </div>
          </TableCell>
        );
      })}
    </TableRow>
  );
}
