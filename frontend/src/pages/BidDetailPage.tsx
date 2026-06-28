import { FormEvent, useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  FileText,
  Building2,
  AlertCircle,
  Pencil,
  Check,
  X,
} from "lucide-react";
import { PageShell } from "@/components/layout/PageShell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LoadingSkeleton } from "@/components/common/LoadingSkeleton";
import { EmptyState } from "@/components/common/EmptyState";
import { BidStatusBadge } from "@/components/bids/BidStatusBadge";
import { AgentResultPanel } from "@/components/bids/AgentResultPanel";
import { apiClient, ApiError } from "@/api/client";
import { formatCurrency, formatDate } from "@/lib/utils";
import type { CorrectionType, IngestedBid } from "@/types";

const IMAGE_EXTS = new Set(["jpg", "jpeg", "png", "gif", "webp", "bmp", "svg"]);
const PDF_EXTS = new Set(["pdf"]);

function fileExt(filename: string | null | undefined): string {
  return (filename ?? "").split(".").pop()?.toLowerCase() ?? "";
}


/**
 * Fetches a protected API URL with the Bearer token and returns a blob: URL
 * the browser can load without needing auth headers on its own. Revokes the
 * blob URL on unmount to avoid memory leaks.
 */
function useAuthBlobUrl(apiUrl: string) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;

    async function load() {
      try {
        const headers = await apiClient.authHeaders();
        const res = await fetch(apiUrl, { headers });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const blob = await res.blob();
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setBlobUrl(objectUrl);
      } catch {
        if (!cancelled) setFailed(true);
      }
    }

    void load();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [apiUrl]);

  return { blobUrl, failed };
}

function AttachmentViewer({
  blobUrl,
  failed,
  apiUrl,
  filename,
}: {
  blobUrl: string | null;
  failed: boolean;
  apiUrl: string;
  filename: string | null | undefined;
}) {
  const ext = fileExt(filename);

  if (failed) return <DownloadFallback url={apiUrl} filename={filename} />;

  if (!blobUrl) {
    return (
      <div className="flex h-[600px] items-center justify-center bg-muted">
        <div className="size-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }

  if (IMAGE_EXTS.has(ext)) {
    return (
      <div className="flex h-[600px] items-center justify-center bg-muted p-4">
        <img
          src={blobUrl}
          alt={filename ?? "attachment"}
          className="max-h-full max-w-full object-contain"
        />
      </div>
    );
  }

  if (PDF_EXTS.has(ext)) {
    return (
      <object
        data={blobUrl}
        type="application/pdf"
        className="h-[600px] w-full bg-muted"
        aria-label="Original bid document"
      >
        <DownloadFallback url={apiUrl} filename={filename} />
      </object>
    );
  }

  return <DownloadFallback url={apiUrl} filename={filename} />;
}

function DownloadFallback({
  url,
  filename,
}: {
  url: string;
  filename: string | null | undefined;
}) {
  return (
    <div className="flex h-[600px] flex-col items-center justify-center gap-3 p-6 text-sm text-muted-foreground">
      <FileText className="size-8 opacity-40" />
      <p>No preview available for this file type.</p>
      <a
        href={url}
        target="_blank"
        rel="noreferrer"
        className="text-primary hover:underline"
      >
        Download {filename}
      </a>
    </div>
  );
}

function BidDocumentCard({ bid }: { bid: IngestedBid }) {
  const apiUrl = apiClient.getBidPdfUrl(bid.id);
  const { blobUrl, failed } = useAuthBlobUrl(apiUrl);

  return (
    <Card className="overflow-hidden">
      <CardHeader className="flex-row items-center justify-between space-y-0 py-3">
        <CardTitle className="flex items-center gap-2 text-sm">
          <FileText className="size-4" />
          <span className="max-w-[220px] truncate">
            {bid.attachmentFilename}
          </span>
        </CardTitle>
        {blobUrl && (
          <a
            href={blobUrl}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-primary hover:underline"
          >
            Open in new tab
          </a>
        )}
      </CardHeader>
      <CardContent className="p-0">
        <AttachmentViewer
          blobUrl={blobUrl}
          failed={failed}
          apiUrl={apiUrl}
          filename={bid.attachmentFilename}
        />
      </CardContent>
    </Card>
  );
}

/**
 * BidDetailPage — the full record for one bid: a side-by-side of the original
 * PDF (streamed through the API blob proxy, build doc decision I1) and the
 * extracted metadata, the per-agent decision trail, and inline correction
 * actions for the project / trade / validation dimensions (build doc 8.4). Each
 * correction feeds the CorrectionDistiller, so the UI confirms submission.
 */
export function BidDetailPage() {
  const { bidId = "" } = useParams();
  const query = useQuery({
    queryKey: ["bid", bidId],
    queryFn: () => apiClient.getBid(bidId),
    enabled: Boolean(bidId),
  });

  if (query.isLoading) {
    return (
      <PageShell title="Bid">
        <LoadingSkeleton lines={6} variant="card" />
      </PageShell>
    );
  }
  if (query.isError || !query.data) {
    return (
      <PageShell title="Bid">
        <EmptyState
          icon={AlertCircle}
          title="Couldn't load this bid"
          description="The bid failed to load or no longer exists."
        />
      </PageShell>
    );
  }

  const bid = query.data;

  return (
    <PageShell
      breadcrumb={
        <Link to="/bids" className="hover:text-foreground">
          ← All bids
        </Link>
      }
      title={bid.vendorName ?? "Unknown vendor"}
      description={bid.emailSubject}
      actions={<BidStatusBadge status={bid.status} />}
    >
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <BidDocumentCard bid={bid} />

        {/* Right: metadata, corrections, agent trail */}
        <div className="space-y-6">
          <BidFacts bid={bid} />
          <CorrectionsCard bid={bid} />
          <div>
            <h2 className="mb-3 text-base font-semibold">Agent decisions</h2>
            <AgentResultPanel results={bid.agentResults} />
          </div>
        </div>
      </div>
    </PageShell>
  );
}

function BidFacts({ bid }: { bid: IngestedBid }) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Details</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-3 text-sm">
        <Fact label="Vendor" value={bid.vendorName ?? "—"} icon={Building2} />
        <Fact label="Total" value={formatCurrency(bid.totalPrice)} />
        <Fact label="Trade" value={bid.tradeCategory ?? "—"} />
        <Fact label="Sender" value={bid.senderEmail} />
        <Fact label="Received" value={formatDate(bid.receivedAt)} />
        <Fact
          label="Address"
          value={bid.addressFromBid ?? bid.normalizedAddress ?? "—"}
        />
        {bid.scopeSummary && (
          <div className="col-span-2">
            <p className="text-xs text-muted-foreground">Scope</p>
            <p>{bid.scopeSummary}</p>
          </div>
        )}
        {bid.secondaryTrades.length > 0 && (
          <div className="col-span-2 flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-muted-foreground">Also covers:</span>
            {bid.secondaryTrades.map((t) => (
              <Badge key={t} variant="muted">
                {t}
              </Badge>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Fact({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string;
  icon?: typeof Building2;
}) {
  return (
    <div className="min-w-0">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="flex items-center gap-1.5 truncate font-medium">
        {Icon && <Icon className="size-3.5 shrink-0 text-muted-foreground" />}
        {value}
      </p>
    </div>
  );
}

/** Inline correction editors for project / trade / validation. */
function CorrectionsCard({ bid }: { bid: IngestedBid }) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Corrections</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <CorrectionField
          bid={bid}
          type="trade"
          label="Trade category"
          current={bid.tradeCategory ?? ""}
          placeholder="e.g. Plumbing"
        />
        <CorrectionField
          bid={bid}
          type="project"
          label="Project"
          current={bid.matchedProjectId ?? ""}
          placeholder="Correct project id or name"
        />
        <CorrectionField
          bid={bid}
          type="validation"
          label="Is this a bid?"
          current={bid.isBid === false ? "Not a bid" : "Is a bid"}
          placeholder="isBid=true / isBid=false"
        />
      </CardContent>
    </Card>
  );
}

function CorrectionField({
  bid,
  type,
  label,
  current,
  placeholder,
}: {
  bid: IngestedBid;
  type: CorrectionType;
  label: string;
  current: string;
  placeholder: string;
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");

  const mutation = useMutation({
    mutationFn: () =>
      apiClient.submitCorrection(bid.id, type, {
        correctedValue: value.trim(),
        reason: reason.trim() || undefined,
      }),
    onSuccess: () => {
      setEditing(false);
      setValue("");
      setReason("");
      // The bid was updated server-side; refetch to reflect new values.
      void queryClient.invalidateQueries({ queryKey: ["bid", bid.id] });
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!value.trim() || mutation.isPending) return;
    mutation.mutate();
  };

  if (!editing) {
    return (
      <div className="flex items-center justify-between gap-3 rounded-md border p-3">
        <div className="min-w-0">
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="truncate text-sm font-medium">{current || "—"}</p>
          {mutation.isSuccess && (
            <p className="text-xs text-emerald-600">
              Correction saved — the system will learn from it.
            </p>
          )}
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            setEditing(true);
            mutation.reset();
          }}
        >
          <Pencil className="size-3.5" /> Correct
        </Button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-2 rounded-md border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <Input
        autoFocus
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={placeholder}
        aria-label={`Corrected ${label}`}
      />
      <Input
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="Why? (optional — helps the system learn)"
        aria-label="Reason"
      />
      {mutation.isError && (
        <p className="text-xs text-destructive">
          {mutation.error instanceof ApiError
            ? mutation.error.message
            : "Failed to save correction."}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setEditing(false)}
        >
          <X className="size-3.5" /> Cancel
        </Button>
        <Button
          type="submit"
          size="sm"
          disabled={!value.trim() || mutation.isPending}
        >
          <Check className="size-3.5" />
          {mutation.isPending ? "Saving…" : "Save"}
        </Button>
      </div>
    </form>
  );
}
