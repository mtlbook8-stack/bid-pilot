/**
 * TypeScript mirrors of the Python domain models in src/core/models/*.py and
 * the enums in src/core/enums.py.
 *
 * Field names are camelCase to match the real API contract: every persisted
 * domain model inherits CamelModel (src/core/models/base.py), which serializes
 * with a camelCase alias generator, and FastAPI emits responses `by_alias=True`.
 * So the JSON over the wire is camelCase and the TS shapes mirror it 1:1 — no
 * mapping layer between the API client and components.
 *
 * Two deliberate exceptions stay snake_case because they are NOT CamelModels —
 * they are raw LLM-parsed JSON dicts returned straight through the API:
 *   - DashboardAnswer  (DashboardAnalyst agent output, section 7 Agent 12)
 *   - SessionSummary   (SessionSummarizer agent output, section 7 Agent 11)
 * The manual-poll SSE progress events (section 8.1) are likewise plain dicts
 * emitted with snake_case keys by the orchestrator.
 */

// ---------------------------------------------------------------------------
// Enums (string unions mirroring src/core/enums.py — values must match exactly)
// ---------------------------------------------------------------------------

export type BidStatus =
  | "Parsed"
  | "Validating"
  | "Validated"
  | "MatchingProject"
  | "ProjectMatched"
  | "CategorizingJob"
  | "Categorized"
  | "Rejected"
  | "Failed";

export type TradeCategory =
  | "Sitework"
  | "Concrete"
  | "Masonry"
  | "Metals/Steel"
  | "Carpentry"
  | "Thermal/Moisture Protection"
  | "Roofing"
  | "Doors/Windows/Glazing"
  | "Finishes"
  | "Drywall"
  | "Flooring"
  | "Painting"
  | "Specialties"
  | "Equipment"
  | "Furnishings"
  | "Plumbing"
  | "HVAC"
  | "Electrical"
  | "Fire Protection"
  | "Elevator"
  | "Demolition"
  | "Earthwork"
  | "Utilities"
  | "Landscaping"
  | "General Conditions"
  | "Other";

export type CorrectionType = "project" | "trade" | "validation";

export type RejectionCategory =
  | "not_construction"
  | "invoice_not_bid"
  | "informational_only"
  | "duplicate";

export type ComparisonPhase = "normalizing" | "comparing" | "ready" | "failed";

export type DecisionStatus = "undecided" | "leaning" | "decided";

export type Sentiment =
  | "favorable"
  | "neutral"
  | "unfavorable"
  | "not_specified";

export type ChatRole = "user" | "assistant" | "system";

export type Severity = "high" | "medium" | "low";

// ---------------------------------------------------------------------------
// Bid (src/core/models/bid.py)
// ---------------------------------------------------------------------------

export interface AgentResult {
  agentName: string;
  confidence: number;
  reasoning: string;
  rawOutput: Record<string, unknown>;
  createdAt: string;
}

export interface IngestedBid {
  id: string;
  messageId: string;
  linkedAccountId: string;
  senderEmail: string;
  emailSubject: string;
  receivedAt: string;
  attachmentFilename: string;
  blobPath: string;
  documentText: string;
  tableCount: number;
  status: BidStatus;
  retryCount: number;
  isBid: boolean | null;
  matchedProjectId: string | null;
  addressFromBid: string | null;
  normalizedAddress: string | null;
  matchedJobId: string | null;
  tradeCategory: TradeCategory | null;
  secondaryTrades: string[];
  vendorName: string | null;
  scopeSummary: string | null;
  totalPrice: number | null;
  agentResults: Record<string, AgentResult>;
  createdAt: string;
  updatedAt: string;
}

// ---------------------------------------------------------------------------
// Project / Job (project.py, job.py)
// ---------------------------------------------------------------------------

export interface ProjectSummary {
  id: string;
  name: string;
  address: string | null;
  normalizedAddress: string | null;
  clientName: string | null;
  clientContact: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface JobSummary {
  id: string;
  projectId: string;
  tradeCategory: TradeCategory;
  jobName: string;
  bidIds: string[];
  createdAt: string;
  updatedAt: string;
}

// ---------------------------------------------------------------------------
// Comparison (comparison.py + agent output shapes from section 7)
// ---------------------------------------------------------------------------

export interface CostCell {
  bidId: string;
  vendorName: string;
  value: number | null;
  originalText: string;
  isLowest: boolean;
  flags: string[];
}

export interface CostRow {
  rowId: string;
  label: string;
  normalizedUnit: string;
  cells: CostCell[];
}

export interface VendorTotal {
  bidId: string;
  vendorName: string;
  totalPrice: number;
  itemsIncluded: number;
  itemsMissing: number;
  scopeCaveats: string[];
}

export interface CostOutlier {
  rowLabel: string;
  bidId: string;
  deviationPercentage: number;
  direction: "above" | "below";
}

export interface CostAnalysis {
  lowestTotalBidId: string | null;
  highestTotalBidId: string | null;
  spreadPercentage: number;
  significantOutliers: CostOutlier[];
}

export interface FeatureCell {
  bidId: string;
  vendorName: string;
  value: string;
  sentiment: Sentiment;
  sourceQuote: string;
}

export interface FeatureRow {
  rowId: string;
  category: string;
  label: string;
  importanceRank: number;
  cells: FeatureCell[];
}

export interface RedFlag {
  bidId: string;
  vendorName: string;
  issue: string;
  severity: Severity;
}

export interface ComparisonTable {
  costRows: CostRow[];
  totals: VendorTotal[];
  costAnalysis: CostAnalysis;
  featureRows: FeatureRow[];
  redFlags: RedFlag[];
  featureSummary: string;
}

export interface ChatMessage {
  role: ChatRole;
  content: string;
  handledBy: string | null;
  createdAt: string;
}

export interface CompactedContext {
  decisionStatus: DecisionStatus;
  leadingVendor: string | null;
  reasoning: string | null;
  conclusions: Array<Record<string, unknown>>;
  tableEdits: Array<Record<string, unknown>>;
  userPreferences: string[];
  openThreads: string[];
  dataCorrections: string[];
  compressedFromMessageCount: number;
}

export interface ComparisonSession {
  id: string;
  projectId: string;
  jobId: string;
  projectName: string;
  jobName: string;
  tradeCategory: string;
  bidIds: string[];
  vendorNames: string[];
  phase: ComparisonPhase;
  table: ComparisonTable | null;
  conversationHistory: ChatMessage[];
  compactedContext: CompactedContext | null;
  createdAt: string;
  updatedAt: string;
}

// ---------------------------------------------------------------------------
// Corrections (correction.py)
// ---------------------------------------------------------------------------

export interface Correction {
  id: string;
  bidId: string;
  correctionType: CorrectionType;
  agentName: string;
  originalValue: Record<string, unknown>;
  correctedValue: string;
  reason: string;
  createdAt: string;
}

/**
 * Body for a correction (corrections_router CorrectionRequest). The backend
 * accepts both casings (populate_by_name) but the alias is camelCase, so we
 * send camelCase for consistency with the wire contract.
 */
export interface CorrectionRequest {
  correctedValue: string;
  reason?: string;
}

// ---------------------------------------------------------------------------
// Rejected email (rejected_email.py)
// ---------------------------------------------------------------------------

export interface RejectedEmailMetadata {
  id: string;
  messageId: string;
  linkedAccountId: string;
  senderEmail: string;
  subject: string;
  receivedAt: string;
  rejectionReason: RejectionCategory;
  agentConfidence: number;
  createdAt: string;
}

// ---------------------------------------------------------------------------
// Linked account (linked_account.py)
// ---------------------------------------------------------------------------

export interface LinkedAccount {
  id: string;
  userId: string;
  emailAddress: string;
  tokenSecretName: string;
  webhookSubscriptionId: string | null;
  webhookExpiresAt: string | null;
  lastProcessedAt: string | null;
  isActive: boolean;
  lastHealthCheckAt: string | null;
  lastHealthOk: boolean | null;
  createdAt: string;
  updatedAt: string;
}

// ---------------------------------------------------------------------------
// Dashboard stats (dashboard_service.get_stats — explicit camelCase dict)
// ---------------------------------------------------------------------------

export interface DashboardStats {
  totalBids: number;
  bidsByStatus: Record<string, number>;
  totalProjects: number;
  totalJobs: number;
  totalSessions: number;
  totalRejected: number;
  needsReview: number;
  recentBids: DashboardRecentBid[];
}

/** Reduced bid shape embedded in DashboardStats.recentBids (camelCase dict). */
export interface DashboardRecentBid {
  id: string;
  vendorName: string | null;
  subject: string;
  status: BidStatus;
  tradeCategory: TradeCategory | null;
  totalPrice: number | null;
  createdAt: string;
}

// ---------------------------------------------------------------------------
// DashboardAnalyst agent output (section 7 Agent 12) — raw LLM JSON, snake_case
// ---------------------------------------------------------------------------

export type VisualizationHint =
  | "bar_chart"
  | "table"
  | "number"
  | "list"
  | "trend_line"
  | null;

export interface DashboardAnswer {
  answer: string;
  data_points: Array<{ label: string; value: string | number }>;
  suggested_actions: string[] | null;
  visualization_hint: VisualizationHint;
}

// ---------------------------------------------------------------------------
// SessionSummarizer agent output (section 7 Agent 11) — raw LLM JSON, snake_case
// ---------------------------------------------------------------------------

export interface SessionSummary {
  title: string;
  overview: string;
  cost_summary: string;
  feature_summary: string;
  decisions: string[];
  open_items: string[];
  recommendation_status: DecisionStatus;
  recommended_vendor: string | null;
  one_liner: string;
}

// ---------------------------------------------------------------------------
// SSE event payloads
// ---------------------------------------------------------------------------

/**
 * Manual poll progress events (build doc 8.1). The orchestrator emits these as
 * plain dicts with snake_case keys (email_ingestion_orchestrator.py), so they
 * are NOT camelCased. An `error` frame carries the AppError envelope
 * (`message` + `error_id`).
 */
export type PollEvent =
  | { event: "started"; account: string }
  | { event: "emails_found"; count: number }
  | { event: "processing"; email: string; index: number; total: number }
  | { event: "bid_saved"; bid_id: string; vendor: string }
  | { event: "completed"; bids_created: number; rejected: number }
  | { event: "error"; message: string; error_id?: string };

/**
 * Comparison chat stream events (build doc 8.3, comparison_service.chat). The
 * service emits exactly these frames as JSON dicts:
 *   - `routed`  : the orchestrator picked a specialist (`agent`).
 *   - `message` : the full assistant reply (`content`) + which agent produced
 *                 it (`handledBy`). There is no token-delta streaming.
 *   - `done`    : terminal success, no fields.
 *   - `error`   : AppError envelope (`message` + `error_id`).
 */
export type ChatStreamEvent =
  | { event: "routed"; agent: string }
  | { event: "message"; content: string; handledBy: string | null }
  | { event: "done" }
  | { event: "error"; message: string; error_id?: string };
