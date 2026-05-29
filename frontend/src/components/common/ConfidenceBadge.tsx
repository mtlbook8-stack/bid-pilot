import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/**
 * ConfidenceBadge — colour-codes an agent confidence score (0–1) so reviewers
 * can triage at a glance:
 *   >= 0.9  emerald (high)
 *   0.7–0.9 default/blue (good)
 *   < 0.7   amber (needs review)
 * Below 0.5 reads as low/destructive-leaning amber as well, but we keep amber
 * for anything under 0.7 per the build instruction's "<0.7 amber" rule.
 */
export function ConfidenceBadge({
  value,
  className,
  showLabel = true,
}: {
  value: number | null | undefined;
  className?: string;
  showLabel?: boolean;
}) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return (
      <Badge variant="muted" className={className}>
        n/a
      </Badge>
    );
  }

  const pct = Math.round(value * 100);
  const variant: "success" | "default" | "warning" =
    value >= 0.9 ? "success" : value >= 0.7 ? "default" : "warning";

  return (
    <Badge variant={variant} className={cn("tabular-nums", className)}>
      {showLabel ? "Confidence " : ""}
      {pct}%
    </Badge>
  );
}
