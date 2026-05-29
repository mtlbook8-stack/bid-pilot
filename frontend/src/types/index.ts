/**
 * TypeScript mirrors of the Python domain models in src/core/models/*.py and
 * the enums in src/core/enums.py.
 *
 * Field names are intentionally snake_case: the FastAPI layer serializes the
 * Pydantic models with `model_dump()` (default field names), so the JSON over
 * the wire is snake_case. Keeping the TS shapes identical means no mapping
 * layer between the API client and components. The agent output JSON shapes
 * (build doc section 7) flow straight into ComparisonTable / chat responses,
 * so those mirror the documented agent contracts too.
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
  agent_name: string;
  confidence: number;
  reasoning: string;
  raw_output: Record<string, unknown>;
  created_at: string;
}

export interface IngestedBid {
  id: string;
  message_id: string;
  linked_account_id: string;
  sender_email: string;
  email_subject: string;
  received_at: string;
  attachment_filename: string;
  blob_path: string;
  document_text: string;
  table_count: number;
  status: BidStatus;
  retry_count: number;
  is_bid: boolean | null;
  matched_project_id: string | null;
  address_from_bid: string | null;
  normalized_address: string | null;
  matched_job_id: string | null;
  trade_category: TradeCategory | null;
  secondary_trades: string[];
  vendor_name: string | null;
  scope_summary: string | null;
  total_price: number | null;
  agent_results: Record<string, AgentResult>;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Project / Job (project.py, job.py)
// ---------------------------------------------------------------------------

export interface ProjectSummary {
  id: string;
  name: string;
  address: string | null;
  normalized_address: string | null;
  client_name: string | null;
  client_contact: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobSummary {
  id: string;
  project_id: string;
  trade_category: TradeCategory;
  job_name: string;
  bid_ids: string[];
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Comparison (comparison.py + agent output shapes from section 7)
// ---------------------------------------------------------------------------

export interface CostCell {
  bid_id: string;
  vendor_name: string;
  value: number | null;
  original_text: string;
  is_lowest: boolean;
  flags: string[];
}

export interface CostRow {
  row_id: string;
  label: string;
  normalized_unit: string;
  cells: CostCell[];
}

export interface VendorTotal {
  bid_id: string;
  vendor_name: string;
  total_price: number;
  items_included: number;
  items_missing: number;
  scope_caveats: string[];
}

export interface CostOutlier {
  row_label: string;
  bid_id: string;
  deviation_percentage: number;
  direction: "above" | "below";
}

export interface CostAnalysis {
  lowest_total_bid_id: string | null;
  highest_total_bid_id: string | null;
  spread_percentage: number;
  significant_outliers: CostOutlier[];
}

export interface FeatureCell {
  bid_id: string;
  vendor_name: string;
  value: string;
  sentiment: Sentiment;
  source_quote: string;
}

export interface FeatureRow {
  row_id: string;
  category: string;
  label: string;
  importance_rank: number;
  cells: FeatureCell[];
}

export interface RedFlag {
  bid_id: string;
  vendor_name: string;
  issue: string;
  severity: Severity;
}

export interface ComparisonTable {
  cost_rows: CostRow[];
  totals: VendorTotal[];
  cost_analysis: CostAnalysis;
  feature_rows: FeatureRow[];
  red_flags: RedFlag[];
  feature_summary: string;
}

export interface ChatMessage {
  role: ChatRole;
  content: string;
  handled_by: string | null;
  created_at: string;
}

export interface CompactedContext {
  decision_status: DecisionStatus;
  leading_vendor: string | null;
  reasoning: string | null;
  conclusions: Array<Record<string, unknown>>;
  table_edits: Array<Record<string, unknown>>;
  user_preferences: string[];
  open_threads: string[];
  data_corrections: string[];
  compressed_from_message_count: number;
}

export interface ComparisonSession {
  id: string;
  project_id: string;
  job_id: string;
  project_name: string;
  job_name: string;
  trade_category: string;
  bid_ids: string[];
  vendor_names: string[];
  phase: ComparisonPhase;
  table: ComparisonTable | null;
  conversation_history: ChatMessage[];
  compacted_context: CompactedContext | null;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Corrections (correction.py)
// ---------------------------------------------------------------------------

export interface Correction {
  id: string;
  bid_id: string;
  correction_type: CorrectionType;
  agent_name: string;
  original_value: Record<string, unknown>;
  corrected_value: string;
  reason: string;
  created_at: string;
}

export interface CorrectionRequest {
  corrected_value: string;
  reason?: string;
}

// ---------------------------------------------------------------------------
// Rejected email (rejected_email.py)
// ---------------------------------------------------------------------------

export interface RejectedEmailMetadata {
  id: string;
  message_id: string;
  linked_account_id: string;
  sender_email: string;
  subject: string;
  received_at: string;
  rejection_reason: RejectionCategory;
  agent_confidence: number;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Linked account (linked_account.py)
// ---------------------------------------------------------------------------

export interface LinkedAccount {
  id: string;
  user_id: string;
  email_address: string;
  token_secret_name: string;
  webhook_subscription_id: string | null;
  webhook_expires_at: string | null;
  last_processed_at: string | null;
  is_active: boolean;
  last_health_check_at: string | null;
  last_health_ok: boolean | null;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Dashboard / stats (dashboard_service.py + DashboardAnalyst agent output)
// ---------------------------------------------------------------------------

export interface DashboardStats {
  total_projects: number;
  total_bids: number;
  total_jobs: number;
  bids_this_week: number;
  unmatched_bids: number;
  needs_review: number;
  rejected_count: number;
  active_sessions: number;
  bids_by_trade: Array<{ trade: string; count: number }>;
  recent_bids: IngestedBid[];
}

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
// Session summary (SessionSummarizer agent output, section 7 Agent 11)
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
// SSE event payloads (section 8.1 manual poll, 8.3 comparison chat streaming)
// ---------------------------------------------------------------------------

export type PollEvent =
  | { event: "started"; account: string }
  | { event: "emails_found"; count: number }
  | { event: "processing"; email: string; index: number; total: number }
  | { event: "bid_saved"; bid_id: string; vendor: string }
  | { event: "completed"; bids_created: number; rejected: number }
  | { event: "error"; message: string };

/**
 * Chat stream events. The orchestrator streams assistant text in deltas, can
 * push an updated table mid-stream, and signals which specialist handled the
 * turn via `handled_by` (build doc 8.3).
 */
export type ChatStreamEvent =
  | { event: "routed"; handled_by: string }
  | { event: "delta"; text: string }
  | { event: "table_update"; table: ComparisonTable }
  | { event: "done"; handled_by: string | null }
  | { event: "error"; message: string };
