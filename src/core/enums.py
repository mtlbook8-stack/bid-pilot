"""
Domain enumerations shared across the entire system.

These live together (an allowed exception to Rule 4) because they are small,
tightly coupled value sets that every layer references. Keeping them in one
place guarantees the API, agents, stores, and frontend type mirror agree on
the exact string values that get persisted to Cosmos.
"""

from enum import Enum


class BidStatus(str, Enum):
    """
    Lifecycle of an ingested bid through the processing pipeline.

    The values double as Cosmos checkpoint markers: the retry trigger resumes
    any bid stuck in an in-progress status (Validating / MatchingProject /
    CategorizingJob) from exactly that checkpoint.
    """

    PARSED = "Parsed"                 # Document parsed, awaiting pipeline
    VALIDATING = "Validating"         # Agent 1 in progress (checkpoint)
    VALIDATED = "Validated"           # Confirmed a bid, awaiting matching
    MATCHING_PROJECT = "MatchingProject"   # Agent 2 in progress (checkpoint)
    PROJECT_MATCHED = "ProjectMatched"     # Project assigned
    CATEGORIZING_JOB = "CategorizingJob"   # Agent 3 in progress (checkpoint)
    CATEGORIZED = "Categorized"       # Terminal success — visible in UI
    REJECTED = "Rejected"             # Not a bid — metadata moved to rejected
    FAILED = "Failed"                 # Exhausted retries

    @property
    def is_in_progress(self) -> bool:
        """True for checkpoint states the retry trigger should resume."""
        return self in {
            BidStatus.VALIDATING,
            BidStatus.MATCHING_PROJECT,
            BidStatus.CATEGORIZING_JOB,
        }

    @property
    def is_terminal(self) -> bool:
        """True once the bid needs no further pipeline work."""
        return self in {BidStatus.CATEGORIZED, BidStatus.REJECTED, BidStatus.FAILED}


class TradeCategory(str, Enum):
    """
    Canonical construction trade categories. JobCategorizer (Agent 3) must emit
    exactly one of these values for `trade_category`.
    """

    SITEWORK = "Sitework"
    CONCRETE = "Concrete"
    MASONRY = "Masonry"
    METALS_STEEL = "Metals/Steel"
    CARPENTRY = "Carpentry"
    THERMAL_MOISTURE = "Thermal/Moisture Protection"
    ROOFING = "Roofing"
    DOORS_WINDOWS_GLAZING = "Doors/Windows/Glazing"
    FINISHES = "Finishes"
    DRYWALL = "Drywall"
    FLOORING = "Flooring"
    PAINTING = "Painting"
    SPECIALTIES = "Specialties"
    EQUIPMENT = "Equipment"
    FURNISHINGS = "Furnishings"
    PLUMBING = "Plumbing"
    HVAC = "HVAC"
    ELECTRICAL = "Electrical"
    FIRE_PROTECTION = "Fire Protection"
    ELEVATOR = "Elevator"
    DEMOLITION = "Demolition"
    EARTHWORK = "Earthwork"
    UTILITIES = "Utilities"
    LANDSCAPING = "Landscaping"
    GENERAL_CONDITIONS = "General Conditions"
    OTHER = "Other"

    @classmethod
    def from_label(cls, label: str) -> "TradeCategory":
        """
        Map an agent-produced label to a canonical category, defaulting to OTHER.
        Tolerant of casing/whitespace so a minor agent formatting drift does not
        crash the pipeline.
        """
        normalized = label.strip().lower()
        for member in cls:
            if member.value.lower() == normalized:
                return member
        return cls.OTHER


class CorrectionType(str, Enum):
    """The dimension of a bid that a user corrected."""

    PROJECT = "project"        # Wrong project match
    TRADE = "trade"            # Wrong trade/job categorization
    VALIDATION = "validation"  # Wrongly rejected/accepted as a bid


class RejectionCategory(str, Enum):
    """Why QuoteValidator (Agent 1) rejected a document."""

    NOT_CONSTRUCTION = "not_construction"
    INVOICE_NOT_BID = "invoice_not_bid"
    INFORMATIONAL_ONLY = "informational_only"
    DUPLICATE = "duplicate"


class DocumentType(str, Enum):
    """Document classification emitted by QuoteValidator."""

    BID = "bid"
    INVOICE = "invoice"
    SUBMITTAL = "submittal"
    RFI = "rfi"
    MARKETING = "marketing"
    INSURANCE = "insurance"
    OTHER = "other"


class MatchType(str, Enum):
    """ProjectMatcher (Agent 2) outcome."""

    EXISTING = "existing"
    NEW = "new"


class ComparisonPhase(str, Enum):
    """Where a comparison session is in its lifecycle."""

    NORMALIZING = "normalizing"   # Agent 5 running
    COMPARING = "comparing"       # Agents 6/7 running
    READY = "ready"               # Table assembled, chat available
    FAILED = "failed"             # Pipeline error


class DecisionStatus(str, Enum):
    """User's decision state within a comparison session."""

    UNDECIDED = "undecided"
    LEANING = "leaning"
    DECIDED = "decided"


class Sentiment(str, Enum):
    """FeatureAnalyst (Agent 7) per-cell sentiment rating."""

    FAVORABLE = "favorable"
    NEUTRAL = "neutral"
    UNFAVORABLE = "unfavorable"
    NOT_SPECIFIED = "not_specified"


class AgentName(str, Enum):
    """
    Canonical agent identifiers. These are the partition keys for the prompts
    and learned-rules containers, and the names used in telemetry, so they must
    match the seeded prompt documents exactly.
    """

    QUOTE_VALIDATOR = "QuoteValidator"
    PROJECT_MATCHER = "ProjectMatcher"
    JOB_CATEGORIZER = "JobCategorizer"
    COMPARISON_ORCHESTRATOR = "ComparisonOrchestrator"
    UNIT_NORMALIZER = "UnitNormalizer"
    COST_COMPARATOR = "CostComparator"
    FEATURE_ANALYST = "FeatureAnalyst"
    CONTEXT_COMPACTOR = "ContextCompactor"
    DATA_QUERY_AGENT = "DataQueryAgent"
    CORRECTION_DISTILLER = "CorrectionDistiller"
    SESSION_SUMMARIZER = "SessionSummarizer"
    DASHBOARD_ANALYST = "DashboardAnalyst"
    DECISION_EXPLAINER = "DecisionExplainer"


class ChatRole(str, Enum):
    """Role of a message in a comparison session conversation."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
