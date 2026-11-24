# The critic as an A2A service

The critic is the one agent whose job is to doubt the others: it checks that a plan's
evidence ids exist, that the chosen root cause is not contradicted by its own evidence, and
that every proposed action is valid, and it can send work back. It runs as a standalone
service that the orchestrator calls over the [Agent2Agent protocol](https://a2a-protocol.org)
(`a2a-sdk` 1.x, spec 1.0).

## Why split it out

- Independent review: the reviewer runs apart from the planner, in its own process,
  with its own configuration. It can use a different model from the agents it reviews, and
  it holds no tool permissions or API keys, only the hash of the key callers must present.
- A standard boundary: any A2A client can call it and any A2A agent can replace it, such as a
  critic written in another framework, run by another team, or using another model, as long
  as it offers the `review_remediation_plan` skill.
- Independent scaling: reviews are stateless, so the critic runs several replicas in
  Kubernetes while the orchestrator stays at one (its SQLite state allows only one).

## How the hop works

1. The orchestrator reads the critic's Agent Card (`/.well-known/agent-card.json`), which
   advertises the skill, the JSON-RPC endpoint and the API-key scheme.
2. It sends the plan with the evidence it cites as a JSON data part. Both sides validate it
   with the same Pydantic models.
3. The critic runs the same checks as the in-process critic and returns
   `{approved, reasons, risk_level}` plus the detailed verdict, so retry routing is unchanged.
4. If the critic is down, times out, rejects the request or returns something malformed, the
   plan counts as not approved: no retries, the reason goes into the report, and the run goes
   to a human, even when the plan changes nothing in production.

## Keys and tracing

The key pair comes from `python -m critic_service.keys`: the orchestrator holds the key, the
critic only its SHA-256 hash, and the SDK's auth interceptor sends it as the card asks. A W3C
`traceparent` header carries the trace across, so one OpenTelemetry trace, with the run's
SentinelAI trace id, spans both services.

## Trade-offs

The hop adds a network call and a failure mode the in-process critic does not have, which is
why failures fall back to human review. `CRITIC_MODE=local` keeps the critic in-process, and
the tests, the benchmark and `make demo` use it by default; Docker Compose and Kubernetes run
it as a service.
