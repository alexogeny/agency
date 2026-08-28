---
name: release-writing
description: Research and write human-facing release notes or changelogs from repository evidence. Use when preparing, drafting, or revising a software release summary; defer to a repository-specific release skill or documented release process when one exists.
---

# Write release notes

Produce a trustworthy account of what changed for people who use or operate the
software. Repository-local release instructions take precedence. If the project
provides its own release skill, read and follow it instead of substituting this
generic workflow.

## Establish the release

1. Read the repository guidance, release workflow, existing notes, changelog,
   version source, and contribution conventions. Match their location and
   structure rather than introducing a second system. Check repository skill
   locations as well as an established top-level `skills/` directory.
2. Identify the target version and comparison point from explicit user input,
   version metadata, existing releases, and tags. Refresh remote state before
   relying on branches, tags, or pull requests. State the exact range used.
3. Distinguish a draft or unreleased version from a published release. Do not
   invent a release date, version, grade of stability, compatibility promise,
   or publication status.

## Build the account from evidence

Inspect non-merge commits, merged pull requests, and relevant diffs across the
range. Trace every consequential statement to repository evidence. Read the
diff when a title is vague, exaggerated, or implementation-centred.

Write for the user, not the commit history:

- Lead with the release's observable theme and most consequential outcome.
- Put breaking changes and migrations first. Name who is affected, the old and
  new behaviour, and the shortest correct migration.
- Group related work by user-visible capability or problem solved. Collapse a
  cluster of implementation commits into one accurate item.
- Describe fixed symptoms and failure modes, not merely internal causes.
- Include performance numbers only when retained measurements establish them;
  preserve the workload, baseline, units, and material caveats.
- Mention security, dependency, platform, deprecation, and operational changes
  when they alter what a user must know or do.
- Roll up documentation, tests, refactors, CI, and maintenance work unless they
  are themselves the release's relevant outcome.

Do not infer intent, claim unverified compatibility, turn commit volume into
importance, enumerate noise, or advertise ordinary maintenance as a feature.

## Shape and voice

Use the repository's established sections. If none exist, choose only the
sections the release needs from: Breaking changes, Added, Changed, Fixed,
Performance, Security, and Internals.

Lead with the result. Use plain, specific, active language and one idea per
dense sentence. Cut promotional language, generic conclusions, canned phrases,
vague attribution, decorative formatting, and explanatory filler. Repeat the
clearest term instead of cycling through synonyms. State uncertainty and
tradeoffs directly. Before finishing, remove anything that sounds generated or
could describe an arbitrary release.

Verify links, version arithmetic, dates, headings, and any repository-specific
navigation or release checks. Report the output path, comparison range, major
omissions or uncertainties, and checks run. Do not publish, tag, commit, push,
or create a release unless the user explicitly asks for that separate action.
