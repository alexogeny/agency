---
name: report-writing
description: Research, draft, and revise the prose of a substantial academic or professional report for its brief, evidence, audience, and rubric. Use when the user asks to write or improve report content; pair with report-generation for structured citations and rendered artifacts. Do not use for a short memo, email, ordinary answer, novel, or codebase assessment.
---

# Write a report

Use the `report-generation` skill when the work also includes source assembly,
YAML or TOML frontmatter, structured references, linked citations, tables,
figures, or PDF output. Use the `thoreau` skill for a deterministic readability
audit after a coherent draft exists.

## Establish the document contract

Read the assignment, brief, rubric, template, audience requirements, source
materials, and existing report index before drafting. Identify required
sections, word limits and exclusions, citation style, identity fields,
submission format, and any human-only verification or declaration.

Do not turn requirements or evidence notes into report prose. Keep research
logs, assessment audits, and handoffs outside the rendered section list. Never
invent a source, citation key, bibliographic field, quote, finding, figure, or
measurement. Treat reference records as verified only when their identity and
the adjacent report claim have actually been checked.

## Draft from evidence

Build each section around its job in the argument. Put the claim first, then the
specific evidence and its implication. Keep one main idea per paragraph. Map
every evidence-dependent claim to a checked source using the citation form
declared by the report index. If structured YAML citations are required, use
exact bibliography IDs such as `{cite: {ids: [S101], mode: narrative}}` and
`{cite: {ids: [S101, S337], mode: parenthetical}}`.

Never invent a source, citation ID, bibliographic field, quote, finding, figure,
or measurement. Do not turn planning notes, grading criteria, source-search
history, or implementation commentary into report prose. Explain specialised
terms only when the intended reader needs the explanation.

## Revise for the reader

Unless the brief or audience calls for another level, target Australian Year 9
readability. This is a clarity target, not permission to remove necessary
technical terms or flatten the argument. Prefer concrete nouns and verbs,
active voice, short transitions, and sentences whose logic remains visible on
one read.

Render a markup-free audit copy, then run Thoreau after substantive revision:

```console
report-build build REPORT_DIR --format text
thoreau style REPORT_DIR/build/report.txt --json
```

This avoids treating YAML citation objects and Markdown labels as prose. Read
the reported Flesch–Kincaid grade, difficult sentences, passive voice,
hedges, wordiness, and register as editing evidence. Revise with judgement and
rerun the audit. Do not use `--fix` unless the user asks for mechanical changes;
it does not replace editorial judgement. Do not imply that readability or style
can establish authorship.

Before handoff, read the prose once without the rubric in view. Remove throat
clearing, repeated conclusions, vague attribution, inflated claims, and details
that explain the production process rather than the subject. Then check the
argument against the rubric and evidence again. Report the measured grade level,
remaining difficult passages, word limits, unresolved evidence questions, and
human-only verification or declaration steps.
