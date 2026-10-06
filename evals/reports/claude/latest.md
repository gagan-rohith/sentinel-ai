# SentinelAI benchmark

Generated 2026-10-06 20:58 UTC in 8785s at commit `26924f0`.

| Setting | Value |
|---|---|
| Agents | anthropic (`claude-sonnet-5-5`) |
| Search backend | elasticsearch |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` |
| Incident cases | 60 |
| QA queries | 42 |

## Retrieval

Runbook retrieval, top 5 after collapsing sections into their runbook.

| Mode | Queries | Recall@1 | Recall@3 | Recall@5 | Precision@3 | MRR | Similar incident hit@3 |
|---|---|---|---|---|---|---|---|
| bm25 | incident (60) | 85.0% | 100.0% | 100.0% | 43.3% | 1.000 | 100.0% |
| bm25 | QA (42) | 71.4% | 91.7% | 91.7% | 30.9% | 0.818 |  |
| vector | incident (60) | 79.2% | 98.3% | 98.3% | 42.2% | 0.967 | 100.0% |
| vector | QA (42) | 79.8% | 97.6% | 97.6% | 33.3% | 0.885 |  |
| hybrid | incident (60) | 85.0% | 100.0% | 100.0% | 43.3% | 1.000 | 100.0% |
| hybrid | QA (42) | 91.7% | 96.4% | 97.6% | 32.5% | 0.952 |  |

## Agents

- **standard**: the incident itself is hidden from similar-incident search.
- **holdout**: every past incident with the same root cause category is hidden too, so the agents cannot copy a matching precedent.

| Metric | standard | holdout |
|---|---|---|
| Cases | 60 | 60 |
| Errors | 0 | 0 |
| Runbook accuracy | 100.0% | 90.0% |
| Category accuracy | 100.0% | 13.3% |
| Semantic match rate | 100.0% | 100.0% |
| Mean semantic similarity | 0.789 | 0.753 |
| Mean confidence | 0.91 | 0.85 |
| Brier score (lower is better) | 0.014 | 0.102 |
| Expected calibration error | 0.093 | 0.055 |
| Citation validity | 100.0% | 100.0% |
| Unsupported claim rate | 2.2% | 1.9% |
| Correct runbook cited | 100.0% | 100.0% |
| Approval required | 55.0% | 53.3% |
| Runs with critic retries | 45.0% | 41.7% |
| Mean tool calls | 12.6 | 12.5 |
| Latency mean / p95 (ms) | 71755 / 134891 | 74314 / 138339 |
| LLM calls / fallbacks | 475 / 0 | 484 / 0 |
| Tokens in / out | 1559322 / 522028 | 1582296 / 541765 |
| Estimated cost (USD) | 8.34 | 8.58 |

### Runbook accuracy by category

| Category | standard | holdout |
|---|---|---|
| autoscaling_misconfiguration | 100.0% | 100.0% |
| bad_deployment | 100.0% | 66.7% |
| broken_feature_flag | 100.0% | 66.7% |
| container_crash_loop | 100.0% | 100.0% |
| cpu_throttling | 100.0% | 100.0% |
| dependency_timeout | 100.0% | 100.0% |
| disk_pressure | 100.0% | 100.0% |
| dns_resolution_failure | 100.0% | 100.0% |
| failed_db_migration | 100.0% | 33.3% |
| iam_permission_regression | 100.0% | 66.7% |
| jwt_auth_failure | 100.0% | 100.0% |
| k8s_oom_killed | 100.0% | 100.0% |
| kafka_consumer_lag | 100.0% | 100.0% |
| load_balancer_misconfiguration | 100.0% | 100.0% |
| postgres_pool_exhaustion | 100.0% | 100.0% |
| queue_backlog | 100.0% | 100.0% |
| redis_memory_eviction | 100.0% | 100.0% |
| secret_rotation_failure | 100.0% | 66.7% |
| slow_query_latency | 100.0% | 100.0% |
| tls_certificate_expired | 100.0% | 100.0% |

Misdiagnosed (holdout): INC-1010, INC-1036, INC-1038, INC-1039, INC-1045, INC-1049

## How to read this

- **Runbook accuracy**: the runbook behind the selected root cause is one of the incident's relevant runbooks. It is the headline metric because it applies whether a hypothesis came from a past incident, a runbook or an LLM.
- **Category accuracy**: the selected hypothesis carries the exact category label. Hypotheses built from runbooks have no label, so this undercounts in holdout.
- **Semantic match**: embedding cosine similarity between the selected root cause and the ground truth is at least 0.6 (sentence-transformers/all-MiniLM-L6-v2).
- **Citation validity**: share of cited evidence ids that exist in the run's evidence catalog. **Unsupported claim rate**: hypotheses with non-zero confidence and remediation steps that cite nothing.
- The dataset is synthetic: 20 failure types with 3 variants each. The standard setting always has two close siblings in the index, which is why holdout is the more honest measure of reasoning.
