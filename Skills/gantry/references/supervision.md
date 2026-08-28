# Gantry supervision and teardown

## Launch and retain the handle

Run the previously prepared workload with `gantry launch ... --yes --json`.
JSON implies detachment. Capture the `lease_id` immediately and tell the user
the lease ID, deadline, and projected cost. Do not use `--keep` unless the user
explicitly requests a machine that remains open after success.

If launch stops after ordering, preserve the existing lease and use
`gantry resume LEASE_ID PROJECT ...`; do not order a replacement merely because
connection or upload failed.

## Supervise

Poll with `gantry watch LEASE_ID --once --json`. Treat `done` as the terminal
condition and `succeeded` as the outcome. Use `seconds_remaining`,
`accrued_usd`, `phase`, `step`, and `tail` to decide whether intervention is
needed. Check `gantry telemetry LEASE_ID --json` when utilisation matters and
`gantry logs LEASE_ID -n 200 --json` when progress stalls or the run fails.

Keep supervising until the run reaches a terminal state or the user directs a
different action. Poll at a sensible interval for the workload; do not create a
tight loop. If the agent session must stop, leave the user the lease ID,
deadline, current cost/state, and exact watch/finish commands. The timebox is a
ceiling, but detached cleanup also relies on the ledger and reaper.

Do not execute ad-hoc remote fixes, raise the budget/timebox, replace the
machine, accept new findings, or launch another lease without authority for
that change. Prefer diagnosing from status, logs, and telemetry first.

## Collect before release

On success, run `gantry collect LEASE_ID --into DESTINATION --json`, then verify
the expected artifacts arrived and are readable before calling
`gantry finish LEASE_ID --json`.

On failure, inspect and collect the logs and useful workspace state before
release unless continued billing makes immediate release the safer choice.
State that tradeoff. Never claim a machine was released unless `finish`
confirmed it. Reconcile with `gantry ps --json` afterwards and report any open
or unconfirmed lease prominently.

Use `gantry reap --all --dry-run` only to inspect possible cleanup. Releasing
unrelated leases or installing a recurring reaper changes external state and
requires separate user direction.
