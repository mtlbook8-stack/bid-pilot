"""
AzureMapsService — IGeocodingService backed by Azure Maps Search.

Normalizes a free-text construction-site address into a single canonical form
used for code-first project matching (build doc 8.2). This is address
NORMALIZATION, not distance/routing — the only thing the orchestrator cares
about is whether two bids resolve to the same canonical address string.

Authentication is managed-identity only: a `DefaultAzureCredential` bearer token
for the Azure Maps token audience plus the account's client id in the
`x-ms-client-id` header (the AAD auth scheme Azure Maps requires). No shared key
ever touches code or config (build doc — keyless access).
"""

import logging

import httpx
from azure.identity.aio import DefaultAzureCredential

from src.api.config import Settings
from src.core.errors.app_error import AppError
from src.core.interfaces.geocoding_service import GeocodeResult

logger = logging.getLogger(__name__)

# Token audience for Azure Maps AAD authentication. Azure Maps does not use the
# Cognitive Services scope — it has its own resource id.
_AZURE_MAPS_SCOPE = "https://atlas.microsoft.com/.default"

# Azure Maps Search address endpoint (REST, api-version 1.0). The base host is a
# fixed Azure Maps endpoint; per-account routing is done via the client-id header.
_SEARCH_ADDRESS_URL = "https://atlas.microsoft.com/search/address/json"
_SEARCH_API_VERSION = "1.0"

# A result at or above this confidence score is treated as a trustworthy hit.
# Azure Maps scores are positive floats where higher is better; 1.0+ is a strong
# match on a complete address. Below this we do not trust the normalization.
_HIGH_CONFIDENCE_SCORE = 1.0


class AzureMapsService:
    """
    IGeocodingService implementation over the Azure Maps Search Address API.

    Why this exists: project matching first tries an exact string compare of
    canonical addresses (cheap, no LLM). For that compare to work, every address
    must pass through the same normalizer, so a vendor writing "123 Elm St." and
    another writing "123 Elm Street" both collapse to one canonical form.

    Dependencies are injected (Rule 3): the HTTP client, the credential, and
    Settings arrive through the constructor so tests can substitute fakes and the
    composition root owns the single transport instance. Every external call is
    wrapped and re-raised as AppError "GEOCODE_AZURE_MAPS" (Rules 7/8); the
    service never logs — the top-level handler does.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        credential: DefaultAzureCredential,
        settings: Settings,
    ) -> None:
        self._http = http_client
        self._credential = credential
        self._settings = settings

    async def _get_bearer_token(self) -> str:
        """
        Fetch a fresh Azure Maps access token.

        Why per-call: azure-identity caches and refreshes internally, so calling
        get_token each request is cheap and guarantees we never send an expired
        token. Wrapped so an identity failure surfaces as a typed AppError
        instead of an opaque azure-core exception.
        """
        try:
            token = await self._credential.get_token(_AZURE_MAPS_SCOPE)
            return token.token
        except Exception as exc:
            raise AppError(
                code="GEOCODE_AZURE_MAPS",
                message="Failed to acquire Azure AD token for Azure Maps",
                context={"scope": _AZURE_MAPS_SCOPE},
                cause=exc,
            )

    async def normalize(self, address: str) -> GeocodeResult:
        """
        Resolve a free-text address to its canonical normalized form.

        Flow: call Azure Maps Search Address, then interpret the result set:
        - no results            → status "not_found"
        - one strong result, or one clearly-best result → status "matched"
        - multiple distinct strong results → status "ambiguous" (the address is
          underspecified, e.g. "Main St" with no city — the orchestrator must not
          trust it for an exact match)

        The canonical address is built from the top result's `freeformAddress`
        when present, falling back to a composed string from the structured
        address fields so we always emit a stable, comparable value.

        An empty/blank input short-circuits to "not_found" without a network
        call — there is nothing to geocode and the API would reject it anyway.
        """
        # Guard the input: a blank address is a definite miss, not an error, and
        # avoids a pointless round-trip.
        if not address or not address.strip():
            return GeocodeResult(
                normalized_address=None, status="not_found", confidence=0.0
            )

        token = await self._get_bearer_token()
        headers = {
            "Authorization": f"Bearer {token}",
            # Azure Maps AAD auth requires the account's client id alongside the
            # bearer token so it can scope the request to the right Maps account.
            "x-ms-client-id": self._settings.azure_maps_client_id,
        }
        params = {
            "api-version": _SEARCH_API_VERSION,
            "query": address.strip(),
        }

        try:
            response = await self._http.get(
                _SEARCH_ADDRESS_URL, headers=headers, params=params
            )
            response.raise_for_status()
        except Exception as exc:
            raise AppError(
                code="GEOCODE_AZURE_MAPS",
                message="Azure Maps search request failed",
                context={"address": address},
                cause=exc,
            )

        try:
            payload = response.json()
        except Exception as exc:
            raise AppError(
                code="GEOCODE_AZURE_MAPS",
                message="Could not parse Azure Maps response",
                context={"address": address},
                cause=exc,
            )

        # All parsing is defensive: the SDK-less REST shape can omit any field.
        # Interpretation is pure logic so it is wrapped only to convert an
        # unexpected structural error into a typed AppError.
        try:
            return self._interpret_results(payload)
        except Exception as exc:
            raise AppError(
                code="GEOCODE_AZURE_MAPS",
                message="Failed to interpret Azure Maps result set",
                context={"address": address},
                cause=exc,
            )

    def _interpret_results(self, payload: dict) -> GeocodeResult:
        """
        Turn a raw Search Address payload into a GeocodeResult.

        Distinctness check for ambiguity: two results with high confidence but
        DIFFERENT canonical addresses mean the query matched more than one real
        place, so we cannot trust any single normalization. Two high-confidence
        results that normalize to the SAME string are not ambiguous — they are
        the same place returned twice — so we still report "matched".
        """
        results = payload.get("results") or []
        if not results:
            return GeocodeResult(
                normalized_address=None, status="not_found", confidence=0.0
            )

        top = results[0]
        top_score = float(top.get("score", 0.0) or 0.0)
        normalized = self._build_canonical_address(top)

        # Collect the distinct canonical forms among high-confidence results to
        # decide between a confident match and a genuinely ambiguous query.
        high_conf_canonicals = {
            self._build_canonical_address(r)
            for r in results
            if float(r.get("score", 0.0) or 0.0) >= _HIGH_CONFIDENCE_SCORE
        }
        high_conf_canonicals.discard("")

        if len(high_conf_canonicals) > 1:
            return GeocodeResult(
                normalized_address=normalized or None,
                status="ambiguous",
                confidence=top_score,
            )

        if top_score >= _HIGH_CONFIDENCE_SCORE and normalized:
            return GeocodeResult(
                normalized_address=normalized,
                status="matched",
                confidence=top_score,
            )

        # There are results but none are confident enough to trust as a canonical
        # match; surface the best guess but mark it as not a reliable hit.
        if normalized:
            return GeocodeResult(
                normalized_address=normalized,
                status="matched" if top_score >= _HIGH_CONFIDENCE_SCORE else "not_found",
                confidence=top_score,
            )
        return GeocodeResult(
            normalized_address=None, status="not_found", confidence=top_score
        )

    @staticmethod
    def _build_canonical_address(result: dict) -> str:
        """
        Compose a stable canonical address string from one search result.

        Prefers `freeformAddress` (Azure's own normalized single-line form)
        because it is already consistent across queries. Falls back to composing
        from structured parts so a result lacking the freeform field still yields
        a comparable string. Returns "" when nothing usable is present so callers
        can treat it as "no canonical form".
        """
        addr = result.get("address") or {}
        freeform = (addr.get("freeformAddress") or "").strip()
        if freeform:
            return freeform

        # Compose from parts in a fixed order so the same place always produces
        # the same string regardless of which fields happen to be populated.
        parts = [
            addr.get("streetNumber"),
            addr.get("streetName") or addr.get("street"),
            addr.get("municipality"),
            addr.get("postalCode"),
            addr.get("country"),
        ]
        return ", ".join(p.strip() for p in parts if p and str(p).strip())
