# 🎀 Mara's agency

Agency turns a fresh CachyOS/Arch workstation into a capable home for serious
agent work. It is part bootstrap, part operating model: shared instructions for
Codex, Claude Code, and Pi; small tools that preserve evidence; and skills that
carry work from a vague request to a checked result.

The workflows below are the reason the package list exists.

## First-class workflows

### Long work stays coordinated

The [`coordinate`](Skills/coordinate/SKILL.md) skill and `agent-work` give
durable or concurrent work a real lifecycle. A task claims the narrowest honest
scope across every worktree, receives its own directory under `~/Scratch`, and
records a timebox, heartbeats, changed paths, checks, and a terminal handoff in
a machine-local SQLite ledger.

```console
agent-work --json status
agent-work --json start --task "repair the parser" --scope src/parser --timebox 45m
agent-work --json heartbeat TASK_ID
agent-work --json finish TASK_ID --status complete \
  --summary "parser repair verified" --changed src/parser \
  --check "focused parser tests passed"
```

That state survives chat compaction and handoff without abusing commits,
branches, or scratch notes as a coordination protocol. Overlapping claims are
rejected atomically. Stale work is evidence to inspect, never permission to kill
someone else's process or take over their files.

Long-running work gets two more guardrails:

- `system-context` refreshes device, power, CPU, memory, and visible GPU context
  when an agent session starts or resumes. Laptop agents keep validation bounded
  and ask before sustained high-load work.
- `oldtasks` opens a friendly inspector for user-owned processes older than two
  hours. It previews each process, asks before `TERM`, and only offers `KILL` for
  survivors.

The same pattern extends to paid remote CPU and GPU work: the
[`gantry`](Skills/gantry/SKILL.md) skill carries an approved workload through a
budgeted lease, supervision, result collection, and confirmed release.

### Reports finish as inspected PDFs

Report work is an end-to-end path, not “write some Markdown and hope the PDF is
fine.” The writing and production responsibilities stay separate:

```text
brief + checked evidence
        ↓
report-writing → report-build check → report-build build → document-inspect
        ↓                                      ↓                 ↓
clear prose                         HTML · TeX · PDF      rendered-page review
```

The [`report-writing`](Skills/report-writing/SKILL.md) skill works from the
brief, rubric, audience, and verified sources. The
[`report-generation`](Skills/report-generation/SKILL.md) skill and
`report-build` assemble modular Markdown with YAML or TOML frontmatter,
structured references, citations, figures, tables, labels, cross-references,
and word limits.

```console title="report-workflow"
report-build init my-report --title "Exact title" --author "Your name"
report-build check my-report
report-build build my-report
document-inspect my-report/build/report.pdf --output my-report-inspection --json
```

Validation refuses unknown citations, broken references, unresolved
placeholders, malformed tables, missing figures, and exceeded word limits. The
built-in writer emits audit-friendly text, monochrome HTML, inspectable TeX, and
a PDF without invoking TeX or a browser. `document-inspect` then renders the
actual pages, extracts layout-preserving text, builds a contact sheet, and
records hashes. A successful build is not treated as proof that the document
looks right.

For larger evidence reviews, `evidence-review` keeps searches, exact
deduplication, screening decisions, and exclusion reasons reproducible before
synthesis. Thoreau audits the assembled prose for readability and awkward
register without pretending style can prove authorship.

### Git gets out of the way

The shell setup includes short, predictable daily commands:

| Command | What it does |
| --- | --- |
| `gcl owner/repo` | Clone the repository under `~/Code`, or safely fast-forward the matching checkout, then enter it. |
| `gpl` | Fetch, prune, and fast-forward the current checkout. If its upstream was deleted, move to the remote's default branch when that can be proved. |
| `g`, `ga`, `gd`, `gs` | Expand to Git, add, diff, and a compact branch-aware status. |
| `lg` | Open Lazygit. |

Global Git defaults prune deleted remote branches, set upstreams on first push,
sort branches by their newest commit and tags by version, remember conflict
resolutions with `rerere`, use histogram diffs with moved-line colouring, and
show conflicts with `zdiff3`. Machine-specific identity and credential settings
stay in an included local file instead of this repository.

The shared agent policy is deliberately conservative around authorship and
uncommitted work. Agents preserve unrelated changes, never add assistant
attribution, and leave Mara's changes uncommitted and unpushed for review. A
global commit hook blocks common AI attribution trailers. Separate skills can
research the real branch and forge state to write a useful PR body or turn an
actual release range into human-facing notes. The broader PR lifecycle skill is
policy-gated; this personal configuration does not permit agents to commit or
push.

### Repositories become legible quickly

`repo-map` creates a deterministic, content-hashed static map of a repository
without importing or executing it. It records manifests, entrypoints, commands,
languages, public Python symbols, imports, tests, and applicable agent guidance.
The map is observable structure, not a speculative architecture essay.

`docs-exec` gives documentation the same treatment. It extracts named Markdown
fences, rehearses them in fresh workspaces, and retains the command, output,
status, and input hashes. Reader-visible examples can therefore be tested
without relying on a warm cache or a conveniently configured home directory.

### Performance claims need evidence

Performance work has an explicit boundary:

- `perf-diagnose` collects counters and profiles to locate expensive work.
- `instruction-bench` compares equivalent baseline and candidate workloads
  using repeated, CPU-pinned, interleaved retired userspace instructions.

Profiles can suggest a cause; they do not prove an improvement. Claim-bearing
benchmarks retain raw samples, verify output equivalence, and avoid treating one
wall-clock run as a result.

### Useful boundaries for the awkward jobs

- `sandbox` runs builds, tests, experiments, or services in Bubblewrap with a
  scrubbed environment, a private process tree, a narrow writable workspace,
  and no network unless it is explicitly enabled.
- `web-research` uses local Firefox for JavaScript-heavy or authenticated pages,
  with persistent named profiles and an on-device full-text index. It keeps
  credentials in the browser and leaves human challenges to a human.
- `sudo-gui` carries one explicitly approved root operation through one KDE
  password dialog and one authentication attempt. It never puts the password in
  arguments, files, environment variables, or captured output.
- `comment-audit` finds empty separators, decorative section labels, and stale
  historical narration without editing the source.
- [`assess`](Skills/assess/SKILL.md) grades writing, creative work, or software
  against a supplied rubric—or a clearly declared diagnostic framework—without
  mutating the submitted work.

See [`Tools/README.md`](Tools/README.md) for the CLI catalogue and `--help`
entrypoints. The matching directories under [`Skills/`](Skills/) describe when
each workflow should and should not run.

## Bootstrap

```sh
git clone <your-repository-url> /path/to/agency
cd /path/to/agency
./install.sh --dry-run
./install.sh
```

Run the dry run first. It resolves hardware, existing files, backup paths, hook
merges, Git migration, packages, and services without requesting sudo or
changing the machine.

The installer is declarative and safe to rerun. The checkout may live anywhere;
managed links are resolved from its actual location. Before replacing a regular
file or directory with a link, the installer moves it into a timestamped tree
under `~/.local/state/agency/backups`. Existing correct links are left alone.

`~/Scratch` is the durable home for reproducible task material. If an older
`~/scratch` exists, installation migrates it without overwriting conflicts.
Disposable outputs and caches can still use task-specific temporary
directories.

The installer asks for `sudo` once and refreshes that authorization while it
runs. Agent CLIs install through Bun under `~/.bun`, so they never need root.
Bun is the JavaScript and TypeScript default, uv is the Python default, and
rootless Podman is the one container stack. Node remains only as a compatibility
runtime for vendor CLI launchers; npm is not used.

## What the workstation receives

- **Agents:** Codex CLI, Claude Code, and Pi with one portable guidance file,
  shared skills, coordinated-worker profiles, and merged session hooks.
- **Development:** uv, Bun, GitHub CLI, GitLab CLI, rustup with stable Rust, yay,
  h2load, Git tooling, and a rose-coloured Fish and Starship shell.
- **Containers:** rootless, daemonless Podman with Pasta networking and Compose
  installed through uv. Docker and nerdctl frontends are removed.
- **Inspection:** ripgrep, fd, jq, btop, bottom, hyperfine, perf, strace, lsof,
  sysstat, iotop-c, powertop, bandwhich, dust, PDF rendering, and OCR.
- **Desktop:** 1Password desktop and CLI, Firefox privacy defaults, uBlock
  Origin, 1Password and Plasma browser integration, encrypted DNS, LAVD
  scheduling, and hardware-aware power policy.
- **Maintenance:** a global ignore file, weekly `fstrim.timer`, timestamped
  backups, and normal-user AUR builds for yay and nghttp2. The nghttp2 recipe
  accepts CachyOS's `zlib-ng-compat` provider.

Personal Git identity is read from `~/.config/git/identity`, which is
intentionally untracked. If it is missing, installation imports an existing
global name, email, and signing key. Other machine-specific Git settings are
preserved in `~/.config/git/local` and included by the managed configuration.

## Layout

```text
Agents/       portable guidance and coordinated-worker profiles
Skills/       cross-agent workflow instructions
Tools/        reusable, independently runnable utilities
Tests/        focused bootstrap and tool contracts
config/       user configuration linked into ~/.config
firefox/      machine policy and profile preferences
scripts/      focused install helpers
system/       scheduler and encrypted DNS configuration
install.sh    idempotent entry point
```

## Sharp edges worth knowing

Review the dry run and the scripts before installing on another machine.
Firefox must be restarted after installation; `about:policies` shows the active
policy.

System DNS uses strict Cloudflare Families DNS-over-TLS with no plaintext
fallback. A network that blocks TCP 853 needs a temporary override or a VPN
before DNS will work.

Desktop installations mask sleep, suspend, hibernate, and hybrid-sleep while
leaving display power saving active. Laptop installations keep those targets
available and select a portable AC/battery policy. The installer checks both
chassis type and system batteries before choosing a profile or changing display
brightness.

`fstrim.timer` runs weekly and only asks mounted filesystems to discard where
their block devices advertise support. Btrfs `discard=async` and the timer can
coexist; the timer still covers other mounted SSDs.
