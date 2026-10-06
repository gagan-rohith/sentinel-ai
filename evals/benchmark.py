"""Run the SentinelAI benchmark.

Usage:
    python -m evals.benchmark                         # heuristic agents, all 60 incidents
    python -m evals.benchmark --provider anthropic    # Claude (needs ANTHROPIC_API_KEY)
    python -m evals.benchmark --provider anthropic --incidents INC-1060   # one-run smoke test
    python -m evals.benchmark --limit 10 --skip-retrieval

Writes evals/reports/benchmark-<timestamp>.json and .md, plus latest.json and latest.md.
Search backend and embedder come from settings (.env).
"""

import argparse
import asyncio
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from agents.llm import AnthropicLLM, StructuredLLM
from app.config import Settings, get_settings
from auth.permissions import AGENT_PRINCIPAL
from data.loader import load_incidents
from evals.agent_eval import CaseResult, SettingSummary, evaluate_agents
from evals.datasets import load_incident_cases, load_qa_cases
from evals.report import BenchmarkReport, BenchmarkSetup, write_report
from evals.retrieval_eval import evaluate_retrieval
from graph.state import AgentDeps
from observability.logging import configure_logging
from retrieval.factory import create_search_backend, embedder_from_settings
from retrieval.hybrid_search import HybridSearcher
from retrieval.indexing import build_documents, ensure_current_index
from tools.backend import SimulatedOpsBackend
from tools.tickets import TicketStore
from tools.tool_registry import build_default_registry

Provider = Literal["heuristic", "anthropic"]
REPORTS_DIR = Path(__file__).resolve().parent / "reports"


def reports_dir_for(base: Path, provider: "Provider") -> Path:
    """Claude runs get their own folder, so they never replace the heuristic baseline."""
    return base / "claude" if provider == "anthropic" else base


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip()


def _llm(settings: Settings, provider: Provider) -> StructuredLLM | None:
    if provider == "heuristic":
        return None
    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
    return AnthropicLLM(
        settings.llm_model,
        api_key=key,
        timeout_s=settings.llm_timeout_seconds,
        effort=settings.llm_effort,
    )


async def run_benchmark(
    settings: Settings,
    *,
    provider: Provider = "heuristic",
    incident_ids: list[str] | None = None,
    limit: int | None = None,
    skip_retrieval: bool = False,
    skip_agents: bool = False,
    out_dir: Path = REPORTS_DIR,
    write: bool = True,
) -> BenchmarkReport:
    started_at = datetime.now(UTC)
    started = time.perf_counter()

    search_backend = create_search_backend(settings)
    embedder = embedder_from_settings(settings)
    ops = SimulatedOpsBackend.from_data_dir(settings.data_dir)
    try:
        await ensure_current_index(
            search_backend, embedder, lambda: build_documents(settings.data_dir, ops)
        )
        searcher = HybridSearcher(search_backend, embedder)

        incidents = {i.incident_id: i for i in load_incidents(settings.data_dir)}
        cases = load_incident_cases()
        if incident_ids:
            cases = [c for c in cases if c.incident_id in set(incident_ids)]
        if limit is not None:
            cases = cases[:limit]
        qa = load_qa_cases()

        retrieval = (
            [] if skip_retrieval else await evaluate_retrieval(searcher, incidents, cases, qa)
        )

        agents: list[SettingSummary] = []
        case_results: list[CaseResult] = []
        llm = _llm(settings, provider)
        if not skip_agents:
            registry = build_default_registry(
                ops, TicketStore(), searcher, timeout_s=settings.tool_timeout_seconds
            )
            deps = AgentDeps(registry, llm, AGENT_PRINCIPAL, settings.max_critic_retries)
            case_results, agents = await evaluate_agents(deps, embedder, incidents, cases)
    finally:
        await search_backend.close()

    report = BenchmarkReport(
        setup=BenchmarkSetup(
            started_at=started_at,
            duration_s=round(time.perf_counter() - started, 1),
            git_commit=_git_commit(),
            search_backend=search_backend.name,
            embedder=embedder.name,
            llm_mode=provider,
            llm_model=llm.model if llm else None,
            incident_cases=len(cases),
            qa_queries=0 if skip_retrieval else len(qa),
        ),
        retrieval=retrieval,
        agents=agents,
        cases=case_results,
    )
    if write:
        write_report(report, out_dir)
    return report


def _print_summary(report: BenchmarkReport) -> None:
    s = report.setup
    print(f"agents={s.llm_mode} model={s.llm_model} backend={s.search_backend} "
          f"embedder={s.embedder} cases={s.incident_cases}")  # fmt: skip
    for m in report.retrieval:
        print(f"retrieval {m.mode:7} incident R@3={m.incident_queries.recall_at[3]:.3f} "
              f"MRR={m.incident_queries.mrr:.3f} | QA R@3={m.qa_queries.recall_at[3]:.3f} "
              f"MRR={m.qa_queries.mrr:.3f}")  # fmt: skip
    for a in report.agents:
        cost = "n/a" if a.cost_usd is None else f"${a.cost_usd:.2f}"
        print(f"agents {a.setting:8} runbook_acc={a.runbook_accuracy:.3f} "
              f"category_acc={a.category_accuracy:.3f} brier={a.brier_score:.3f} "
              f"errors={a.errors} fallbacks={a.fallbacks} cost={cost}")  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(description="SentinelAI benchmark")
    parser.add_argument("--provider", choices=["heuristic", "anthropic"], default="heuristic")
    parser.add_argument("--incidents", help="comma separated incident ids to evaluate")
    parser.add_argument("--limit", type=int, help="evaluate only the first N incidents")
    parser.add_argument("--skip-retrieval", action="store_true")
    parser.add_argument("--skip-agents", action="store_true")
    parser.add_argument(
        "--out", type=Path, help="report folder (default: evals/reports, or its claude/ subfolder)"
    )
    args = parser.parse_args()

    # Per-tool-call logs would drown the summary; keep warnings and errors only.
    configure_logging("WARNING", "console")

    report = asyncio.run(
        run_benchmark(
            get_settings(),
            provider=args.provider,
            incident_ids=args.incidents.split(",") if args.incidents else None,
            limit=args.limit,
            skip_retrieval=args.skip_retrieval,
            skip_agents=args.skip_agents,
            out_dir=args.out or reports_dir_for(REPORTS_DIR, args.provider),
        )
    )
    _print_summary(report)
    print(f"report written to {args.out}")


if __name__ == "__main__":
    main()
