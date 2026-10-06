import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import structlog
from pydantic import BaseModel

from app.config import Settings
from core.exceptions import InvalidStateError
from evals.benchmark import Provider, reports_dir_for, run_benchmark
from evals.report import BenchmarkReport, load_latest

log = structlog.get_logger(__name__)


class EvalStatus(BaseModel):
    state: Literal["idle", "running", "failed"]
    started_at: datetime | None = None
    provider: Provider | None = None
    error: str | None = None


class EvaluationService:
    """Runs one benchmark at a time in the background for the /evals API."""

    def __init__(self, settings: Settings, reports_dir: Path) -> None:
        self.settings = settings
        self.reports_dir = reports_dir
        self.status = EvalStatus(state="idle")
        self._task: asyncio.Task[None] | None = None

    def latest(self, provider: Provider = "heuristic") -> BenchmarkReport | None:
        return load_latest(reports_dir_for(self.reports_dir, provider))

    def start(self, provider: Provider, limit: int | None) -> EvalStatus:
        if self._task is not None and not self._task.done():
            raise InvalidStateError(
                "a benchmark is already running",
                details={"started_at": str(self.status.started_at)},
            )
        self.status = EvalStatus(state="running", started_at=datetime.now(UTC), provider=provider)
        self._task = asyncio.create_task(self._run(provider, limit))
        return self.status

    async def wait(self) -> None:
        if self._task is not None:
            await self._task

    async def shutdown(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _run(self, provider: Provider, limit: int | None) -> None:
        try:
            await run_benchmark(
                self.settings,
                provider=provider,
                limit=limit,
                out_dir=reports_dir_for(self.reports_dir, provider),
            )
        except Exception as exc:
            # Background task: record the failure for GET /evals/status and log the traceback.
            log.exception("benchmark_failed")
            self.status = self.status.model_copy(
                update={"state": "failed", "error": f"{type(exc).__name__}: {exc}"}
            )
            return
        self.status = EvalStatus(state="idle")
