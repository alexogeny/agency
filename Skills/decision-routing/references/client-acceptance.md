# Verify client delivery

Run this matrix after changing Jev client wiring or upgrading a client. The
offline suite executes CLI/MCP processes and configured hook commands, and
simulates Pi events. It cannot prove that a real client emits those events or
displays the result. A successful hosted call proves provider connectivity,
not client display or usefulness on real work.

## Record the environment

Use an existing authorized task record outside the repository. Record the
client name, exact version, CLI versus desktop interface, shell or MCP transport,
Agency tree revision, hook/extension version, and date. Mark each case passed,
failed, unavailable, or not run. Keep only the command/tool name, receipt ID,
counts, and observed display; do not copy unrelated session history or secrets.

Restart the client to load changed hooks and MCP contracts. Complete any normal
client hook-trust review; do not disable trust to obtain a passing result.
Use a fresh scratch session with no unrelated Jev calls. Run `agency-decide
doctor` without printing the credential file. If access is unavailable, record
that result and complete the offline cases instead of inventing provider output.

## Exercise the paths

Use this fictional state for hosted cases:

```json title="client-state.json"
{"query":"Locate the upload route.","passage":"The upload route is defined in uploads.py."}
```

Ask the client to perform each case in a separate user turn. For CLI cases,
save the state under the scratch session and run:

```console title="client-classify"
agency-decide classify --profile context --input client-state.json
```

Hosted cases consume provider credit. Keep a budget of at most four unique
hosted decisions per client/transport pass; stop when that budget is exhausted.
Labels may vary; count successful receipts, not a particular semantic answer.

| Case | Action | Required observation |
| --- | --- | --- |
| Offline zero | Run `profiles --profile context`, `doctor`, then the CLI case with `--dry-run`. | Zero decisions; no provider call. |
| CLI success | Run the CLI case once with full output visible. | One completed decision and its receipt; turn-end display shows one. |
| MCP success | Call `classify` with profile `context` and the state object. | One completed decision; count once even when text and structured output both contain the receipt. Pi currently uses CLI only. |
| Batch reuse | Call `classify_batch` with two different IDs and identical profile/state. | One decision, one reused result; one provider request. Use `classify-batch` for Pi. |
| Input failure | Call the CLI or MCP with `context` state `{"query":"Locate the route."}`. | Zero decisions, one error, no provider call; normal work can continue. |
| Wrapped call | Where the client supports code-mode/nested tools, repeat one success through that path and preserve the complete result. | One observed decision; record unavailable if that transport or its events are unsupported. |
| Interruption | After observing a receipt, interrupt before normal completion. | Codex interruption reports the count; after continuation, no duplicate attribution. Record other clients' actual behavior separately. |
| New turn | Send a new request that makes no Jev calls. | Count resets to zero; the previous receipt is not counted again. |
| Lost output | In an offline turn, redirect a failing CLI call's output so its receipt is hidden. | `count incomplete` where the client exposes the call; an unobserved transport must not be recorded as verified. |

For Codex, shell and unified-exec calls are documented as the canonical `Bash`
hook name; a finishing `write_stdin` poll can deliver the original command's
event. Check the completed event rather than widening matchers based on the
tool name shown to the model. See the
[Codex hook interface](https://developers.openai.com/codex/hooks).
For Claude, exercise both `PostToolUse` and `PostToolUseFailure` where applicable;
see its [hook interface](https://code.claude.com/docs/en/hooks).
For Pi, observe the footer across intermediate model turns, a retry, and the
next user run. Inspect the installed extension API when event names change.

Run the delegated-worker case only when delegation is already authorized:
one worker decision must not reset or inflate the parent's count. Worker counts
are separate; no parent display is a total across the team. Without an actual
delegated run, mark this row not run, even if its offline regression passes.

## Acceptance boundary

Record a path as verified only after comparing the actual receipt with the
actual client display/event stream. Replayed payloads are offline evidence.
Do not infer a pass from hook installation, a configured credential, or tests
for another client version. Fix failures in the supported path and rerun that
case; retain unavailable and failed rows in the record. This procedure neither
changes client settings nor enables recording automatically.
