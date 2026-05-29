import { useCallback, useState } from "react";
import { useSSE } from "./useSSE";
import { apiClient } from "@/api/client";
import type { PollEvent } from "@/types";

/**
 * usePollProgress — drives the "Poll Now" live-progress experience for a linked
 * mailbox (build doc 8.1). It connects to the manual-poll SSE endpoint and
 * folds the `started / emails_found / processing / bid_saved / completed`
 * events into a single progress view the EmailAccountsPage renders.
 */
export interface PollProgress {
  /** Whether a poll is currently streaming. */
  running: boolean;
  /** The mailbox address echoed back on `started`. */
  account: string | null;
  /** Total emails the account reported (from `emails_found`). */
  total: number | null;
  /** Index of the email currently processing (from `processing`). */
  currentIndex: number | null;
  /** Subject line of the email currently processing. */
  currentEmail: string | null;
  /** Vendors of bids saved during this run (from `bid_saved`). */
  savedVendors: string[];
  /** Terminal counts once `completed` arrives. */
  result: { bidsCreated: number; rejected: number } | null;
  /** A user-safe error message if the stream failed. */
  error: string | null;
}

const EMPTY: PollProgress = {
  running: false,
  account: null,
  total: null,
  currentIndex: null,
  currentEmail: null,
  savedVendors: [],
  result: null,
  error: null,
};

export function usePollProgress() {
  const [progress, setProgress] = useState<PollProgress>(EMPTY);

  const handleEvent = useCallback((evt: PollEvent) => {
    setProgress((prev) => {
      switch (evt.event) {
        case "started":
          // Fresh run: reset everything but mark running.
          return { ...EMPTY, running: true, account: evt.account };
        case "emails_found":
          return { ...prev, total: evt.count };
        case "processing":
          return {
            ...prev,
            currentIndex: evt.index,
            currentEmail: evt.email,
            total: evt.total,
          };
        case "bid_saved":
          return { ...prev, savedVendors: [...prev.savedVendors, evt.vendor] };
        case "completed":
          return {
            ...prev,
            running: false,
            result: { bidsCreated: evt.bids_created, rejected: evt.rejected },
          };
        case "error":
          return { ...prev, running: false, error: evt.message };
        default:
          return prev;
      }
    });
  }, []);

  const { start, stop, active } = useSSE<PollEvent>({
    onEvent: handleEvent,
    onError: (err) =>
      setProgress((prev) => ({ ...prev, running: false, error: err.message })),
  });

  /** Begin polling a specific linked account. */
  const poll = useCallback(
    (accountId: string) => {
      setProgress({ ...EMPTY, running: true });
      // GET SSE endpoint — no body, so useSSE issues a GET stream.
      void start(apiClient.getPollUrl(accountId));
    },
    [start]
  );

  /** Reset back to the idle state (e.g. to clear a finished/failed run). */
  const reset = useCallback(() => {
    stop();
    setProgress(EMPTY);
  }, [stop]);

  return { progress, poll, reset, active };
}
