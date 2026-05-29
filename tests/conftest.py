"""
Shared pytest fixtures.

Keeps the unit suite dependency-light: the tests here exercise pure domain logic
(error chaining, JSON parsing, enums, cost math, the sandbox) that needs no Azure
services, so the whole suite runs offline in CI and in web sessions.
"""

import sys
from pathlib import Path

import pytest

# Make `src` importable when tests run from the repo root without installation.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@pytest.fixture
def sample_normalizer_output() -> dict:
    """A minimal UnitNormalizer-shaped payload for cost-code style tests."""
    return {
        "groups": [
            {
                "group_id": "g1",
                "group_label": "Rooftop units",
                "normalized_unit": "EA",
                "bids": [
                    {"bid_id": "b1", "vendor_name": "ABC", "normalized_extended_price": 40000.0},
                    {"bid_id": "b2", "vendor_name": "Delta", "normalized_extended_price": 47000.0},
                ],
                "conversion_notes": None,
            }
        ],
        "ungrouped_items": [],
        "summary": {"total_groups": 1, "total_ungrouped": 0, "bids_analyzed": 2,
                    "normalization_warnings": []},
    }
