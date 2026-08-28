---
name: coordinate
description: Coordinate parallel agent tasks across a repository and its worktrees with atomic scope claims, unique scratch space, heartbeats, timeboxes, completion evidence, and handoffs. Use when multiple agents may work concurrently or when starting, checking, transferring, or closing coordinated work.
---

# Coordinate parallel work

Use the installed `agent-work` command. Its machine-local ledger groups Git
worktrees by their shared repository, so separate worktrees do not bypass scope
collision checks.

## Delegate bounded work

Keep the model selected by the parent session unless the user explicitly asks
for another one. Set every coordinated worker to the second-lowest reasoning
level supported by that model, never the lowest. For the current Codex and
Claude Code effort scales, this means `medium`. Set it explicitly so a worker
does not inherit a parent running at `high`, `xhigh`, or `max`.

- In Codex, use the personal `coordinated_worker` agent when available. For an
  ad hoc spawn, leave the model unset so it inherits the selected model, set
  `reasoning_effort` to `medium`, and pass only the context the remit needs.
- In Claude Code, use `@coordinated-worker`. Its `model: inherit` and
  `effort: medium` settings preserve the selected model at the intended effort.
- If a client or selected model does not expose `medium`, choose the supported
  effort immediately above its lowest value. If effort cannot be controlled,
  tell the parent instead of silently using the lowest setting.

Give each worker a complete, narrow remit before spawning it:

```text
Outcome: one concrete result
Scope: exact files, subsystem, question, or data
Inputs: only the context and artifacts needed
May change: explicit paths or none
Must not: adjacent work, commits, delegation, destructive or external actions
Verify: exact checks or evidence expected
Return: concise result, changed paths, checks, risks, and blockers
Stop: when the outcome and verification are complete
```

Tell the worker to work directly, not overthink, and stop rather than broaden
the task. Do not delegate work that needs frequent parent decisions, overlaps
another worker's writes, or is too coupled to produce an independent result.

## Register before working

Inspect active work first:

```console
agent-work --json status
```

Register a concrete task, its narrowest honest scope, and a realistic timebox:

```console
agent-work --json start --task "describe the outcome" \
  --scope path/or/subsystem --timebox 45m
```

Use the returned task ID for later commands and the returned scratch directory
for every temporary or exploratory artifact. Do not invent another scratch
name. Supply `--pid` only when the persistent worker PID is actually known.

Treat a scope conflict as coordination information. Do not evade it with a
broader worktree, a differently spelled path, or an unregistered edit. Narrow
the task, wait, or ask the user to resolve ownership. Claim newly necessary
paths before editing them:

```console
agent-work --json claim TASK_ID another/path
```

## Stay bounded

Heartbeat at meaningful stage boundaries and at least every fifteen minutes
during long work:

```console
agent-work --json heartbeat TASK_ID
agent-work --json heartbeat TASK_ID --status waiting
```

Read `seconds_remaining` each time. As the deadline approaches, stop expanding
scope, preserve usable partial results, run the most consequential available
checks, and prepare a handoff. A timebox is not permission to mark incomplete
work complete or to discard another agent's changes.

Use `agent-work --json stale` to inspect overdue, silent, or dead tasks. This is
read-only evidence. Correlate suspicious records with `oldtasks` and repository
state; never kill a process, release a claim, delete scratch data, or close
another agent's task merely because it appears stale.

## Close with evidence

Finish only when work has reached a genuine terminal state:

```console
agent-work --json finish TASK_ID --status complete \
  --summary "specific outcome" \
  --changed path/to/file \
  --check "exact command and result"
```

Use `failed`, `abandoned`, or `superseded` honestly when appropriate. Include
all changed files, checks and outcomes, unresolved risks, active processes,
external state, and the next executable step in the summary or user handoff.
Do not commit, push, stage, clean, or otherwise dispose of work while closing a
coordination record.
