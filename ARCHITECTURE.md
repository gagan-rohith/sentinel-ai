# Architecture

This document explains how SentinelAI is put together and why. The [README](README.md) covers
what it does and how to run it; this is for someone reviewing the design or extending it.

## Overview

```
                +-------------------+
 Web UI, curl   |  FastAPI          |  X-API-Key -> Principal(role) -> Permission check
 make demo ---->|  app/api          |  X-Trace-Id middleware, typed error responses
                +---------+---------+
                          |
                +---------v---------+       +-------------------------+
                |  IncidentAnalyzer |------>|  SQLite (one connection)|
                |  graph/runner.py  |       |  incidents, runs,       |
                +---------+---------+       |  approvals, checkpoints |
                          |                 +-------------------------+
                +---------v---------+
                |  LangGraph        |  supervisor, triage, context collection, retrieval,
                |  graph/           |  root cause, remediation, critic, human approval,
                +---------+---------+  action execution, postmortem
                          |
 MCP clients    +---------v---------+       +-------------------------+
 (Claude) ----->|  ToolRegistry     |------>|  Simulated ops backend  |
 mcp_server/    |  tools/           |       |  Hybrid search -> ES 8  |
                +-------------------+       +-------------------------+
```

Three rules shape the design:

1. **Every tool call goes through the registry.** Agents, the REST API and the MCP server all
   call `ToolRegistry.invoke`, which checks permissions, validates input and output, applies a
   timeout, records the call, and enforces the approval gate. There is no second path to a
   tool, so there is no second place where safety can be got wrong.
2. **Facts that matter for safety come from code, not from a model.** Whether an action is
   destructive comes from the tool spec. Whether a citation is real is a set lookup. Whether an
   approval covers an action is a string comparison in the database. Models propose; code
   decides what is allowed.
3. **Everything runs without an LLM.** Each agent step has a deterministic heuristic over the
   same evidence. With `ANTHROPIC_API_KEY` set, Claude does the reasoning; without it, or when a
   Claude call fails, the heuristic does. This keeps tests, CI, the demo and the benchmark free
   and reproducible, and it gives the Claude mode a baseline to beat.

## Why LangGraph

The workflow is a state machine with loops and a pause, not a chain:

- The critic can send work back to three different earlier nodes (retrieval, root cause or
  remediation), up to a retry budget.
- A run has to stop in the middle, wait minutes or days for a human, survive a restart, and
  then continue from exactly where it stopped.

LangGraph gives both directly: conditional edges for the loops, and `interrupt()` plus a
checkpointer for the pause. Writing that by hand would mean persisting and restoring the
workflow position myself.

What LangGraph is **not** used for: agents are plain async functions that take state and return
a partial update. There are no LangChain agent executors, tool-calling loops or memory classes.
The routing functions in `graph/routing.py` are pure and unit tested. Context collection is not
an agent at all; it is a function that calls five tools in parallel. The graph is the only
framework piece, and pause and resume are the reason it is there.

## State management

`graph/state.py` defines `IncidentState`, a `TypedDict` that every node reads and partially
updates. Most keys are overwritten by the node that owns them (`triage_summary`,
`remediation_plan`, `critic_feedback`). Three are append-only through reducers, because several
nodes contribute to them and none should overwrite another's entries:

- `tool_calls`: every tool call with status, latency and arguments
- `agent_calls`: every agent step with mode (llm, heuristic or fallback), model, latency and tokens
- `data_gaps`: things that could not be collected, such as a tool that timed out

**The evidence catalog** (`agents/evidence.py`) is the core of grounding. Context collection
and retrieval turn everything they find into `Evidence` items with short ids (`E1`, `E2`, ...),
a kind, a one-line summary and a source reference. Items are deduplicated by source reference,
so a retry that finds the same runbook again does not create a new id. Agents cite ids, never
free text, which is what makes the critic's checks possible.

**Persistence.** There are two kinds of state:

| State | Where | Why |
|---|---|---|
| Run position and full graph state | LangGraph checkpoints (`AsyncSqliteSaver`) | Needed to resume a paused run |
| Run status, stage, report; approvals; incidents | App tables in `storage/` | Queried by the API and UI |

Both live in the same SQLite file and share **one** `aiosqlite` connection
(`storage/db.py`). An earlier version gave the checkpointer its own connection; in WAL mode a
transaction that upgrades from read to write fails immediately with "database is locked"
instead of waiting, and the two connections tripped over each other under load. One connection
plus a busy timeout removed the failures in a stress test.

Checkpoints are deserialized with an **allowlist** (`graph/checkpoint.py`): only the Pydantic
models and enums from the project's own state modules can be rebuilt from the database, so a
tampered checkpoint cannot instantiate arbitrary classes.

## Why Elasticsearch

Retrieval needs keyword search (error strings, metric names and service names must match
exactly), vector search (a paraphrased question must find the runbook that answers it), and
metadata filters (service, environment, source type, excluding specific incidents), all over
the same documents.

Elasticsearch does all three in one index: `text` fields with BM25, a `dense_vector` field
(384 dimensions, cosine) for kNN, and keyword fields for filters. One system to run, one place
to index, and it is what many SRE teams already operate for logs. A dedicated vector database
would have added a second store and still needed a keyword engine next to it.

The index carries a **signature** in its mapping metadata: a document format version, the
embedding model name and the vector size. The ingestion job compares it on every start and
rebuilds only when something changed, so an index built with a different model or an older
document format is never searched by mistake. This came from a real bug during development,
where a stale index silently served old documents.

Behind a `SearchBackend` protocol there is also an in-memory backend (a small BM25
implementation plus numpy cosine similarity). Tests and CI use it with a deterministic hash embedder, so the suite needs
neither Docker nor a model download. CI still runs the Elasticsearch integration tests against
a real service container.

## Why hybrid retrieval

BM25 and vectors fail in different ways. BM25 misses a question worded differently from the
runbook; vectors blur exact identifiers such as `HikariPool-1` or `OOMKilled`. The benchmark
shows it on 42 paraphrased questions:

| Mode | Recall@1 | MRR |
|---|---|---|
| BM25 | 71.4% | 0.818 |
| Vector | 79.8% | 0.885 |
| Hybrid | 91.7% | 0.952 |

**Fusion is done client-side with reciprocal rank fusion** (`retrieval/hybrid_search.py`):
each document scores `sum(1 / (60 + rank))` over the two rankings. RRF uses ranks, not scores,
so it needs no tuning to reconcile BM25 scores with cosine similarities, and doing it in Python
keeps it independent of Elasticsearch license tiers and makes it unit-testable. A weighted
score fusion is available as an option, and a cross-encoder reranker can be switched on with
`RERANKER_MODEL`.

Runbooks are indexed as sections, so a hit points at the relevant part. Results are
over-fetched and then **collapsed to one hit per parent document**, so five sections of the
same runbook do not crowd out other runbooks.

## Why MCP

The investigation tools are useful outside the agent workflow too: an engineer in Claude
Desktop or Claude Code should be able to ask "check checkout-api's logs and find the matching
runbook". The Model Context Protocol is the standard way to expose tools to those clients, so
there is no custom plugin per client.

`mcp_server/` is a thin adapter: each MCP tool maps to a registry tool, with its input schema,
output schema and `readOnlyHint` or `destructiveHint` annotation. Authentication uses the same
API keys as the REST API (an environment variable over stdio, a header over HTTP). Because the
adapter calls the same `ToolRegistry.invoke`, MCP gets the permission checks and the approval
gate for free. The practical result is that an assistant connected over MCP can investigate
anything its key allows but cannot restart or roll back a service, since that needs an admin
key and an approval id from the human workflow.

Inside the graph, agents call the registry directly in-process rather than going through MCP.
A network hop to reach tools that live in the same process would add latency and failure modes
without adding any safety, because the checks live in the registry either way.

## Human approval design

**When a run pauses.** The remediation agent marks the plan as needing approval if any step
calls a tool whose spec is `destructive=True`. That flag is set in code in
`tools/tool_registry.py`, so a model cannot talk its way out of an approval by describing a
restart as harmless. After the critic, `route_after_critic` sends such a plan to
`human_approval` even when the critic's retries ran out with issues still open; those issues are
shown to the approver instead.

**How it pauses.** `human_approval_node` builds an `ApprovalRequest` (root cause, confidence,
the destructive actions with their exact arguments, overall risk, rollback plan, unresolved
critic issues) and calls `interrupt()`. LangGraph saves the checkpoint and the run's background
task ends. `IncidentAnalyzer` reads the interrupt, stores the request in the `approvals` table,
and marks the run `awaiting_approval`. Nothing is held in memory, so the API can restart while
a run waits.

**How a decision is made.**

- Approving needs `remediation:execute`, which only `admin` has. Rejecting needs
  `remediation:reject`, which `operator` has, and a reason. Stopping a change should be easier
  than making one.
- The decision is a conditional update: `UPDATE approvals ... WHERE status = 'pending'`. Of two
  concurrent decisions exactly one succeeds; the other gets 409.
- The run resumes with `Command(resume=decision)`. `interrupt()` returns the decision inside the
  node, and routing sends the run to `action_execution` or straight to `postmortem`.

**How actions run.** `action_execution_node` runs each approved action **as the approver**, not
as the agent identity, so the audit trail names the human. The registry's approval check then
verifies, in the database, that:

1. the approval exists and is approved,
2. this exact tool and argument set is one of the approved actions,
3. it has not been consumed yet.

The consumed list is updated with a compare-and-set, so each approved action runs exactly once,
whether it is called from the workflow, the REST API or MCP. Execution stops at the first failed
action rather than applying later steps on a system in an unexpected state.

The agents themselves run as `agent:sentinel` with the operator role, so even a bug that
skipped the graph's approval node would be refused by the registry.

## Retry strategy

The critic (`agents/critic_agent.py`) combines code checks with an optional model review.

**Code checks**, each mapped to the stage that can fix it:

| Finding | Verdict | Goes back to |
|---|---|---|
| No runbook evidence; selected cause cites nothing; confidence below 0.35 | `need_more_evidence` | retrieval |
| A hypothesis cites an evidence id that does not exist; the selected cause has more evidence against than for; fewer than 3 hypotheses | `revise_root_cause` | root cause |
| No steps, or no mitigation or fix step; a step cites unknown evidence; an action's arguments fail the tool's schema; a rollback targets a deployment not in the evidence | `revise_remediation` | remediation |

When several findings disagree, the most upstream wins (evidence before root cause before
remediation), since a better plan cannot be built on missing evidence.

**The model may be stricter than the code, never more lenient.** If Claude approves but a code
check failed, the code verdict is used and its findings are added to the issues.

**The budget.** Each loop increments `retry_count`. After `MAX_CRITIC_RETRIES` (3 by default)
the run moves forward with `unresolved_critic_issues` set; the report and the approval request
both show the open issues. A LangGraph recursion limit of 50 is a second, hard stop against a
routing bug. In the benchmark, runs on unseen incident types trigger a retry 20% of the time,
and runs on seen types never do, which is the pattern you would want.

## Failure handling

The principle is to degrade visibly, never silently.

| Failure | What happens |
|---|---|
| A telemetry tool fails or times out (5 s default) | Recorded as a data gap; the run continues with what it has. Gaps appear in the report. |
| No telemetry at all | The supervisor stops the run with `missing_incident_data` rather than let agents guess. |
| Elasticsearch down | The API still starts and `/health` reports search as unavailable; search calls raise `SearchUnavailableError`, which becomes a data gap in a run. |
| A Claude call fails (rate limit, API error, refusal, schema mismatch) | That step falls back to its heuristic, recorded as `mode="fallback"` with the error. The report's mode becomes `mixed`, and metrics count fallbacks. |
| A tool returns data that does not match its output schema | `MalformedToolResponseError`; the output is never passed on unvalidated. |
| An unexpected exception in a run | Caught at the top of the background task, logged with the traceback, and the run is marked failed with the error. A background task has no caller to raise to. |
| The run store itself fails while recording a failure | Logged as `run_failure_not_recorded`; the next startup marks the run interrupted. |
| The API restarts mid-run | On startup, runs left `queued` or `running` are marked failed with `interrupted`. Runs awaiting approval are untouched; they resume from their checkpoint. |
| An approved action fails | Recorded as failed in the report, and no later action runs. |

All errors raised on purpose are subclasses of `SentinelError` with a stable `code`, an HTTP
status and structured `details`. The API returns them in one shape,
`{"error": {"code", "message", "details", "trace_id"}}`, so a client or an MCP-connected model
can act on the code rather than parse a message.

## Auth model

**API keys.** Keys are random, prefixed with `sk_sentinel_`, and configured only as SHA-256
hashes: `API_KEYS=operator:<sha256>,admin:<sha256>`. Plaintext keys never live in config,
environment files or the database. If someone pastes a plaintext key into `API_KEYS` by
mistake, startup fails with a message that names the entry's position but never echoes its
value. A caller's identity in logs and approvals is `apikey:<first 8 hex of the hash>`.

**Roles and permissions** (`auth/rbac.py`):

| Permission | viewer | operator | admin |
|---|---|---|---|
| Read incidents and reports | yes | yes | yes |
| Create incidents, run analyses, read tools, create tickets, run evals | | yes | yes |
| Reject a remediation | | yes | yes |
| Approve and execute a remediation | | | yes |

Endpoints declare the permission they need with a FastAPI dependency. Tools declare it in their
spec, and the registry checks it on every call regardless of the caller. Destructive tools need
the permission **and** a valid approval.

**Why keys and not OAuth.** This is a local, single-tenant demo. API keys keep setup to one
command while still exercising real role-based authorization. Swapping in an identity provider
means producing a `Principal` from a token instead of a key hash; nothing downstream of the
`Principal` would change.

## Observability

- **Trace ids.** Every request gets an id, the caller's `X-Trace-Id` when it is well formed or a
  new one otherwise, returned in the response header and bound to the logging context. A run
  started by a request inherits it, so the API call, every agent step and every tool call of
  that run share one id, and so does the final report.
- **Logs.** structlog JSON (or console format for local reading). Run logs also carry `run_id`.
  Tool calls log the tool, status, latency and caller; arguments are recorded in the run's
  tool call list rather than the log stream.
- **Metrics** at `/metrics`, all prefixed `sentinel_`: HTTP requests and latency by route
  template, tool calls and latency by tool and status, agent steps and latency by mode, runs by
  outcome, critic retries, approval decisions, LLM tokens and estimated cost. Labels are bounded
  (route templates, tool and agent names, never raw paths or arguments), so cardinality does
  not grow with traffic.
- **LangSmith**, only when `LANGSMITH_API_KEY` is set: one trace per run with spans for each
  agent, Claude call and tool call. The test suite forces tracing off so it never uploads
  anything.
- **The report is an audit record.** Every run's report includes each agent call with its
  mode, latency and tokens, the number of tool calls, data gaps, critic retries and the
  approval decision with the approver's identity.

## Trade-offs and known limits

- **SQLite means one API process per database.** It keeps the stack to Elasticsearch plus the
  app, and LangGraph checkpoints sit next to app data in one file. Running several replicas
  would mean moving both to PostgreSQL; LangGraph has a PostgreSQL checkpointer, and the
  repositories are small.
- **Background runs are asyncio tasks in the API process.** Simple and enough for this scale.
  A queue and separate workers would be the next step for long or numerous runs; paused runs
  already live in the checkpointer, so only in-flight runs are tied to a process.
- **The UI polls** run status every 700 ms instead of streaming progress.
- **Ops data is simulated**, so tool handlers are thin. Real integrations (Prometheus, a log
  store, the Kubernetes API) would replace the handlers behind the same tool specs, and the
  registry, agents and MCP server would not change.
- **The heuristic agents are strong on incident types they have seen and weak on new ones**
  (100% vs 41.7% runbook accuracy). Claude closes most of that gap (90% on unseen types), at
  about a minute and 14 cents per incident, with slightly more unsupported claims and more
  plans that need approval. The heuristics stay as the free, offline fallback and baseline.
