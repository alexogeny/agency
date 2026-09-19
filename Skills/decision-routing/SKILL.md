---
name: decision-routing
description: Use Jev through OpenRouter for bounded System One judgments about skill suggestions, context relevance, evidence relationships, and agent updates. Use for repeated or ambiguous classifications, not coding, planning, authorization, or facts that code can compute exactly.
---

# Make small advisory decisions

Jev is the System One part of Agency: fast recognition from a small, relevant
input. The reasoning agent supplies System Two: decomposition, investigation,
planning, and resolving ambiguity. Design the decision boundary around that
division. Do not ask Jev to think through a repository, weigh an entire plan,
invent missing facts, or explain its answer.

Put exact code and explicit user instructions first. Give Jev the remaining
semantic choice only when a knowledgeable person could make it at a glance.
Keep the answer space small and include `unsure`. When a decision requires
several dependent steps, hand it to the reasoning agent rather than disguising
the chain as one classification question. Independent questions may be composed;
their dependencies and final actions belong in code.

Use the `agency-decide` MCP server's `profiles` and `classify` tools when
available, or the equivalent `agency-decide` CLI. This is a hosted OpenRouter
request: send only the task excerpt or candidate passage needed for the question,
within the user's authorized data scope. Never include credentials or an entire
session by default.

Skip Jev when an explicit instruction, exit code, parser, or ordinary judgment
already resolves the choice. Prefer it when classifying repeated candidates or
when a narrow ambiguous decision would otherwise consume substantial context.
Do not insert a model call before every tool invocation.

## Choose the decision

`agency-decide profiles` is the source of truth for versioned questions,
labels, and criteria. Each request asks one Choice question. Use these states:

| Profile | State | Use of the answer |
| --- | --- | --- |
| `skill` | `{"task":"the immediate requested work"}` | Suggest one of the listed skills; `none` and `unsure` remain valid. Named skills and required workflows take precedence. |
| `context` | `{"query":"current task","passage":"candidate excerpt"}` | Order optional retrieved context. Preserve mandatory instructions and retain conflicting evidence for inspection. |
| `update` | `{"update":"agent status","task_status":"running"}` | Label an update for an attention queue. Explicit questions, approval requests, errors, and failed checks always remain visible. |
| `research` | `{"claim":"specific claim","passage":"opened evidence"}` | Identify support, conflict, background, or irrelevance. This neither verifies a source nor establishes that the claim is true. |

The skill list is deliberately bounded, not an inventory of every installed
skill. A `none` result does not mean no other skill exists. Use the normal skill
catalog for work outside that list.

Call the CLI with a small input file or standard input:

```sh
agency-decide doctor
printf '%s\n' '{"query":"Where is the upload limit set?","passage":"MAX_BODY_BYTES configures the request body limit."}' |
  agency-decide classify --profile context --input - --dry-run
```

Remove `--dry-run` to send the displayed request. The runtime resolves the
1Password reference in `${XDG_CONFIG_HOME:-~/.config}/agency/openrouter.json`;
`OPENROUTER_API_KEY` can override it for automation. `agency-decide setup --interactive`
discovers an **API Key** field in the **OpenRouter** item and saves only its
secret reference; the installer uses prompt-free setup. If the key is not yet
present, state that once and continue useful local work. `doctor` reports local
configuration without resolving the vault secret or authenticating to OpenRouter.
Never put a key in tool arguments, prompts, repository files, or troubleshooting output. An unavailable
credential or provider is a reason to continue with ordinary reasoning, not to
ask repeatedly or invent a prediction.

## Interpret the result

The result carries `decision`, `probabilities`, `confidence`, the actual `model`,
`profile_version`, `latency_ms`, `usage`, and `advisory: true`. Missing confidence
stays null. A confident label can still be wrong; there is no default threshold
that authorizes autonomous actions. Keep arithmetic, deadlines, permissions,
mandatory checks, and source verification in their existing workflows.

Do not use a classification to approve a command, send a message, hide a failure,
discard mandatory context, or mark a task complete. Do not manufacture an
explanation attributed to Jev: this model returns labels and probabilities.
If the model says `unsure`, disagrees with explicit evidence, or returns an error,
preserve the input for the reasoning agent or human.

## Use preferences and evidence narrowly

When personalizing a decision, consult the local working preferences at
`${XDG_CONFIG_HOME:-~/.config}/agency/preferences.json` if present. Read the
compact rule statements, scope, exceptions, and review status; inspect source
quotes only when necessary. Explicit preferences and tentative inferences are
different. A one-off authorization is never standing permission, and inferred
rules never override the current request. The runtime does not upload this file.

Prefer prior decisions and corrections to a large manual labeling exercise.
Keep personal evidence outside the repository and raw transcripts out of Jev
requests. Before changing automated behavior, validate the relevant rubric on
representative examples, separate tuning from held-out evaluation, and report
denominators, uncertainty, and errors. Increment the rubric version when its
meaning changes. An empty comparison set is unmeasured, never a pass.
