// Replay mode for the static demo site. Every run, approval request and report comes from a
// real run recorded with `python -m app.record_demo`; this module plays the recordings back
// with the same interface and the same role rules as the HTTP API.

import {
  ApiError,
  type ApprovalRecord,
  type BenchmarkReport,
  type FinalReport,
  type Incident,
  type RunRecord,
} from "../api";

const STEP_MS = 700;
const COMMENT = "__DEMO_COMMENT__";
const DATA = `${import.meta.env.BASE_URL}demo`;

export const DEMO_KEYS = { operator: "demo-operator", admin: "demo-admin" } as const;

interface Recording {
  incident_id: string;
  approval: ApprovalRecord | null;
  stages?: string[];
  report?: FinalReport;
  stages_approved?: string[];
  stages_rejected?: string[];
  report_approved?: FinalReport;
  report_rejected?: FinalReport;
}

interface DemoRun {
  runId: string;
  incidentId: string;
  recording: Recording;
  createdAt: number;
  // The current phase started at this time: the analysis, or the work after a decision.
  phaseStart: number;
  decision: "approved" | "rejected" | null;
  comment: string;
  decidedAt: number;
}

const cache = new Map<string, Promise<unknown>>();
const runs = new Map<string, DemoRun>();
let seeded: Promise<void> | null = null;

function load<T>(path: string): Promise<T> {
  let entry = cache.get(path);
  if (!entry) {
    entry = fetch(`${DATA}/${path}`).then((response) => {
      if (!response.ok) throw new ApiError(response.status, "not_found", `no recording for ${path}`, null);
      return response.json();
    });
    cache.set(path, entry);
  }
  return entry as Promise<T>;
}

function role(key: string): string {
  if (key === DEMO_KEYS.admin) return "admin";
  if (key === DEMO_KEYS.operator) return "operator";
  throw new ApiError(401, "unauthorized", "missing or invalid API key", null);
}

function forbidden(key: string, permission: string): ApiError {
  return new ApiError(403, "forbidden", `role '${role(key)}' is missing permission '${permission}'`, null);
}

function getRun(runId: string): DemoRun {
  const run = runs.get(runId);
  if (!run) throw new ApiError(404, "not_found", `run ${runId} not found`, null);
  return run;
}

// The stages this run goes through in its current phase.
function phaseStages(run: DemoRun): string[] {
  const { recording } = run;
  if (!recording.approval) return recording.stages ?? [];
  if (run.decision === null) {
    const all = recording.stages_approved ?? [];
    return all.slice(0, all.indexOf("human_approval") + 1);
  }
  const all = (run.decision === "approved" ? recording.stages_approved : recording.stages_rejected) ?? [];
  return all.slice(all.indexOf("human_approval") + 1);
}

function retriesUpTo(stages: string[]): number {
  return Math.max(0, stages.filter((s) => s === "critic").length - 1);
}

function snapshot(run: DemoRun, now = Date.now()): RunRecord {
  const stages = phaseStages(run);
  const step = Math.floor((now - run.phaseStart) / STEP_MS);
  const base = {
    run_id: run.runId,
    incident_id: run.incidentId,
    requested_by: "demo operator",
    error_code: null,
    error_message: null,
    created_at: new Date(run.createdAt).toISOString(),
    updated_at: new Date(Math.min(now, run.phaseStart + stages.length * STEP_MS)).toISOString(),
  };
  const preApproval = run.recording.approval ? (run.recording.stages_approved ?? []) : [];
  const priorRetries = run.decision ? retriesUpTo(preApproval) : 0;

  if (step < stages.length) {
    const seen = stages.slice(0, step + 1);
    const pausing = run.recording.approval && run.decision === null && step === stages.length - 1;
    return {
      ...base,
      status: pausing ? "awaiting_approval" : "running",
      stage: stages[step] ?? null,
      retry_count: priorRetries + retriesUpTo(seen),
    };
  }
  if (run.recording.approval && run.decision === null) {
    return { ...base, status: "awaiting_approval", stage: "human_approval", retry_count: retriesUpTo(stages) };
  }
  return { ...base, status: "completed", stage: "postmortem", retry_count: finalReport(run).retries };
}

function finalReport(run: DemoRun): FinalReport {
  const { recording } = run;
  if (!recording.approval) return recording.report as FinalReport;
  return (run.decision === "approved" ? recording.report_approved : recording.report_rejected) as FinalReport;
}

// Put the visitor's comment and the time they decided into the recorded report.
function personalize(run: DemoRun): FinalReport {
  const comment = run.comment.trim() || "no comment";
  const escaped = JSON.stringify(comment).slice(1, -1);
  const report = JSON.parse(JSON.stringify(finalReport(run)).replaceAll(COMMENT, escaped)) as FinalReport;
  report.run_id = run.runId;
  if (report.approval) {
    const recordedAt = Date.parse((report.approval as { decided_at?: string }).decided_at ?? "");
    if (!Number.isNaN(recordedAt)) {
      const shift = run.decidedAt - recordedAt;
      const move = (iso: string) => new Date(Date.parse(iso) + shift).toISOString();
      report.timeline = report.timeline.map((event) =>
        Date.parse(event.timestamp) >= recordedAt ? { ...event, timestamp: move(event.timestamp) } : event,
      );
    }
  }
  return report;
}

async function start(incidentId: string, createdAt: number): Promise<DemoRun> {
  const recording = await load<Recording>(`runs/${incidentId}.json`);
  const run: DemoRun = {
    runId: `run-demo-${Math.random().toString(16).slice(2, 14)}`,
    incidentId,
    recording,
    createdAt,
    phaseStart: createdAt,
    decision: null,
    comment: "",
    decidedAt: 0,
  };
  runs.set(run.runId, run);
  return run;
}

// A few runs so the overview has history on first visit: one paused for a decision and two
// finished ones, all from the recordings.
function seed(): Promise<void> {
  seeded ??= (async () => {
    const minutes = (n: number) => Date.now() - n * 60_000;
    await start("INC-1031", minutes(48));
    await start("INC-1003", minutes(31));
    await start("INC-1045", minutes(12));
  })().catch(() => undefined);
  return seeded;
}

function decide(run: DemoRun, decision: "approved" | "rejected", comment: string): RunRecord {
  const current = snapshot(run);
  if (current.status !== "awaiting_approval") {
    throw new ApiError(409, "invalid_state", `run ${run.runId} is ${current.status}, not awaiting approval`, null);
  }
  run.decision = decision;
  run.comment = comment;
  run.decidedAt = Date.now();
  run.phaseStart = run.decidedAt;
  return snapshot(run);
}

export interface DemoManifest {
  recorded_at: string;
  incidents: number;
  critic_mode?: "local" | "a2a";
  search_backend?: string;
}

export function demoManifest(): Promise<DemoManifest> {
  return load<DemoManifest>("manifest.json");
}

export const demoApi = {
  health: async (): Promise<{ status: string; checks: Record<string, string> }> => ({
    status: "replay",
    checks: {},
  }),
  incidents: async (key: string) => {
    role(key);
    return load<Incident[]>("incidents.json");
  },
  recentRuns: async (key: string) => {
    role(key);
    await seed();
    return [...runs.values()]
      .sort((a, b) => b.createdAt - a.createdAt)
      .slice(0, 25)
      .map((run) => snapshot(run));
  },
  benchmark: async (key: string, provider: "heuristic" | "anthropic" = "heuristic") => {
    role(key);
    return load<BenchmarkReport>(provider === "anthropic" ? "benchmark-claude.json" : "benchmark.json");
  },
  analyze: async (key: string, incidentId: string) => {
    role(key);
    await seed();
    return snapshot(await start(incidentId, Date.now()));
  },
  status: async (key: string, runId: string) => {
    role(key);
    return snapshot(getRun(runId));
  },
  approval: async (key: string, runId: string) => {
    role(key);
    const run = getRun(runId);
    if (!run.recording.approval) throw new ApiError(404, "not_found", `no approval for ${runId}`, null);
    return { ...run.recording.approval, status: run.decision === null ? "pending" : run.decision } as ApprovalRecord;
  },
  approve: async (key: string, runId: string, comment: string) => {
    if (role(key) !== "admin") throw forbidden(key, "remediation:execute");
    return decide(getRun(runId), "approved", comment);
  },
  reject: async (key: string, runId: string, reason: string) => {
    role(key);
    return decide(getRun(runId), "rejected", reason);
  },
  report: async (key: string, runId: string) => {
    role(key);
    const run = getRun(runId);
    if (snapshot(run).status !== "completed") {
      throw new ApiError(409, "invalid_state", `run ${runId} has not completed`, null);
    }
    return personalize(run);
  },
};
