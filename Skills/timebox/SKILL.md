---
name: timebox
description: Execute work against an explicit elapsed wall-clock budget, such as “spend 30 minutes” or “30-minute timebox,” with deadline-based checkpoints and a bounded handoff. Use when duration controls the requested effort; do not use for estimates, passive waiting, schedules, or command timeouts.
---

# Work to a wall-clock timebox

Treat the user's duration as an elapsed-time budget, not a token, turn, or tool-call
budget. Start the clock before broad exploration or implementation.

## Establish the deadline

For repository work, use the `coordinate` skill and register the task with the
requested `--timebox`. Claim only paths the task may write. Retain the returned
`deadline_at` and use `seconds_remaining` from heartbeats as the authoritative
clock.

If coordination is unavailable or inappropriate, record an absolute deadline
from the system clock and re-read the clock at checkpoints. Never estimate
elapsed time from conversational turns or model effort.

Tell the user the duration and absolute deadline at the start. Reserve the last
10% of the budget for verification and handoff, with a minimum of one minute and
a maximum of five minutes.

## Spend the work phase deliberately

At each meaningful milestone, and at least every five minutes:

1. Read the remaining wall-clock time.
2. Compare progress with the requested outcome.
3. Choose the highest-value next action that fits before the handoff reserve.
4. Record a coordination heartbeat when a task record exists.

Do not stop merely because a first plausible result exists. For open-ended
investigation, review, or improvement, use the remaining work phase for another
evidence-gathering, falsification, refinement, or validation pass. Do not idle or
invent scope to consume time.

A timebox is an upper bound, not a requirement to delay a genuinely complete
and verified result. Finish early only when the requested outcome has reached a
real terminal condition, not when more useful in-scope work remains.

Bound long-running commands and remote operations so their plausible completion
time fits inside the work phase. Poll ongoing work frequently enough to retain
the handoff reserve; do not launch a new expensive pass near the boundary.

## Enforce the boundary

When the handoff reserve begins, stop expanding the work. Preserve the current
result, run only checks that fit, collect concrete evidence, and prepare the
handoff. At the deadline, yield with the best accurate state available rather
than silently overrunning for optional cleanup.

Time expiry does not make an unfinished objective complete. Close any
coordination record with an honest status and report:

- the requested duration and actual elapsed time;
- what completed and what verification ran;
- what remains, including any still-running external work;
- the next executable step when the outcome is partial or blocked.
