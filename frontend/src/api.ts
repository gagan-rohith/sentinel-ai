// Typed client for the SentinelAI API. Types mirror the backend's Pydantic models,
// limited to the fields this page shows.

import { demoApi } from "./demo/replay";

export type Severity = "sev1" | "sev2" | "sev3" | "sev4";
export type RunStatus = "queued" | "running" | "awaiting_approval" | "completed" | "failed";
export type Risk = "low" | "medium" | "high";

export interface Incident {
  incident_id: string;
  title: string;
  description: string;
  service: string;
  environment: string;
  severity: Severity;
  status: string;
  timestamp: string;
  symptoms: string[];
  error_messages: string[];
  metrics_summary: Record<string, number>;
}

export interface RunRecord {
  run_id: string;
  incident_id: string;
  status: RunStatus;
  stage: string | null;
  retry_count: number;
  requested_by: string;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

interface RetrievalScores {
  queries: number;
  recall_at: Record<string, number>;
  precision_at_3: number;
  mrr: number;
}

export interface BenchmarkReport {
  setup: {
    started_at: string;
    git_commit: string;
    search_backend: string;
    embedder: string;
    llm_mode: string;
    llm_model: string | null;
    incident_cases: number;
    qa_queries: number;
  };
  retrieval: {
    mode: "bm25" | "vector" | "hybrid";
    incident_queries: RetrievalScores;
    qa_queries: RetrievalScores;
    similar_incident_hit_at_3: number;
  }[];
  agents: {
    setting: "standard" | "holdout";
    cases: number;
    runbook_accuracy: number;
    category_accuracy: number;
    mean_confidence: number;
    brier_score: number;
    citation_validity: number;
    retry_rate: number;
  }[];
}

export interface ProposedAction {
  tool: string;
  arguments: Record<string, string>;
  description: string;
  risk: Risk;
}

export interface ApprovalRecord {
  approval_id: string;
  status: "pending" | "approved" | "rejected";
  decided_by: string | null;
  request: {
    root_cause: string;
    root_cause_confidence: number;
    actions: ProposedAction[];
    overall_risk: Risk;
    rollback_plan: string;
    unresolved_critic_issues: string[];
  };
}

export interface Evidence {
  id: string;
  kind: string;
  summary: string;
  timestamp: string | null;
}

export interface Hypothesis {
  title: string;
  description: string;
  category: string | null;
  evidence_for: string[];
  evidence_against: string[];
  confidence: number;
}

export interface RemediationStep {
  description: string;
  kind: "diagnostic" | "mitigation" | "fix" | "prevention";
  risk: Risk;
  action: { tool: string; service: string; deployment_id: string | null } | null;
  evidence: string[];
}

export interface FinalReport {
  run_id: string;
  trace_id: string | null;
  mode: "llm" | "heuristic" | "mixed";
  triage: {
    assessed_severity: Severity;
    severity_reason: string;
    subsystem: string;
  } | null;
  postmortem: {
    title: string;
    summary: string;
    impact: string;
    root_cause: string;
    remediation: string;
    prevention: string[];
    open_questions: string[];
  };
  timeline: { timestamp: string; description: string; source: string }[];
  selected_root_cause: Hypothesis;
  hypotheses: Hypothesis[];
  remediation_plan: {
    summary: string;
    steps: RemediationStep[];
    rollback_plan: string;
    overall_risk: Risk;
    approval_required: boolean;
  };
  approval_status: string;
  approval: { decided_by: string; approved: boolean; comment: string | null } | null;
  executed_actions: { tool: string; status: string; message: string }[];
  critic_review: { verdict: string; confidence: number; issues: string[] } | null;
  unresolved_critic_issues: boolean;
  retries: number;
  data_gaps: string[];
  evidence: Evidence[];
  tool_call_count: number;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly traceId: string | null,
  ) {
    super(message);
  }
}

async function request<T>(path: string, key: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { "X-API-Key": key, "Content-Type": "application/json", ...init.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const error = body?.error;
    const detail = Array.isArray(body?.detail) ? body.detail[0]?.msg : undefined;
    throw new ApiError(
      response.status,
      error?.code ?? "http_error",
      error?.message ?? detail ?? `request failed with status ${response.status}`,
      error?.trace_id ?? response.headers.get("x-trace-id"),
    );
  }
  return (await response.json()) as T;
}

const liveApi = {
  health: async (): Promise<{ status: string; checks: Record<string, string> }> => {
    const response = await fetch("/api/health");
    return response.json();
  },
  incidents: (key: string) => request<Incident[]>("/incidents?limit=200", key),
  recentRuns: (key: string) => request<RunRecord[]>("/agents/runs?limit=25", key),
  benchmark: (key: string, provider: "heuristic" | "anthropic" = "heuristic") =>
    request<BenchmarkReport>(`/evals/latest?provider=${provider}`, key),
  analyze: (key: string, incidentId: string) =>
    request<RunRecord>(`/agents/analyze/${incidentId}`, key, { method: "POST" }),
  status: (key: string, runId: string) => request<RunRecord>(`/agents/status/${runId}`, key),
  approval: (key: string, runId: string) =>
    request<ApprovalRecord>(`/agents/${runId}/approval`, key),
  approve: (key: string, runId: string, comment: string) =>
    request<RunRecord>(`/agents/${runId}/approve`, key, {
      method: "POST",
      body: JSON.stringify({ comment: comment || null }),
    }),
  reject: (key: string, runId: string, reason: string) =>
    request<RunRecord>(`/agents/${runId}/reject`, key, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  report: (key: string, runId: string) => request<FinalReport>(`/agents/${runId}/report`, key),
};

export type Api = typeof liveApi;

// Built with VITE_DEMO=1 for the static demo site: recorded runs replace the HTTP API.
export const DEMO = import.meta.env.VITE_DEMO === "1";
export const api: Api = DEMO ? demoApi : liveApi;
