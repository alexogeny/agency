# Research corpus implementation contract

The corpus is portable sanitized evidence. Browser profiles, credentials, the
shared page cache and generated SQLite databases stay outside it.

## Shared interfaces

`Tools/research-corpus` is a Python standard-library CLI. Its core lives in
`Tools/research_corpus_core.py`; index, audit and screening services live in
`Tools/research_corpus_services.py`. Both CLI and MCP dispatch to this CLI/core.
Imports resolve relative to the real tool path, including installed symlinks.

The core exports `CorpusError(code, message, stage='', retriable=False,
next_action='')`, `read_manifest(root) -> dict`,
`committed_records(root) -> list[dict]`, `load_record(root, entry) -> dict`,
`safe_path(root, relative) -> Path`, `canonical_bytes(value) -> bytes`,
`sha256(bytes) -> str`, `atomic_json(path, value)` and
`corpus_lock(root)` (context manager). Paths reject traversal and symlink
components. JSON serialization is sorted UTF-8 with one trailing newline.

`manifest.json` has schema `agency/research-corpus/1`, `corpus_id`, `protocol`,
`active_run`, `runs` (a list of run dictionaries with `run_id`, recipe and
software references), `sources` (stable source ID to URL/aliases), and `records`.
Each committed record entry has `record_id`, `kind` (`discovery`, `source`,
`protocol`, `screening` or `synthesis`),
`run_id`, nullable `source_id`, `paths` (`json`, `text`, `markdown`, all relative),
and `hashes` (relative artifact path to SHA-256). A published record bundle is
immutable; the manifest references it only after all siblings are durable.
Local UTF-8 artifacts enter through `retain CORPUS FILE --kind KIND
--operation-id ID`, using the same immutable sanitized commit pipeline.

Record JSON uses schema `agency/research-record/1`, `record_id`, `kind`, `run_id`,
`source_id`, `created_at`, `title`, `url`, `payload` (sanitized backend result),
`text`, `markdown`, `retrieval`, `extraction`, `bibliography` and `process`.
`extraction.coverage` is conservative (`unknown` unless supported), with
truncated fields and limitations. Access, coverage, delivery, screening and
process states remain independent. Bibliography preserves raw fields,
field provenance, nullable verified authors/year, and verification status.
Missing historical evidence metadata remains unknown.

Services export `dispatch(args) -> dict` and `add_parsers(subparsers)`.
Subcommands are `index build CORPUS --db PATH [--manifest PATH]`,
`index query CORPUS EXPRESSION --db PATH [--prefix PATH --kind KIND --limit N]`,
`audit CORPUS`, `compare CORPUS --old RUN --new RUN`, and
`screening reconcile CORPUS --ledger OLD --output NEW`.
Services never edit the corpus manifest/core files. Derived index/ledger
outputs use separate explicit paths, with no overwrite of human decisions.

## Browser boundary

The default backend is the adjacent `web-research` executable. Tests may inject
`RESEARCH_CORPUS_WEB_COMMAND` as an executable path, never a shell expression.
Search uses existing `search QUERY --strategy ... --limit ... --json --profile`.
Source reads use `scrape URL --format json --preflight --profile ...`.
Live reruns use `--index` instead of `--preflight`, forcing current retrieval
while refreshing the cache. Each backend has an owned process group supervised
through a lifetime pipe; deadline, CLI termination, or MCP termination closes
the pipe and stops its descendants. Successful backend exit also clears leftover
descendants while preserving its exit status.
Strict index export uses `scrape URL --format json --from-index` and never
launches a browser or creates/migrates a database. Missing/stale/legacy states
are explicit. Profile operations use
`web-research profile-create|profile-close|profile-cleanup` with JSON requests
on stdin and JSON results. The profile
request schema is `agency/owned-profile-request/1`. Creation receives
`owner_execution`, `purpose`, `mode` and
`authorization: {reference, owner_execution, disposable: true}`. It returns a
handle with schema `agency/owned-profile/1`, `profile`, `nonce`,
`owner_execution`, `canonical_path`, `created_at`, `metadata_id`, `mode`,
`purpose` and `authorization`. Close and cleanup receive
`{handle, owner_execution, authorization}`. Private handle/path material stays
outside ordinary corpus source records. An authorization reference records
existing scope; supplying a string does not grant permission.
Cleanup checkpoints the exact identity in lifecycle metadata before deleting
the directory. A retry may remove remaining metadata only when the checkpoint
matches and the directory is still absent; replacement directories are refused.

MCP adds a separate `corpus` tool taking `{command: [string, ...]}` and routes
it without a shell to adjacent `research-corpus`; ordinary web operations stay
compatible. The CLI emits bounded JSON results and stable error objects
(`code`, `stage`, `retriable`, `next_action`, partial artifact IDs when present).
Private lifecycle plans use the CLI's actual argument parser, including accepted
option order and abbreviations. Handle enumeration and planning remain internal
IPC and cannot be invoked through the public MCP command array.

## Reproduction and completion

A recipe records exact/effective ordered queries, provider strategy/order,
filters, absolute date windows, budgets, locale/access context, actual attempts
and omissions, source selections and stopping decisions. Unsupported provider
controls are labelled unsupported, never silently accepted. Record actual
tool/code hashes and runtime versions, including modified source. Archive the
minimal sanitized offline processing code with dependency/toolchain identity.
Do not require an old browser for offline reproduction.

Offline reproduction verifies hashes and rebuilds deterministic exports from
retained inputs using the archived processing code without network, browser,
old cache or original paths. Index verification compares canonical document
records, not database file bytes. Live rerun creates a new linked run, preserves
the original window unless explicitly changed and reports changed access,
rankings, bodies and software. It never promises identical future web results.

Workers write focused regression tests first and retain the intended failing
result. The parent reviews all changes and repairs integration. Completion
requires a relocated offline workflow plus crash/resume, cross-client, privacy,
index-generation, screening-preservation and owned-cleanup checks. No worker
may commit, push, broaden research, or operate existing user browser profiles.
