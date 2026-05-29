import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * LoadingSkeleton — a stack of shimmering placeholder lines used while data
 * loads. `lines` controls how many rows; `variant="card"` wraps them in a card
 * surface for use inside list/grid layouts.
 */
export function LoadingSkeleton({
  lines = 4,
  className,
  variant = "lines",
}: {
  lines?: number;
  className?: string;
  variant?: "lines" | "card";
}) {
  const rows = (
    <div className={cn("space-y-3", className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className="h-4"
          // Vary widths so the placeholder reads like real text, not a grid.
          style={{ width: `${90 - (i % 3) * 15}%` }}
        />
      ))}
    </div>
  );

  if (variant === "card") {
    return (
      <div className="rounded-lg border bg-card p-6 shadow-sm">{rows}</div>
    );
  }
  return rows;
}

/** A grid of card skeletons for list pages. */
export function CardGridSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: count }).map((_, i) => (
        <LoadingSkeleton key={i} variant="card" lines={3} />
      ))}
    </div>
  );
}
