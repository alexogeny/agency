---
name: pr-writing
description: Research and write or revise a pull-request title and body from the actual branch, diff, tests, and repository conventions. Use when the user asks for a PR description, pull-request narrative, review guide, or help explaining a change to reviewers.
---

# Write a pull request

Create a reviewer-facing map of the change, not a transcript of how it was
built and not a restatement of the diff.

## Establish the change

1. Refresh remote state before inspecting branches or pull requests. If the
   request concerns an existing or live PR, query the forge first and identify
   it from repository, author, head, base, and conversation context; do not
   assume the checked-out branch owns it.
2. Read repository guidance and any PR template. Establish the exact head/base
   range, then inspect the commit subjects and bodies, diff summary, meaningful
   source changes, tests, documentation, compatibility surface, and retained
   measurements.
3. Preserve unrelated work. Distinguish committed branch content from local
   uncommitted changes and say which one the body describes.

Every claim must be grounded in the range. If the title or commits undersell,
overstate, or misdescribe the diff, follow the implementation and verified
behaviour instead. Do not infer design intent from comments or previous agent
narratives.

## Compose for review

Scale the body to the change and omit empty sections. A substantial PR often
benefits from:

- **Summary:** the outcome and scope in one short paragraph or a few cohesive
  bullets.
- **Why:** the concrete problem, missing boundary, or measured cost that made
  the change necessary. Explain the problem rather than narrating the patch.
- **Main changes:** groups organised by behaviour or subsystem, not a file dump.
- **Compatibility and failure modes:** defaults, migrations, refusal paths,
  security boundaries, and operational consequences reviewers must verify.
- **Measured result:** exact retained measurements with baseline, workload,
  units, controls, and caveats. Never manufacture a benchmark narrative from a
  code-level optimisation claim.
- **Review guide:** a short ordered path through the riskiest or most important
  code, with what to examine at each stop.
- **Quick test:** the shortest copy-paste command or manual path that lets a
  reviewer observe the changed behaviour, followed by the expected result.
- **Verification:** commands or CI checks actually run and their outcomes.
  Distinguish passed, failed, skipped, unavailable, and not run.

Small changes may need only Summary and Verification. Do not bury the point
under generated inventories, exhaustive test filenames, raw commit lists,
diff statistics, or boilerplate. Include them only when they materially help a
reviewer understand scope or confidence.

## Make reproduction cheap

When the change can be exercised directly, include this compact block near
Verification:

````markdown
### Quick test

```sh
exact command
```

Expected: one observable result.
````

Optimise for time to first signal: lead with the smallest useful check and put
full suites later in Verification. Add one prerequisite line only when a clean
checkout and the repository's normal setup are insufficient. Name required
environment variables without values, use a small deterministic input or
fixture, and prefer one useful path over a testing catalogue. For a regression,
say what fails before the change and passes after it. If no honest reproduction
is available, state the exact blocker instead of giving vague instructions.

## Title and voice

Follow the repository's title convention. Name the dominant user-visible or
architectural outcome with a concrete verb; do not join unrelated commit titles
or append vague scope such as “updates” or “improvements.”

Lead with the result. Use plain, specific, active language. Keep one idea per
dense sentence, repeat the clearest term, vary rhythm naturally, and state
uncertainty or tradeoffs directly. Cut puffery, promotional claims, canned
phrases, vague attribution, generic conclusions, unnecessary headings,
decorative emoji, and implementation explanations a reviewer can read in the
diff. Remove any sentence that could describe an arbitrary pull request.

Never add or check an authorship declaration, co-authorship trailer, generation
notice, tool attribution, signature, or certification on the user's behalf.
Preserve required template text but leave personal attestations for the user.

Return a ready-to-paste title and body, plus any unresolved factual gaps. Do not
create or edit the forge PR unless the user explicitly asks for that external
mutation.
