"""
EmailFilter — code-only, pre-AI keyword gate for incoming mail (build doc 8.1).

This is the cheap first stage of email ingestion. Before any attachment is
uploaded to Blob or sent to Document Intelligence (and long before the LLM
QuoteValidator runs), this filter decides whether an email is even worth
processing. It is deterministic, runs entirely in-process, makes NO external
calls, and uses NO AI — that is intentional: it must be fast and free so the
30-minute poll can discard the bulk of unrelated mail without spending money.

The rule is simple and conservative: an email is worth processing only if it
has at least one attachment AND a bid-related keyword appears somewhere in the
subject, body, or any attachment filename. Tier 2 widens the net for emails that
clear the attachment bar but whose metadata is keyword-free, by re-checking
against text extracted from the attachment itself.
"""

import logging

logger = logging.getLogger(__name__)

# Default keyword list from build doc section 8.1. These are the words that
# reliably appear in construction bid correspondence; matching is case-insensitive
# and substring-based so "pricing" matches "Pricing", "repricing", etc.
_DEFAULT_KEYWORDS: tuple[str, ...] = (
    "quote",
    "estimate",
    "bid",
    "proposal",
    "price",
    "scope",
    "pricing",
    "cost",
    "invoice",
    "submittal",
)


class EmailFilter:
    """
    Decides whether an incoming email should enter the ingestion pipeline.

    Why a class (Rule 1): the keyword set is data this filter owns, and the
    matching logic is the behavior that acts on that data. Keeping them together
    lets the composition root inject a custom keyword list (e.g. a per-tenant
    override) without changing call sites.

    Why no AppError: this class performs no I/O and no external calls, so there
    is nothing to wrap (Rule 7 applies to external calls). It still guards its
    inputs defensively — a missing subject/body or a None in the filename list is
    treated as empty rather than allowed to raise — because it sits on the hot
    path for every polled email and must never crash the poll.
    """

    def __init__(self, keywords: list[str] | None = None) -> None:
        """
        Store the keyword set used for matching.

        Keywords are normalized to lowercase once at construction so the
        per-email match loop does not re-lowercase the same constants thousands
        of times across a poll. Blank entries are dropped so a stray "" cannot
        match every string.
        """
        source = keywords if keywords is not None else list(_DEFAULT_KEYWORDS)
        self._keywords: tuple[str, ...] = tuple(
            k.lower().strip() for k in source if k and k.strip()
        )

    def should_process(
        self,
        *,
        subject: str | None,
        body: str | None,
        attachment_filenames: list[str] | None,
    ) -> bool:
        """
        Tier 1 decision: process if there is at least one attachment.

        This mailbox is dedicated to receiving bids, so any email with an
        attachment is worth processing — Agent 1 (QuoteValidator) will decide
        downstream whether it is actually a bid. The only hard gate is the
        attachment requirement: an email with no attachment cannot carry a bid
        document and is skipped immediately.

        Returns False on empty/None inputs rather than raising.
        """
        filenames = [f for f in (attachment_filenames or []) if f]
        return bool(filenames)

    def should_process_with_text(
        self,
        *,
        subject: str | None,
        body: str | None,
        attachment_filenames: list[str] | None,
        extracted_text: str | None,
    ) -> bool:
        """
        Tier 2 fallback: when an email has attachments but NO keyword in its
        metadata, allow it through if a keyword appears in text extracted from
        the attachment (build doc 8.1 "Tier 2 fallback: in-memory text
        extraction from PDF").

        Why a separate method: Tier 2 only makes sense after Tier 1's metadata
        check fails and the caller has paid to extract attachment text. Splitting
        it keeps Tier 1 free of any extraction dependency. The attachment
        requirement still applies — extracted text without an attachment is not a
        meaningful case.

        If Tier 1 already passes on metadata alone, this returns True immediately
        without inspecting the (potentially large) extracted text.
        """
        if self.should_process(
            subject=subject,
            body=body,
            attachment_filenames=attachment_filenames,
        ):
            return True

        filenames = [f for f in (attachment_filenames or []) if f]
        # Mirror the Tier 1 invariant: extracted document text is only relevant
        # when there was an attachment to extract it from.
        if not filenames:
            return False

        return self._any_keyword_in([extracted_text or ""])

    def _any_keyword_in(self, haystacks: list[str]) -> bool:
        """
        Return True if any configured keyword appears (case-insensitive) in any
        of the provided strings.

        Each haystack is lowercased once and checked against the pre-lowercased
        keyword set. Substring matching is deliberate: it catches inflections
        ("priced", "pricing") and embedded forms ("Re:Bid") that a whole-word
        match would miss, which suits a permissive first-stage gate.
        """
        for raw in haystacks:
            if not raw:
                continue
            lowered = raw.lower()
            if any(keyword in lowered for keyword in self._keywords):
                return True
        return False
