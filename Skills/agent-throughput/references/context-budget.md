# Context budget

Load the smallest evidence packet that lets the agent locate the owner, preserve
the required behaviour, and prove completion.

## Audit before editing prompts

Run:

```console
agent-context codex .
```

Use `--json` when another tool will consume the result and `--check` for a gate
that should fail on truncated project guidance. Resolve truncation, duplicated
policy, and contradictory instructions before raising reasoning effort: a
stronger model cannot recover instructions it never received, and Astra is
particularly sensitive to instructions in skills and `AGENTS.md`.

## Preserve a stable prefix

Keep shared policy concise and stable so clients can reuse cached prefixes.
Move subsystem history and conditional procedure into routed references. Do not
raise an instruction byte limit merely to retain prose that every task must then
pay to read.

Prefer a short work packet plus paths and search terms. Let the agent inspect
the current source. Supply file contents only when the worker cannot access the
repository or when an exact immutable excerpt is the evidence.

Avoid:

- complete generated repository maps;
- large directory listings or test logs;
- several speculative implementations;
- incident history unrelated to the selected subsystem;
- a second model restating the first model's context without a distinct check.

For broad repositories, query a deterministic map for candidate owners, direct
tests, and commands under a hard output ceiling. A map is routing data, not
prompt preamble.

## Bound the loop

Start with the focused acceptance check. Expand verification only when the
change's risk or a failure warrants it. Retain the original stable context when
the client supports changing effort without rebuilding the prompt. End the run
as soon as acceptance evidence is complete; unrequested cleanup consumes the
same context and creates new review surface.

Source last reviewed 2026-09-07: [OpenAI's GPT-6 Astra model guidance](https://developers.openai.com/api/docs/guides/latest-model).
