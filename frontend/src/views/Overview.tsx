import { useEffect, useState } from "react";

import { api, DEMO, type BenchmarkReport, type Incident, type RunRecord } from "../api";
import { dateTime, percent, relativeTime } from "../format";
import { BarList, StatTile, StatusBadge } from "../components/ui";
import { HowItWorks } from "../demo/HowItWorks";

interface Props {
  apiKey: string;
  health: string;
  incidents: Incident[];
  onOpenRun: (run: RunRecord) => void;
}

type AgentRow = BenchmarkReport["agents"][number];

function agentBars(report: BenchmarkReport, mode: string, emphasize: boolean) {
  const order = (a: AgentRow) => (a.setting === "standard" ? 0 : 1);
  return [...report.agents].sort((a, b) => order(a) - order(b)).map((a) => ({
    label: `${a.setting === "standard" ? "Seen" : "Unseen"}, ${mode}`,
    value: a.runbook_accuracy,
    display: percent(a.runbook_accuracy, 1),
    emphasis: emphasize && a.setting === "holdout",
    note: `${a.cases} cases, retry rate ${percent(a.retry_rate, 1)}`,
  }));
}

function Benchmark({ report, claude }: { report: BenchmarkReport; claude: BenchmarkReport | null }) {
  const { setup } = report;
  const retrieval = report.retrieval.map((r) => ({
    label: r.mode === "bm25" ? "BM25 keyword" : r.mode === "vector" ? "Vector" : "Hybrid (RRF)",
    value: r.qa_queries.mrr,
    display: r.qa_queries.mrr.toFixed(3),
    emphasis: r.mode === "hybrid",
    note: `recall@3 ${percent(r.qa_queries.recall_at["3"] ?? 0, 1)}`,
  }));
  // With a Claude report, interleave the two modes per setting so each pair compares directly.
  const heuristic = agentBars(report, "heuristic", claude === null);
  const agents = claude
    ? heuristic.flatMap((bar, i) => [bar, agentBars(claude, "Claude", true)[i]].filter((b) => b !== undefined))
    : heuristic;

  return (
    <section className="card">
      <div className="card-head">
        <h2>Latest benchmark</h2>
        <span className="muted small">{dateTime(setup.started_at)}</span>
      </div>
      <p className="muted small">
        {setup.incident_cases} incidents and {setup.qa_queries} questions. Agents in{" "}
        {setup.llm_mode} mode{setup.llm_model ? ` (${setup.llm_model})` : ""}, search on{" "}
        {setup.search_backend} with {setup.embedder}, commit {setup.git_commit.slice(0, 7)}.
        {claude &&
          ` Claude agents: ${claude.setup.llm_model}, ${dateTime(claude.setup.started_at)}, commit ${claude.setup.git_commit.slice(0, 7)}.`}
      </p>
      <div className="charts">
        <BarList
          bars={retrieval}
          max={1}
          caption="Runbook retrieval on paraphrased questions, mean reciprocal rank"
        />
        <BarList
          bars={agents}
          max={1}
          caption={
            claude
              ? "Correct runbook chosen as root cause, heuristic agents against Claude. Unseen failure types are held out of the similar-incident index."
              : "Correct runbook chosen as root cause. Unseen categories are held out of the similar-incident index."
          }
        />
      </div>
    </section>
  );
}

export function Overview({ apiKey, health, incidents, onOpenRun }: Props) {
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [report, setReport] = useState<BenchmarkReport | null>(null);
  const [claude, setClaude] = useState<BenchmarkReport | null>(null);
  const [benchmarkError, setBenchmarkError] = useState<string | null>(null);

  useEffect(() => {
    if (!apiKey) return;
    api.recentRuns(apiKey).then(setRuns).catch(() => setRuns([]));
    api
      .benchmark(apiKey)
      .then(setReport)
      .catch(() => setBenchmarkError("No benchmark report yet. Run python -m evals.benchmark."));
    // Optional: shown alongside the baseline when a Claude benchmark exists.
    api
      .benchmark(apiKey, "anthropic")
      .then(setClaude)
      .catch(() => setClaude(null));
  }, [apiKey]);

  const count = (status: RunRecord["status"]) => runs.filter((r) => r.status === status).length;
  const open = incidents.filter((i) => i.status === "open").length;
  const waiting = runs.filter((r) => r.status === "awaiting_approval");

  return (
    <div className="overview">
      <div className="tiles">
        <StatTile label="Open incidents" value={open} detail={`of ${incidents.length} on record`} />
        <StatTile
          label="Awaiting approval"
          value={waiting.length}
          tone={waiting.length > 0 ? "warning" : undefined}
          detail="runs paused for a human"
        />
        <StatTile label="Completed runs" value={count("completed")} detail={`last ${runs.length} runs`} />
        <StatTile
          label="Failed runs"
          value={count("failed")}
          tone={count("failed") > 0 ? "critical" : undefined}
          detail={`last ${runs.length} runs`}
        />
        <StatTile
          label="API"
          value={health}
          tone={
            health === "ok" || health === "replay" ? "good" : health === "checking" ? undefined : "critical"
          }
        />
      </div>

      {waiting.length > 0 && (
        <section className="card callout tone-warning">
          <h2>Needs your decision</h2>
          <ul className="plain">
            {waiting.map((r) => (
              <li key={r.run_id} className="decision-row">
                <span>
                  <strong>{r.incident_id}</strong>{" "}
                  <span className="muted small">paused {relativeTime(r.updated_at)}</span>
                </span>
                <button type="button" onClick={() => onOpenRun(r)}>
                  Review
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="card">
        <h2>Recent runs</h2>
        {runs.length === 0 ? (
          <p className="muted small">No runs yet. Open an incident and analyze it.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Incident</th>
                  <th>Status</th>
                  <th>Stage</th>
                  <th className="num">Retries</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.run_id} className="clickable" onClick={() => onOpenRun(r)}>
                    <td>
                      <button type="button" className="link" onClick={() => onOpenRun(r)}>
                        {r.incident_id}
                      </button>
                    </td>
                    <td>
                      <StatusBadge status={r.status} />
                    </td>
                    <td>{r.stage?.replace("_", " ") ?? "none"}</td>
                    <td className="num">{r.retry_count}</td>
                    <td className="muted">{relativeTime(r.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {report ? (
        <Benchmark report={report} claude={claude} />
      ) : (
        benchmarkError && <p className="muted small">{benchmarkError}</p>
      )}

      {DEMO && <HowItWorks />}
    </div>
  );
}
