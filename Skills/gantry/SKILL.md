---
name: gantry
description: Plan, launch, supervise, collect, and release timeboxed remote CPU or GPU work with Gantry. Use when the user asks to rent compute, run a workload remotely, supervise paid work, inspect an active Gantry lease, or recover and finish a remote run.
---

# Supervised remote work with Gantry

Use the installed `gantry` CLI. Remote leases cost money and can outlive the
agent process, so preserve the approval, ledger, collection, and release
boundaries below. Read [references/supervision.md](references/supervision.md)
before launching or taking over a lease; ordinary offline analysis does not
need the reference.

## Prepare without spending

1. Run `gantry ls` and, when credentials are configured, `gantry ps --json` to
   reconcile open leases before proposing another.
2. Inspect the project with `gantry analyze PROJECT --json` and
   `gantry audit PROJECT --min high --json`. Use `--units` when the directory
   may contain independent workloads.
3. Review or create an explicit workload with a realistic timebox, budget,
   lane, entrypoint, inputs, and result paths. Do not include secrets or bulky
   ignored artifacts in the payload accidentally.
4. Rehearse locally when practical. A local run checks startup and payload
   completeness, not remote performance or benchmark validity.
5. Run `gantry prepare PROJECT --workload FILE --json`. Resolve blockers from
   evidence. Never add `--accept`, choose a lane override, or apply `--fix`
   merely to make `ready` become true; each is a substantive decision.

`analyze`, `audit`, `plan`, `doctor`, and ordinary `prepare` do not order a
machine. They are safe to use while forming a proposal, although `--write`,
`--write-dir`, `--bundle`, and `--fix` can write local files.

## Approval boundary

Immediately before the first paid `launch` or `run`, show the user the proposed
provider/machine, lane, workload, timebox, maximum budget, projected cost,
accepted findings, overrides, and collection destination. Obtain explicit
approval unless the current request already approves those exact limits.

Do not request provider secrets in chat or place them in command lines,
transcripts, workload files, or repositories. Use existing Gantry configuration
and report missing setup through `gantry doctor`; let the user enter credentials
through the intended setup flow.

After approval, follow the supervision and teardown procedure in the reference.
Use `--json` for agent-driven operations and parse the returned fields rather
than terminal prose. If installed syntax differs from this skill, inspect
`gantry COMMAND --help` and preserve these safety boundaries.
