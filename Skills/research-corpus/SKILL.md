---
name: research-corpus
description: Create, retain, index, audit, reproduce, or rerun a portable sanitized research corpus with explicit evidence coverage and owned profile lifecycle. Use for durable multi-search evidence collection; use web-research for a quick lookup.
---

# Retain reproducible research evidence

Use `research-corpus` for durable discovery and opened sources. Read the
[command reference](../web-research/references/commands.md) for browser access
and use [evidence-review](../evidence-review/SKILL.md) for eligibility decisions.
Keep browser state, credentials, ledger credentials, and generated SQLite files
outside both the corpus and the repository.

Declare the research question, exact eligibility criteria, source classes,
absolute date window, access context, budget, and stopping rule in a nonempty
JSON protocol before collection. Relative windows such as “last year” must be
resolved to dates. Provider capabilities are recorded separately: an unsupported
control in the recipe is a limitation, not proof that the provider applied it.

For example, write a scoped `protocol.json` under the task's scratch directory:

```json
{"question":"Which public studies address the declared intervention?","source_classes":["journal"],"date_window":{"start":"2025-01-01","end":"2025-12-31"},"eligibility":"Study directly evaluates the intervention","budget":{"queries":3,"sources":10},"stopping_rule":"Three declared searches or ten opened sources"}
```

Initialize a new corpus. When task-owned cleanup is authorized, create the owned
profile before collection and use its returned profile name for every subsequent
`--profile` argument. `AUTHORIZATION_REFERENCE` identifies the user's existing
permission to create and remove this exact disposable task profile; obtain that
permission if it has not already been granted. Commit each search before the next one.
Use a stable operation ID to resume an uncertain search without duplicate
publication. Source IDs come from `manifest.json`; never assign them from rank. Replace
`OWNED_PROFILE_NAME` with the returned profile name, rather than creating an
unrelated named profile. If collection uses an existing approved user profile,
that profile has no task-owned deletion permission.

```console
research-corpus init "$TASK/corpus" --protocol "$TASK/protocol.json"
research-corpus profiles create "$TASK/corpus" --owner-execution WORK_ID --purpose "Scoped corpus collection" --mode persistent --authorization AUTHORIZATION_REFERENCE
research-corpus discover "$TASK/corpus" --query "EXACT QUERY" --profile OWNED_PROFILE_NAME --operation-id search-01 --strategy federated --limit 8
research-corpus open "$TASK/corpus" --source-id SOURCE_ID --profile OWNED_PROFILE_NAME
research-corpus resume "$TASK/corpus"
```

A committed discovery bundle contains sanitized JSON, text, and Markdown plus
its manifest entry and checkpoint. On interruption, run `resume` before another
search. Inspect the typed error and retained artifacts if backend failure left
useful evidence. Process exit, browser release, delivery truncation, access,
coverage, and screening are independent states.

The protocol's `budget` (or `budgets`) query/source ceilings are enforced per
run, including failed attempts. Evaluate narrative stopping criteria from the
retained evidence and record the actual stopping decision:

```console
research-corpus stop "$TASK/corpus" --reason "Declared topic coverage reached; unresolved sources remain labelled"
```

Stopping prevents further live collection in that run. Offline exports,
retention, indexing and audit remain available; `rerun` creates a new run.

Prefer explicit index-only export when retained page evidence is sufficient:

```console
research-corpus export "$TASK/corpus" --source-id SOURCE_ID --from-index --format all
research-corpus index build "$TASK/corpus" --db "$TASK/index.sqlite"
research-corpus index query "$TASK/corpus" "SEARCH EXPRESSION" --db "$TASK/index.sqlite" --limit 20
research-corpus index query "$TASK/corpus" "SEARCH EXPRESSION" --db "$TASK/index.sqlite" --kind discovery --prefix records/ --limit 20
research-corpus audit "$TASK/corpus" --json
```

`export --from-index` does not authorize a live refresh. Missing, stale, or
legacy cache evidence requires a separate scoped `open`. Corpus index queries
are read-only and default to `source` documents. Retain scoped UTF-8 protocol,
screening and synthesis documents through the same sanitized commit pipeline:

```console
research-corpus retain "$TASK/corpus" "$TASK/protocol.json" --kind protocol --operation-id protocol-01
research-corpus retain "$TASK/corpus" "$TASK/synthesis.md" --kind synthesis --format markdown --operation-id synthesis-01
```

Other kinds require an
explicit `--kind`; `--kind all` is useful for navigation but does not turn search
snippets into opened source evidence. Hits include the original record, source,
URL, artifact path, matched line range, access, and coverage limitations.
Databases and sidecars remain outside repositories and the corpus. A generation mismatch requires
rebuilding them. A failed rebuild preserves the previous usable generation.

Do cite the inspected source and actual retained lines, qualifying abstract-only
or partial coverage. Do not infer full text from body length, a citation ledger,
metadata, or an uninspected search result. `full-public-extract` describes the
public page fields actually extracted; it does not promise all tables, figures,
attachments, or article text.

Reconcile into a new screening ledger and inspect exact duplicate candidates:

```console
research-corpus screening reconcile "$TASK/corpus" --ledger "$TASK/screening-old.csv" --output "$TASK/screening-new.csv"
evidence-review audit "$TASK/screening-new.csv" --output "$TASK/screening-audit.json" --json
```

For a first ledger, create a CSV with just the `source_id` header. Existing
manual decisions, reasons, custom columns, and pending full-text status survive
reconciliation. Exact DOI/title/URL candidates remain separate records. Raw
byline/date values and their field provenance are retained. `parsed_year` is a
format interpretation, not verified bibliography; only field-specific verified
authors/year with supporting provenance enter those formatted columns. Each
verified field needs its own `authors_verification_status` or
`year_verification_status` set to `verified`, plus a `field_provenance` object
for `authors` or `year` with `origin` (`metadata`, `visible-main`, or an
authoritative record), `inspected: true`, and `alignment_verified: true`. Record
that alignment only after inspecting author/title/DOI agreement. Do not
promote a related-content byline, reviewer, contact, or verified title into
verified authors. Ambiguous dates remain unknown.

## Reproduce after six months

Offline processing requires a compatible Python runtime, SQLite FTS5 for
indexing, and Agency `sandbox` with a functioning OS isolation backend (Linux
user namespaces/Bubblewrap or macOS Seatbelt). Record those runtime versions;
archived source does not bundle an interpreter or remove these prerequisites.

Retain the complete corpus, including `software/`, manifest, record siblings,
and journals. Move a copy to another directory or machine, then use the archived
processing code without a browser, network, old cache, or original paths:

```console
python3 "$COPY/software/SOFTWARE_DIGEST/research-corpus" reproduce "$COPY" --offline --output "$TASK/reproduced"
research-corpus index build "$COPY" --db "$TASK/relocated-index.sqlite"
research-corpus audit "$COPY" --json
```

Replace `SOFTWARE_DIGEST` with the selected run's `software.path` directory
name from the manifest. Offline reproduction verifies retained hashes and
rebuilds exports from retained sanitized inputs. It cannot reconstruct discarded
secrets or upstream bytes that policy did not retain. Compare canonical index
documents and generations, not SQLite file bytes.

A live rerun is a different operation and uses current web access:

```console
research-corpus rerun "$TASK/corpus" --from RUN_ID --profile OWNED_PROFILE_NAME
research-corpus compare "$TASK/corpus" --old RUN_ID --new NEW_RUN_ID
```

The rerun records a linked run, preserves the declared historical window, and
fetches selected sources live even when the local index has a fresh cached copy.
Inspect changed bodies, rankings, access, additions/removals, recipe, and software.
Do not promise identical future search results. Audit recipe omissions and
unsupported controls before claiming search coverage or independent-source counts.

## Close and clean up owned profiles

Create disposable profiles before collection as shown above. After collection,
close the exact owned profile using the same owner execution and authorization
reference:

```console
research-corpus profiles close "$TASK/corpus" --owner-execution WORK_ID --authorization AUTHORIZATION_REFERENCE
research-corpus profiles cleanup "$TASK/corpus" --owner-execution WORK_ID --authorization AUTHORIZATION_REFERENCE --receipt "$TASK/cleanup-receipt.json"
```

`--authorization` refers to explicit user permission already granted for the
exact owned disposable profile. A string or eligibility flag does not grant
permission. Preserve the receipt. Identity/path, lifecycle lock, process release,
and exact ownership must pass; refuse unknown, reused, active, or mismatched
profiles. Exact owned-process verification currently requires Linux `/proc`;
other platforms return `profile-inspection-unavailable`. Owned ephemeral mode
returns `unsupported-profile-mode`; use persistent owned profiles with exact
authorized cleanup. Never delete another profile or shared captures/indexes.
For partial cleanup, inspect the receipt before retrying with a new receipt path.
When the directory was removed but metadata remains, a matching durable cleanup
checkpoint permits metadata-only recovery. A replacement directory or missing
checkpoint is refused. Keep the same owner, authorization, and private handle
until both removal postchecks pass.

## Verify without live research

Run the bundled synthetic example with a new output directory:

```console
python3 Skills/research-corpus/examples/offline-demo.py "$HOME/Scratch/corpus-offline-example"
```

It uses a synthetic backend, commits discovery and an abstract, builds/queries
the source index, audits, preserves screening decisions, relocates the corpus,
and runs offline reproduction. It opens no browser and makes no network calls.
Use `--tool /path/to/research-corpus` when running the example outside this
checkout. Do not use this fixture as research evidence.
