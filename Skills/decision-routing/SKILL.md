---
name: decision-routing
description: Run bounded System One judgments inside Agency skills using Jev through OpenRouter. Supports rubric bands, evidence screening, relevance, novelty, failure families, scope, steering, feedback, comment purpose, cost patterns, and change impact. Use for semantic decisions with inspectable evidence, not planning, authorization, or facts code can compute exactly.
---

# Make small advisory decisions

This skill owns the shared Jev workflow for every calling skill: evidence
preparation, execution, review, follow-ups, and reporting. Calling skills define
their triggers, contract-specific inputs, and how the result informs their work.
Keep common rules here rather than copying them into each caller.

Jev supplies System One: fast recognition from compact evidence. The reasoning
agent supplies System Two: investigation, decomposition, planning, and resolving
ambiguity. Use Jev for repeated candidates or a narrow semantic choice a person
could make at a glance. Skip choices resolved by explicit instructions, code,
or ordinary judgment. Do not insert calls before every tool invocation.

Use the `agency-decide` MCP tools (`profiles`, `classify`, `classify_batch`) or
CLI. Requests go to OpenRouter: send only necessary excerpts within the user's
authorized data scope, never credentials or whole sessions. Unavailable access
means continue with ordinary reasoning, not repeated prompts or invented labels.

## Select a contract

Read the needed versioned definition with `profiles`'s `profile` argument or
`agency-decide profiles --profile NAME`. These are the canonical contracts:

| Profile | State fields | Purpose |
| --- | --- | --- |
| `skill` | `task` | Suggest an optional skill; named and mandatory skills take precedence. The bounded list is not the full skill catalog. |
| `context` | `query`, `passage` | Order optional retrieved context; retain mandatory instructions and conflicting evidence. |
| `update` | `update`, `task_status` | Triage attention; preserve questions, approvals, errors, and failed checks. |
| `research` | `claim`, `passage` | Label opened evidence as support, conflict, background, or irrelevant. Verify the source separately. |
| `novelty` | `existing`, `candidate` | Group repetitions while preserving additions, contradictions, and sources. |
| `failure` | `diagnostic` | Select an investigation family from a redacted diagnostic. |
| `scope` | `task`, `action` | Flag requested, supporting, or outside work for review. |
| `steering` | `task`, `message` | Recognize corrections, additions, status questions, replacements, or separate requests. Apply the actual message. |
| `feedback` | `message` | Identify explicit corrections or preferences without creating standing instructions or writing memory. |
| `assess/criterion` | `criterion`, `evidence`, `evidence_complete`, `bands` | Propose an exact rubric band, `insufficient`, or `unsure`. |
| `evidence-review/eligibility` | `criterion`, `evidence`, `evidence_complete` | Judge one inclusion criterion: include, exclude, pending, or unsure. |
| `comment-audit/purpose` | `comment`, `context` | Identify constraints, documentation, redundancy, history, decoration, or protected material. |
| `performance-design/pattern` | `observation` | Select a cost investigation without claiming a bottleneck or improvement. |
| `pr-writing/impact` | `change` | Group verified changes by audience; check compatibility candidates against actual interfaces. |

Evidence fields are nonempty text. `evidence_complete` is a boolean about the
particular criterion. `bands` maps 2–8 stable IDs to exact descriptors, including
source band names and score ranges. IDs start with a letter and contain letters,
digits, underscores, or hyphens, at most 64 characters; `insufficient` and
`unsure` are reserved. Definitions live in each owning skill's `decisions.json`
and use one shared runtime.

## Run the owning skill's decision step

Prepare evidence first; retain record IDs and source references locally.
Prefer direct excerpts, measurements, and observable facts. When summarizing,
preserve relevant strengths, limitations, and contradictions; distinguish
observations from agent interpretations. Exclude the proposed label or grade
and evaluative wording that supplies the answer instead of evidence. A judgment
on an agent-written summary is not an independent review of the source.

Batch independent questions. Dependent judgments require separate stages.
A substantive assessment may warrant 5–10 judgments, never a quota.

```sh
agency-decide classify-batch --input decisions.json --dry-run
agency-decide classify-batch --input decisions.json
```

Example manifest:

```json
{"items":[{"id":"criterion-1","profile":"assess/criterion","state":{"criterion":"State a limitation.","evidence":"The small sample limits generalization.","evidence_complete":true,"bands":{"met":"Explicitly states a limitation.","unmet":"Does not state a limitation."}}}]}
```

Defaults: 10 calls, 4 workers, 30 seconds. Identical requests share a result
within the batch; credentials resolve once. Inspect every item: invalid input,
exhausted budgets, provider failures, and deadlines are errors, not `unsure`.
Partial CLI failure exits 1; MCP retains rows and marks the result as an error.
No implicit retries, persistent cache, or history. Limits bound calls and input,
not dollar charges; incomplete usage leaves cost null. Calling workflows own
budgets across batches. See [CLI limits and setup](../../Tools/README.md#agency-decide)
for the full interface.

`doctor` and `--dry-run` need no vault or provider access. The full installer
imports the key from 1Password once into the private local
`${XDG_CONFIG_HOME:-~/.config}/agency/openrouter.json` file. Runtime reads only
that file or the `OPENROUTER_API_KEY` environment override, so Jev remains
available unattended across restarts. `setup --interactive` imports missing keys
or old references; never put credential contents in prompts, arguments, or the
repository.

## Review before acting

Labels are advisory. Initially cross-check semantic judgments against evidence;
reduce review only on evaluated contracts. Always inspect uncertainty,
contradictions, incomplete evidence, hard constraints, and consequential
boundaries. `scope` carries `review_required: true` because it can confuse
explicit requests with implied supporting steps, even at high confidence.
An absent review flag does not waive evidence checks.

A label cannot authorize actions, hide failures, remove mandatory context,
verify a source, prove correctness, or complete a task. Keep arithmetic,
deadlines, permissions, and required checks in code or the owning workflow.
Repeated agreement is not independent verification. Jev returns labels and
probabilities, not explanations; never attribute invented reasoning to it.
Escalate `unsure`, errors, and evidence conflicts to the reasoning agent.

Keep Jev's result distinct from the reasoning agent's final decision. An
override needs an evidence-based reason. A follow-up judgment after new evidence
is a separate result, not an override: retain the earlier label and identify
what changed. Do not repeat unchanged packets to obtain a preferred answer.
Use the workflow's existing record for this history where one exists.

When Jev contributes, include one short usage line in the user handoff, such as
“Jev: 5 judgments (1 follow-up), 0 errors, 0 agent overrides.” Count completed,
non-reused judgments, exclude dry runs, and report errors separately. Mention
consequential disagreements or changed results and link an existing decision
record when useful; do not create extra artifacts solely for this summary.

## Learn from real corrections

When personalizing, read compact rules, scope, exceptions, and review status in
`${XDG_CONFIG_HOME:-~/.config}/agency/preferences.json` if present. Inspect source
quotes only when needed. Distinguish explicit preferences from tentative
inferences; one-off authorization is not standing permission. The runtime does
not upload that file. Keep raw transcripts out of requests.

Evaluate authorized, representative examples before changing automation:

```sh
agency-decide evaluate --input cases.json
```

Use the batch format plus `expected` on each item. This makes hosted calls;
errors remain in the denominator, mismatches/errors exit 1, and invalid/empty
input exits 2. Keep tuning and held-out cases separate, preserve failures, and
report denominators and uncertainty. Increment versions when rubric meaning
changes. Synthetic accuracy does not establish calibrated confidence or useful
automation: measure accepted outcomes, elapsed time, reasoning cost, and repairs.

No records are saved automatically. When requested, retain minimal results
outside the repository with IDs, model, profile version, rubric hash, and source
references. Explicit corrections can label that decision; inferred preferences
and successful commands cannot supply human labels.
