# Daily evidence packets

Use these fictional examples as packet shapes, replacing excerpts with inspected
evidence. Each JSON block is one batch item; place items in the manifest's
`items` array. Keep the ID mapped to source paths, line ranges, artifact versions,
and check records in the existing local workflow record. Local pointers establish
traceability, not permission to upload their contents. Send only authorized,
necessary excerpts. Do not add a suggested label or leading evaluation to the
state. Expected answers belong only in evaluation cases, never evidence packets.

## Test ordering

Caller: `performance-design` or `babysit-pr`, when several tests plausibly cover
a change. Include actual setup and assertions, not just test names. Preserve
mandatory checks and run the direct regression first; skip this step when the
coverage is already obvious.

```json
{"id":"test-1","profile":"test-relevance","state":{"change":"Accept multipart image uploads up to 20 MiB; the form parser previously rejected a 70 KiB text field before the handler.","test":"Posts a 1 MiB image and a 70 KiB text field to /render; asserts HTTP 200 and a decoded output image."}}
```

Local provenance: changed parser setting and handler lines, the test function,
and collected test ID. A label does not establish that the test passed.

## Failure triage

Caller: `babysit-pr` or `docs-verification`, when an unfamiliar diagnostic needs
an investigation family. Supply the command context, exit status, and redacted
failure excerpt. Check straightforward diagnostics directly.

```json
{"id":"failure-1","profile":"failure","state":{"diagnostic":"CI command: package fetch. Exit 1. Registry response: HTTP 403, token lacks packages:read. The compile step did not start."}}
```

Local provenance: run/job ID and log lines. Investigate the indicated family;
do not infer a root cause or request expanded access from a label. For repeated
failures use `novelty` only after matching version, trigger, and diagnostics.

## Requirement coverage

Caller: `assess` or the implementation acceptance review, once one literal
requirement and its evidence have been collected. Verify counts, file presence,
and other deterministic requirements directly.

```json
{"id":"requirement-1","profile":"assess/criterion","state":{"criterion":"Explain how to recover when an upload fails.","evidence":"The error panel says: Upload failed. Your draft is saved. Choose Retry to upload again.","evidence_complete":true,"bands":{"met":"Explains the recovery action when an upload fails.","unmet":"Does not explain a recovery action when an upload fails."}}}
```

Local provenance: exact brief clause and inspected panel source/render. Mark
`evidence_complete` false if relevant states remain uninspected; absent evidence
is not an unmet requirement. Coverage does not authorize release or completion.

## Draft claims

Caller: `benchmark`, `pr-writing`, `release-writing`, or `coordinate`, when a
consequential draft claim needs comparison with retained evidence. Include
workload, measured resource, failed/skipped checks, and unavailable verification.

```json
{"id":"claim-1","profile":"claim-fit","state":{"claim":"The parser uses less memory on all inputs.","evidence":"On fixture A (1 MiB), repeated runs measured median peak allocated bytes of 640000 before and 480000 after; parsed outputs matched. Other input sizes and resident memory were not measured."}}
```

Local provenance: build/version IDs, raw samples, equivalence output, and check
record. Compute numbers directly; inspect scope mismatches before retaining copy.

## Research screening

Caller: `web-research` or `report-writing`, after opening several candidate
passages. Supply one exact claim and the relevant passage with its conditions.
Use `evidence-review/eligibility` instead when screening against an inclusion
criterion in a formal evidence review.

```json
{"id":"research-1","profile":"research","state":{"claim":"The measured benefit persists at batch size 64.","passage":"At batch size 8, median latency decreased from 40 ms to 30 ms. Batch sizes above 16 were not evaluated."}}
```

Local provenance: source ledger ID, direct URL, publication/retrieval dates,
content hash, and opened line range. Verify authority and freshness separately;
preserve conflicting passages and distinct sources.

## PR review and dependency triage

Caller: `babysit-pr`, when several review comments need sorting or an upstream
change needs comparison with local usage. Read current threads and the relevant
diff; dependency packets need the actual imported API and configuration.

```json
{"id":"review-1","profile":"babysit-pr/review","state":{"comment":"Please cover retries when the first request times out.","context":"The current diff adds a retry loop. Its added test returns HTTP 200 on the first request. The thread has no follow-up confirmation."}}
```

```json
{"id":"dependency-1","profile":"babysit-pr/dependency","state":{"update":"Version 3 removes the Client(timeout_seconds=...) constructor argument and accepts timeout=... instead.","usage":"The lockfile selects version 2.8. The local adapter constructs Client(timeout_seconds=15). No other Client construction was found in the inspected source tree."}}
```

Local provenance: repository/PR/head, comment/thread IDs and diff lines; for
dependencies, upstream release source, lockfile version, import and call-site
lines. No label posts replies, resolves threads, installs updates, establishes
security, or waives required CI.

# Staged advisory rollout

Evaluate profiles separately for the workloads where they will be used. Start
with a small useful subset, such as test ordering and claim review; keep the
remaining profiles available when their caller triggers apply. No call quota
or automatic expansion follows from starting a trial.

1. **Check packets offline.** Review state fields, provenance, redaction, and
   bounded budgets with the CLI dry run. This validates inputs, not judgments.
2. **Evaluate held-out cases.** Separate tuning from evaluation; include routine,
   ambiguous, incomplete, and contradictory evidence from the target workload.
   Keep profile version, rubric hash, and model attached to results. Report
   errors and mismatches in the denominator, with sample size and uncertainty.
3. **Run paired advisory trials.** Compare ordinary reasoning with Jev-assisted
   work on equivalent tasks, with the same acceptance criteria and required
   checks. Alternate or randomize order where possible; avoid learning the
   answer from the first run. Review every judgment during this stage. Measure
   end-to-end time including packet preparation, provider latency, review, and
   repair, plus reasoning tokens/cost, provider usage/cost, accepted outcomes,
   and rework. Preserve unsuccessful attempts and missing measurements.
4. **Decide per profile.** Use the offline trial report to summarize supplied
   pairs, then inspect their evidence. Keep full review or stop routine use
   when overhead, errors, or repairs outweigh the benefit. Reduce routine review
   only for a demonstrated useful workload and retain checks for uncertainty,
   contradictions, incomplete evidence, required-review contracts, and
   consequential boundaries. Re-evaluate after material model, rubric, or
   workload changes; restore full review when failures change the conclusion.

Task acceptance must come from the agreed checks and evidence review, not Jev's
agreement with the agent. A faster rejected outcome is not a productivity win.
Report time, token use, monetary cost, quality, and repairs separately; lower
reasoning-token use may still cost more or take longer. Missing provider usage
means unknown cost, not zero. Small or synthetic samples and a high returned
probability do not establish calibrated confidence or safe automation. Neither
the trial report nor reduced review authorizes actions or automatic retention.

Use existing authorized workflow records, outside the repository, for retained
trial evidence. This guidance does not start logging, save decisions, infer
standing preferences, or grant permission to send additional data.

## Record a paired trial

Start with `test-relevance` and `claim-fit` on work where packet preparation is
small and the acceptance evidence already exists. Treat both as awaiting
representative evaluation until an inspected trial record establishes otherwise.
Synthetic fixture coverage and a successful live smoke test do not change that
status. Keep other profiles available under their existing advisory triggers.

Before running either arm, record the workload ID, exact task versions, allowed
inputs, required checks, acceptance criteria, and order assignment. Use separate
fresh sessions with equivalent context for baseline and assisted arms. Include
routine, ambiguous, incomplete, and contradictory evidence; keep held-out tasks
separate from cases used to tune a contract. A baseline must not see the assisted
answer or its labels. Counterbalance order or use equivalent independent tasks
when repeating the same task would reveal the answer.

For test ordering, acceptance requires the direct regression and all required
checks to run, relevant adjacent boundaries to be reviewed, and omissions to be
identified against actual test assertions. Measure the whole selection and
validation task, including packet preparation and review. For claim review,
acceptance requires retained claims to match the source artifacts and their
limits, with contradictions and unavailable checks preserved. Jev's agreement
with a draft is never the acceptance label.

Use the [paired trial format](../../../Tools/README.md#paired-usefulness-trials).
Copy the actual model revision, profile version, and rubric hash from each
result into provenance. Include both reasoning-model configurations and a
workload ID tied to fixed acceptance criteria. If a task uses multiple Jev
revisions or contracts, split the experiment or assign a separate workflow
record; do not attribute it to one homogeneous profile cohort.

Keep a companion record keyed by pair ID with source references, order,
acceptance-check output, review/repair notes, and the evidence for any override.
Supply full end-to-end elapsed time, costs including failed attempts, and
nullable reasoning-token counts. An unavailable token measurement is null,
not a guess based on text length. Do not fill sample records with fabricated
baseline timings or acceptance decisions.

Review `by_cohort` separately, including unsuccessful attempts and missing
measurements. Record one of: awaiting evaluation, full advisory review retained,
routine use stopped, or review reduced for this exact workload. Include sample
size, observed tradeoffs, unresolved uncertainty, and the evidence for that
decision. No numeric threshold in the reporter changes this status. Model,
rubric, reasoning configuration, or workload changes require fresh evaluation.
