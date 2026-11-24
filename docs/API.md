# REST API

Every request except `/health` needs an `X-API-Key` header. Interactive docs are served at
http://localhost:8000/docs.

## A full run

```bash
KEY=<operator key>; ADMIN=<admin key>

# Start an analysis
curl -X POST -H "X-API-Key: $KEY" localhost:8000/agents/analyze/INC-1060
# {"run_id": "run-4f1c...", "status": "queued", ...}

# Poll until it completes or pauses
curl -H "X-API-Key: $KEY" localhost:8000/agents/status/run-4f1c...

# See what it wants to do
curl -H "X-API-Key: $KEY" localhost:8000/agents/run-4f1c.../approval

# Approve (admin) or reject (operator, reason required)
curl -X POST -H "X-API-Key: $ADMIN" -H "Content-Type: application/json" \
  -d '{"comment": "pool saturation confirmed"}' localhost:8000/agents/run-4f1c.../approve
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"reason": "restart during peak is too risky"}' localhost:8000/agents/run-4f1c.../reject

# Full report: evidence, hypotheses, plan, executed actions, postmortem
curl -H "X-API-Key: $KEY" localhost:8000/agents/run-4f1c.../report
```

## Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /incidents`, `GET /incidents/{id}`, `POST /incidents` | Incident records |
| `POST /agents/analyze/{id}` | Start a run |
| `GET /agents/runs`, `GET /agents/status/{run_id}` | Run list and status |
| `GET /agents/{run_id}/approval`, `POST .../approve`, `POST .../reject` | Human approval |
| `GET /agents/{run_id}/report` | Final report |
| `GET /tools/logs/{service}`, `/tools/metrics/{service}`, `/tools/deployments/{service}`, `/tools/search` | Direct tool access |
| `GET /evals/latest`, `POST /evals/run` | Benchmark results |
| `GET /health`, `GET /metrics` | Health and Prometheus metrics |

## Errors and tracing

Errors share one shape, `{"error": {"code", "message", "details", "trace_id"}}`, and every
response carries an `X-Trace-Id` header that also appears in the logs.
