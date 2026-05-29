import { Link } from "react-router-dom";
import { Building2, FileText } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { BidStatusBadge } from "./BidStatusBadge";
import { formatCurrency, formatDate } from "@/lib/utils";
import type { IngestedBid } from "@/types";

/**
 * BidCard — compact summary of one ingested bid for grids and lists. Links to
 * the bid detail page. Surfaces the vendor, trade, total, status, and scope so
 * the user can scan without opening each one.
 */
export function BidCard({ bid }: { bid: IngestedBid }) {
  return (
    <Link
      to={`/bids/${encodeURIComponent(bid.id)}`}
      className="block focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-lg"
    >
      <Card className="h-full transition-shadow hover:shadow-md">
        <CardContent className="flex h-full flex-col gap-3 p-4">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <Building2 className="size-4 shrink-0 text-muted-foreground" />
                <span className="truncate font-medium">
                  {bid.vendor_name ?? "Unknown vendor"}
                </span>
              </div>
              <p className="mt-0.5 truncate text-xs text-muted-foreground">
                {bid.email_subject}
              </p>
            </div>
            <BidStatusBadge status={bid.status} />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {bid.trade_category && (
              <Badge variant="outline">{bid.trade_category}</Badge>
            )}
            <span className="text-lg font-semibold tabular-nums">
              {formatCurrency(bid.total_price)}
            </span>
          </div>

          {bid.scope_summary && (
            <p className="line-clamp-2 text-sm text-muted-foreground">
              {bid.scope_summary}
            </p>
          )}

          <div className="mt-auto flex items-center justify-between pt-1 text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <FileText className="size-3.5" />
              <span className="max-w-[160px] truncate">
                {bid.attachment_filename}
              </span>
            </span>
            <span>{formatDate(bid.received_at)}</span>
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}
