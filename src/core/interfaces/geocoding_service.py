"""IGeocodingService — contract for address normalization via Azure Maps."""

from typing import Protocol

from pydantic import BaseModel


class GeocodeResult(BaseModel):
    """
    Normalization outcome. `normalized_address` is the canonical form used for
    code-first project matching; `status` distinguishes a confident hit from a
    miss so the orchestrator knows whether the address is trustworthy.
    """

    normalized_address: str | None
    status: str  # "matched" | "ambiguous" | "not_found" | "error"
    confidence: float = 0.0


class IGeocodingService(Protocol):
    """Normalizes a free-text address into a canonical form (not distance)."""

    async def normalize(self, address: str) -> GeocodeResult: ...
