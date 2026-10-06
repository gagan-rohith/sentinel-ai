from dataclasses import dataclass

import structlog
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from agents.llm import AnthropicLLM, StructuredLLM
from app.config import Settings
from auth.api_keys import ApiKeyAuthenticator, parse_key_config
from auth.permissions import AGENT_PRINCIPAL
from core.exceptions import SearchUnavailableError
from critic_service.client import A2ACriticClient
from data.loader import load_incidents
from evals.service import EvaluationService
from graph.checkpoint import open_checkpointer
from graph.runner import IncidentAnalyzer
from graph.state import AgentDeps
from retrieval.backend import SearchBackend
from retrieval.factory import create_search_backend, embedder_from_settings, reranker_from_settings
from retrieval.hybrid_search import HybridSearcher
from retrieval.indexing import build_documents, ensure_current_index
from storage.approvals import ApprovalStore
from storage.db import Database
from storage.incidents import IncidentRepository
from storage.runs import RunRepository
from tools.backend import SimulatedOpsBackend
from tools.tickets import TicketStore
from tools.tool_registry import ToolRegistry, build_default_registry

log = structlog.get_logger(__name__)


@dataclass
class Container:
    """Long-lived application services, built once at startup."""

    settings: Settings
    db: Database
    incidents: IncidentRepository
    backend: SimulatedOpsBackend
    search_backend: SearchBackend
    searcher: HybridSearcher
    tools: ToolRegistry
    api_keys: ApiKeyAuthenticator
    analyzer: IncidentAnalyzer
    checkpointer: AsyncSqliteSaver
    evals: EvaluationService

    @classmethod
    async def create(cls, settings: Settings) -> "Container":
        db = Database(settings.database_path)
        await db.connect()
        incidents = IncidentRepository(db)
        if settings.seed_incidents and await incidents.count() == 0:
            await incidents.seed(load_incidents(settings.data_dir))

        backend = SimulatedOpsBackend.from_data_dir(settings.data_dir)
        search_backend = create_search_backend(settings)
        embedder = embedder_from_settings(settings)
        searcher = HybridSearcher(search_backend, embedder, reranker_from_settings(settings))
        if settings.auto_index:
            await _ensure_indexed(settings, search_backend, searcher, backend)

        approvals = ApprovalStore(db)
        tools = build_default_registry(
            backend,
            TicketStore(),
            searcher,
            approvals=approvals,
            timeout_s=settings.tool_timeout_seconds,
        )
        deps = AgentDeps(
            tools=tools,
            llm=create_llm(settings),
            principal=AGENT_PRINCIPAL,
            max_retries=settings.max_critic_retries,
            critic=_remote_critic(settings),
        )
        checkpointer = await open_checkpointer(db.conn)
        runs = RunRepository(db)
        interrupted = await runs.fail_interrupted()
        if interrupted:
            log.warning("runs_interrupted_by_restart", count=interrupted)
        return cls(
            settings=settings,
            db=db,
            incidents=incidents,
            backend=backend,
            search_backend=search_backend,
            searcher=searcher,
            tools=tools,
            api_keys=ApiKeyAuthenticator(parse_key_config(settings.api_keys)),
            analyzer=IncidentAnalyzer(deps, runs, approvals, checkpointer),
            checkpointer=checkpointer,
            evals=EvaluationService(settings, settings.eval_reports_dir),
        )

    async def close(self) -> None:
        await self.evals.shutdown()
        await self.analyzer.shutdown()
        await self.search_backend.close()
        await self.db.close()


def _remote_critic(settings: Settings) -> A2ACriticClient | None:
    if settings.critic_mode != "a2a":
        return None
    if settings.critic_api_key is None or not settings.critic_api_key.get_secret_value():
        # A configuration mistake, not an outage: fail at startup rather than on every run.
        raise ValueError("CRITIC_MODE=a2a needs CRITIC_API_KEY; see python -m critic_service.keys")
    log.info("critic_mode_a2a", url=settings.critic_url)
    return A2ACriticClient(
        settings.critic_url,
        api_key=settings.critic_api_key.get_secret_value(),
        timeout_s=settings.critic_timeout_seconds,
    )


def create_llm(settings: Settings) -> StructuredLLM | None:
    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
    if settings.llm_provider == "heuristic" or (settings.llm_provider == "auto" and not key):
        log.info("llm_disabled", reason="heuristic mode")
        return None
    # With llm_provider=anthropic and no key, the SDK resolves credentials itself
    # (for example an `ant auth login` profile).
    return AnthropicLLM(
        settings.llm_model,
        api_key=key,
        timeout_s=settings.llm_timeout_seconds,
        effort=settings.llm_effort,
    )


async def _ensure_indexed(
    settings: Settings,
    search_backend: SearchBackend,
    searcher: HybridSearcher,
    ops: SimulatedOpsBackend,
) -> None:
    # The API still starts when Elasticsearch is down; /health reports it and search
    # calls fail with SearchUnavailableError until it is reachable.
    try:
        await ensure_current_index(
            search_backend, searcher.embedder, lambda: build_documents(settings.data_dir, ops)
        )
    except SearchUnavailableError as exc:
        log.error("search_index_unavailable", error=exc.message)
