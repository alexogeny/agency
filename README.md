# 🎀 Agency

Agency turns a fresh CachyOS/Arch workstation into a capable, evidence-minded
home for Codex, Claude Code, and Pi. It combines a declarative bootstrap with an
operating model for reliable agent work. A compact global policy handles shared
rules. Specialised skills load when needed, and small tools leave useful
evidence behind.

The goal is not to give an agent more prose. It is to give each kind of work a
safe path from request to checked result.

## What makes it different

- **Authority stays explicit.** Agents preserve unrelated work and use the
  configured human Git identity. They never add assistant attribution, and
  touch Git or a forge only when the current ask allows that lifecycle.
- **The global policy stays small.** `Agents/AGENTS.md` has an enforced 8 KiB
  budget. General rules remain always available; detailed procedures live in
  skills and load only for matching work.
- **Checks leave evidence.** Sandboxes, task ledgers, document manifests,
  benchmark samples, and PR checks make it harder for warm caches or stale
  output to impersonate success.
- **The workstation is one system.** Bun, uv, rootless Podman, Git defaults,
  agent hooks, desktop policy, and inspection tools arrive through one
  idempotent installer.

## Hero stories

### Keep terminal work calm and legible

`agency-ui` gives interactive tools one shared visual language: soft
pink-and-purple phases, smoothly animated work, compact success summaries, and
full diagnostic output only when something fails. `gpl` and `git-get` use it to
turn noisy Git transport into a short account of what changed.

```text
◇ Updating agency
  ⠸ Fetching origin ·· 1.2s
  ✓ origin is refreshed · 1.3s
  ↳ Recovered deleted upstream through main
  ✓ main is already current · 12ms
```

Presentation stays on stderr so stdout remains usable as data. Pipes, CI, and
`TERM=dumb` receive stable plain output. Set `AGENCY_UI=plain` for an unstyled
static view, `AGENCY_UI=quiet` to retain errors only, `AGENCY_MOTION=reduce` to
disable animation, or `NO_COLOR` to remove colour without removing progress.
SSH authentication remains interactive, so presentation never competes with a
key passphrase prompt.

### Scale out without worktree choreography

Parallel agents need ownership, not automatic isolation. Agency keeps an atomic
write-claims ledger. Many agents can share one checkout when they work on
separate paths. Claims never block reads. Any agent can search, review, or learn
from a claimed file. The ledger rejects only overlapping writes.

```text
one repository
    ├── agent A claims src/parser     ─┐
    ├── agent B claims Tests/parser   ├─ work in parallel
    ├── agent C claims docs           ┘
    └── every agent may read all three scopes
```

[`coordinate`](Skills/coordinate/SKILL.md) and `agent-work` turn that ownership
model into a durable lifecycle. Each task gets unique scratch space. The local
SQLite ledger records deadlines, heartbeats, changed paths, checks, and final
handoffs.

```console
agent-work --json start --task "repair the parser" --scope src/parser \
  --timebox 45m --owner codex-root
agent-work --json heartbeat TASK_ID --agent codex-root \
  --note "focused tests passed; preparing integration"
agent-work --json status --repo "$PWD"
agent-work --json history TASK_ID
agent-work --json finish TASK_ID --status complete \
  --agent codex-root --summary "parser repair verified" \
  --changed src/parser --check "focused parser tests passed"
```

This unlocks massively parallel work. Agents do not need branch and worktree
choreography for every task. Use a worktree for a separate branch history, an
incompatible dependency state, or an isolated whole-tree build. Otherwise,
narrow write claims keep integration visible and remove most handoff overhead.

Heartbeats let work survive chat boundaries. History preserves the event
sequence. Repository status stays bounded unless `--all-repos` requests the
machine-wide board. Stale records are evidence to inspect, never permission to
kill a process or seize another task's files.

The [claim-routed messaging workshop](Workshops/claim-routing.md) sketches the
next step: deterministic requests to claim owners, client-specific delivery,
and atomic subtree yielding without forcing either task into another worktree.

### Give a workload a clean room

The [`sandbox`](Skills/sandbox/SKILL.md) skill and `sandbox` command run tests,
builds, experiments, and services inside Bubblewrap. The current workspace is
the only writable project path by default. Other home files and inherited
variables are hidden, networking is off, and the process tree is private.

```console title="sandbox-tests"
sandbox -- python3 -m unittest -v Tests.test_install_helpers
```

Grant only what a workload needs:

```console
sandbox --ro ./fixtures --rw ./results -- COMMAND...
sandbox --internet -- COMMAND...
sandbox --publish tcp:8080 -- COMMAND...
```

This is a strong boundary against accidental ambient state, not a separate
kernel. Genuinely hostile code belongs in a VM. Credentials stay outside the
sandbox unless the current task explicitly exposes a narrow input.

### Carry a dirty tree to a supervised PR

An explicit request such as:

```text
Babysit a PR with the current changes.
```

activates [`babysit-pr`](Skills/babysit-pr/SKILL.md) and authorises the normal
branch, commit, push, PR, and CI lifecycle. It does not authorise force-pushing
or merging.

```text
dirty tree
    ↓ inspect tracked, staged, and untracked work
identify repository, branch, author, base, and any live PR
    ↓
run focused and repository checks
    ↓
commit with the configured human identity → push → create or update PR
    ↓
watch checks → inspect failures → fix in new commits → resume watching
    ↓
green CI, or one concrete blocker with evidence
```

The workflow fetches and prunes before reasoning about branches, queries the
forge instead of assuming the checked-out branch owns a PR, stages only reviewed
paths, and preserves unrelated work. [`pr-writing`](Skills/pr-writing/SKILL.md)
builds the review narrative from the real diff and verified checks. No assistant
identity, co-authorship trailer, or generated-by notice enters Git or the PR.

### Make code fast for a reason

Performance work has three distinct jobs:

```text
performance-design        perf-diagnosis              benchmark
choose the shape    →     locate costly work    →     substantiate the claim
```

[`performance-design`](Skills/performance-design/SKILL.md) runs as a lightweight
preflight whenever an agent writes executable code, so expected scale, call
frequency, complexity, allocation, and expensive boundaries shape the first
implementation. Deeper performance work applies the highest-leverage cost
reduction first: skip work, do it fewer times, move less data, keep memory access
compact and sequential, batch boundaries, and only then tune instruction-level
details. Guard clauses and deterministic ordering are treated as structural
choices unless they avoid material work or improve a measured path.

[`perf-diagnosis`](Skills/perf-diagnosis/SKILL.md) and `perf-diagnose` collect
counters or profiles when the costly path is uncertain:

```console
perf-diagnose events --contains cache
perf-diagnose stat --event instructions:u --event cache-misses:u \
  --output counters.json --json -- COMMAND...
perf-diagnose record --event cycles:u --output profile.data \
  --manifest profile.json -- COMMAND...
```

Profiles suggest causes; they do not prove an improvement. The
[`benchmark`](Skills/benchmark/SKILL.md) skill and `resource-bench` compare
equivalent baseline and candidate workloads with repeated, CPU-pinned,
interleaved measurements of the resource named by the claim:

```console
resource-bench SPEC.toml --dry-run
resource-bench SPEC.toml --output results.json
```

The retained JSON includes every sample, dispersion, commands, environment,
Git state, output-equivalence evidence, collection methods, units, and absolute
and relative deltas. Retired instructions measure executed CPU work; direct
allocation, copied-byte, RSS/PSS, I/O, latency, or throughput metrics support
claims about those resources. A material resource reduction remains a real win
when instructions are flat, but it does not establish an unmeasured downstream
benefit.

### Stamp out repository plumbing

The [`setup-repository`](Skills/setup-repository/SKILL.md) skill turns Agency's
repository profiles for Python, JavaScript, TypeScript, Go, and Rust into CI,
optional Pages and trusted publishing, contributor forms, and a reviewed
GitHub ruleset. The `repository-setup` command renders a hashed bundle in
`~/Scratch`; apply can preview every action and makes conflict handling
explicit.

```console
task_scratch=/home/USER/Scratch/TASK
repository-setup render --output "$task_scratch/repository-setup" \
  --project example --repository OWNER/example \
  --profile python --runtime-version 3.14 --json
repository-setup apply "$task_scratch/repository-setup" "$PWD" \
  --dry-run --conflict abort --json
```

Python defaults to Ruff lint and format checks, ty, and pytest. JavaScript and
TypeScript use Bun, Prettier, ESLint, tests, and TypeScript checking where
applicable; Go uses gofmt, vet, and tests; Rust uses rustfmt, Clippy, and tests.
After the preview, `keep` can no-op divergent files or an explicitly authorised
`replace` can overwrite regular files. Symlinks and non-regular destinations
remain blocked under every policy.

The skill audits GitHub's live merge policy, Actions permissions, environments,
Pages, labels, security settings, and default-branch rules before changing
them. Required status checks are activated only after GitHub has observed the
workflow context, preventing a fresh ruleset from locking the default branch.

For paid remote CPU or GPU work, [`gantry`](Skills/gantry/SKILL.md) carries an
approved workload through budgeted launch, supervision, result collection, and
confirmed release.

### Turn the live web into durable evidence

[`web-research`](Skills/web-research/SKILL.md) is Agency's local research
system for the parts of the web that ordinary HTTP clients cannot reliably
read. It starts with the cheapest useful path, escalates to the installed
Firefox only when rendering or first-party browser state matters, and keeps the
result inspectable on the workstation.

```text
focused query → direct retrieval → rendered Firefox → bounded human handoff
                    ↓                    ↓                       ↓
             typed HTTP facts       extracted evidence       resumed named profile
                    └── append-only checkpoints + local full-text index ──┘
```

```console
web-research search "QUERY" --json --profile TASK
web-research search "QUERY" --strategy federated --json
web-research search "QUERY" --domain example.org --json
web-research retrieve URL... --json
web-research scrape URL --format json --preflight --profile TASK
web-research scrape URL --format json --capture --index --profile TASK
web-research replay CAPTURE_ID --json
web-research local "SEARCH TERMS" --json
```

Direct retrieval records redirects, status, content type, byte count, digest,
retrieval time, and a typed failure for each URL. Browser work adds adaptive
page settling, bounded scrolling and interaction, main-content extraction,
optional frame or same-origin JSON evidence, snapshots, link maps, and scoped
crawls. Resolved URLs and discovered links are sanitized before they reach
output or the SQLite full-text index.

Larger searches use resumable, append-only NDJSON checkpoints and persistent
provider and origin health sidecars. They reuse one browser, pace requests
deterministically, round-robin page origins, and honour challenges, rate limits,
and bounded `Retry-After` signals across restarts. Crawls remain same-origin,
single-worker, robots-aware, and bounded by depth, page count, queue size, and
per-page admission limits.

Opt-in captures store sanitized extraction inputs as deduplicated,
content-addressed objects. Offline replay verifies their schemas and hashes,
then reruns fusion without Firefox or network access. JSON fields carry
provenance, while named quality observations explain weak, conflicting, or
truncated evidence without hiding it behind a scalar score.

Strict search options prevent misspelled flags from becoming query text, and
explicit domain filters keep scoped corpora on the intended destination hosts.
Federated discovery fuses DuckDuckGo, Brave, and Bing rankings while reusing a
single Firefox process. The installed `agency-web` MCP tool gives Codex and
Claude Code compact `search_query`, `open`, `find`, and `click` operations with
stable in-session references, bounded responses, domain exclusions, automatic
freshness-aware index preflight, and opt-in capture evidence. Opened-page and
find results carry a citation source ledger, content identity, retrieval and
refresh dates, and exact displayed or matching evidence lines. Pi receives the
same contract through its installed `agency_web` extension tool.

Preflight avoids a Firefox launch when the canonical URL or one of its aliases
has fresh extracted text. Entries store a change-likelihood marker: frequently
changing subjects refresh daily, maintained and undated documents after 14
days, older published documents after 180 days, and clearly historical
published articles remain immutable. Expired pages are rendered and safely
re-indexed before their new evidence is returned.

Persistent named profiles retain ordinary first-party state for a research
task without exporting cookies or credentials. Automated work stays headless.
When a site genuinely needs a login or human challenge, the tool reports that
boundary; an explicit `browser` session lets the user complete it and then
hands the same named profile back to the research workflow. It never treats a
CAPTCHA as something to defeat unattended.

The [web-research resilience record](Workshops/web-research-resilience.md)
documents what shipped and which scale or live-testing ideas are WONTDO.

### Finish reports as inspected documents

Report prose and report production remain separate responsibilities:

```text
brief + checked evidence
        ↓
report-writing → report-build check → report-build build → document-inspect
        ↓                                      ↓                 ↓
clear prose                         HTML · TeX · PDF      rendered-page review
```

[`report-writing`](Skills/report-writing/SKILL.md) works from the brief, rubric,
audience, and verified evidence. [`report-generation`](Skills/report-generation/SKILL.md)
and `report-build` assemble modular Markdown with structured references,
citations, figures, tables, cross-references, and word limits.

```console title="report-workflow"
report-build init my-report --title "Exact title" --author "Your name"
report-build check my-report
report-build build my-report
document-inspect my-report/build/report.pdf --output my-report-inspection --json
```

Validation refuses broken references, unknown citations, unresolved
placeholders, malformed tables, missing figures, and exceeded limits. The
[`document-inspection`](Skills/document-inspection/SKILL.md) workflow renders
the real pages, extracts layout-preserving text, builds a contact sheet, and
records hashes. Compilation alone is never treated as proof that the document
looks right.

For larger reviews, [`evidence-review`](Skills/evidence-review/SKILL.md) keeps
searches, exact deduplication, screening decisions, and exclusion reasons
separate from the final prose. Thoreau provides readability and register
diagnostics without pretending style can establish authorship.

### Make an unfamiliar repository legible

[`repo-map`](Skills/repo-map/SKILL.md) creates a deterministic, content-hashed
static map without importing or executing project code. It records manifests,
entrypoints, commands, languages, public symbols, imports, tests, and agent
guidance. The map is observable structure, not an invented architecture.

[`docs-verification`](Skills/docs-verification/SKILL.md) and `docs-exec` rehearse
named Markdown fences in fresh workspaces and retain commands, file hashes,
stdout, stderr, and status. Documentation therefore has to work as a reader
sees it, without borrowing a warm cache or a conveniently configured home.

## Supporting cast

- `sudo-gui` runs one approved root operation through sudo's one-attempt KDE
  askpass path without capturing the password or relying on a cached timestamp.
- `comment-audit` finds empty, decorative, and historical comments without
  editing source or treating heuristic findings as verdicts.
- [`assess`](Skills/assess/SKILL.md) evaluates writing, creative work, or
  software against a supplied rubric or declared framework without mutation.
- `gcl`, `gpl`, `g`, `ga`, `gd`, `gs`, and `lg` keep daily Git work short while
  preserving fast-forward pulls and legible branch state.

See [`Tools/README.md`](Tools/README.md) for the CLI catalogue. Each directory
under [`Skills/`](Skills/) states when its workflow should and should not run.

## Bootstrap

```sh
git clone <your-repository-url> /path/to/agency
cd /path/to/agency
./install.sh --dry-run
./install.sh
./install.sh --update
```

Run the dry run first. It resolves hardware, existing files, backups, hook
merges, Git migration, packages, services, tools, and skills without requesting
sudo or changing the machine.

The installer is declarative and safe to rerun. It resolves links from the
checkout's actual location and moves replaced regular files or directories into
a timestamped tree under `~/.local/state/agency/backups`. Correct links remain
untouched.

A normal rerun installs missing tools but leaves existing stable Rust, yay,
h2load, 1Password desktop and CLI, Codex, Claude Code, Pi, Gantry, Thoreau, and
podman-compose versions untouched. It prints a warning so an older installation
cannot look freshly updated. Versioned user tools and AUR recipes are pinned in
the repository; update those reviewed pins, then pass `--update` to reinstall
them. Combine `--dry-run --update` to inspect that plan first.

`~/Scratch` is the durable home for reproducible task material. Installation
migrates an older `~/scratch` without overwriting conflicts. Disposable outputs
and caches may still use scoped temporary directories.

The installer asks for `sudo` once and refreshes that authorisation while it
runs. Agent CLIs install through Bun under `~/.bun`; Python tools use uv; and
rootless Podman is the only container stack. Node remains only as a compatibility
runtime for vendor launchers.

## What the workstation receives

- **Terminal experience:** animated phased progress, compact results, quiet Git
  transport, failure detail on demand, and accessible plain or reduced-motion
  modes through `agency-ui`.
- **Agents:** Codex CLI, Claude Code, and Pi with one portable global policy,
  shared skills, coordinated-worker profiles, and merged session hooks.
- **Development:** uv, Bun, GitHub CLI, GitLab CLI, stable Rust, yay, h2load,
  Git tooling, and a rose-coloured Fish and Starship shell.
- **Containers:** rootless, daemonless Podman with Pasta networking and Compose
  installed through uv. Docker and nerdctl frontends are removed.
- **Inspection:** ripgrep, fd, jq, btop, bottom, hyperfine, ShellCheck, perf,
  strace, lsof, sysstat, iotop-c, powertop, bandwhich, dust, PDF rendering, OCR,
  profiling, benchmarking, document checking, and comment auditing.
- **Desktop:** 1Password desktop and CLI, its automatically installed Firefox
  extension, Firefox privacy policy, uBlock Origin, browser integration,
  encrypted DNS, LAVD scheduling, and hardware-aware power policy.
- **Maintenance:** a global ignore file, weekly `fstrim.timer`, timestamped
  backups, and normal-user AUR builds for yay and nghttp2. The nghttp2 recipe
  accepts CachyOS's `zlib-ng-compat` provider.

Git identity lives in untracked `~/.config/git/identity`. If absent,
installation imports an existing global name, email, and signing key. The
managed configuration includes other machine-specific settings from
`~/.config/git/local`.

## Layout

```text
Agents/       portable guidance and coordinated-worker profiles
Skills/       progressively disclosed workflow instructions
Tools/        reusable, independently runnable utilities
Tests/        focused bootstrap, tool, and policy contracts
config/       user configuration linked into ~/.config
firefox/      machine policy and profile preferences
scripts/      focused install helpers
system/       scheduler and encrypted DNS configuration
install.sh    idempotent entry point
```

## Sharp edges worth knowing

Review the dry run and scripts before installing on another machine. Firefox
must restart before its policy is visible in `about:policies`.

System DNS uses strict Cloudflare Families DNS-over-TLS with no plaintext
fallback. Networks that block TCP 853 need a temporary override or VPN.

Desktop installations mask sleep, suspend, hibernate, and hybrid-sleep while
keeping display power saving active. Laptop installations leave those targets
available and select a portable AC/battery policy. Both chassis type and system
batteries inform the choice.

`fstrim.timer` runs weekly and only requests discard where mounted filesystems
advertise support. It can coexist with Btrfs `discard=async` and still cover
other mounted SSDs.
