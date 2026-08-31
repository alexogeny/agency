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
scratch directories, rejects overlapping hierarchical scope claims, tracks
owned heartbeats and stage notes, retains task history, bounds repository-scoped
boards, and records terminal handoffs without modifying Git. Existing ledgers
are backed up and upgraded in place when new coordination fields are needed.
Use `agent-work --help` for the task lifecycle and JSON interface.

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
