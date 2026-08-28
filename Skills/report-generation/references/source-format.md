# Report source format

The format uses standard YAML or TOML frontmatter and a focused Markdown subset.
The report index controls assembly; its body is working documentation and does
not enter the rendered output.

## YAML index

```yaml
---
schema_version: 1
title: Report title
assessment: Assessment title
language: en-AU
citation_style: apa-7
citation_markup:
  id_source: {path: references.md, field: id}
identities:
  - {name: First author, identifier: "12345678", role: Student}
  - {name: Second author, identifier: "87654321", role: Student}
institution:
  name: Example University
  course: ABC123 - Course name
cover_page: {enabled: true}
word_count: {limit: 1800, tolerance_percent: 10}
presentation: {font_size_pt: 12}
sections:
  - {id: problem, order: 1, path: sections/01-problem.md, include_in_submission: true, include_in_word_count: true, max_words: 500}
  - {id: references, order: 2, path: references.md, include_in_submission: true, include_in_word_count: false, record_encoding: yaml}
required_identity_fields: [name, identifier]
---
```

New projects created by `report-build init` use YAML. TOML frontmatter delimited
by `+++` is also supported through `schema = 1`,
`references = "references.md"`, `required_fields`, `word_limit`,
`word_tolerance_percent`, and `[[sections]]`.

Repeat `--author`, `--identifier`, and optionally `--role` in the same order
when initialising a multi-author report. Existing `student.name` and
`student.number` frontmatter remains supported as a single legacy identity.

Reports have a cover page by default. It contains the title and assessment,
followed by dedicated author and institution sections when those records are
present. The cover has no page number; body numbering starts at 1. Use
`cover_page: false` to omit it, or customise its labels with:

```yaml
cover_page:
  enabled: true
  author_heading: Author
  institution_heading: Institution
```

An institution may be plain text or a structured mapping. Structured records
support `name`, `course`, `faculty`, and `department`. Use
`required_institution_fields: [name, course]` when both must be complete.

## Presentation profiles

The `standard` profile is the default. The `compact` profile uses 9.2-point
body text, tighter spacing, and 15 mm margins. Both profiles accept explicit
overrides:

```yaml
presentation:
  profile: compact
  font_size_pt: 9.2
  margins_mm: {top: 14, right: 13, bottom: 16, left: 15}
  line_height: 1.3
  paragraph_spacing_pt: 2
  heading_spacing_pt: {before: 5, after: 2}
  caption_spacing_pt: {before: 2, after: 3}
  title: {alignment: center, size_pt: 17.5, top_margin_mm: 18}
  columns: 2
  column_gap_mm: 6
```

`font_size_pt` accepts integer or decimal point sizes from 6 to 72 in HTML,
TeX, and native PDF output. `margins_mm` may also be one number for all four
edges. `columns` accepts 1 or 2; references and the cover remain single-column.
Check narrow tables and figures visually when using two columns.

Only configured submission sections are assembled. Reference and title-detail
records are rendered from index metadata rather than duplicated as body
sections. `include_in_word_count` and `count_words` are equivalent.

A configured reference database produces a References section only when the
report contains at least one resolved citation.

## References and citations

The bibliography may contain one fenced YAML record per source:

````markdown
```yaml
id: S101
citation_key: CarterEtAl2024
type: journal_article
authors:
  - {family: Carter, given: "Stacy M."}
  - {family: Popic, given: Diana}
issued: {year: 2024}
title: "Checked source title"
container_title: "Checked journal title"
volume: "12"
issue: "3"
pages: {first: 101, last: 119}
doi: 10.0000/example
apa7_plain: "Complete, checked APA 7 reference with a stable DOI or URL"
verified: true
```
````

Use the record's `id` in structured prose citations:

```markdown
{cite: {ids: [S101], mode: narrative}} identifies the boundary.
The boundary is established {cite: {ids: [S101], mode: parenthetical}}.
Two sources agree {cite: {ids: [S101, S337], mode: parenthetical}}.
The detail appears here {cite: {ids: [S101], mode: parenthetical, locator: "p. 14"}}.
```

The renderer alphabetises works inside grouped parenthetical citations from the
resolved APA sort keys. Narrative citation groups retain source order because
their order forms part of the sentence.

Each rendered citation links to its bibliography entry. Narrative and
parenthetical author forms, year suffixes, ordering, and bibliography entries
are derived from the same structured record. For `citation_style: apa-7`, the
generator supports `journal_article`; report and guide types
`government_report`, `government_guide`, `government_framework`, `report`,
`guide`, and `standalone_report`; and webpage types `webpage`,
`standalone_webpage`, `corporate_author_webpage`, and
`regulator_guidance_webpage`.

The index `citation_style` selects the renderer. The reference-file frontmatter
must declare the same value. Unsupported or conflicting values fail validation.
`apa7_plain` is an audit preview and never overrides complete structured
metadata. A deliberately unstructured legacy record may opt in with
`bibliography_fallback: apa7_plain`.

Fenced TOML references and Pandoc-style `[@key]`, `[@key, p. 14]`,
`[@first; @second]`, and narrative `@key` remain supported. TOML records use
`key`, `author`, `year`, `citation`, `bibliography`, and `verified`.

Treat a record as verified only after checking its identity and the adjacent
claim. Keep `require_verified_references = true` for final output.

## Figures and cross-references

```markdown
![Informative caption](assets/result.png){#fig:result width=82%}

The relationship is shown in {@fig:result}.
```

A caption and `fig:` label are mandatory. Width is optional and ranges from 1
to 100 percent. Use an 8-bit, non-interlaced PNG or a JPEG when building the
native PDF; PDF figure sources remain available in the emitted TeX but are not
rasterised by the dependency-free PDF writer.

## Tables and cross-references

```markdown
| Actor | Responsibility | Evidence |
| --- | --- | --- |
| Service | Local validation | Protocol and test record |
| Supplier | Update notice | Versioned release notice |

Table: Lifecycle evidence by actor. {#tbl:lifecycle}

The handoff is summarised in {@tbl:lifecycle}.
```

Keep tables narrow enough for the page. Put detailed inventories in an appendix
or separate evidence artifact.

## Supported body markup

The renderer supports headings, paragraphs, emphasis, strong text, inline code,
HTTP links, lists, block quotes, fenced code, `$$` display math, horizontal
rules, citations, figures, tables, and figure/table cross-references. Extend and
test the renderer when a report genuinely needs another construct.
