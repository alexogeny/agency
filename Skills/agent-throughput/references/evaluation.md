# Evaluate throughput

Evaluate a routing decision on representative accepted work, not isolated model
answers.

## Corpus

Use completed historical tasks whose expected behaviour and checks are known.
Include several examples of each repeated task shape, such as bounded fixes,
multi-file behaviour changes, and stateful or cross-cutting defects. Keep the
work packet, repository state, permissions, harness, and acceptance oracle
equivalent between lanes.

Run the candidate default and current baseline on every task. Add other models
or efforts only where their proposed lane applies. Repeat close or unstable
results; do not spend repetitions proving a large operational difference.

## Per-run record

Capture:

- accepted on the first pass and accepted after repair;
- focused and broader check outcomes, including skips;
- uncached input, cached input, output, and reasoning tokens;
- model requests and tool operations;
- elapsed time and human review or repair time;
- scope or authority violations;
- model, effort, harness version, repository revision, and work-packet digest.

Use actual billed cost when available. Otherwise label API-rate calculations as
estimates and record the price source and date. Subscription quota depletion is
not interchangeable with API token cost.

## Decision metric

The primary comparison is total cost per accepted task:

```text
(all model and tool cost + valued human review and repair time)
--------------------------------------------------------------
                       accepted tasks
```

Report success rate, elapsed time, repair burden, and scope violations beside
that number. Price per token, raw benchmark score, and number of calls are
diagnostics, not routing decisions. A more expensive model wins only when fewer
attempts, less context, or less repair outweighs its rate.

Promote a lane after it improves the repeated workload without a material
quality or safety regression. Keep a dated result and reevaluate after model,
harness, instruction, or repository changes large enough to invalidate it.

Sources last reviewed 2026-09-07: [OpenAI model guidance](https://developers.openai.com/api/docs/guides/latest-model), [Artificial Analysis Astra benchmarks](https://artificialanalysis.ai/articles/benchmarking-gpt-6-astra), and [CodeRabbit's Astra evaluation](https://www.coderabbit.ai/blog/gpt-6-astra-code-review-evaluation).
