import { acquireApiToken } from "@/auth/AuthProvider";
import type {
  IngestedBid,
  ProjectSummary,
  JobSummary,
  ComparisonSession,
  Correction,
  CorrectionRequest,
  CorrectionType,
  RejectedEmailMetadata,
  LinkedAccount,
  DashboardStats,
  DashboardAnswer,
  SessionSummary,
} from "@/types";

/**
 * ApiError — surfaces the backend's structured error envelope (build doc Rule 8:
 * { message, error_id }) without leaking technical detail, while still keeping
 * the HTTP status for callers that branch on it (e.g. 401 → re-auth).
 */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly errorId?: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * Shape of the backend error body (mirrors AppError.user_message). This is a
 * plain dict, not a CamelModel, so `error_id` stays snake_case on the wire.
 */
interface ApiErrorBody {
  message?: string;
  error_id?: string;
}

/**
 * ApiClient — the single typed gateway between the SPA and the FastAPI backend.
 *
 * Every method maps to one router endpoint group (build doc section 3). The
 * MSAL access token is attached as a bearer header on each request; in dev the
 * Vite proxy forwards `/api/*` to http://localhost:8000 so there is no CORS or
 * base-URL juggling. SSE endpoints (chat, poll) are handled by the hooks, which
 * reuse `authHeaders()` for their fetch-stream connections.
 */
const DEFAULT_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL ?? "/api").replace(/\/$/, "");

export class ApiClient {
  constructor(private readonly baseUrl: string = DEFAULT_BASE_URL) {}

  /** Build the Authorization header from the current MSAL token (if any). */
  async authHeaders(): Promise<Record<string, string>> {
    const token = await acquireApiToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  /** Core fetch wrapper: attaches auth, parses JSON, normalises errors. */
  private async request<T>(
    path: string,
    init: RequestInit = {}
  ): Promise<T> {
    const auth = await this.authHeaders();
    const headers: Record<string, string> = {
      Accept: "application/json",
      ...auth,
      ...(init.headers as Record<string, string> | undefined),
    };
    if (init.body && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }

    let res: Response;
    try {
      res = await fetch(`${this.baseUrl}${path}`, { ...init, headers });
    } catch {
      // Network failure — surface a friendly message (status 0 = no response).
      throw new ApiError(0, "Network request failed", undefined);
    }

    if (!res.ok) {
      let body: ApiErrorBody = {};
      try {
        body = (await res.json()) as ApiErrorBody;
      } catch {
        // Non-JSON error response; fall back to status text.
      }
      throw new ApiError(
        res.status,
        body.message ?? res.statusText ?? "Request failed",
        body.error_id
      );
    }

    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  }

  // ----- auth (/api/auth) --------------------------------------------------

  /**
   * Begin linking a Microsoft mailbox. Returns the Microsoft OAuth consent URL
   * the browser should navigate to; the backend handles the callback.
   */
  getEmailLinkUrl(): Promise<{ authorizeUrl: string; state: string }> {
    return this.request("/auth/login");
  }

  /** Current authenticated user profile (from the validated Entra token). */
  getCurrentUser(): Promise<{ userId: string; email: string }> {
    return this.request("/auth/me");
  }

  // ----- bids (/api/bids) --------------------------------------------------

  /** List bids, optionally filtered by project, job, or status. */
  listBids(params?: {
    projectId?: string;
    jobId?: string;
    status?: string;
  }): Promise<IngestedBid[]> {
    const qs = new URLSearchParams();
    if (params?.projectId) qs.set("projectId", params.projectId);
    if (params?.jobId) qs.set("jobId", params.jobId);
    if (params?.status) qs.set("status", params.status);
    const suffix = qs.toString() ? `?${qs}` : "";
    return this.request(`/bids${suffix}`);
  }

  getBid(bidId: string): Promise<IngestedBid> {
    return this.request(`/bids/${encodeURIComponent(bidId)}`);
  }

  /**
   * URL for the PDF proxy endpoint. The backend streams the original blob to the
   * browser (build doc decision I1), so this can be used directly as an iframe
   * or object src. Note: the proxy authenticates via session/cookie or query
   * token on the backend side; embedded viewers cannot set bearer headers.
   */
  getBidPdfUrl(bidId: string): string {
    return `${this.baseUrl}/bids/${encodeURIComponent(bidId)}/pdf`;
  }

  // ----- projects (/api/projects) ------------------------------------------

  listProjects(): Promise<ProjectSummary[]> {
    return this.request("/projects");
  }

  getProject(projectId: string): Promise<ProjectSummary> {
    return this.request(`/projects/${encodeURIComponent(projectId)}`);
  }

  listProjectJobs(projectId: string): Promise<JobSummary[]> {
    return this.request(`/projects/${encodeURIComponent(projectId)}/jobs`);
  }

  // ----- comparison (/api/comparison) --------------------------------------

  /** Kick off the comparison pipeline (Agents 5/6/7) for a job's bids. */
  startComparison(
    projectId: string,
    jobId: string
  ): Promise<ComparisonSession> {
    return this.request(
      `/comparison/${encodeURIComponent(projectId)}/${encodeURIComponent(
        jobId
      )}/start`,
      { method: "POST" }
    );
  }

  /** All comparison sessions for a project. */
  listSessions(projectId: string): Promise<ComparisonSession[]> {
    return this.request(
      `/comparison/${encodeURIComponent(projectId)}/sessions`
    );
  }

  getSession(
    projectId: string,
    sessionId: string
  ): Promise<ComparisonSession> {
    return this.request(
      `/comparison/${encodeURIComponent(projectId)}/sessions/${encodeURIComponent(
        sessionId
      )}`
    );
  }

  /** Request a shareable summary of a session (SessionSummarizer, Agent 11). */
  getSessionSummary(
    projectId: string,
    sessionId: string
  ): Promise<SessionSummary> {
    return this.request(
      `/comparison/${encodeURIComponent(projectId)}/sessions/${encodeURIComponent(
        sessionId
      )}/summary`
    );
  }

  // ----- corrections (/api/corrections) ------------------------------------

  /** Submit a correction for a bid (project / trade / validation). */
  submitCorrection(
    bidId: string,
    type: CorrectionType,
    payload: CorrectionRequest
  ): Promise<Correction> {
    return this.request(
      `/corrections/${encodeURIComponent(bidId)}/${type}`,
      { method: "POST", body: JSON.stringify(payload) }
    );
  }

  // ----- email accounts (/api/email-accounts) ------------------------------

  listEmailAccounts(): Promise<LinkedAccount[]> {
    return this.request("/email-accounts");
  }

  unlinkEmailAccount(accountId: string): Promise<void> {
    return this.request(`/email-accounts/${encodeURIComponent(accountId)}`, {
      method: "DELETE",
    });
  }

  /**
   * URL for the manual poll SSE endpoint. usePollProgress connects to this via
   * a streaming fetch and parses the section 8.1 progress events.
   */
  getPollUrl(accountId: string): string {
    return `${this.baseUrl}/email-accounts/${encodeURIComponent(
      accountId
    )}/poll`;
  }

  // ----- rejected (/api/rejected) ------------------------------------------

  listRejected(): Promise<RejectedEmailMetadata[]> {
    return this.request("/rejected");
  }

  /**
   * Restore a wrongly-rejected email — re-ingests it (build doc 8.5). The
   * backend returns the freshly-created IngestedBid.
   */
  restoreRejected(id: string): Promise<IngestedBid> {
    return this.request(`/rejected/${encodeURIComponent(id)}/restore`, {
      method: "POST",
    });
  }

  // ----- stats (/api/stats) ------------------------------------------------

  getDashboardStats(): Promise<DashboardStats> {
    return this.request("/stats");
  }

  /** Ask the DashboardAnalyst (Agent 12) a natural-language portfolio question. */
  askDashboard(question: string): Promise<DashboardAnswer> {
    return this.request("/stats/ask", {
      method: "POST",
      body: JSON.stringify({ question }),
    });
  }

  /** Chat SSE endpoint URL — consumed by useComparison's streaming fetch. */
  getChatUrl(projectId: string, sessionId: string): string {
    return `${this.baseUrl}/comparison/${encodeURIComponent(
      projectId
    )}/sessions/${encodeURIComponent(sessionId)}/chat`;
  }
}

/** App-wide singleton client. */
export const apiClient = new ApiClient();
