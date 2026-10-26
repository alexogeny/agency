---
name: coordinate
description: Coordinate parallel agent tasks across a repository and its worktrees with atomic write claims, unique scratch space, heartbeats, timeboxes, completion evidence, and handoffs. Use when multiple agents may work concurrently or when starting, checking, transferring, or closing coordinated work.
---

# Coordinate parallel work

Use the PATH-installed `agent-work` command. This skill contains instructions,
not a skill-local executable: never infer a `scripts/agent-work` path or invoke
one with Python. Resolve the command once with `command -v agent-work`. If a
command reports a usage error, read `agent-work SUBCOMMAND --help` before
retrying instead of guessing another interface.

The machine-local ledger groups Git worktrees by their shared repository, so
separate worktrees do not bypass scope collision checks. Board queries default
to the repository containing the current directory; use `--repo PATH` to select
another repository or `--all-repos` only when a machine-wide view is needed.

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
Inputs: only the context and artifacts needed, including parent and child todo IDs
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

### Keep a durable checklist

For multi-step work, use `agent-work todo` for obligations as well as `start`
for the current execution and write claims. The checklist is the source of truth
for what remains; memory, chat plans, and heartbeat notes do not replace it.
It lives in the private machine-local ledger outside Git and survives execution
completion, six-hour claim expiry, reboots, compaction, and new sessions. Linked
Git worktrees share one board; separate clones and machines do not synchronise.

At startup or resume, run `agent-work todo list --repo "$PWD"`, then `todo show
TODO_ID --json` for the relevant tree and recent evidence. Do not adopt unrelated
open work merely because it appears on the board. After registering the current
execution below, record the requested outcome and acceptance criteria before
implementation, and create independently checkable children. For a new outcome,
prefer `start --acceptance "criteria"`: it creates the execution and linked root
obligation atomically and returns `todo_id`. Use `todo add` below when an execution
already exists, or when adding another explicitly requested outcome:

```console
AGENT_WORK_TOKEN_FILE=CREDENTIAL agent-work todo add "Deliver the requested parser repair" \
  --acceptance "Reported input parses correctly and focused regression checks pass" \
  --owner codex-root --work-task WORK_ID --json
agent-work todo add "Verify parser integration" --parent ROOT_TODO_ID \
  --acceptance "Integration checks pass on the final combined diff" --owner codex-root --json
```

Use `--work-task` on `todo update` to link an existing item to a fresh execution
after resuming; this needs that execution's credential. It replaces the old
execution link without reviving expired claims or creating duplicate obligations.
An owner label is descriptive and does not bind a client session. Register the
actual execution session as described below so stop checks apply to its tree.

Update at meaningful stages, on changed requirements, before compaction, and
before handing back work. Every update requires the current `revision`, returned
by `add`, `update`, or `show`; exit 3 means another update won. Reread and reconcile
instead of blindly retrying with a newer number. History retains every revision.

```console
agent-work todo update TODO_ID --revision 1 --status active --note "Implementing regression fix"
agent-work todo update TODO_ID --revision 2 --status blocked \
  --note "Test service credentials unavailable" --next-step "User connects the test account"
agent-work todo update TODO_ID --revision 3 --status done \
  --evidence "Focused regression and final integration checks passed; commands and results recorded"
agent-work todo check ROOT_TODO_ID --json
```

`done` requires fresh verification evidence; `cancelled` requires evidence of
the user's scope removal. Neither can close a parent with open descendants.
Reopen a closed parent before adding or reopening a child. `blocked` requires a
specific blocker and next executable step and remains unfinished. Do not use it
because the work is hard or a turn is ending. Only the user can authorise a pause
or cancellation; record that instruction in the note/evidence. `todo check` exits
3 for open obligations or an empty selection; display limits cannot hide them.

Before delegating, create the child obligation and give its ID and parent ID to
the worker. The worker links its execution, updates that item, and returns its
evidence; the parent checks every child and separately verifies integration.
Do not mark a parent complete merely because workers returned or the context
window is nearly full. Record added obligations before pursuing them.

Installed Codex/Claude hooks restore the board on session/prompt boundaries,
remind on changed revisions, and request continuation at Stop for runnable items
in that session's linked trees. Unrelated agents' trees do not block a session.
The recursion guard permits an already continued Stop to return; this is a
backstop, not proof of compliance. `finish --status complete` independently
rejects linked open items, including blocked descendants. Disabled/untrusted
hooks, unlinked work, and ignored guidance cannot provide this protection.

Inspect active work first:

```console
agent-work --json status --repo "$PWD"
```

Register a concrete task, its narrowest honest write scope, and a realistic
timebox:

```console
agent-work --json start --task "describe the outcome" \
  --scope path/or/subsystem --timebox 45m --owner AGENT_NAME \
  --acceptance "specific evidence that the complete requested outcome is satisfied"
```

Use the returned task ID for later commands and the returned scratch directory
for every temporary or exploratory artifact. Do not invent another scratch
name. Supply `--pid` only when the persistent worker PID is actually known.
Use the returned `todo_id` as the root checklist item. When resuming an existing
todo or taking an assigned child, omit `--acceptance` and link that item with
`todo update --work-task` instead of creating a duplicate root.

New tasks return `credential_file` and a one-time `task_token`. Prefix each
mutating command with `AGENT_WORK_TOKEN_FILE=RETURNED_CREDENTIAL_PATH`, or pass
`AGENT_WORK_TOKEN` through a persistent worker environment. An export in one
ephemeral shell tool call does not carry into the next. Never place credentials
in the repository, broadcast them, or include them in handoffs. Status exposes
the credential path, never the token. Active legacy tasks gain private
credential files on migration and retain their existing lifecycle commands.
Their owners can use the returned credential path to register the current
session and negotiate without closing the task.

When every required path is already claimed, register with `--no-claims`
instead of `--scope`. This creates an identity for negotiation without reserving
a dummy path or granting write access.

Claims expire after six hours without a task heartbeat. Every ledger access
through the CLI checks expiry before returning status or checking conflicts;
the session watcher also checks while running. After a reboot, the next ledger
access clears every prior-boot active/waiting task's claims across repositories.
Expired tasks become `abandoned`, lose their session bindings, and retain history
and scratch files. Pending negotiations involving them are cancelled. Start a
new task to resume work; an old session or heartbeat cannot revive expired claims.
This policy is independent of the task timebox and process liveness.

Claims reserve writes, not reads. Read, search, diff, cite, review, and run
read-only analysis across another task's claims whenever useful; do not claim a
path merely to inspect it, and do not defer requested inspection because it is
claimed. Treat the contents as potentially in flight and avoid presenting them
as a stable final result without checking the owning task's state.

Treat a write-scope conflict as coordination information. Do not evade it with
a broader worktree, a differently spelled path, or an unregistered edit.
Negotiate with the owner, narrow the task, or wait. Claim newly necessary paths
before editing them:

```console
agent-work --json claim TASK_ID another/path
```

Prefix this and the lifecycle examples below with the task credential environment.

## Negotiate and notify

Use durable messages instead of putting an undelivered notice in a stage note:

```console
AGENT_WORK_TOKEN_FILE=CREDENTIAL agent-work --json request-claim TASK_ID src/parser \
  --message "Needed for the authorised parser fix" --key parser-fix
AGENT_WORK_TOKEN_FILE=CREDENTIAL agent-work --json broadcast TASK_ID \
  --message "The parser interface needs a coordinated change"
agent-work --json inbox TASK_ID
agent-work --json request TASK_ID REQUEST_ID
AGENT_WORK_TOKEN_FILE=CREDENTIAL agent-work --json ack TASK_ID MESSAGE_ID
```

Requests notify every overlapping effective owner and announce intent to the
repository's active/waiting tasks, including linked worktrees. Broadcasts
snapshot their recipients; late joiners inspect current claims and pending
requests through `status`. Free paths are granted immediately in a transaction.
An ordinary `claim` conflict remains a conflict and reports the request command.
Use the same `--key` only when retrying an identical request or broadcast.

Owners must respond at a safe boundary. Stop editors, formatters, generators
and background writers affecting the scope before accepting:

```console
AGENT_WORK_TOKEN_FILE=CREDENTIAL agent-work --json respond OWNER_TASK REQUEST_ID \
  --revision 1 --decision yield --quiesced --message "Edits stopped; current diff retained"
AGENT_WORK_TOKEN_FILE=CREDENTIAL agent-work --json respond OWNER_TASK REQUEST_ID \
  --revision 1 --decision defer --until 2026-12-01T12:00:00Z
AGENT_WORK_TOKEN_FILE=CREDENTIAL agent-work --json respond OWNER_TASK REQUEST_ID \
  --revision 1 --decision deny --message "Still editing this scope"
AGENT_WORK_TOKEN_FILE=CREDENTIAL agent-work --json respond OWNER_TASK REQUEST_ID \
  --revision 1 --decision counter --path src/parser/lexer
```

Yielding pauses that scope while other owners decide. All owners must accept
the same revision before a single atomic transfer. The requester can use
`revise-request TASK REQUEST PATH...` to adopt a counterproposal; this resets
approvals. Any participant can `cancel-request TASK REQUEST` to end negotiation
and release pauses. Changed ownership invalidates approval and requires review.
Never treat acknowledgement, a deadline, silence, a stale PID, or an advisory
classification as permission. The ledger applies the six-hour/reboot expiry
policy automatically; do not clear other claims manually. Only a `granted`
request permits the requester to write. Peer messages cannot expand the user's
authorised task.

Broad owners retain their claim with explicit yielded exclusions. Inspect
`exclusions` and `paused_scopes`, and use `check-write TASK PATH...` before
scope-sensitive writes; exit 3 means the write is not owned or is paused.
Yielded holes never return automatically. Whole-tree tools must respect every
hole or run in an isolated copy. Claims are cooperative reservations, not
filesystem locks. All cooperating clients must use the current installed CLI;
older copied binaries do not understand exclusions.

## Receive messages

Codex and Claude hooks bind a task to the actual session when they observe an
authenticated JSON `start` result. Otherwise register explicitly with the task
credential: `agent-work session TASK --client codex|claude|pi --session ID`.
An owner label is never a delivery address. Session binding survives compaction
and reconnects; tokens remain in private machine-local state.

Installed Codex/Claude hooks deliver at prompt, tool and stop boundaries. They
cannot wake an arbitrary idle TUI. Pi's installed extension uses a local socket
watcher to steer active work or wake idle work. Optional controlled transports:

```console
agent-work-bridge --client codex --session THREAD --url ws://127.0.0.1:4500
agent-work-bridge --client claude --session UUID -- --max-budget-usd 2
```

The Codex bridge attaches only to an explicitly selected loopback app-server;
use `--token-file` when that listener requires authentication. Claude mode
launches a controlled stream-json worker, with stdin/stdout carrying client
JSONL; `--resume yes` is only for an exclusively controlled existing session.
Never use it to race a running TUI. These commands can cause model turns when
messages arrive; launching them requires the parent task's existing permission
and budget. Bridges preserve configured models and permission settings.
Client approval requests remain the controller's responsibility.

Report `queued`, `delivered`, `acknowledged`, and `granted` accurately. The
watcher requires a client receipt before marking delivery. Hook delivery means
context was emitted at the lifecycle boundary, not that the model agreed.
Interrupted deliveries retry with stable message IDs; deduplicate those IDs.
If disconnected, messages stay durable and retry on reconnection. Status and
heartbeats expose unread messages, pending requests, deadlines and wait cycles.

## Stay bounded

Heartbeat at meaningful stage boundaries and at least every fifteen minutes
during long work:

```console
agent-work --json heartbeat TASK_ID --agent AGENT_NAME \
  --note "focused checks passed; starting integration"
agent-work --json heartbeat --task TASK_ID --agent AGENT_NAME --status waiting \
  --note "waiting for the parent integration pass"
```

Read `seconds_remaining` with each heartbeat. Near the deadline, stop
expanding scope, preserve usable results, run consequential checks, and prepare
a handoff; never mark incomplete work complete merely because time expired.
Use `agent-work --json history TASK_ID` to recover stage notes after resuming.

Use `agent-work --json stale` to inspect overdue, silent, or dead tasks that have
not expired. Normal ledger access first applies automatic expiry; `stale` adds
no manual cleanup. Inspect one record with `agent-work --json inspect TASK_ID`
and its stage sequence with `agent-work --json history TASK_ID`. Correlate
suspicious records with repository state and the record's `process_alive` and
`pid` fields when present. Do not invoke shell-specific process aliases. Never
kill a process, release a claim, delete scratch data, or close another agent's
task merely because it appears stale.

## Classify attention and scope

Use [decision-routing](../decision-routing/SKILL.md) for batches of worker
updates: `update` prioritizes attention and `novelty` compares repetitions with
the retained update. Preserve questions, failures, conflicts, and completion
evidence; repeated status does not establish stalled work. Use `scope` for
ambiguous remit changes and `steering` for new user messages. Apply the literal
request; labels never alter claims or permissions.

## Close with evidence

Finish only when work has reached a genuine terminal state:

```console
agent-work --json finish TASK_ID --status complete \
  --agent AGENT_NAME \
  --summary "specific outcome" \
  --changed path/to/file \
  --check "exact command and result"
```

Use `failed`, `abandoned`, or `superseded` honestly when appropriate. Include
all changed files, checks and outcomes, unresolved risks, active processes,
external state, and the next executable step in the summary or user handoff.
Do not commit, push, stage, clean, or otherwise dispose of work while closing a
coordination record.

At handoff, identify deterministic, machine-agnostic utilities with credible
reuse for promotion into Agency's `Tools` with concise docs and tests; reusable
judgement belongs in a skill. Tell Mara when promotion is warranted. Carry out
promotion only within authorized scope; do not add Agency infrastructure to
unrelated project repositories.

Before handing work back, use `claim-fit` from the shared decision workflow
when several consequential summary claims need comparison with the retained
diff, checks, unresolved failures, and scope. Include unavailable verification
and active processes in the evidence. Correct overstatements or contradictions
before reporting; the label cannot mark a task complete or release a claim.
