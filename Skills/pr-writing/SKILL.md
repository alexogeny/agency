---
name: pr-writing
description: Research and write or revise a pull-request title and body from the actual branch, diff, tests, and repository conventions. Use when the user asks for a PR description, pull-request narrative, review guide, or help explaining a change to reviewers.
---

# Write a pull request

## Establish the evidence

Refresh remote state using the authenticated GitHub flow in
[babysit-pr](../babysit-pr/SKILL.md). Identify an existing PR by repository,
author, head, base, and conversation; do not assume the checkout owns it.
Read repository guidance and the PR template, then inspect the exact head/base
range: commits, meaningful source changes, tests, docs, compatibility surfaces,
and retained measurements. State whether the description covers committed
content or also uncommitted work.

Ground claims in the implementation and verification. Commit titles and prior
agent narratives cannot establish intent or behaviour.

## Group verified impact

Use [decision-routing](../decision-routing/SKILL.md) with `pr-writing/impact`
when several changes need grouping by audience. Supply one verified behaviour
change per item. Use compatibility, user, operator, developer, and internal
labels to organize the description. Verify compatibility candidates against
supported interfaces; labels do not establish breakage or select versions.
For uncertain draft claims, use `research` against relevant diff or check
evidence before retaining them.

## Write for the reviewer

Follow repository title conventions; use a concrete verb naming the dominant
outcome. Lead the body with the problem and resulting behaviour, using a
before/after example when useful. Scale to complexity: a small PR needs only
a short explanation and verification. For larger changes, include only useful
sections covering:

- Behaviour or subsystem changes, grouped by purpose.
- Compatibility, migrations, refusal paths, and operational consequences.
- Measured results with baseline, workload, units, controls, and caveats.
- A short review path through consequential code and what to inspect.
- Checks actually run, distinguishing passes, failures, skips, and unavailable
  checks.

Omit empty sections, file inventories, raw commit lists, and generic prose.
Write the final implementation, not a development diary. Keep abandoned
approaches only when they explain a trade-off.

## Make reproduction cheap

Include the smallest useful command or manual path and its observable expected
result. Add prerequisites only beyond normal repository setup; name environment
variables without values. Prefer deterministic fixtures. For regressions, state
what fails before and passes after. If reproduction is blocked, name the blocker.
Full suites belong after the quick check.

Return a ready-to-paste title and body plus unresolved factual gaps. Preserve
required template text, but leave personal attestations unchecked for the user.
Never add authorship declarations, signatures, or tool attribution. Create or
edit the forge PR only when the request authorizes that action.
