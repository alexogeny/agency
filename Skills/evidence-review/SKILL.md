---
name: evidence-review
description: Build and audit a reproducible evidence-screening ledger for scoped literature, policy, or technical reviews with searches, deduplication, inclusion decisions, and exclusion reasons. Do not use for a quick lookup or informal source list.
---

# Review a structured evidence set

Define the review question, source scope, search date, exact queries, eligibility
criteria, and stopping rule before screening. Keep search logs and screening
records separate from report prose.

Use the installed `evidence-review` command to normalise CSV, JSON, or JSONL
exports into a stable ledger:

```console
evidence-review ingest EXPORT.csv --source PUBMED-S1 --output screening.csv
evidence-review audit screening.csv --output audit.json --json
```

For JSON whose records sit below a container, pass `--records-key`, using dots
for nested keys. The tool recognises common title, year, author, DOI, URL, and
record-ID fields. It marks exact normalised DOI or title duplicates only. Treat
those links as candidates to verify; never use fuzzy similarity to silently
discard a source.

Make inclusion and exclusion decisions from the supplied criteria and the
record actually inspected. Record a specific reason for every exclusion. Keep
`pending` when the available title, abstract, or full text is insufficient.
Never invent bibliographic fields, screening decisions, or unavailable full
text.

Audit before synthesis. Report databases and queries, dates, records found,
duplicates, screened and pending counts, exclusions by reason, unresolved
records, and retained ledger/audit paths.
