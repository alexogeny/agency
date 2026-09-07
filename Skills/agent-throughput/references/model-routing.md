# Provisional model routing

These lanes are hypotheses for local evaluation, not capability rankings.
Choose from task shape and failure cost, then replace them with measured
repository-specific routing.

| Lane | Start here when |
| --- | --- |
| Astra low | The change is small, explicit, and local, with a cheap focused check. |
| Astra medium | Substantial repository work needs cross-file understanding or several coherent steps. This is the default serious implementation lane. |
| Astra high | Persisted state, retries, concurrency, protocols, or several coupled invariants make an omitted path expensive. |
| Sol high | A checklist-heavy execution pass or independent edge-case review benefits from persistent enumeration. |
| Fable 5.1 | Architecture, product or UI direction, visual judgment, or taste dominates mechanical implementation. |

Use a second model only when the likely cost of an undetected failure or later
repair exceeds the full review cost. Give the reviewer a distinct remit and
acceptance oracle, not a generic request to check everything.

Escalate effort after evidence: repeated incorrect fixes, an unresolved coupled
invariant, or failure to form a checkable plan. Do not escalate merely because a
task is important. De-escalate or stop once the difficult decision is resolved.

## Why these lanes are tentative

- OpenAI describes Astra as coherent on long multistep work, more likely to ask
  material clarifying questions, more instruction-sensitive, and potentially
  less inclined to delegate without prompting.
- One same-repository account found Astra medium cheaper than Sol high because
  it used far fewer requests and tokens, while Astra high did better on coupled
  state and recovery. That is one task, not a general result.
- Independent coding-agent and code-review evaluations show stronger Astra
  token efficiency and cross-file review in their harnesses, but mixed results
  on broader intelligence tasks.
- Early Fable 5.1 review evidence favoured lower reasoning and restraint, while
  practitioner accounts still prefer Claude-family models for visual taste.

## Sources

Last reviewed 2026-09-07:

- [OpenAI GPT-6 Astra model guidance](https://developers.openai.com/api/docs/guides/latest-model)
- [OpenAI GPT-6 Astra model and pricing](https://developers.openai.com/api/docs/models/gpt-6-astra)
- [OpenAI GPT-5.6 Sol model and pricing](https://developers.openai.com/api/docs/models/gpt-5.6-sol)
- [Anthropic models overview](https://platform.claude.com/docs/en/models/overview)
- [Astra medium versus Sol high repository account](https://dev.to/shinpr/switching-from-gpt-56-sol-to-gpt-6-astra-start-with-medium-effort-25ao)
- [Artificial Analysis Astra benchmarks](https://artificialanalysis.ai/articles/benchmarking-gpt-6-astra)
- [CodeRabbit Astra code-review evaluation](https://www.coderabbit.ai/blog/gpt-6-astra-code-review-evaluation)
- [CodeRabbit Fable 5.1 evaluation](https://www.coderabbit.ai/blog/fable-5-1-model-review)
- [Matt Shumer's Astra field report](https://somethingbig.ai/astra-review)
