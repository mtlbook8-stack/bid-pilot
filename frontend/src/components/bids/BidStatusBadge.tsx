import { Badge, type BadgeProps } from "@/components/ui/badge";
import type { BidStatus } from "@/types";

/**
 * BidStatusBadge — maps each pipeline status (build doc 8.2 / BidStatus enum)
 * to a colour + readable label. In-progress checkpoint states read as "muted"
 * (work ongoing), terminal success as "success", failure/rejection as warning
 * or destructive.
 */
const STATUS_META: Record<
  BidStatus,
  { label: string; variant: BadgeProps["variant"] }
> = {
  Parsed: { label: "Parsed", variant: "muted" },
  Validating: { label: "Validating", variant: "secondary" },
  Validated: { label: "Validated", variant: "secondary" },
  MatchingProject: { label: "Matching project", variant: "secondary" },
  ProjectMatched: { label: "Project matched", variant: "secondary" },
  CategorizingJob: { label: "Categorizing", variant: "secondary" },
  Categorized: { label: "Ready", variant: "success" },
  Rejected: { label: "Rejected", variant: "warning" },
  Failed: { label: "Failed", variant: "destructive" },
};

export function BidStatusBadge({ status }: { status: BidStatus }) {
  const meta = STATUS_META[status] ?? {
    label: status,
    variant: "muted" as const,
  };
  return <Badge variant={meta.variant}>{meta.label}</Badge>;
}
