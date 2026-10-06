import { useEffect, useState } from "react";

import { dateTime } from "../format";
import { demoManifest, type DemoManifest } from "./replay";

const REPO = "https://github.com/gagan-rohith/sentinel-ai";

// What the replay is showing, for visitors who did not come from the README.
export function HowItWorks() {
  const [manifest, setManifest] = useState<DemoManifest | null>(null);

  useEffect(() => {
    demoManifest()
      .then(setManifest)
      .catch(() => setManifest(null));
  }, []);

  const overA2A = manifest?.critic_mode === "a2a";

  return (
    <section className="card how-it-works">
      <h2>How it works</h2>
      <ul>
        <li>
          <strong>Agents in a LangGraph workflow.</strong> Triage, context collection, retrieval,
          root cause and remediation run in sequence; a critic checks every cited evidence id and
          can send work back.
        </li>
        <li>
          <strong>Hybrid search on Elasticsearch.</strong> Runbooks and past incidents are found with
          BM25 and vector search fused by reciprocal rank.
        </li>
        <li>
          <strong>A human approves production changes.</strong> The run pauses; only an admin can
          approve, and each approval executes once.
        </li>
        <li>
          <strong>The critic is a separate A2A service.</strong> The orchestrator calls it over the
          Agent2Agent protocol with an API key, and one OpenTelemetry trace spans both services.{" "}
          {overA2A
            ? "Every review in these recordings came back from that service."
            : "These recordings ran the critic in-process; the Docker and Kubernetes setups run it as the service."}
        </li>
      </ul>
      {manifest && (
        <p className="muted small">
          Recorded {dateTime(manifest.recorded_at)}: {manifest.incidents} incidents, search on{" "}
          {manifest.search_backend ?? "elasticsearch"}, deterministic agent mode.{" "}
          <a href={`${REPO}#a2a-design`} target="_blank" rel="noreferrer">
            A2A design
          </a>{" "}
          <a href={`${REPO}#architecture`} target="_blank" rel="noreferrer">
            Architecture
          </a>
        </p>
      )}
    </section>
  );
}
