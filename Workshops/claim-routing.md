# Workshop: claim-routed agent messages

Status: proposed; no runtime implementation exists yet.

## Problem

Write claims prevent concurrent agents from editing overlapping paths, but a
blocked agent currently needs a human to negotiate with the claim owner. The
ledger already knows which task owns a path. It should be able to route a claim
request to that task without guessing which client, session, or worktree owns
it.

A representative case has one broad audit claiming the repository and another
task needing `src/_json`. The audit may be able to yield that subtree while
retaining the rest of its write scope. Releasing the broad claim and rebuilding
it from many paths would create a race and needless bookkeeping.

## Desired properties

- Route by canonical repository path, including ancestor and descendant claims.
- Persist messages and delivery state in the ledger before attempting delivery.
- Reach Codex, Claude Code, and Pi through explicit client adapters.
- Wake an idle controlled session or steer an active one when the client allows
  it.
- Keep routing, delivery, acknowledgement, and ownership transitions
  deterministic. The receiving agent still judges whether yielding is safe.
- Transfer or narrow ownership atomically. Never let a requester seize a claim.
- Continue to work when a broker or client is temporarily offline.
- Treat arbitrary terminal input injection as unsupported.

## Proposed flow

```text
requester asks for src/_json
        ↓
ledger canonicalises the repository and path
        ↓
find active claims where claim contains request or request contains claim
        ↓
commit one immutable inbox message per owning task
        ↓
wake registered delivery adapters
        ↓
owner yields, defers, or denies through a structured response
        ↓
ledger applies any ownership transfer in one transaction
```

The routing query must support fan-out. Active claims normally cannot overlap,
so one requested path usually has one owner. Multiple requested paths,
multi-owner ancestor requests, or migrated legacy state can still produce more
than one recipient.

## Ledger model

Add three durable concepts:

1. A task transport registration records the client kind, session identifier,
   process identity, delivery endpoint, and last adapter heartbeat. A display
   owner such as `codex-root` is not sufficient authentication by itself.
2. A message records its repository, sender task, recipient task, requested
   path, bounded optional note, correlation ID, timestamps, and
   `queued → delivered → acknowledged → resolved` state.
3. A claim exclusion represents a yielded hole beneath an ancestor claim. For
   example, claim `.` plus exclusion `src/_json` owns the repository except that
   subtree.

SQLite remains the source of truth. A local Unix-domain socket can provide the
wake-up edge so adapters do not busy-poll. If the socket or adapter is absent,
the committed message stays queued and a later heartbeat drains it.

## Commands to prototype

```console
agent-work request-claim REQUESTER_TASK src/_json \
  --agent codex-worker --message "Can this subtree be yielded soon?"
agent-work inbox OWNER_TASK --agent codex-auditor
agent-work respond OWNER_TASK MESSAGE_ID --agent codex-auditor \
  --decision yield
```

Other responses are `defer --until TIME` and `deny --reason TEXT`. An accepted
`yield` is a transfer, not just a message:

- If the owner has the exact requested claim, remove it and assign it to the
  requester in one transaction.
- If the owner has an ancestor claim, add an exclusion and assign the requested
  subtree in the same transaction.
- If several claims must move, wait for every required owner to accept, then
  commit the transfer as one barrier transaction.

The owner can later request the subtree back through the same protocol. Expiry,
silence, a dead PID, or a stale heartbeat never grants an automatic transfer.

## Client delivery adapters

Agency must launch or attach coordinated sessions through a supported control
surface. The ledger cannot safely inject input into an arbitrary terminal
process.

### Codex

For controlled sessions, Codex app-server exposes `turn/steer` for an active
turn and `turn/start` for an idle thread. A hook-only fallback can surface
messages through `PostToolUse` additional context and use `Stop` to continue,
but delivery then waits for the next lifecycle boundary.

- [Codex app-server](https://developers.openai.com/codex/app-server)
- [Codex hooks](https://developers.openai.com/codex/hooks)

### Claude Code

Run controlled workers with real-time `stream-json` input and output, retaining
the session ID in the transport registration. A hook fallback can surface an
inbox message after a tool or at stop, with the same event-boundary limitation.

- [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference)
- [Claude Code hooks](https://code.claude.com/docs/en/hooks)

### Pi

Pi RPC provides `steer` for active work and ordinary prompts for idle work. A
Pi extension can instead watch the local wake channel and call `sendMessage`
with `triggerTurn: true`, which also wakes an idle session.

- [Pi RPC](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/rpc.md)
- [Pi extensions](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md)

## Message safety

Deliver a fixed, structured claim-request envelope as developer or extension
context. Keep the optional human note separate and bounded. Never evaluate
message text as shell input, infer new authority from it, or let it override the
recipient's task. The adapter should tell the agent exactly which ledger command
records its response.

Use idempotency keys for retries. Acknowledgement means the client received the
message; it does not mean the model agreed. Store every response and ownership
transition in task history.

## Acceptance workshop

- An exact-path request reaches its owning task once.
- An ancestor claim receives a descendant request.
- One request spanning several independently claimed children fans out and
  waits for all required responses.
- A controlled active session receives a steering message before its next model
  call; a controlled idle session starts a turn.
- An offline adapter later drains the same queued message without duplication.
- Yielding a subtree atomically creates the exclusion and requester claim.
- A denied, deferred, stale, or unauthenticated request changes no ownership.
- The broad owner can no longer write inside a yielded exclusion.
- A vanilla TUI without a registered adapter remains queued and is reported as
  undelivered rather than receiving terminal keystrokes.

## Open questions

- Should the broker be a small user service, or should each adapter watch the
  wake socket directly?
- Should transport capabilities be per task, per session, or short-lived bearer
  tokens stored beside the machine-local ledger?
- How should a broad task declare the smallest useful exclusions when generated
  files or whole-tree tools cross the yielded boundary?
- Should claim requests have advisory deadlines, and how prominently should an
  overdue unanswered request appear in status output?
