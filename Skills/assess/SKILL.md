---
name: assess
description: Grade, assess, critique, or evaluate a submitted work against supplied requirements or an appropriate declared framework. Use for academic and professional writing, creative work, or software/codebases when the user wants evidence-backed judgement rather than ordinary editing or code review.
---

# Assess a work

Evaluate the artifact that was actually supplied. Do not infer missing content,
intent, process, or quality from the author’s identity, prior conversations, or
unseen drafts. Assessment is read-only unless the user separately asks for
edits or fixes.

## Establish the basis

1. Identify the artifact, its intended form and audience, and whether the user
   supplied a rubric, brief, specification, genre convention, or scoring scale.
2. Treat explicit requirements and supplied rubrics as authoritative. Preserve
   their criteria, weights, bands, boundary rules, caps, and hard constraints.
   Do not silently repair ambiguous or internally inconsistent criteria.
3. If no rubric exists, derive a small framework appropriate to the artifact
   and declare it before applying it. Call the result a diagnostic assessment,
   not an official grade. Do not invent institutional grade boundaries.
4. Check that the available artifact is complete enough for the requested
   judgement. Assess missing material as missing only when it was required;
   distinguish missing, inaccessible, and unverifiable evidence.

Read only the relevant mode guidance:

- Academic, analytical, technical, or professional prose: read
  [references/written-work.md](references/written-work.md).
- Fiction, memoir, poetry, scripts, or other creative writing: read
  [references/creative-work.md](references/creative-work.md).
- Repositories, patches, programs, notebooks, or other software: read
  [references/software.md](references/software.md).

For a mixed artifact, combine only the relevant criteria and explain the
weighting rather than grading every component as though it were the same form.

## Judge from evidence

- Audit compliance and hard gates before scoring quality.
- For every criterion, record concrete evidence first: page, section, heading,
  line, symbol, test, behaviour, or concise excerpt. Then select the band or
  judgement and any precise score.
- Apply descriptors holistically. Do not average isolated strengths into a band
  whose central requirements the work does not meet.
- Reward demonstrated effectiveness, not effort proxies such as length,
  complexity, citation count, test count, formatting, or polish by themselves.
- Verify factual, bibliographic, or behavioural claims when verification is
  necessary and available. Flag a concern as suspected until evidence confirms
  it; never convert lack of access into an accusation.
- Keep criticism proportional. Separate correctness or requirement failures
  from optional improvements and personal taste.

## Make criterion decisions with Jev

Follow [decision-routing](../decision-routing/SKILL.md) for the shared Jev workflow.
Once the rubric and evidence are established, run `assess/criterion` for the
bounded semantic criteria. A substantial assessment will commonly yield 5–10
independent judgments; use fewer when fewer are meaningful. Check exact counts,
format rules, and arithmetic in code before preparing model questions.

Read the contract with `agency-decide profiles --profile assess/criterion`.
For each criterion, supply its exact requirement, a concise evidence excerpt,
`evidence_complete`, and the rubric's actual `bands`. Set completeness only when
the supplied packet covers the evidence needed for that criterion. Use stable
band IDs and preserve original names, descriptors, score ranges, and exceptions
in their definitions. Keep the criterion ID and source locations in the local
assessment record. Do not send a whole submission by default.

Use the returned bands as provisional criterion judgments. Check evidence
coverage, hard-gate implications, and consequential band boundaries before
scoring. Keep the band and final score alongside the criterion's evidence in the
assessment record. Calculate weights and totals in code using the actual rubric.

For requirement-coverage reviews, reuse this contract with one literal
requirement per item and explicit met/unmet bands, or the supplied descriptors.
Set `evidence_complete` for that requirement only. Missing inspection yields
insufficient evidence, not an invented unmet finding. Verify deterministic
requirements directly; provisional coverage labels do not approve a release or
establish that the overall task is complete.

## Report the assessment

Match the supplied output format when one exists. Otherwise report:

1. **Basis and scope:** artifact assessed, framework used, completeness, and
   any exclusions or limits.
2. **Requirements audit:** satisfied, missing, and unverifiable requirements.
3. **Criterion assessments:** judgement or score, specific evidence, and the
   main reason each criterion did not rate higher.
4. **Overall result:** arithmetic total only when the scale supports one; verify
   the calculation. Do not invent an overall label.
5. **Priority revisions:** a short, ordered set of changes with the greatest
   likely impact, without rewriting the work unless asked.
6. **Confidence:** high, medium, or low, with the specific reason.

Be candid and precise without becoming prosecutorial. A useful assessment lets
the user trace every consequential judgement back to the work and the chosen
standard.
