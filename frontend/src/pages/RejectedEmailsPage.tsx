import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MailX, Undo2, AlertCircle, Loader2 } from "lucide-react";
import { PageShell } from "@/components/layout/PageShell";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfidenceBadge } from "@/components/common/ConfidenceBadge";
import { LoadingSkeleton } from "@/components/common/LoadingSkeleton";
import { EmptyState } from "@/components/common/EmptyState";
import { apiClient, ApiError } from "@/api/client";
import { formatDate } from "@/lib/utils";
import type { RejectionCategory } from "@/types";

/**
 * RejectedEmailsPage — lists emails QuoteValidator (Agent 1) classified as
 * non-bids (lightweight metadata only, build doc 6.4) and lets the user Restore
 * one. Restore re-ingests the email skipping Agent 1 and feeds a correction so
 * the system learns from the mistake (build doc 8.5).
 */
const REASON_LABELS: Record<RejectionCategory, string> = {
  not_construction: "Not construction",
  invoice_not_bid: "Invoice, not a bid",
  informational_only: "Informational only",
  duplicate: "Duplicate",
};

export function RejectedEmailsPage() {
  const query = useQuery({
    queryKey: ["rejected"],
    queryFn: () => apiClient.listRejected(),
  });

  return (
    <PageShell
      title="Rejected emails"
      description="Emails the validator decided weren't bids. Restore any it got wrong."
    >
      {query.isLoading ? (
        <LoadingSkeleton lines={6} variant="card" />
      ) : query.isError ? (
        <EmptyState
          icon={AlertCircle}
          title="Couldn't load rejected emails"
          description="The list failed to load. Try refreshing."
        />
      ) : !query.data || query.data.length === 0 ? (
        <EmptyState
          icon={MailX}
          title="Nothing rejected"
          description="When the validator rejects an email, it shows up here for review."
        />
      ) : (
        <Card className="overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Subject</TableHead>
                <TableHead>Sender</TableHead>
                <TableHead>Reason</TableHead>
                <TableHead>Confidence</TableHead>
                <TableHead>Received</TableHead>
                <TableHead className="text-right">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {query.data.map((email) => (
                <RejectedRow key={email.id} email={email} />
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </PageShell>
  );
}

function RejectedRow({
  email,
}: {
  email: import("@/types").RejectedEmailMetadata;
}) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const restore = useMutation({
    mutationFn: () => apiClient.restoreRejected(email.id),
    onSuccess: () => {
      // Row is removed server-side; drop it from the cached list + refresh bids.
      void queryClient.invalidateQueries({ queryKey: ["rejected"] });
      void queryClient.invalidateQueries({ queryKey: ["bids"] });
    },
    onError: (err) =>
      setError(
        err instanceof ApiError ? err.message : "Failed to restore this email."
      ),
  });

  return (
    <TableRow>
      <TableCell className="max-w-[260px] truncate font-medium">
        {email.subject}
      </TableCell>
      <TableCell className="text-muted-foreground">
        {email.senderEmail}
      </TableCell>
      <TableCell>
        <Badge variant="muted">
          {REASON_LABELS[email.rejectionReason] ?? email.rejectionReason}
        </Badge>
      </TableCell>
      <TableCell>
        <ConfidenceBadge value={email.agentConfidence} showLabel={false} />
      </TableCell>
      <TableCell className="text-muted-foreground">
        {formatDate(email.receivedAt)}
      </TableCell>
      <TableCell className="text-right">
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            setError(null);
            restore.mutate();
          }}
          disabled={restore.isPending}
        >
          {restore.isPending ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : (
            <Undo2 className="size-3.5" />
          )}
          Restore
        </Button>
        {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
      </TableCell>
    </TableRow>
  );
}
