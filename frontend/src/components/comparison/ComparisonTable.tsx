import { useMemo } from "react";
import { Trophy, TrendingUp, AlertTriangle, ChevronRight } from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { CostRow } from "./CostRow";
import { FeatureRow } from "./FeatureRow";
import { cn, formatCurrency } from "@/lib/utils";
import type {
  ComparisonTable as ComparisonTableType,
  FeatureRow as FeatureRowType,
  RedFlag,
  Severity,
  VendorTotal,
} from "@/types";

/**
 * ComparisonTable — THE core product surface. Renders the assembled comparison
 * (build doc section 7, Agents 6 + 7) as two stacked tables sharing one fixed
 * vendor column order:
 *
 *  1. COST: line-item rows (CostRow) with the cheapest cell highlighted and
 *     analysis-flagged outliers ringed, capped by a sticky totals row that
 *     marks the lowest overall bid with a trophy and shows scope caveats.
 *  2. FEATURES: non-cost rows grouped by category, sentiment-tinted, preceded
 *     by a red-flag callout strip for high/medium severity issues.
 *
 * The table is horizontally scrollable with a sticky first column so wide
 * vendor sets stay readable, and it degrades gracefully when a section is empty.
 */
const SEVERITY_META: Record<Severity, { label: string; cls: string }> = {
  high: { label: "High", cls: "bg-rose-100 text-rose-800 border-rose-200" },
  medium: { label: "Medium", cls: "bg-amber-100 text-amber-800 border-amber-200" },
  low: { label: "Low", cls: "bg-slate-100 text-slate-700 border-slate-200" },
};

export function ComparisonTable({ table }: { table: ComparisonTableType }) {
  // Canonical column order derived from totals (falls back to cost cells).
  const vendorOrder = useMemo(() => {
    if (table.totals.length > 0) return table.totals.map((t) => t.bid_id);
    const seen = new Set<string>();
    const order: string[] = [];
    for (const row of table.cost_rows) {
      for (const cell of row.cells) {
        if (!seen.has(cell.bid_id)) {
          seen.add(cell.bid_id);
          order.push(cell.bid_id);
        }
      }
    }
    return order;
  }, [table]);

  // Vendor name lookup for column headers.
  const vendorNames = useMemo(() => {
    const map = new Map<string, string>();
    for (const t of table.totals) map.set(t.bid_id, t.vendor_name);
    for (const row of table.cost_rows) {
      for (const cell of row.cells) {
        if (!map.has(cell.bid_id)) map.set(cell.bid_id, cell.vendor_name);
      }
    }
    return map;
  }, [table]);

  // Group feature rows by category, ordered by the most important row in each.
  const featureGroups = useMemo(() => {
    const groups = new Map<string, FeatureRowType[]>();
    for (const row of table.feature_rows) {
      const list = groups.get(row.category) ?? [];
      list.push(row);
      groups.set(row.category, list);
    }
    return [...groups.entries()]
      .map(([category, rows]) => ({
        category,
        rows: [...rows].sort((a, b) => a.importance_rank - b.importance_rank),
        rank: Math.min(...rows.map((r) => r.importance_rank)),
      }))
      .sort((a, b) => a.rank - b.rank);
  }, [table]);

  // Outliers keyed by row label → set of bid ids, for CostRow highlighting.
  const outliersByRow = useMemo(() => {
    const map = new Map<string, Set<string>>();
    for (const o of table.cost_analysis.significant_outliers) {
      const set = map.get(o.row_label) ?? new Set<string>();
      set.add(o.bid_id);
      map.set(o.row_label, set);
    }
    return map;
  }, [table]);

  const hasCost = table.cost_rows.length > 0 || table.totals.length > 0;
  const hasFeatures = table.feature_rows.length > 0;

  return (
    <div className="space-y-6">
      <AnalysisStrip table={table} vendorNames={vendorNames} />

      {hasCost && (
        <section>
          <SectionHeading icon={TrendingUp} title="Cost comparison" />
          <Card className="overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="sticky left-0 z-20 min-w-[180px] bg-card">
                    Line item
                  </TableHead>
                  {vendorOrder.map((bidId) => (
                    <TableHead
                      key={bidId}
                      className="min-w-[140px] text-right text-foreground"
                    >
                      {vendorNames.get(bidId) ?? bidId}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {table.cost_rows.map((row) => (
                  <CostRow
                    key={row.row_id}
                    row={row}
                    vendorOrder={vendorOrder}
                    outlierBidIds={
                      outliersByRow.get(row.label) ?? EMPTY_SET
                    }
                  />
                ))}
                <TotalsRow
                  totals={table.totals}
                  vendorOrder={vendorOrder}
                  lowestId={table.cost_analysis.lowest_total_bid_id}
                />
              </TableBody>
            </Table>
          </Card>
        </section>
      )}

      {table.red_flags.length > 0 && (
        <RedFlagStrip flags={table.red_flags} />
      )}

      {hasFeatures && (
        <section>
          <SectionHeading icon={ChevronRight} title="Feature comparison" />
          {table.feature_summary && (
            <p className="mb-3 text-sm text-muted-foreground">
              {table.feature_summary}
            </p>
          )}
          <Card className="overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="sticky left-0 z-20 min-w-[180px] bg-card">
                    Feature
                  </TableHead>
                  {vendorOrder.map((bidId) => (
                    <TableHead
                      key={bidId}
                      className="min-w-[180px] text-foreground"
                    >
                      {vendorNames.get(bidId) ?? bidId}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {featureGroups.map((group) => (
                  <FeatureGroup
                    key={group.category}
                    category={group.category}
                    rows={group.rows}
                    vendorOrder={vendorOrder}
                    colSpan={vendorOrder.length + 1}
                  />
                ))}
              </TableBody>
            </Table>
          </Card>
        </section>
      )}
    </div>
  );
}

const EMPTY_SET = new Set<string>();

function SectionHeading({
  icon: Icon,
  title,
}: {
  icon: typeof TrendingUp;
  title: string;
}) {
  return (
    <h2 className="mb-3 flex items-center gap-2 text-base font-semibold">
      <Icon className="size-4 text-muted-foreground" />
      {title}
    </h2>
  );
}

/** Headline analysis: lowest bid, spread, outlier count. */
function AnalysisStrip({
  table,
  vendorNames,
}: {
  table: ComparisonTableType;
  vendorNames: Map<string, string>;
}) {
  const { cost_analysis } = table;
  const lowest = cost_analysis.lowest_total_bid_id;
  const lowestTotal = table.totals.find((t) => t.bid_id === lowest);

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <Card>
        <CardContent className="flex items-center gap-3 p-4">
          <div className="flex size-9 items-center justify-center rounded-md bg-emerald-100 text-emerald-700">
            <Trophy className="size-4" />
          </div>
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">Lowest total</p>
            <p className="truncate font-semibold">
              {lowest ? vendorNames.get(lowest) ?? lowest : "—"}
            </p>
            {lowestTotal && (
              <p className="text-sm tabular-nums text-emerald-700">
                {formatCurrency(lowestTotal.total_price)}
              </p>
            )}
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="flex items-center gap-3 p-4">
          <div className="flex size-9 items-center justify-center rounded-md bg-blue-100 text-blue-700">
            <TrendingUp className="size-4" />
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Price spread</p>
            <p className="font-semibold tabular-nums">
              {cost_analysis.spread_percentage.toFixed(1)}%
            </p>
            <p className="text-xs text-muted-foreground">
              low to high total
            </p>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="flex items-center gap-3 p-4">
          <div className="flex size-9 items-center justify-center rounded-md bg-amber-100 text-amber-700">
            <AlertTriangle className="size-4" />
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Outliers flagged</p>
            <p className="font-semibold tabular-nums">
              {cost_analysis.significant_outliers.length}
            </p>
            <p className="text-xs text-muted-foreground">
              line items deviating &gt;30%
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

/** Sticky totals row with trophy on the lowest bid + scope caveats. */
function TotalsRow({
  totals,
  vendorOrder,
  lowestId,
}: {
  totals: VendorTotal[];
  vendorOrder: string[];
  lowestId: string | null;
}) {
  const byBid = new Map(totals.map((t) => [t.bid_id, t]));
  return (
    <TableRow className="border-t-2 bg-muted/50 hover:bg-muted/50">
      <TableCell className="sticky left-0 z-10 bg-muted/50 font-semibold">
        Total
      </TableCell>
      {vendorOrder.map((bidId) => {
        const total = byBid.get(bidId);
        if (!total) {
          return (
            <TableCell key={bidId} className="text-right text-muted-foreground">
              —
            </TableCell>
          );
        }
        const isLowest = bidId === lowestId;
        return (
          <TableCell key={bidId} className="text-right align-top">
            <div className="flex flex-col items-end gap-1">
              <span
                className={cn(
                  "flex items-center gap-1 text-base font-bold tabular-nums",
                  isLowest && "text-emerald-700"
                )}
              >
                {isLowest && <Trophy className="size-3.5" />}
                {formatCurrency(total.total_price)}
              </span>
              <span className="text-xs text-muted-foreground">
                {total.items_included} items
                {total.items_missing > 0 &&
                  ` · ${total.items_missing} missing`}
              </span>
              {total.scope_caveats.map((caveat, i) => (
                <span
                  key={i}
                  className="text-right text-[11px] text-amber-600"
                >
                  {caveat}
                </span>
              ))}
            </div>
          </TableCell>
        );
      })}
    </TableRow>
  );
}

/** Category header row + its feature rows. */
function FeatureGroup({
  category,
  rows,
  vendorOrder,
  colSpan,
}: {
  category: string;
  rows: FeatureRowType[];
  vendorOrder: string[];
  colSpan: number;
}) {
  return (
    <>
      <TableRow className="bg-muted/30 hover:bg-muted/30">
        <TableCell
          colSpan={colSpan}
          className="sticky left-0 z-10 py-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground"
        >
          {category}
        </TableCell>
      </TableRow>
      {rows.map((row) => (
        <FeatureRow key={row.row_id} row={row} vendorOrder={vendorOrder} />
      ))}
    </>
  );
}

/** Prominent strip of red flags above the feature table. */
function RedFlagStrip({ flags }: { flags: RedFlag[] }) {
  // Sort high → medium → low so the worst issues lead.
  const order: Severity[] = ["high", "medium", "low"];
  const sorted = [...flags].sort(
    (a, b) => order.indexOf(a.severity) - order.indexOf(b.severity)
  );
  return (
    <section>
      <SectionHeading icon={AlertTriangle} title="Red flags" />
      <div className="space-y-2">
        {sorted.map((flag, i) => {
          const meta = SEVERITY_META[flag.severity] ?? SEVERITY_META.low;
          return (
            <div
              key={i}
              className={cn(
                "flex items-start gap-3 rounded-md border p-3 text-sm",
                meta.cls
              )}
            >
              <Badge
                variant="outline"
                className="shrink-0 border-current bg-white/40"
              >
                {meta.label}
              </Badge>
              <div>
                <span className="font-medium">{flag.vendor_name}:</span>{" "}
                {flag.issue}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
