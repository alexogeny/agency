# 🧰 Tools

Reusable, machine-agnostic utilities graduate here from `~/Scratch` once they
are useful beyond a single task. Each tool should be documented and independently
runnable; transient experiments stay out of this directory.

## `git-get`

Accepts GitHub `owner/repository` shorthand or a complete Git URL. It clones
into `${CODE_ROOT:-~/Code}/repository`, or runs a safe fast-forward-only pull
when the matching checkout already exists. Fish exposes it as `gcl`; `gpl`
pulls the current checkout when called without an argument and otherwise has
the same locate-or-clone behaviour.

## `long-processes`

Opens a fuzzy, multi-select inspector for processes owned by the current user
that have been running for at least two hours. It shows process details before
asking to send `TERM`, waits briefly, then offers `KILL` only for survivors.
Use `--age 30m` (or another `s`, `m`, `h`, or `d` duration) to change the age
threshold. Fish also exposes the friendlier `oldtasks` abbreviation.

## `sandbox`

Runs a command with Bubblewrap using a private process tree, scrubbed
environment, and an allowlisted filesystem. The current directory is the only
writable host path by default, and networking starts disabled. `--internet`
adds rootless outbound networking through Pasta; `--publish tcp:3000` or
`--publish udp:5353` exposes only the named listening ports on host loopback.

Use `--ro PATH` and `--rw PATH` to make more host paths visible, `--env NAME`
to forward a specific environment variable, and `--dry-run` to inspect the
exact launch command. Run `sandbox --help` for examples and the full interface.
It shares the host kernel, so use a VM when genuinely hostile code needs a
separate kernel boundary.

Bubblewrap and Pasta deliberately cover this use case without Firejail. Keeping
one isolation model makes profiles easier to inspect and avoids depending on
Firejail's setuid mode.

## `agent-work`

Coordinates parallel work across a repository and its Git worktrees with an
atomic SQLite ledger under `~/.local/state/agent-work`. It creates unique
scratch directories, rejects overlapping hierarchical write-scope claims, tracks
owned heartbeats and stage notes, retains task history, bounds repository-scoped
boards, and records terminal handoffs without modifying Git. Existing ledgers
are backed up and upgraded in place when new coordination fields are needed.
Claims reserve writes only: reading, searching, reviewing, or otherwise
inspecting a claimed path remains allowed. `inspect TASK_ID` reads one exact
record; `inspect` without an ID opens or emits the active board. Use
`agent-work --help` for the task lifecycle and JSON interface.

## `repository-setup`

Renders Agency's Python, JavaScript, TypeScript, Go, and Rust repository
profiles into a reviewable, hashed bundle. The bundle contains CI, optional
Pages and trusted-publishing workflows, issue and pull-request templates, plus
a separate default-branch ruleset payload. `apply --dry-run` reports every
planned action and risk without writing. Divergent regular files use an
explicit `abort`, `keep`, or `replace` policy; symlinks and non-regular files
are always blocked. The tool can restrict output to selected components and
never mutates GitHub settings; the `setup-repository` skill owns the live
audit, human-facing preview, authorisation, ordering, and read-back workflow.

## `instruction-bench`

Runs declarative, CPU-pinned, interleaved baseline/candidate comparisons with
`perf stat`, measuring retired userspace instructions only. It verifies stable
output evidence and retains raw counts plus reproducibility metadata in JSON.
Use `instruction-bench --help`; the global `benchmark` skill contains the TOML
format and evidence rules.

## `document-inspect`

Renders a PDF into numbered page images, extracts layout-preserving text,
builds a contact sheet, and writes a hashed JSON manifest. Optional local OCR
supports image-only documents. It refuses a populated output directory so a
new inspection cannot silently mix with stale pages.

## `docs-exec`

Extracts Markdown code fences by their `title=` values and executes declarative
TOML cases in isolated temporary directories. Each result retains the command,
extracted-file hashes, stdout, stderr, and status. The `docs-verification` skill
defines how to rehearse reader-visible instructions safely.

## `evidence-review`

Normalises CSV, JSON, and JSONL evidence exports into a stable screening ledger,
marks exact DOI or normalised-title duplicates, and audits decisions, exclusion
reasons, identifiers, and duplicate links. It never makes substantive screening
judgements.

## `perf-diagnose`

Captures `perf stat` counters or `perf record` profiles with machine metadata
and a machine-readable manifest. Its results are explicitly diagnostic; use
`instruction-bench` for evidence supporting optimisation claims.

## `comment-audit`

Scans common source and configuration formats for empty comments, decorative
section comments, and historical narration. Python comments and docstrings use
the tokenizer and AST. Findings are review prompts and no files are changed.

## `repo-map`

Builds a deterministic static JSON map from Git-visible files without importing
or executing repository code. It records content hashes, manifests, commands,
entrypoints, languages, public Python symbols, imports, tests, and applicable
agent guidance. Content-keyed parsing keeps repeat runs fast while identical
trees produce identical output.

## `report-build`

Creates, validates, and renders modular report source using YAML- or
TOML-frontmatter Markdown and structured reference records. The uv Python tool
uses the standard library and locally installed SIL Open Font License Computer
Modern Unicode fonts. The bootstrap installs and verifies the four required
faces without installing TeX. It maps
structured or Pandoc-style citation keys to linked bibliography entries,
enforces configured word limits, and validates figures, captioned tables,
labels, cross-references and placeholders. It emits audit-friendly text,
monochrome print-ready HTML, inspectable TeX, and a PDF from its built-in
writer. The global `report-writing` and `report-generation` skills
separate prose craft from source assembly and final inspection.

## `system-context`

Prints a compact, read-only summary of the local device class, AC or battery
state, battery percentage, CPU and memory capacity, and visible NVIDIA or AMD
KFD device nodes. Codex and Claude Code consume its plain-text output through
session-start hooks so laptop sessions prefer bounded validation and ask before
sustained high-load work. Use `system-context --json` for diagnostics or other
tooling.

## `sudo-gui`

Opens one KDE password dialog for an explicitly approved sudo operation, makes
one authentication attempt, and runs the requested workflow in the same
process context so sudo's cached authorization remains usable. It refuses to
prompt during an active PAM lockout and never retries automatically. Passwords
remain in process memory only and are not written to files, arguments,
environment variables, or output.

## `web-research`

Runs local web search, JavaScript rendering, main-content extraction, link
mapping, scoped crawling, and SQLite full-text indexing through the installed
Firefox and Bun. Persistent named profiles support user-completed login and
challenge flows without exporting cookies. Crawls are same-origin,
single-worker, robots-aware, and skip common state-changing links. The global
`web-research` skill defines source handling, concurrency, and interactive-page
boundaries.

`web-research retrieve URL... --json` provides a cheaper direct-HTTP evidence
path before browser rendering is needed. It returns one typed result per URL,
including the final URL, redirect chain, status, content type, byte count,
SHA-256 digest, live retrieval time, provider, safety decision, and exact
failure code. Redirect hops are checked independently, private networks require
`--allow-private`, and one failure does not discard successful batch results.

Automated Firefox work is headless by default, so normal searches, extraction,
crawls, snapshots, and downloads do not open over the desktop or steal keyboard
focus. The explicit `browser` command remains attached for user-completed login
and releases its profile lock when the window closes.

Automatic search reuses one Firefox process while falling back through
DuckDuckGo, Brave, and Bing. A challenged provider is skipped without blind
retries or another browser launch. Page access checks distinguish visible login
walls and challenge controls from incidental prose, so ordinary content titled
“Just a Moment” is not treated as a CAPTCHA. Login prompts layered over
substantial public content are labeled as soft gates and extracted; actual
authentication redirects and dominant challenges remain hard stops.

An entirely empty document gets one bounded 500-millisecond recovery sample.
If it remains empty, extraction returns a clear incomplete-content error rather
than a DOM exception or a successful blank record.

Dynamic pages settle against observable URL, title, text, height, link, and
open-shadow-root state after interactive readiness. Navigation, settling,
bounded lazy-feed scrolling, content size, and link count all have explicit
budgets, with truncation reported in JSON. Each bounded scroll is captured and
deduplicated so virtualized feeds retain earlier evidence. Extraction also
merges bounded page metadata and sanitized JSON-LD, recording access state,
sources, and capture count.

Optional semantic interaction steps dismiss narrowly recognized overlays and
activate expand, read-more, or load-more controls while recording whether each
action changed evidence. Scrolling prefers substantive feed/list containers.
Optional Firefox BiDi response collection adds bounded same-origin JSON/API
evidence without returning headers, cookies, or request bodies.

`--ephemeral-profile` gives unauthenticated automated work a clean, randomly
suffixed run-scoped profile and deletes it after Firefox exits. It uses the
requested profile name only as a label and never copies the user's ordinary
Firefox identity or session state. Fresh profiles are intended for isolation;
a stable named profile is usually a better fit for a larger research run.

`--profile-template current` may seed either a stable named profile or an
ephemeral one with a fixed allowlist of validated, non-secret language, theme,
browser-chrome, zoom, colour, and autoplay preferences from Firefox's
`prefs.js`. It ignores identifiers, extensions, authentication and browsing
state, network settings, and UA overrides. Automated contexts also normalize
Firefox's automation-only `navigator.webdriver` value before navigation while
leaving browser and system-derived signals intact.

Resolved URLs, canonical URLs, and discovered links are sanitized before
output or indexing. URL credentials, fragments, and token-, signature-,
session-, or challenge-shaped query parameters are removed. Empty interactive
code nodes are also omitted from Markdown instead of producing delimiter noise.

`search-batch` and `scrape-batch` provide append-only NDJSON checkpoints for
large research. They validate resume state, avoid launching Firefox for fully
completed inputs, reuse a single browser, apply deterministic pacing, and open
provider or origin circuits after real challenges. Search checkpoints feed
directly into page extraction, and successful pages can be indexed in the same
run. Page batches round-robin origins and apply a separate per-origin delay so
one difficult site does not monopolize the request sequence. When a search
checkpoint already contains evidence for a URL that later hard-gates, the page
checkpoint retains it as a labeled partial result rather than losing it or
claiming it was extracted from the source.
Rate-limit pages also open the origin circuit instead of entering the index.

Crawls use a bounded, tracking-normalized frontier with constant-time dequeue,
per-page admission limits, query-complexity limits, one prepared SQLite writer,
and explicit incomplete-frontier reporting.

`web-research download` reuses a dedicated authenticated profile without
exporting its browser state. It confines each transfer to a temporary directory
under an explicit output root, enforces origin, time, and byte bounds, waits for
partial files to settle, validates common document and image signatures, and
atomically promotes only a verified file. Site-specific discovery stays outside
the command.

Optional frame extraction enumerates Firefox child browsing contexts instead
of mistaking an iframe shell for complete content. It extracts text from
same-origin frames, requires an explicit origin for any cross-origin frame, and
redacts frame queries while reporting skipped and failed frames.
