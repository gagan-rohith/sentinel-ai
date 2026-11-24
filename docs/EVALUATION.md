# Evaluation

`make bench` runs the benchmark and writes `evals/reports/latest.json` and `latest.md`.
`python -m evals.benchmark --provider anthropic --out evals/reports/claude` runs the same
benchmark with Claude doing the agents' reasoning.

## Dataset

60 synthetic incidents: 20 failure types (connection pool exhaustion, OOM kills, expired TLS
certificates, bad deploys, Kafka lag, and so on), 3 variants each, with logs, metrics, deploy
history, ground truth root cause and the relevant runbooks. Plus 42 paraphrased questions,
written to avoid the runbooks' own wording, for testing retrieval.

## Two agent settings

- **Standard:** the incident under test is hidden from similar-incident search, but its two
  sibling variants are not.
- **Holdout:** every past incident with the same failure type is hidden too, so the agents
  cannot copy a matching precedent and have to reason from runbooks and telemetry. This is the
  more honest measure.

## Results

Retrieval and the heuristic agents are from
[evals/reports/latest.md](../evals/reports/latest.md) (commit `d8d68bb`); the Claude agents are
from [evals/reports/claude/latest.md](../evals/reports/claude/latest.md) (commit `26924f0`,
`claude-sonnet-5-5` at its default effort, 2026-10-06). Both use Elasticsearch with
all-MiniLM-L6-v2, 60 incidents and 42 questions.

| Retrieval on paraphrased questions | Recall@1 | Recall@3 | MRR |
|---|---|---|---|
| BM25 | 71.4% | 91.7% | 0.818 |
| Vector | 79.8% | 97.6% | 0.885 |
| Hybrid (RRF) | **91.7%** | 96.4% | **0.952** |

| Agents | Heuristic, standard | Claude, standard | Heuristic, holdout | Claude, holdout |
|---|---|---|---|---|
| Correct runbook chosen as root cause | 100.0% | 100.0% | 41.7% | **90.0%** |
| Root cause matches the ground truth in meaning | 100.0% | 100.0% | 0.0% | 100.0% |
| Citation validity (cited ids that exist) | 100.0% | 100.0% | 100.0% | 100.0% |
| Unsupported claim rate | 0.0% | 2.2% | 0.0% | 1.9% |
| Brier score (lower is better) | 0.127 | 0.014 | 0.253 | 0.102 |
| Runs where the critic sent work back | 0.0% | 45.0% | 20.0% | 41.7% |
| Plans that needed human approval | 20.0% | 55.0% | 25.0% | 53.3% |
| Mean time per incident | 164 ms | 72 s | 204 ms | 74 s |
| Cost of the 60 runs | $0 | $8.34 | $0 | $8.58 |

## How to read this

- Hybrid retrieval puts the right runbook first far more often than either method alone
  (91.7% vs 71.4% and 79.8%), which is what the agents consume.
- Standard accuracy is 100% for both because a sibling incident with the same root cause is
  always in the index. Holdout, with every precedent hidden, is the real measure of reasoning.
- On failure types it has never seen, Claude picks the right runbook 90% of the time against
  41.7% for the heuristic agents. It fixed 29 of the heuristics' 35 holdout misses and broke
  none of their hits.
- Claude's six holdout misses are correct diagnoses that the strict metric does not count: the
  explanation matches the ground truth (hence 100% semantic match), but the chosen hypothesis
  does not cite the runbook evidence the metric requires. The strict number is kept as the
  headline because it is the same rule the heuristic numbers use.
- Claude is much better calibrated (Brier 0.014 and 0.102 against 0.127 and 0.253).
- The costs: about 2% unsupported claims against none, the critic sends work back far more
  often, each incident takes about a minute and about 14 cents, and plans propose
  production-changing actions more often, so about half of them wait for human approval.
- The dataset is synthetic and small. Treat the numbers as a regression baseline, not as
  evidence of production performance.
