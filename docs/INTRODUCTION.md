# SentinelAI, explained simply

New to the project? Start here. This page explains what SentinelAI does and how it works
without assuming you know much about operations or AI. The [README](../README.md) and
[ARCHITECTURE.md](../ARCHITECTURE.md) go deeper once you have the big picture.

**Try it first:** https://gagan-rohith.github.io/sentinel-ai/ (click "Walk through INC-1060").

## In one sentence

SentinelAI is a team of AI assistants that investigates when a website or service breaks,
works out the most likely cause, suggests a fix, and waits for a person to approve anything
risky.

## The problem

Companies run many small services that depend on each other: a checkout service, a payment
service, a database, and so on. When one of them breaks, an alarm goes off and an engineer
on call has to find out why, often at night.

Most of that first half hour is spent gathering information:

- reading error logs,
- checking graphs of traffic, memory and response times,
- checking whether anyone changed or deployed something recently,
- looking up the team's instructions for this kind of problem (called **runbooks**),
- remembering whether something similar happened before.

SentinelAI does that gathering automatically, in seconds, and hands the engineer a
reasoned explanation with the evidence attached.

## What happens when an alarm goes off

Here is the example the demo uses, incident **INC-1060**: during a flash sale, the checkout
service starts failing for many customers.

1. **First look.** An assistant reads the alert and decides what kind of problem this is.
   Here: a database problem, high severity.
2. **Gathering facts.** The system pulls the service's error logs, its traffic and timing
   graphs, and its recent changes. The logs say the service is waiting for database
   connections, and all 100 of them are in use.
3. **Looking things up.** It searches the runbooks and past incidents for anything similar,
   and finds the runbook for "database connection pool exhaustion".
4. **Working out the cause.** It writes down several possible explanations and weighs the
   evidence for and against each one. A software update from three hours earlier looks
   suspicious, but the errors only started after the traffic jump, so it rules the update
   out. The winner: the flood of sale traffic used up all the database connections.
5. **Suggesting a fix.** It proposes steps from the runbook, ending with restarting the
   checkout service.
6. **Double-checking.** A separate reviewer assistant (the **critic**) checks the work: is
   every piece of evidence it quotes real, does the fix match the cause, is anything
   unsupported? It can send the work back to be redone.
7. **Asking a human.** Restarting a live service is a real change, so the system stops and
   waits. A regular operator is not allowed to approve it; an administrator is. Once
   approved, the restart runs exactly once.
8. **Writing it up.** Finally it writes a short report of what happened, with a timeline,
   for the team to review later.

## The team of assistants

Each step is handled by its own specialist, like a small team where everyone has one job.

| Assistant | Its job, in plain words |
|---|---|
| Triage | "What kind of problem is this, and how bad?" |
| Context collection | Gathers logs, graphs and recent changes. (A plain program, not AI.) |
| Retrieval | Searches runbooks and past incidents. |
| Root cause | Lists possible causes and picks the best-supported one. |
| Remediation | Turns the matching runbook into concrete fix steps. |
| Critic | Checks the others' work and can send it back. |
| Human approval | Pauses until a person approves or rejects risky actions. |
| Postmortem | Writes the final report and timeline. |

## Why you can trust it (or check it)

AI can sound confident and still be wrong, so the system is built so that its work can be
checked and it cannot act on its own.

- **Every claim points to evidence.** Each fact it collects gets a short label, like `E4`.
  When the system says "the database pool is full", it must cite the labels that show it.
  A program, not the AI, checks that every cited label really exists.
- **A reviewer checks the work.** The critic catches missing evidence, contradictions and
  invalid fixes, and sends the work back up to three times.
- **Risky actions need a person.** Restarting or rolling back a service always waits for
  human approval, only administrators can approve, and each approval can be used once.
- **Nothing is hidden.** If a step fails or a tool times out, the report says so instead
  of quietly guessing.

## A few terms, explained

| Term | What it means here |
|---|---|
| Incident | Something broke and needs attention. |
| Runbook | A team's written instructions for handling a known kind of problem. |
| Agent | An AI assistant with one specific job and a fixed set of tools. |
| Root cause | The underlying reason something broke, not just the symptom. |
| Hybrid search | Searching by exact words and by meaning at the same time, then combining the results. It finds the right runbook even when the question is worded differently. |
| Human in the loop | The system pauses for a person before doing anything risky. |
| MCP | A standard way to give AI assistants like Claude access to tools. SentinelAI's investigation tools can be used from Claude Desktop this way. |
| A2A | A standard way for one AI agent to call another. The critic runs as its own service, and the main system calls it over A2A. |
| Trace | A record that follows one request through every part of the system, so you can see where time went and what happened. |

## How well does it work?

The project includes a test bench of 60 made-up but realistic incidents, covering 20 kinds
of failure, each with the correct answer written down.

- **Finding the right runbook from a differently worded question:** combining word search
  with meaning search ranks the right runbook first about 92% of the time, against about
  71% for word search alone.
- **Picking the right cause:** the system can reason in two ways. Its built-in rule-based
  mode is free and instant; it picks the right runbook every time on kinds of problems it
  has seen before, but only about 42% of the time on kinds it has never seen. With Claude
  doing the reasoning, it gets about 90% right on those unseen kinds, at about a minute and
  14 cents per incident.

Two caveats, stated plainly:

- The "never seen" numbers are the honest ones: in that test, past incidents of the same
  kind are hidden, so the system cannot just copy an earlier answer.
- The incidents are synthetic. The numbers compare approaches fairly, but they do not
  promise the same accuracy on a real company's systems.

## What it is not

- It is not connected to real servers. Logs, graphs and restarts come from a realistic
  simulation, so nothing real is ever changed.
- It does not replace on-call engineers. It does the gathering and suggests an
  explanation; people decide.

## Try it yourself

| Way | What you need | What you see |
|---|---|---|
| [Live demo](https://gagan-rohith.github.io/sentinel-ai/) | A browser | Real recorded runs, replayed. Switch between operator and admin to see the approval rules. |
| Terminal demo | Python | `make demo ARGS=--memory` prints the whole INC-1060 story. |
| Full system | Docker | The web app, search, the critic service and dashboards, on your machine. See the [README](../README.md#quick-start). |

## Where to go next

- [README](../README.md): features, setup, API, results and security, in more detail.
- [docs/DEMO.md](DEMO.md): a guided tour of the demo.
- [ARCHITECTURE.md](../ARCHITECTURE.md): why it is built the way it is.
- [docs/MCP.md](MCP.md): using the tools from Claude Desktop.
