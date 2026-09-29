# 🧰 Tools

Reusable, machine-agnostic utilities graduate here from `~/Scratch` once they
are useful beyond a single task. Each tool should be documented and independently
runnable; transient experiments stay out of this directory.

## `agency-decide`

Uses Jev as Agency's System One model: fast recognition from a small input,
with a fixed answer space. Code handles exact rules; the reasoning agent handles
planning, investigation, and ambiguity. Versioned contracts cover shared
classifications and skill-owned decisions, including supplied assessment bands,
evidence screening, comment purpose, observed cost patterns, and change impact.

```sh
agency-decide setup --interactive
agency-decide doctor
agency-decide profiles --profile assess/criterion
printf '%s\n' '{"task":"Check that the README commands execute as documented."}' |
  agency-decide classify --profile skill --input - --dry-run
```

The full installer imports the concealed **API Key** field from the single
1Password item titled **OpenRouter**. Initial setup allows desktop authorization;
each vault operation has a 30-second timeout. It writes the key to
`${XDG_CONFIG_HOME:-~/.config}/agency/openrouter.json` as `{"api_key":"…"}`,
with mode `0600` in a directory created with mode `0700`, outside the repository.
The write is atomic. Setup never changes the vault or logs the key. Empty keys
and ambiguous matches leave configuration untouched and report the problem.

CLI and MCP classifications read this local file, with no 1Password dependency
at runtime or on subsequent boots. An `OPENROUTER_API_KEY` process-environment
override takes precedence. There is no session cache or background credential
service. Existing local credentials are preserved when setup or the installer
reruns. Setup checks the local file even when an environment override is present;
a temporary environment key does not replace the persistent import.
An older reference-only configuration is imported in place during setup; runtime
reports that setup is needed instead of resolving a legacy reference itself.

`setup --interactive` imports a missing key or old reference with desktop
authorization. Plain `setup` disables desktop prompts for automation;
`setup --dry-run` makes no changes or vault calls. To reimport a rotated vault
key, remove the local credential file and rerun setup. Updating the vault alone
does not change the imported copy.

`doctor` checks local configuration without contacting either service.
`credential_verified` means valid local syntax, not successful provider
authentication. Keep the credential file private; never put its contents in
arguments, prompts, repository files, or troubleshooting output.

Remove `--dry-run` to send the displayed request to OpenRouter's dedicated
`POST /api/alpha/decisions` endpoint using `typesafe/jev-1.13`. Input may be UTF-8
text or a JSON object/array/string, from a file or standard input. The result
contains a label, full probability distribution, optional confidence, actual
model ID, rubric version and hash, usage, and request latency. Missing confidence stays
null. See [`decision-routing`](../Skills/decision-routing/SKILL.md) for the state
shapes and how to use the outputs.

`agency_decisions.py` is the shared implementation behind the CLI and MCP
adapter. It stays beside the executable when installed by symlink. Requests use
one fixed HTTPS endpoint, refuse redirects, disable environment proxies, bound
input and response sizes, and do not retry automatically. The CLI uses a
10-second socket timeout, not a total elapsed deadline. Invalid results remain
errors; CLI failures exit 2 with JSON diagnostics on stderr. No classification
executes an action or supplies permission.

For independent judgments, use `agency-decide classify-batch --input FILE`
(or `--input -`). A manifest contains `items` with unique `id`, `profile`, and
`state` values. Defaults are 10 unique calls, four workers, and a 30-second
batch deadline. Optional `max_calls`, `concurrency`, and `deadline_seconds`
allow at most 32 calls, four workers, and 60 seconds. Up to 32 items and 256 KiB
are accepted per batch; the minimum deadline is five seconds and each state is
limited to 64 KiB. Item IDs contain letters, digits, periods, underscores, or
hyphens, at most 80 characters. Identical requests reuse one result within the batch.
Credentials resolve once and stay in process memory and worker environments.
Each classification runs in a subprocess that is killed and reaped on timeout.

Results retain input order and per-item errors. A partial batch exits 1 and
preserves successful rows; invalid manifests exit 2 before credential access.
`--dry-run` validates the batch and displays requests without vault or provider
access. Call and input limits bound usage, not a guaranteed dollar charge.
Usage counts successful unique calls; `usage_complete` is false after errors,
on dry runs, or when any successful call omits cost. Cost remains null when a
complete amount is unavailable; a known zero cost is complete. Budget across
batches in the caller; the runtime stores no automatic history or cache.

`agency-decide evaluate --input FILE` runs a batch whose items also contain
`expected` labels. It reports agreement, errors, and a confusion table; all
cases remain in the denominator. Mismatches or provider failures exit 1, and
invalid or empty sets exit 2. `Tests/fixtures/decisions.json` contains synthetic
contract checks, not human-labelled calibration data. Select at most 32 cases
per evaluation manifest and budget calls across batches; running evaluation uses
hosted requests. Keep private examples and evaluation outputs outside the repository.

Shared contracts live in `Skills/decision-routing/decisions.json`; skill-owned
contracts live beside the owning `SKILL.md` and use names such as
`assess/criterion`. The runtime discovers these trusted repository definitions
through the same installed symlink. It validates required evidence fields and
preserves supplied band descriptors. See the routing skill for complete state
shapes and skill-specific use.

## `agency-decision-usage`

Shows per-turn Jev usage from the local CLI/MCP result receipts:

```text
Jev: 5 decisions · 1 error · 2 reused
```

The installer adds `UserPromptSubmit`, `PostToolUse`, and `Stop` hooks to Codex
and Claude Code while preserving other hooks. They display a short turn-end
message through the supported `systemMessage` interface; they do not modify the
native `Worked for …` line or replace a configured status line. Codex also reports
on interruption. Claude observes failed tool calls through `PostToolUseFailure`.
Review and trust updated Codex hooks when the client requests it; installation
does not bypass hook trust. Restart clients to load updated configuration and
MCP profile schemas.

Pi's `agency-decisions.ts` extension shows the same counter in a footer status
item. It observes CLI results from bash and resets at the next user run after
`agent_settled`, so intermediate model turns and automatic retries keep their
count. It does not add messages to the model conversation or record a transcript.

A decision is a completed, non-reused classification result. `unsure` still
counts as a completed decision. Errors are separate unique failed items or
failed single requests, including validation/configuration failures; they are
not necessarily provider calls. Dry runs, profile reads, and doctor checks
contribute zero. Batch worker receipts are removed from aggregate output so
inspecting an embedded result cannot count it again. Duplicate observations of
the same receipt count once, and receipts older than the turn are ignored.

Counters use session and turn identities rather than the working directory.
Claude subagent events are excluded; Codex events for other turn IDs are ignored.
The display covers results observed by this agent's hooks, not an aggregate of
all delegated workers. Keep `_agency_decisions` metadata in CLI/MCP output.
Redirecting or filtering output can hide results. Known missing or truncated
receipts show `count incomplete`; missing turn starts show `usage unavailable`.
An unreadable event conservatively marks active turns for that client incomplete.
Disabled hooks or unsupported client transports cannot provide a complete count.

Only counts, timestamps, hashed session/turn identities, and opaque receipt IDs
are stored, under `$XDG_RUNTIME_DIR/agency-decision-usage` or a private
`agency-decision-usage-UID` directory in the system temporary directory. Each
session retains only its latest turn with at most 2,048 receipt IDs. Files are
mode `0600` inside a mode `0700` directory, with locking and symlink refusal.
No prompts, tool inputs, decisions, credentials, or transcripts are retained or
uploaded by the counter. It makes no model calls and never blocks a turn.

Client interfaces: [Codex hooks](https://developers.openai.com/codex/hooks),
[Claude Code hooks](https://code.claude.com/docs/en/hooks), and Pi's installed
`docs/extensions.md` (`agent_start`, `agent_settled`, `tool_result`, `setStatus`).

## `agency-decide-mcp`

Exposes `profiles`, `classify`, and `classify_batch` through newline-delimited
stdio MCP, using the
same implementation and credentials as the CLI. The installer registers
`agency-decide` for Codex and Claude Code while preserving existing registrations.
Restart the client to discover newly registered tools. Pi and shell workflows
can use `agency-decide` directly.

Single classification workers have a hard 10-second deadline. Batch workers
share the batch deadline and each have at most 10 seconds; expired workers are
killed and reaped. Read one contract with the optional `profile` argument to
`profiles`, keeping unrelated rubrics out of agent context. Cancellation notifications do not interrupt an active request before
that deadline. Provider failures are tool errors, never manufactured predictions.
Only the supplied state and selected rubric are sent to OpenRouter; private
profiles and transcript history are not automatically included.

## `agency-ui`

Renders phased terminal work with a soft pink-and-purple palette and a bounded
spinner that settles into one final result line. `agency-ui run --capture`
stores child output in temporary files, discards it on success, and replays it
on failure while preserving the command's exit status. Plain passthrough mode
keeps prompts and confirmations interactive.

Human TTYs receive animation. Redirected output, CI, and `TERM=dumb` remain
static; `AGENCY_UI=plain`, `AGENCY_UI=quiet`, `AGENCY_MOTION=reduce`, and
`NO_COLOR` provide explicit accessibility and automation controls. Status and
animation use stderr, leaving child stdout available for data and composition.

## `git-get`

Accepts GitHub `owner/repository` shorthand or a complete Git URL. It clones
into `${CODE_ROOT:-~/Code}/repository`, or runs a safe fast-forward-only pull
when the matching checkout already exists. Fish exposes it as `gcl`; `gpl`
pulls the current checkout when called without an argument and otherwise has
the same locate-or-clone behaviour. Both paths use `agency-ui` to collapse Git
transport chatter into named fetch, recovery, switch, and fast-forward phases.

## `long-processes`

Opens a fuzzy, multi-select inspector for processes owned by the current user
that have been running for at least two hours. It shows process details before
asking to send `TERM`, waits briefly, then offers `KILL` only for survivors.
Use `--age 30m` (or another `s`, `m`, `h`, or `d` duration) to change the age
threshold. Fish also exposes the friendlier `oldtasks` abbreviation.

## `sandbox`

On Linux, runs a command with Bubblewrap using a private process tree, scrubbed
environment, and an allowlisted filesystem. The current directory is the only
writable host path by default, and networking starts disabled. `--internet`
adds rootless outbound networking through Pasta; `--publish tcp:3000` or
`--publish udp:5353` exposes only the named listening ports on host loopback.

Use `--ro PATH` and `--rw PATH` to make more host paths visible, `--env NAME`
to forward a specific environment variable, and `--dry-run` to inspect the
exact launch command. Run `sandbox --help` for examples and the full interface.
It shares the host kernel, so use a VM when genuinely hostile code needs a
separate kernel boundary.

On macOS, the same command delegates to `sandbox-macos`, using the pinned
Anthropic Sandbox Runtime and Apple's native Seatbelt. Default reads cover
system/runtime paths and the declared workspace; other home files are denied.
The environment is scrubbed and each run gets a temporary HOME and TMPDIR,
removed on normal completion. Extra inherited descriptors are closed.
`--workspace-ro`, `--ro`, `--rw`, `--env`, and `--set-env` retain their purpose.
`--dry-run` prints the policy as JSON without executing a command or creating
temporary state. Environment values are omitted from that preview.

Use `--allow-domain HOST` (repeatable, optionally `HOST:PORT`) for macOS network
access through HTTP/SOCKS proxies. `--internet` requires these explicit grants.
`--publish` and `--name` need Linux namespaces and are rejected with a VM hint.
Programs ignoring proxies cannot connect. Native isolation has no private PID,
hostname, or mount namespace. SRT protects configuration filenames such as
`.gitconfig` even inside a writable tree; glob-shaped paths are rejected to avoid
turning a literal grant into a pattern. HOME and temporary-directory variables
are managed by the adapter and cannot be overridden. Never fall back to running
unsandboxed when this backend fails. Apple marks `sandbox-exec` deprecated.
Forwarded variables are applied only to the payload after isolation, not to the
Node or shell launchers. A sandboxed supervisor preserves signal termination as
a nonzero exit status instead of relying on SRT's child-signal status mapping.

`Tests/test_sandbox_macos.py` checks argument and policy handling on either OS.
`python -m unittest discover -s Tests/macos -v` verifies actual Seatbelt read,
write, environment, descriptor, and network enforcement on macOS. That suite
requires Node, the pinned `srt`, and `sandbox-exec`; it is a separate macOS CI
step and fails if run without its native prerequisites.
`Tests/test_sandbox_linux.py` checks Linux launcher argv and exit propagation
with fixtures on either host (Bash 4+ required). The separate Linux CI command
`python -m unittest discover -s Tests/linux -v` exercises real Bubblewrap and
Pasta, including preload environment isolation and signal statuses.
Ubuntu CI loads `.github/ci/sandbox-userns.apparmor` to grant namespace creation
to `/usr/bin/bwrap` and `/usr/bin/pasta`, following Ubuntu's
[application-specific user namespace policy](https://discourse.ubuntu.com/t/ubuntu-24-04-lts-noble-numbat-release-notes/39890).
The tests remain unprivileged; the workflow does not disable AppArmor or its
system-wide user namespace restriction. These CI profiles are not installed on
workstations.

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

## `agent-context`

Audits the instruction files Codex would select for a working directory without
loading repository code or changing files. It follows configured root markers,
global and project override precedence, trusted project configuration, trust
state, fallback names, and the combined project-byte budget. The report
pinpoints the first truncated byte and line, lists Markdown headings hidden
beyond the cutoff, and detects identical selected documents.
Use `agent-context codex PATH`, add `--json` for stable structured output, or
`--check` to fail only when project guidance is truncated. Configuration output
is restricted to instruction-discovery keys.

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

## `resource-bench`

Runs declarative, CPU-pinned, interleaved baseline/candidate comparisons with a
claim-matched primary metric and optional context metrics. It collects `perf`
events, sampled process-tree RSS/PSS, and structured JSON metrics emitted by a
workload or profiler for allocation, copying, I/O, transfers, latency, or
throughput. It verifies stable output evidence and retains raw samples, units,
methods, dispersion, absolute and relative deltas, and reproducibility metadata.
Use `resource-bench --help`; `instruction-bench` remains a compatibility entry
point that preserves its instruction-only result schema.

## `document-inspect`

Renders a PDF into numbered page images, extracts layout-preserving text,
builds a contact sheet, and writes a hashed JSON manifest. Optional local OCR
supports image-only documents. It refuses a populated output directory so a
new inspection cannot silently mix with stale pages.

## `docs-exec`

Extracts Markdown code fences by their `title=` values and executes declarative
TOML cases in isolated temporary directories. Cases default to a 300-second
deadline and 1 MiB per-stream output cap; `timeout_seconds` and
`max_output_bytes` may set tighter bounds. Each result retains the command,
extracted-file hashes, bounded output, truncation state, and status. The
`docs-verification` skill defines how to rehearse reader-visible instructions
safely.

## `evidence-review`

Normalises CSV, JSON, and JSONL evidence exports into a stable screening ledger,
marks exact DOI or normalised-title duplicates, and audits decisions, exclusion
reasons, identifiers, and duplicate links. It never makes substantive screening
judgements.

## `perf-diagnose`

Captures `perf stat` counters or `perf record` profiles with machine metadata
and a machine-readable manifest. A single diagnostic run locates work; use
`resource-bench` for repeated equivalent comparisons supporting optimisation
claims.

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
accelerators. NVIDIA model, VRAM, and CUDA-core details are cached until the
device or query tools change. Codex and Claude Code consume the plain-text output
through session-start hooks so laptop sessions prefer bounded validation and ask
before sustained high-load work. Use `system-context --json` for diagnostics or
other tooling, and `system-context --refresh` to bypass the accelerator cache.

## `sudo-gui`

On Linux, gives an explicitly approved sudo operation a one-attempt KDE askpass helper.
Direct sudo commands authenticate and execute in the same sudo invocation;
script workflows receive a private PATH-scoped sudo proxy. Sudo reuses valid
authorization or command-specific `NOPASSWD` rules without a dialog. The helper
refuses to prompt during an active PAM lockout and blocks sudo password retries.
Passwords remain in the dialog process memory only and are not written to
files, arguments, environment variables, or captured output.

On macOS, `sudo-gui --prompt "Reason" -- sudo COMMAND` requests authorization
through the system administrator dialog. A fixed AppleScript receives the
prompt and shell-quoted argv as data, never password arguments. Cancellation
returns 130 with no retry; command failures retain their reported exit status.
macOS may replace the custom prompt with generic system text.
`--dry-run` prints a preview without authorizing anything.

For `sudo-gui -- ./workflow.sh`, the script runs as the normal user and only
PATH-resolved sudo commands are redirected. A failed or cancelled request
blocks later proxy calls even if the workflow ignores the failure. Absolute
sudo paths bypass the proxy. No reusable sudo timestamp is created, and later
commands may need another OS authorization request. The native API buffers text
output and supplies no interactive stdin or TTY. Sudo options are unsupported;
use a visible terminal for interactive or identity-changing commands.

This does not change PAM or guarantee Touch ID. The macOS authentication
dialog owns password entry; Touch ID for ordinary sudo is a separate
`pam_tid.so` configuration. The native adapter and argument/cancellation tests
live in `sudo-gui-macos` and `Tests/test_sudo_gui_macos.py`.

## `web-research`

Runs local web search, JavaScript rendering, main-content extraction, link
mapping, scoped crawling, and SQLite full-text indexing through the installed
Firefox and Bun. Persistent named profiles support user-completed login and
challenge flows without exporting cookies. Crawls are same-origin,
single-worker, robots-aware, and skip common state-changing links. The global
`web-research` skill defines source handling, single-worker pacing, and
interactive-page boundaries.

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
DuckDuckGo, Brave, and Bing. Federated mode queries all three in that process,
deduplicates destination URLs, and fuses their rankings. A challenged provider
is skipped without blind retries or another browser launch. Page access checks
distinguish visible login walls and challenge controls from incidental prose,
so ordinary content titled “Just a Moment” is not treated as a CAPTCHA. Login
prompts layered over substantial public content are labeled as soft gates and
extracted; actual authentication redirects and dominant challenges remain hard
stops.

One-shot searches without `--profile` use disposable profiles, avoiding
contention with unrelated named research sessions. Unknown search options fail
before Firefox starts. Textual `site:` terms remain provider hints;
`--domain HOSTNAME` strictly filters cleaned destination hosts and subdomains.
`--exclude-domain HOSTNAME` removes a host and its subdomains after inclusion
filtering.

`web-research-mcp` exposes the same stack to Codex and Claude Code through one
bounded `run` tool with `search_query`, `open`, `find`, `click`, `local_query`,
and `replay` operations. URL opens preflight the extracted-text index, follow
requested and canonical aliases, reuse fresh or immutable entries, and render
then re-index stale pages. Stable in-session references keep page bodies out of
search results, and `response_length` bounds model-facing text. Open and find
records include citation-ready URLs, freshness metadata, content hashes, and
exact evidence lines in a deduplicated source ledger. Pi's installed
`agency_web` extension speaks to the same server and retains those references
for the life of its session.

Large MCP opens are divided into bounded four-page backend batches. A failed or
login-gated page returns a typed per-page error while successful siblings remain
available and citable. Extracted job cards are returned as structured records
with title, URL, company, location, summary, visible posting age, and a normalized
publication date when the page supplies enough evidence.

If a backend batch is malformed, the MCP retries that bounded group as individual
opens so recoverable pages remain available. Thin interstitials with a recognized
challenge title are classified as access failures even when they expose no visible
challenge control. A blocked search reference retains its ranking metadata as a
typed `index_snapshot` with `page_verified: false`; snapshots remain auditable
discovery evidence but do not become page-verified citations.

Automated browser and direct-HTTP traffic pass through a per-run validating
proxy that resolves and pins each destination address and blocks private,
link-local, and other non-public ranges at every request. `--allow-private` is
an explicit opt-in for authorised local or intranet work. Multi-item MCP search,
open, find, and click operations reuse one browser batch instead of launching a
browser per item.

An entirely empty document gets one bounded 500-millisecond recovery sample.
If it remains empty, extraction returns a clear incomplete-content error rather
than a DOM exception or a successful blank record.
Navigation timeouts retain usable DOM and bounded network evidence as an
explicit partial result, including the failed stage and attempt count. Bounded
retries are opt-in, and partial pages never enter the index.

Dynamic pages settle against observable URL, title, text, height, link, and
open-shadow-root state after interactive readiness. Navigation, settling,
bounded lazy-feed scrolling, content size, and link count all have explicit
budgets, with truncation reported in JSON. Each bounded scroll is captured and
deduplicated so virtualized feeds retain earlier evidence. Extraction also
merges bounded page metadata and sanitized JSON-LD, recording access state,
sources, and capture count. Job listings and job-board result pages use a daily
refresh window; relative posting ages are resolved against the recorded live
retrieval time and retained with the original visible age.

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
provider or origin circuits after real challenges. A strict health sidecar
persists outcomes, failure counts, latency, cooldowns, and bounded
`Retry-After` values across resume. Search checkpoints feed directly into page
extraction, and successful pages can be indexed in the same run. Page batches
round-robin origins and apply a separate per-origin delay so one difficult site
does not monopolize the request sequence. When a search checkpoint already
contains evidence for a URL that later hard-gates, the page checkpoint retains
it as a labeled partial result rather than losing it or claiming it was
extracted from the source. Rate-limit pages also open the origin circuit
instead of entering the index.

`--append-input` supports incremental query and URL lists only when the
previously accepted file remains an unchanged byte prefix. Ordinary resume
still requires an exact fingerprint and reports concrete recovery choices when
the input or profile identity changes.

JSON extraction reports field-level provenance and named quality observations
for rendered DOM, metadata, JSON-LD, frames, same-origin network JSON, and
partial search snippets. `--capture` opt-in stores only the sanitized bounded
extraction input as a SHA-256-addressed object plus a capture manifest.
`web-research replay CAPTURE_ID --json` verifies and re-fuses it without
Firefox or network access. `capture-gc --max-manifests N` previews retention;
add `--apply` to delete old manifests and objects no live manifest references.

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
