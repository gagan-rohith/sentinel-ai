"""Record real runs for the web UI's replay mode (the GitHub Pages demo).

Run with: python -m app.record_demo --out frontend/public/demo

Every incident is analyzed through the real HTTP API in-process, with throwaway keys and a
temporary database, as in app.demo. Runs that pause for approval are recorded twice, once
approved and once rejected, so the replay can show either decision. The output is plain
JSON that the frontend plays back without a server.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.demo import DemoError, _expect, _wait, demo_settings
from app.main import create_app
from auth.api_keys import generate_key, hash_key

# Placeholders the replay swaps for what the visitor typed and who they chose to be.
COMMENT = "__DEMO_COMMENT__"
ADMIN = "demo admin"
OPERATOR = "demo operator"


def _subject(key: str) -> str:
    return f"apikey:{hash_key(key)[:8]}"


def stage_sequence(report: dict[str, Any], decision: str | None) -> list[str]:
    """Graph nodes in the order the run went through them, rebuilt from its agent calls."""
    stages: list[str] = []
    for call in report["agent_calls"]:
        agent = call["agent"]
        if agent == "postmortem":
            continue
        stages.append(agent)
        if agent == "triage":
            stages.append("context_collection")
    if decision is not None:
        stages.append("human_approval")
        if decision == "approved":
            stages.append("action_execution")
    stages.append("postmortem")
    return stages


def _anonymize(data: Any, keys: dict[str, str]) -> Any:
    text = json.dumps(data)
    text = text.replace(_subject(keys["admin"]), ADMIN)
    text = text.replace(_subject(keys["operator"]), OPERATOR)
    return json.loads(text)


class Recorder:
    def __init__(self, client: TestClient, keys: dict[str, str]) -> None:
        self.client = client
        self.keys = keys
        self.operator = {"X-API-Key": keys["operator"]}
        self.admin = {"X-API-Key": keys["admin"]}

    def _start(self, incident_id: str) -> dict[str, Any]:
        run = _expect(
            self.client.post(f"/agents/analyze/{incident_id}", headers=self.operator), 202
        )
        return _wait(self.client, self.operator, run["run_id"])

    def _report(self, run_id: str) -> dict[str, Any]:
        response = self.client.get(f"/agents/{run_id}/report", headers=self.operator)
        report = dict(_expect(response, 200))
        # A recording must show a real review, never the fallback for an unreachable critic.
        review = report.get("critic_review") or {}
        if any(issue.startswith("critic unavailable") for issue in review.get("issues", [])):
            raise DemoError(f"the critic was unavailable during {run_id}: {review['issues'][0]}")
        return report

    def _decide(self, run_id: str, approve: bool) -> dict[str, Any]:
        if approve:
            response = self.client.post(
                f"/agents/{run_id}/approve", headers=self.admin, json={"comment": COMMENT}
            )
        else:
            response = self.client.post(
                f"/agents/{run_id}/reject", headers=self.operator, json={"reason": COMMENT}
            )
        _expect(response, 202)
        run = _wait(self.client, self.operator, run_id)
        if run["status"] != "completed":
            raise DemoError(f"run {run_id} ended as {run['status']} after the decision")
        return self._report(run_id)

    def record(self, incident_id: str) -> dict[str, Any]:
        run = self._start(incident_id)
        if run["status"] == "completed":
            report = self._report(run["run_id"])
            return {
                "incident_id": incident_id,
                "approval": None,
                "stages": stage_sequence(report, None),
                "report": report,
            }

        approval = _expect(
            self.client.get(f"/agents/{run['run_id']}/approval", headers=self.operator), 200
        )
        approved = self._decide(run["run_id"], approve=True)
        # A second run of the same incident, rejected this time.
        rejected = self._decide(self._start(incident_id)["run_id"], approve=False)
        recording: dict[str, Any] = _anonymize(
            {
                "incident_id": incident_id,
                "approval": approval,
                "stages_approved": stage_sequence(approved, "approved"),
                "stages_rejected": stage_sequence(rejected, "rejected"),
                "report_approved": approved,
                "report_rejected": rejected,
            },
            self.keys,
        )
        return recording


def record_all(
    client: TestClient,
    keys: dict[str, str],
    out: Path,
    setup: dict[str, str] | None = None,
) -> dict[str, Any]:
    recorder = Recorder(client, keys)
    health = _expect(client.get("/health"), 200)
    if health["checks"].get("search") != "ok":
        raise DemoError("search is not available; start Elasticsearch or pass --memory")

    incidents = _expect(client.get("/incidents?limit=200", headers=recorder.operator), 200)
    benchmarks = {
        "benchmark.json": client.get("/evals/latest", headers=recorder.operator),
        "benchmark-claude.json": client.get(
            "/evals/latest?provider=anthropic", headers=recorder.operator
        ),
    }

    if out.exists():
        shutil.rmtree(out)
    (out / "runs").mkdir(parents=True)
    paused: list[str] = []
    for incident in incidents:
        recording = recorder.record(incident["incident_id"])
        if recording["approval"] is not None:
            paused.append(incident["incident_id"])
        _write(out / "runs" / f"{incident['incident_id']}.json", recording)

    manifest = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "incidents": len(incidents),
        "needs_approval": paused,
        **(setup or {}),
    }
    _write(out / "incidents.json", incidents)
    for name, response in benchmarks.items():
        if response.status_code == 200:
            _write(out / name, _benchmark_summary(response.json()))
    _write(out / "manifest.json", manifest)
    return manifest


def _benchmark_summary(report: dict[str, Any]) -> dict[str, Any]:
    """What the overview panel shows; per-case details stay in evals/reports."""
    return {key: report[key] for key in ("setup", "retrieval", "agents")}


def _write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record runs for the web UI replay mode.")
    parser.add_argument("--out", type=Path, default=Path("frontend/public/demo"))
    parser.add_argument("--memory", action="store_true", help="use the in-memory search backend")
    args = parser.parse_args(argv)

    keys = {"operator": generate_key(), "admin": generate_key()}
    with tempfile.TemporaryDirectory(prefix="sentinel-record-") as tmp:
        settings = demo_settings(Path(tmp), args.memory, keys)
        try:
            with TestClient(create_app(settings)) as client:
                setup: dict[str, str] = {
                    "critic_mode": settings.critic_mode,
                    "search_backend": settings.search_backend,
                }
                manifest = record_all(client, keys, args.out, setup)
        except DemoError as exc:
            print(f"recording failed: {exc}", file=sys.stderr)
            return 1
    print(
        f"recorded {manifest['incidents']} incidents "
        f"({len(manifest['needs_approval'])} pause for approval, critic "
        f"{manifest['critic_mode']}, search {manifest['search_backend']}) to {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
