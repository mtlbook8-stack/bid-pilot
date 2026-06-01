import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Mail,
  Plus,
  RefreshCw,
  Unlink,
  AlertCircle,
  CheckCircle2,
  Loader2,
  CircleDot,
  Zap,
  ZapOff,
} from "lucide-react";
import { PageShell } from "@/components/layout/PageShell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { LoadingSkeleton } from "@/components/common/LoadingSkeleton";
import { EmptyState } from "@/components/common/EmptyState";
import { usePollProgress } from "@/hooks/usePollProgress";
import { apiClient, ApiError } from "@/api/client";
import { formatDate } from "@/lib/utils";
import type { LinkedAccount } from "@/types";

/**
 * EmailAccountsPage — manages linked Microsoft mailboxes. Lists each account
 * with its health and last-poll time, supports linking a new mailbox (OAuth
 * redirect), unlinking (with confirm), and "Poll Now" which streams live
 * ingestion progress via SSE (build doc 8.1) into an inline progress panel.
 */
export function EmailAccountsPage() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["email-accounts"],
    queryFn: () => apiClient.listEmailAccounts(),
  });

  // Handle OAuth-callback redirect: ?linked=ok|error[&detail=...]
  // The backend 303s back here after the OAuth round-trip; show a toast-style
  // banner, then strip the query params so a refresh doesn't re-trigger.
  const [linkBanner, setLinkBanner] = useState<
    { kind: "ok" | "error"; detail?: string } | null
  >(null);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const linked = params.get("linked");
    if (!linked) return;
    setLinkBanner({
      kind: linked === "ok" ? "ok" : "error",
      detail: params.get("detail") || undefined,
    });
    void queryClient.invalidateQueries({ queryKey: ["email-accounts"] });
    // Strip the query params from the URL so a refresh is idempotent.
    const url = new URL(window.location.href);
    url.searchParams.delete("linked");
    url.searchParams.delete("detail");
    window.history.replaceState({}, "", url.toString());
  }, [queryClient]);

  const link = useMutation({
    mutationFn: () => apiClient.getEmailLinkUrl(),
    onSuccess: (res) => {
      // Hand off to Microsoft's consent screen; backend handles the callback.
      window.location.href = res.authorizeUrl;
    },
  });

  return (
    <PageShell
      title="Email accounts"
      description="Linked mailboxes BidPilot watches for incoming bids."
      actions={
        <Button onClick={() => link.mutate()} disabled={link.isPending}>
          {link.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Plus className="size-4" />
          )}
          Link mailbox
        </Button>
      }
    >
      {linkBanner && (
        <div
          className={`mb-4 flex items-center gap-2 rounded-md border p-3 text-sm ${
            linkBanner.kind === "ok"
              ? "border-green-500/30 bg-green-500/10 text-green-700 dark:text-green-300"
              : "border-destructive/30 bg-destructive/10 text-destructive"
          }`}
        >
          {linkBanner.kind === "ok" ? (
            <>
              <CheckCircle2 className="size-4" /> Mailbox linked successfully.
            </>
          ) : (
            <>
              <AlertCircle className="size-4" /> Couldn't link mailbox
              {linkBanner.detail ? ` (${linkBanner.detail})` : ""}. Please try
              again.
            </>
          )}
        </div>
      )}

      {link.isError && (
        <p className="mb-4 text-sm text-destructive">
          {link.error instanceof ApiError
            ? link.error.message
            : "Couldn't start linking. Try again."}
        </p>
      )}

      {query.isLoading ? (
        <LoadingSkeleton lines={4} variant="card" />
      ) : query.isError ? (
        <EmptyState
          icon={AlertCircle}
          title="Couldn't load accounts"
          description="The account list failed to load. Try refreshing."
        />
      ) : !query.data || query.data.length === 0 ? (
        <EmptyState
          icon={Mail}
          title="No mailboxes linked"
          description="Link a Microsoft mailbox so BidPilot can ingest bids from it automatically."
          action={
            <Button onClick={() => link.mutate()} disabled={link.isPending}>
              <Plus className="size-4" /> Link mailbox
            </Button>
          }
        />
      ) : (
        <div className="space-y-4">
          {query.data.map((account) => (
            <AccountCard key={account.id} account={account} />
          ))}
        </div>
      )}
    </PageShell>
  );
}

function AccountCard({ account }: { account: LinkedAccount }) {
  const queryClient = useQueryClient();
  const { progress, poll, reset } = usePollProgress();
  const [confirmUnlink, setConfirmUnlink] = useState(false);

  const unlink = useMutation({
    mutationFn: () => apiClient.unlinkEmailAccount(account.id),
    onSuccess: () => {
      setConfirmUnlink(false);
      void queryClient.invalidateQueries({ queryKey: ["email-accounts"] });
    },
  });

  const onPoll = () => {
    reset();
    poll(account.id);
  };

  // When a poll completes, refresh bids + accounts so newly-created bids show up.
  const pollDone = Boolean(progress.result) && !progress.running;
  useEffect(() => {
    if (pollDone) {
      void queryClient.invalidateQueries({ queryKey: ["bids"] });
      void queryClient.invalidateQueries({ queryKey: ["email-accounts"] });
    }
  }, [pollDone, queryClient]);

  const health = healthMeta(account);
  const webhook = webhookMeta(account);

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="flex size-8 items-center justify-center rounded-md bg-primary/10 text-primary">
                <Mail className="size-4" />
              </span>
              <span className="truncate font-medium">
                {account.emailAddress}
              </span>
              <Badge variant={health.variant} className="gap-1">
                <health.icon className="size-3" />
                {health.label}
              </Badge>
              <Badge
                variant={webhook.variant}
                className="gap-1"
                title={webhook.tooltip}
              >
                <webhook.icon className="size-3" />
                {webhook.label}
              </Badge>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              Last polled {formatDate(account.lastProcessedAt)}
              {account.lastHealthCheckAt &&
                ` · checked ${formatDate(account.lastHealthCheckAt)}`}
            </p>
          </div>

          <div className="flex shrink-0 gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={onPoll}
              disabled={progress.running}
            >
              {progress.running ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <RefreshCw className="size-3.5" />
              )}
              Poll now
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setConfirmUnlink(true)}
            >
              <Unlink className="size-3.5" /> Unlink
            </Button>
          </div>
        </div>

        {(progress.running || progress.result || progress.error) && (
          <PollProgressPanel progress={progress} />
        )}
      </CardContent>

      <Dialog open={confirmUnlink} onOpenChange={setConfirmUnlink}>
        <DialogHeader>
          <DialogTitle>Unlink {account.emailAddress}?</DialogTitle>
          <DialogDescription>
            BidPilot will stop watching this mailbox for new bids. Existing bids
            are kept. You can re-link it later.
          </DialogDescription>
        </DialogHeader>
        {unlink.isError && (
          <p className="text-sm text-destructive">
            {unlink.error instanceof ApiError
              ? unlink.error.message
              : "Failed to unlink the account."}
          </p>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={() => setConfirmUnlink(false)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={() => unlink.mutate()}
            disabled={unlink.isPending}
          >
            {unlink.isPending ? "Unlinking…" : "Unlink"}
          </Button>
        </DialogFooter>
      </Dialog>
    </Card>
  );
}

/** Inline live progress for a manual poll (SSE events, build doc 8.1). */
function PollProgressPanel({
  progress,
}: {
  progress: ReturnType<typeof usePollProgress>["progress"];
}) {
  const pct =
    progress.total && progress.currentIndex
      ? Math.round((progress.currentIndex / progress.total) * 100)
      : progress.result
      ? 100
      : 0;

  return (
    <div className="mt-4 rounded-md border bg-muted/30 p-3 text-sm">
      {progress.error ? (
        <p className="flex items-center gap-2 text-destructive">
          <AlertCircle className="size-4" /> {progress.error}
        </p>
      ) : (
        <>
          <div className="mb-2 flex items-center justify-between">
            <span className="font-medium">
              {progress.result
                ? "Poll complete"
                : progress.total
                ? `Processing ${progress.currentIndex ?? 0} of ${progress.total}`
                : "Connecting…"}
            </span>
            {progress.running && (
              <Loader2 className="size-4 animate-spin text-muted-foreground" />
            )}
          </div>

          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-primary transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>

          {progress.currentEmail && !progress.result && (
            <p className="mt-2 truncate text-xs text-muted-foreground">
              {progress.currentEmail}
            </p>
          )}

          {progress.savedVendors.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {progress.savedVendors.map((v, i) => (
                <Badge key={`${v}-${i}`} variant="success">
                  {v}
                </Badge>
              ))}
            </div>
          )}

          {progress.result && (
            <p className="mt-2 text-xs text-muted-foreground">
              Created {progress.result.bidsCreated} bid
              {progress.result.bidsCreated === 1 ? "" : "s"} ·{" "}
              {progress.result.rejected} rejected.
            </p>
          )}
        </>
      )}
    </div>
  );
}

/** Map an account's health flags to a badge. */
function healthMeta(account: LinkedAccount): {
  label: string;
  variant: "success" | "warning" | "muted";
  icon: typeof CheckCircle2;
} {
  if (!account.isActive)
    return { label: "Inactive", variant: "muted", icon: CircleDot };
  if (account.lastHealthOk === false)
    return { label: "Needs attention", variant: "warning", icon: AlertCircle };
  return { label: "Healthy", variant: "success", icon: CheckCircle2 };
}

/**
 * Map an account's webhook subscription state to a badge.
 *
 * "Push" = active Graph subscription (new mail arrives within seconds).
 * "Polling" = no subscription; ingestion happens on the 30-min timer instead.
 * "Expired" = subscription exists but its expiry is in the past (renewer hasn't
 * caught up yet); polling still covers it.
 */
function webhookMeta(account: LinkedAccount): {
  label: string;
  variant: "success" | "warning" | "muted";
  icon: typeof Zap;
  tooltip: string;
} {
  if (!account.webhookSubscriptionId) {
    return {
      label: "Polling",
      variant: "muted",
      icon: ZapOff,
      tooltip: "No active webhook — new mail is picked up by the 30-min poll.",
    };
  }
  if (account.webhookExpiresAt) {
    const expired = new Date(account.webhookExpiresAt).getTime() < Date.now();
    if (expired) {
      return {
        label: "Webhook expired",
        variant: "warning",
        icon: AlertCircle,
        tooltip: `Subscription expired at ${account.webhookExpiresAt}. Renewer will restore push notifications.`,
      };
    }
  }
  return {
    label: "Push active",
    variant: "success",
    icon: Zap,
    tooltip: account.webhookExpiresAt
      ? `Graph webhook active until ${account.webhookExpiresAt}.`
      : "Graph webhook active.",
  };
}
