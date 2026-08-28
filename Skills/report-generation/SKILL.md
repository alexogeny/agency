---
name: report-generation
description: Assemble, validate, and render a substantial report from modular Markdown, YAML or TOML frontmatter, structured references, linked citations, tables, figures, cross-references, word limits, HTML, TeX, and PDF. Use when creating report source infrastructure or producing final report artifacts; pair with report-writing when drafting or revising the prose.
---

# Generate a report

Use the installed `report-build` command. The source stays readable Markdown;
YAML or TOML carries document structure and reference data. The built-in PDF
writer embeds the open Computer Modern Unicode typesetting family and does not
invoke TeX or a browser. Body paragraphs are justified; headings, lists,
captions, and references retain their conventional alignment. Render academic
work in black on white; do not apply personal or application colour palettes to
a report unless its brief requires them. Read
[the source-format reference](references/source-format.md) before creating or
changing report markup.

## Establish the document contract

Read the assignment, brief, rubric, template, audience requirements, source
materials, and existing report index. Identify section order, word limits and
exclusions, citation style, identity fields, submission format, and human-only
verification or declarations. Keep research logs, assessment audits, and
handoffs outside the rendered section list.

For a new report, start with:

```console
report-build init REPORT_DIR --title "Exact title" --author "Name"
```

Use stable bibliography IDs. When the source contract calls for structured
citations, write `{cite: {ids: [S101], mode: narrative}}` or
`{cite: {ids: [S101, S337], mode: parenthetical}}`. Every ID must resolve to
one checked reference record. Never invent a source, key, bibliographic field,
quote, finding, figure, or measurement.

Use labelled figures and tables only when they clarify a relationship better
than prose. Give each an informative caption and refer to it in the text. Keep
assets inside the report project.

## Validate and render

Run validation throughout assembly and before claiming completion:

```console
report-build check REPORT_DIR
report-build build REPORT_DIR
```

`check` refuses unknown or unverified citations, missing figures, unlabelled
figures or tables, broken cross-references, duplicate labels, unresolved
placeholders, malformed tables, and exceeded configured word limits. It reports
unused references and unreferenced floats.

`build` emits audit-friendly plain text, print-ready HTML, inspectable TeX, and
PDF. Inspect the PDF rather than treating compilation as presentation proof.
Check page count, cover identity and institution details, the absent cover page
number, body numbering, section order, table widths, figure legibility,
captions, citation and cross-reference links, bibliography hanging indents,
page breaks, columns, margins, spacing, widows and orphans, and the configured
font size. Extract PDF text when useful.

Return the source and rendered paths, counted words and limits,
citation/reference counts, exact validation commands, remaining human actions,
and any layout or evidence limitation. Do not commit or submit the report unless
the user separately asks.
