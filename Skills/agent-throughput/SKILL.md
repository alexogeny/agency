---
name: agent-throughput
description: Choose a model and reasoning effort, reduce agent token spend, compare agent runs, or prepare a bounded handoff. Use for routing and throughput decisions, not ordinary coding work.
---

# Route agent work for accepted outcomes

Optimize for accepted work, including verification and repair, rather than for
the cheapest token or fewest calls. Treat every model profile here as
provisional: repository evidence overrides the starting lanes.

## Shape the run

1. State the acceptance evidence and the cost of a wrong result.
2. Audit Codex instruction load with `agent-context codex .` when context size,
   truncation, duplication, or conflicting guidance may affect the run. Read
   [context-budget.md](references/context-budget.md) before reducing context or
   composing a handoff.
3. Select the cheapest lane likely to finish without a repair cycle. Read
   [model-routing.md](references/model-routing.md) when choosing between models
   or efforts.
4. Stop when the work packet's acceptance check passes. Escalate only on its
   named condition or concrete evidence that the current lane cannot finish.

Use this bounded work packet:

```text
Outcome:
Scope:
Required behaviour:
Forbidden expansion:
Relevant owners:
Acceptance check:
Escalate when:
Stop when:
```

Keep it short enough to scan as a contract. Link exact repository paths or
commands instead of pasting broad maps, file trees, logs, or design history.
Preserve the user's authority boundaries; a handoff never grants new actions.

For concurrent or durable work, use [`coordinate`](../coordinate/SKILL.md) for
claims, scratch space, heartbeats, and handoffs. Do not reproduce those
mechanics here or invoke coordination for a single ordinary task.

## Compare only when it can change routing

Run a comparison when selecting a repeated workflow or when a second pass is
cheaper than the expected failure. Read
[evaluation.md](references/evaluation.md) before designing or interpreting it.
Record total cost per accepted task, including unsuccessful attempts and human
repair. Do not promote an anecdote or cross-harness benchmark into a permanent
default.
