from fastapi import APIRouter, Body, Depends, Query, status
from pydantic import BaseModel, Field

from app.container import Container
from app.dependencies import get_container, require
from auth.permissions import Principal
from auth.rbac import Permission
from core.enums import Role
from core.exceptions import NotFoundError, UnauthorizedActionError
from evals.benchmark import Provider
from evals.report import BenchmarkReport
from evals.service import EvalStatus

router = APIRouter(prefix="/evals", tags=["evaluations"])


class RunBody(BaseModel):
    provider: Provider = "heuristic"
    limit: int | None = Field(default=None, ge=1, le=500)


@router.get("/latest", response_model=BenchmarkReport)
async def latest(
    provider: Provider = Query(default="heuristic", description="which agent mode's report"),
    container: Container = Depends(get_container),
    _: Principal = Depends(require(Permission.READ_REPORTS)),
) -> BenchmarkReport:
    report = container.evals.latest(provider)
    if report is None:
        raise NotFoundError(
            f"no {provider} benchmark has been run yet; POST /evals/run or python -m "
            "evals.benchmark"
        )
    return report


@router.get("/status", response_model=EvalStatus)
async def eval_status(
    container: Container = Depends(get_container),
    _: Principal = Depends(require(Permission.READ_REPORTS)),
) -> EvalStatus:
    return container.evals.status


@router.post("/run", response_model=EvalStatus, status_code=status.HTTP_202_ACCEPTED)
async def run(
    body: RunBody = Body(default_factory=RunBody),
    container: Container = Depends(get_container),
    principal: Principal = Depends(require(Permission.RUN_EVALS)),
) -> EvalStatus:
    # LLM benchmarks spend money, so only admins may start them.
    if body.provider == "anthropic" and principal.role is not Role.ADMIN:
        raise UnauthorizedActionError("only admins can start a benchmark that calls Claude")
    return container.evals.start(body.provider, body.limit)
