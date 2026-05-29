import { CheckCircle2, Circle, Clock } from "lucide-react";
import {
  Dialog,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { LoadingSkeleton } from "@/components/common/LoadingSkeleton";
import type { DecisionStatus, SessionSummary as SessionSummaryType } from "@/types";

/**
 * SessionSummaryDialog — renders the SessionSummarizer (Agent 11) output as a
 * shareable, PM-friendly brief: a headline one-liner, decision status, and the
 * cost/feature/decisions/open-items breakdown. Shown in a modal so the user can
 * pull a summary without leaving the live comparison.
 */
const STATUS_META: Record<
  DecisionStatus,
  { label: string; variant: BadgeProps["variant"]; icon: typeof Circle }
> = {
  decided: { label: "Decided", variant: "success", icon: CheckCircle2 },
  leaning: { label: "Leaning", variant: "warning", icon: Clock },
  undecided: { label: "Undecided", variant: "muted", icon: Circle },
};

export function SessionSummaryDialog({
  open,
  onOpenChange,
  summary,
  loading,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  summary: SessionSummaryType | null;
  loading: boolean;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {loading || !summary ? (
        <>
          <DialogHeader>
            <DialogTitle>Generating summary…</DialogTitle>
            <DialogDescription>
              The session summarizer is reviewing the conversation and table.
            </DialogDescription>
          </DialogHeader>
          <LoadingSkeleton lines={6} />
        </>
      ) : (
        <SummaryBody summary={summary} />
      )}
    </Dialog>
  );
}

function SummaryBody({ summary }: { summary: SessionSummaryType }) {
  const status = STATUS_META[summary.recommendation_status] ?? STATUS_META.undecided;
  const StatusIcon = status.icon;

  return (
    <div className="max-h-[70vh] overflow-y-auto pr-1">
      <DialogHeader>
        <div className="flex items-center gap-2">
          <DialogTitle>{summary.title}</DialogTitle>
          <Badge variant={status.variant} className="gap-1">
            <StatusIcon className="size-3" />
            {status.label}
          </Badge>
        </div>
        <DialogDescription>{summary.one_liner}</DialogDescription>
      </DialogHeader>

      <div className="space-y-4 text-sm">
        <Section title="Overview">{summary.overview}</Section>
        <Section title="Cost comparison">{summary.cost_summary}</Section>
        <Section title="Non-cost factors">{summary.feature_summary}</Section>

        {summary.recommended_vendor && (
          <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3">
            <p className="text-xs font-medium uppercase tracking-wide text-emerald-700">
              Recommended
            </p>
            <p className="font-semibold text-emerald-900">
              {summary.recommended_vendor}
            </p>
          </div>
        )}

        {summary.decisions.length > 0 && (
          <ListSection title="Decisions made" items={summary.decisions} />
        )}
        {summary.open_items.length > 0 && (
          <ListSection title="Open items" items={summary.open_items} />
        )}
      </div>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h4>
      <p className="leading-relaxed text-foreground">{children}</p>
    </div>
  );
}

function ListSection({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h4>
      <ul className="space-y-1">
        {items.map((item, i) => (
          <li key={i} className="flex items-start gap-2 leading-relaxed">
            <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-muted-foreground/50" />
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}
