# Claim-routed agent messages

Status: implemented in `Tools/agent-work`, `Tools/agent_work_messages.py`, the
delivery helpers and client adapters. Tests use isolated ledgers and local
protocol fixtures; they do not establish compatibility with every installed
client version or run paid model sessions.

## Ownership and communication

The machine-local SQLite register is the source of truth. A task can start with
no claims, broadcast to other active/waiting tasks in its canonical repository,
or request paths from all overlapping effective owners. Linked Git worktrees
share the repository identity. Recipient labels never determine delivery.
Repository-root claims do not encompass absolute scratch claims outside that
repository; negotiation cannot silently take or discard those reservations.

A broadcast snapshots recipients when committed. A claim request records exact
paths, a revision, its ownership snapshot, reason and optional advisory deadline.
It creates owner inbox messages and a repository intent notice in the same
transaction. Late joiners consult current claims and pending requests; old
broadcasts do not become a historical replay for every new task.

Owners yield, defer, deny or counter. A counterproposal is advisory until the
requester adopts it with `revise-request`; all prior approvals are invalidated.
Either the requester or an affected owner can cancel, releasing temporary pauses.
Finishing a participant cancels its open negotiations. Wait cycles and overdue
response deadlines are visible without changing ownership.

## Atomic transfer

```text
register requester without claims
    -> commit request and recipient messages
    -> notify client adapters
    -> each owner stops affected writers and accepts the exact revision
    -> recheck the effective ownership snapshot
    -> transfer all required claims in one transaction
    -> deliver grant confirmation to participants
```

No scope moves before every required owner accepts. An accepted owner's scope
is paused while other owners decide. Changed ownership produces `needs-review`
and releases pauses; the requester must revise before continuing. There is no
timeout-based acceptance or stale-process takeover.

An ancestor claim can retain its broad reservation with a yielded exclusion:
claim `.` plus exclusion `src/parser` reserves the repository except that
subtree. Effective overlap checks, status, ordinary claims and `check-write`
understand exclusions. A recipient finishing does not return the hole to the
broad owner. Explicit reacquisition checks for current conflicts again.

The register is cooperative. It cannot stop arbitrary filesystem writes or a
formatter already running. Owners must quiesce all relevant writers before
`yield --quiesced`; whole-tree tools must respect exclusions or use an isolated
copy. Every cooperating client must use the current CLI. An old binary copied
elsewhere cannot be made to understand new exclusions by updating the database.

## Persistence and identity

The schema adds task credential hashes, claim exclusions, claim requests and
responses, messages, per-recipient delivery state, session registrations and
short-lived delivery batches. Task history records messages, acknowledgements,
responses and ownership transitions. State and private credential files remain
outside Git. The credential path is recoverable from task status; its contents
are not printed there.

New tasks return a one-time token and a private token file. Mutations require
the correct task capability, not an owner display label. Active legacy tasks
receive private credential files during migration and retain their old
lifecycle commands. Owners can bind their current sessions with those
credentials, without closing the tasks. These capabilities prevent accidental
cross-task actions, not hostile access by another process running as the same
operating-system user.

Request and broadcast idempotency keys reject mismatched retries. Notifications
have stable IDs. Delivery retries are at least once, so recipients should
deduplicate message IDs and check the current request revision before acting.
Acknowledgement never implies consent or a grant.

## Delivery

Persistence precedes notification. Watchers bind private Unix datagram sockets;
ledger mutations send wake edges. Each watcher reconciles at least every
fifteen seconds, so a missed edge or restarted adapter does not lose messages.
No always-running broker service or arbitrary terminal input injection is
required.

Session registrations bind task IDs to explicit client/session IDs and delivery
capabilities. Multiple tasks in one session share bounded inbox batches. The
context is capped at eight messages and 32 KiB; full records remain inspectable.
Routine claim notices coalesce to the latest ownership snapshot, retaining
`superseded` delivery records without inventing acknowledgements. The
watcher reserves a batch, emits it as JSONL and requires a receipt on stdin
before marking it delivered. Unconfirmed leases retry; delivered messages
without acknowledgement reappear after five minutes. Queued, delivered and
acknowledged are separate from the request's granted or denied outcome.

Codex and Claude hooks can bind a JSON `start` result to the real invoking
session after checking the task token and repository. They surface inboxes at
prompt/tool/stop boundaries. Stop delivery avoids repeated continuation when
`stop_hook_active` is already true. A hook marks submission after emitting
model context; it cannot prove the client consumed stdout after a crash.

Pi's extension starts a watcher only for registered sessions, delivers custom
messages using `triggerTurn: true` and `deliverAs: steer`, and confirms the
batch after the extension API accepts it. Session changes stop the watcher and
discard asynchronous output belonging to the old session.

Optional `agent-work-bridge` transports cover explicitly controlled sessions:

- Codex: connect to a supplied loopback app-server WebSocket; initialize, read
  thread state, steer the active turn or start an idle turn. No model, reasoning
  or permission overrides are supplied. Approval requests remain with the
  caller. WebSocket transport support depends on the installed Codex version.
- Claude: launch an exclusive stream-json worker and forward ordinary client
  JSONL. Input replay acknowledgements confirm context delivery. This is not
  attachment to an arbitrary existing TUI.

Unregistered or unsupported idle sessions stay queued and report no successful
delivery. Peer messages remain bounded coordination data and confer no authority
to expand the receiving task.

## Acceptance evidence

`Tests/test_agent_work_messages.py` exercises broadcasts, unclaimed startup,
idempotency, exact and ancestor transfers, multiple owners, exclusions and
reacquisition, deferral, denial, counterproposals, cancellation, stale revisions,
changed claims, wait cycles, concurrent acquisition, task credentials and CLI
errors. `Tests/test_agent_work.py` retains lifecycle and migration coverage.

`Tests/test_agent_work_delivery.py` exercises two registered sessions through
request, reply, grant and acknowledgement; offline queues; actual-session
binding; stop-loop protection; watcher receipts; Pi idle wake and session
cleanup; installation fragments; and controlled Codex/Claude protocol contracts.
The Bun fixtures use the real extension/helper/watcher paths with mocked client
APIs, and mocked Codex/Claude transports with checked message envelopes.

## Client protocol references

- [Codex hooks](https://learn.chatgpt.com/docs/hooks)
- [Codex app-server](https://learn.chatgpt.com/docs/app-server)
- [Claude hooks](https://code.claude.com/docs/en/hooks)
- [Claude CLI](https://code.claude.com/docs/en/cli-reference)
- [Pi extensions](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md)
