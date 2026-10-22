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
`POST /api/alpha/decisions` endpoint using `typesafe/jev-1.13`. Supply a UTF-8
JSON object with the selected contract's required fields, from a file or standard
input. Version 2 of `skill`, `context`, `update`, and `research` requires structured
evidence too: migrate legacy text/array callers to their documented field names.
Missing or blank fields fail before credential or provider access. The result
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

`agency-decide evaluate --input FILE` runs cases whose items also contain
`expected` labels. An evaluation accepts 1–1024 cases in up to 4 MiB and splits
them deterministically into batches of at most 32 distinct requests and 256 KiB.
Defaults remain 10 calls, four workers, and 30 seconds, now shared across the
whole evaluation. Set `max_calls` up to 1024 and `deadline_seconds` up to 600
explicitly for a larger run; concurrency remains at most four. Each chunk is
also bounded to 60 seconds and individual workers to ten seconds. Validate all
cases before credential access; credentials resolve once for the evaluation.
Identical requests reuse their result across chunks without extra calls, while
each case retains its own expected label and place in the input order.

The result reports overall and per-profile agreement, errors, a confusion table,
usage, elapsed time, and `planned_batches`. Failed and undispatched cases stay
in every applicable denominator. Mismatches, provider failures, or exhausted
budgets exit 1; invalid or empty input exits 2. Partial/missing cost remains null.
`--dry-run` validates the complete set and shows planned requests without
credentials or hosted calls. Its accuracy/correct fields are null and it counts
zero decisions; insufficient planned call budget still exits 1.

From the repository root, validate the supplied 84-case synthetic fixture:

```console title="decision-evaluation-dry-run"
agency-decide evaluate --input Tests/fixtures/decisions.json --dry-run
```

Remove `--dry-run` to spend OpenRouter credit on the fixture's explicitly
configured budget of up to 84 unique calls, spanning every profile and multiple
labels per profile. These are synthetic contract checks,
not human-labelled calibration data. Keep private examples and evaluation
outputs outside the repository; do not mix tuning and held-out examples.

Shared contracts live in `Skills/decision-routing/decisions.json`; skill-owned
contracts live beside the owning `SKILL.md` and use names such as
`assess/criterion`. The runtime discovers these trusted repository definitions
through the same installed symlink. It validates required evidence fields and
preserves supplied band descriptors. See the routing skill for complete state
shapes and skill-specific use.

### Paired usefulness trials

`agency-decide trial-report --input FILE` summarizes supplied baseline and
Jev-assisted task outcomes offline. It performs no provider or credential calls,
starts no logging, writes no files, and emits no decision receipt. It accepts
1–1024 unique pairs in up to 4 MiB. Supply one profile per pair so the report can
compare that profile's contribution; evaluate multi-profile workflows separately
rather than attributing one outcome to several profiles. The report retains all
pairs, including unaccepted outcomes, in overall and per-profile summaries.

Save this fictional format example as `trial-pairs.json` in a task directory
under `~/Scratch`; replace its values with observed paired outcomes before
drawing conclusions:

```json title="trial-pairs.json"
{
  "items": [{
    "id": "claim-review-1",
    "profile": "claim-fit",
    "provenance": {
      "model": "jev-revision-from-result",
      "profile_version": "1",
      "rubric_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "workload": "claim-review-v1",
      "baseline_model": "reasoner-revision",
      "assisted_model": "reasoner-revision"
    },
    "baseline": {
      "accepted": true, "elapsed_ms": 120000, "cost": null, "repairs": 1,
      "reasoning_tokens": null
    },
    "jev": {
      "accepted": true, "elapsed_ms": 125000, "cost": null, "repairs": 0,
      "preparation_ms": 3000, "decision_ms": 650,
      "overrides": 0, "useful_corrections": 1, "reasoning_tokens": null
    }
  }]
}
```

Run from the directory containing that file:

```console title="decision-trial-report"
agency-decide trial-report --input trial-pairs.json
```

Outcome fields are required; `provenance` and each arm's `reasoning_tokens`
are optional for compatibility with earlier trial files. Other fields are
rejected. When supplied, provenance must contain all six shown nonempty fields,
each at most 256 characters, with a 64-character lowercase hexadecimal rubric
hash. Use the actual result's model, version, and hash, not the example values.
The workload ID identifies a fixed task family, acceptance criteria, and harness
configuration; change it when any of those change. Record the reasoning-model
revision and effort/configuration in `baseline_model` and `assisted_model`.
IDs contain 1–128 letters, digits, underscores, or hyphens. `accepted` is a boolean based on
the task's agreed checks, never a Jev label. `repairs`, `overrides`, and
`useful_corrections` are nonnegative integer counts from inspected outcomes.
`elapsed_ms` is the full task duration, including preparation, review, and repair.
Preparation and decision durations are diagnostic components that may overlap;
the report does not add them to elapsed time. Use the same monetary unit for
all `cost` values, including reasoning, Jev, failed attempts, and repair costs
where measurable. Missing costs must be null, not zero. `reasoning_tokens`
counts the full arm's reasoning tokens across attempts and repairs; use null
when unmeasured, including when the provider does not expose them. Known counts
must be nonnegative integers no greater than 2^53 - 1. Keep source pointers,
case ordering, and acceptance evidence keyed by pair ID in an existing
authorized local record, outside the repository. Neither provenance nor tokens
are inferred or collected automatically.

The report shows acceptance rates; total and mean time, repairs, and measured
cost; preparation/decision time; overrides; useful corrections; and mean paired
deltas (Jev minus baseline). Time and cost per accepted outcome include all
attempts and become null when none is accepted. Incomplete cost coverage makes
cost totals and comparisons null, with known/missing counts retained. A valid
report exits 0 even when Jev outcomes are worse; invalid input exits 2.
Reasoning tokens have the same known/missing counts and null-total behavior as
cost. `by_cohort` separates profile, Jev revision, profile version, rubric hash,
workload, and both reasoning-model configurations; it preserves pair IDs and
provenance. Overall and per-profile summaries are descriptive aggregates:
`mixed_provenance` flags combined cohorts and `provenance_complete` plus
known/missing counts expose legacy records. Unattributed records have a null
cohort provenance and must not establish a version-specific rollout result.
It does not assess statistical significance, calibrate confidence, or promote
a profile to automation. Follow the [staged advisory workflow](../Skills/decision-routing/references/daily-use.md#staged-advisory-rollout)
to judge quality, overhead, and repairs together before changing routine use.

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
Use the [client acceptance matrix](../Skills/decision-routing/references/client-acceptance.md)
to verify real client delivery after wiring or version changes. The offline
installation tests execute configured hook commands against actual CLI/MCP
receipts, but simulated event dispatch does not verify the client's display.

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
## `agency-storage`

Moves selected large directories onto an existing Linux filesystem and keeps
`~/.cache`, `~/Scratch`, and rootless Podman's `~/.local/share/containers` at
their familiar paths through symbolic links.
The filesystem mounts by UUID at `/mnt/storage` through a managed `fstab`
entry; its label does not need to change. Existing files on the drive remain
in place. Machine-specific selections live in
`${XDG_CONFIG_HOME:-~/.config}/agency/storage.json`, outside the repository.

```sh
agency-storage inspect --json
agency-storage setup --interactive
agency-storage status
agency-storage setup --dry-run
```

For an explicitly selected filesystem:

```sh
agency-storage setup --uuid YOUR-FILESYSTEM-UUID --mount /mnt/storage \
  --folders cache scratch --apply
```

Migration needs `rsync` and root authorization for mount configuration and
read-only process inspection across users. This also inspects non-dumpable
processes that an ordinary desktop user cannot check.
Install `rsync` first if it is absent: storage setup runs before the installer's
package and tool installation. Stop processes using a selected directory
before migrating it. The tool checks active users and refuses to switch a
busy directory. Original directories remain as backups; remove those only
through a separate, explicit cleanup after verification. Until cleanup, they
continue to consume space on the boot filesystem.

Installer reruns check saved configuration before writing to Scratch or
installing tools. Healthy storage is unchanged. Missing mounts, changed links,
and unfinished migrations stop the installation with diagnostics. Inspect
with `status` and `setup --dry-run`, resolve the reported condition, then use
`setup --apply` to resume the saved plan. Dry runs never prompt or change storage configuration or copy files. For an
already mounted container store, status queries Podman's effective configuration;
Podman may update its own runtime lock metadata during that query.
An unattended installation with no saved configuration skips storage setup.

For rootless Podman alone:

```sh
agency-storage setup --uuid YOUR-FILESYSTEM-UUID --folders containers --dry-run
# Review auto-remove settings, then stop containers and the Podman API service.
sudo-gui --message 'Move Podman images and volumes to secondary storage.' -- \
  agency-storage setup --uuid YOUR-FILESYSTEM-UUID --folders containers --apply
podman info --format '{{.Store.GraphRoot}} {{.Store.ImageCopyTmpDir}}'
```

Restart the containers that were running after setup succeeds. Existing container
IDs and volume paths are retained: changing Podman's configured graphRoot would
conflict with paths stored in its database. The data behind those paths moves
to `/mnt/storage/agency/<uid>/containers`. A managed `containers.conf.d` snippet
sets `image_copy_tmp_dir = "storage"`, so image downloads also use that drive.
The UUID automount works on access after reboot. `TMPDIR` or explicit Podman
storage/config overrides can override these defaults; setup rejects them and
custom graphRoots instead of silently migrating the wrong directory. Once mounted,
status and setup check Podman's effective `imageCopyTmpDir`, including configuration
precedence; a later snippet overriding the download location is reported for
manual correction, not overwritten.

Check each running container's `HostConfig.AutoRemove` with `podman inspect`
before stopping it. Containers created with `--rm` delete themselves and can
delete anonymous volumes on exit; preserve or clone those containers and their
data first if they must survive. The migration copies the store after shutdown.

Container migration uses a privileged copy to preserve subordinate UIDs/GIDs
and inspect open files across users. Only Podman's verified overlay self-bind is
released in its user namespace; mounted containers and other nested mounts block
the move. Keep other Podman operations stopped until migration completes. Source
data remains at `~/.local/share/containers.agency-storage-backup` for recovery;
cleanup refuses backups whose contents have since diverged from the active store.
Container backup checks and removal use sudo directly, avoiding fresh Podman
initialization during the comparison. Only `storage/storage.lock` is excluded
from checksums because Podman rewrites this runtime coordination file; database
and volume contents are still compared.

For separate migration sessions, select Scratch first:

```sh
agency-storage setup --folders scratch --interactive
```

After all work using Scratch has finished, this copies and verifies its contents,
then atomically exchanges the directory with a link. It retains the original as
`~/Scratch.agency-storage-backup`. Cache uses the equivalent
`~/.cache.agency-storage-backup` name. The per-user destination is a private
`agency/<uid>/` directory on the selected filesystem.

To add cache later, sign out of the desktop, switch to a text console with
Ctrl+Alt+F3, and log in there. Preview and then apply the expanded selection:

```sh
agency-storage setup --folders scratch cache --dry-run
agency-storage setup --folders scratch cache --apply
agency-storage status
agency-storage cleanup --dry-run
agency-storage cleanup --apply
```

Existing Scratch storage is left in place. Applications and agents must remain
stopped during migration; process checks are snapshots, not locks against future
writers. Nested mounts and conflicting destinations block migration. Cleanup
checks the recorded backup identity and compares its contents with the copy;
if either changed, it retains the backup for review. Prefer checking and cleaning
up while applications are still stopped, then return to the desktop. Do not run
migration from a working directory inside a folder being moved.

An armed systemd automount is reported as `mount on access` without activating
it during a dry run. Its destination is checked once mounted. Container status
reports verification pending while the automount is armed; access `/mnt/storage`
and rerun status to verify the effective Podman configuration. The underlying
mountpoint is protected against ordinary user writes when the disk is absent;
applications using redirected paths will be unavailable until storage returns.
Cleanup previews require the filesystem to be mounted already. A desktop mount
of the same filesystem can coexist with `/mnt/storage`; existing conflicting
`fstab` entries or use of the chosen target require manual review.

The tool uses systemd, util-linux, GNU coreutils, rsync, and Linux's atomic
`renameat2` exchange. It neither reformats nor relabels disks and does not schedule
logout or reboot tasks. Before Agency has installed its command link, invoke
`./Tools/agency-storage` from the checkout.

## `housekeeping` / `cleanup`

Scans your home directory and presents an animated pink/purple terminal report:
filesystem capacity, ranked folder bars, native cache cleanup proposals, and
larger directories that need review. The interactive Fish alias `cc` opens the
same tool; `command cc` and non-interactive build processes retain the C compiler.
The Fish `cleanup` function overrides the distribution's orphan-package removal
alias, so all three names open the same scanner. Scanning and previews are
read-only; cleanup requires `--apply` and interactive confirmation.
New shells load the alias automatically. In an existing Fish shell, run
`source ~/.config/fish/config.fish` once.

```sh
housekeeping
cleanup ~/Code
cc ~/Code --dry-run   # Preview environments and dependencies, without removal
cc ~/Code --apply     # Select project folders, then confirm or cancel
cc --apply            # Review native caches and optional project folders
cc --verbose          # Full breakdowns, paths and trade-offs
cc --limit 15
housekeeping --plain
housekeeping --json > /tmp/housekeeping.json
housekeeping --dry-run --json             # Inventory plus complete cleanup eligibility
housekeeping --dry-run --system-caches    # Also plan pacman retention without elevation
housekeeping --dry-run --system-caches --pacman-keep 3
```

The default view shows five folders with their two largest categories, compact
cache candidates, and the three largest generated directories. Use `--verbose`
for the expanded report.

The expanded view includes a size/percentage breakdown for Python environments,
Node dependencies, Rust and recognized framework build output, bytecode, known
caches, Git metadata, possible generated folders, and source/other files. The
three largest generated directories appear beneath their containing folder;
scan that folder directly to explore its projects. Python environments use a
regular `pyvenv.cfg`; Rust output checks the neighboring `Cargo.toml`. Ambiguous
`build`/`dist` names remain possible generated folders. Node dependency and
bytecode categories use their conventional directory names. These observations
do not establish that files are unmodified, disposable or reproducibly rebuildable.
“Source & other files” includes unclassified data, not just canonical source.

The breakdown is computed during the same scan and partitions the measured
folder total. Nested dependency trees and hardlinks are counted once. JSON schema
version 2 adds `breakdown` to totals and folders, `generated_directories` with
classification evidence to folders, and `breakdown_note` to the result. Generated
detail is bounded; if its limit is reached, category totals continue and the
report marks the omitted detail.

`--dry-run` lists native cache actions, application cleanup rules and project
candidates, including recognized Python environments and `node_modules`. With
`--apply`, a scrollable checkbox picker starts with every application target and
project folder unselected. Use Up/Down to move,
Space to toggle `[ ]` / `[x]`, and Enter to review the chosen folders. Review-only
rows display `[-]` and cannot be selected; toggling one keeps your other choices.
Before the picker opens, eligible folders are checked for active use, changed
paths, mounts and Git ownership. Blocked rows show the reason; active-use reasons
name the process, PID and kind of use. Press `R` after closing an app to refresh
availability. Refresh preserves eligible checked folders; a newly unblocked
folder stays unchecked until you choose it.

The picker includes all candidates regardless of `--limit`. Esc, `q` or Ctrl+C
cancels the entire cleanup, including native cache actions. Enter with no checked
folders keeps all project folders; native cache actions still require their
final confirmation. Uncertain build folders and incomplete scans remain
review-only.

Folders are checked again when you press Enter and after final confirmation.
If a folder becomes unavailable, the picker reopens with that row disabled and
other choices still checked. Review the updated selection and confirm again.
Completed cache commands are reported and are not repeated if a later project
availability change returns you to the picker. A removal failure after work has
started still stops and reports any completed actions.

After selection, the tool shows the exact project paths to delete permanently,
alongside the native cache plan, and asks `[y/N]`. Enter or `no` at this final
prompt cancels the entire plan; Ctrl+C or EOF also cancels before execution.
There is no unattended confirmation switch. Entire selected project folders are removed, including local edits within them; reinstall their
dependencies before using those projects again. A real interactive terminal
is required for both input and output, and `--apply` cannot be combined with `--json` or `--dry-run`.
Default scans, verbose reports and dry runs never execute cleanup commands.

Supported cleanup uses native `uv cache prune`, `bun pm cache rm`, and the
scanner's isolated Python interpreter with `-I -B -m pip cache purge`. Only the standard home
cache locations are eligible for automatic execution. Custom configured cache
locations, unavailable tools, and incompletely scanned cache trees are explicitly
excluded. Each cache root is checked for changed identity, symlink traversal and
mount boundaries before execution. Commands use fixed argument arrays with the
observed cache path set in the tool's environment; displayed text is never
executed as a shell command. A failure stops subsequent actions and reports
prior completed commands. Bun runs from a temporary empty project and its
reported cache location must match the scanned target before removal. Pip
availability is checked with the same isolated interpreter used for cleanup.

Cache sizes describe the complete observed cache, not predicted recovery;
uv pruning removes unused entries only. Re-run the scan after cleanup to inspect
the result. `--dry-run --json` includes a structured `cleanup_plan` with eligible
actions, excluded actions and their reasons, and all bounded `project_candidates`
and `application_candidates` with classification, sizes, selection eligibility
and reasons. Application discovery continues below review groups such as
`.local/share` and `.codex`. Proposal sizes partition the scanned files; a
proposal's `subtree_totals` additionally includes nested proposals. Whole-profile
candidate sizes use this inclusive total. Selecting a profile together with its
caches is rejected, so overlapping sizes are never an additive recovery estimate.

Application rules cover:

- Web-research profiles: only `cache2` and `startupCache` in inactive Agency
  profiles are cache targets. Their removal preserves cookies, logins, history,
  site storage, extensions, captures and the research index. Agency PID locks,
  Firefox POSIX record locks and process references block active profiles.
- Whole web-research profiles: separate, explicit selections require valid
  Agency lifecycle metadata, an unpinned profile, recorded completion and no
  recorded use for at least 30 days. Legacy profiles without metadata remain
  review-only. Whole-profile removal also removes that profile's login and site
  data; captures and the index remain outside this action.
- Codex app-server releases: match installation metadata under
  `~/.codex/packages/app-server-daemon/releases`. Keep the current symlink target,
  one immediately older rollback, newer staged releases and observed active
  releases. Unknown versions, layouts and platforms remain review-only. Apply
  takes the installation lock and rechecks retention before removing a selected
  release. Sessions, memory and databases have no deletion rule.
- Desktop thumbnails: only recognized thumbnail directory layouts containing
  regular PNG previews are eligible. Unknown files, symlinks and other layouts
  remain review-only; previews regenerate after cleanup.
- Pacman archives: `--system-caches` explicitly adds `/var/cache/pacman/pkg` to
  the inventory even though it lies outside the selected scan root. Its usage is
  reported separately under `additional_scans`, not added to home totals.
  Read-only `paccache -d` determines candidate files and bytes. Retain two versions
  per package by default; `--pacman-keep N` changes that rule and requires at least
  one. Inaccessible temporary download directories keep the inventory partial,
  while individually verified native archive candidates can remain selectable.
  Apply checks the native candidate manifest again and invokes `sudo-gui` only
  after explicit selection and final confirmation. Authentication cancellation
  or a cleanup error stops subsequent actions without an automatic retry.

New application targets are optional; merely running `--apply` does not select
them. Their paths, retention rules and trade-offs appear in the final review.
Read-only planning may run native discovery commands; it never runs cleanup or
requests administrator access. Same-user process inspection gaps are visible
and require care when selecting affected applications. Paths and mount
boundaries are rechecked before descriptor-anchored directory removal.
Firefox's Linux lock handling uses the `.parentlock` POSIX record lock from
[Mozilla's profile-lock implementation](https://searchfox.org/firefox-main/source/toolkit/profile/nsProfileLock.cpp),
alongside conservative checks for its legacy symlink locks.

File modification bounds and directory modification time accompany application
proposals in JSON. They are activity hints, not proof of last use. Access times
are not used: `noatime` filesystems cannot provide that evidence. Persistent
web-research profiles record actual claim/release use in an adjacent
`NAME.agency.json` file, outside the repository. They start pinned; starting a
profile again clears its completed state. Inspect or explicitly change that
state with `web-research profile-state` as documented in its command reference.

Scratch tasks, remaining application data and possible build outputs require ownership
and rebuild checks. A directory named `cache`, `venv` or `build` alone does not
make its contents disposable.

The scan stays on the selected filesystem, skips links and nested mounts, and
counts hardlinks once. A linked scan root is rejected: provide its real directory
explicitly if you intend to inspect another drive. Allocated and apparent sizes
are observations, not promised recovery on Btrfs with compression, reflinks or
snapshots. Directory metadata is excluded. A live filesystem can change while
being scanned; inaccessible subtrees and bounded detail limits produce visible
partial-scan warnings.

`--no-animation` retains colour without motion. `--plain`, `NO_COLOR`,
`AGENCY_UI=plain`, `AGENCY_UI=quiet`, non-terminal output, and
`AGENCY_MOTION=reduce` respect terminal preferences. `--limit` controls displayed
folders and proposals in previews (default five); the interactive picker and
JSON include all bounded detail, and apply confirmation always shows all selected commands. Exit codes are 0 for a
complete scan or declined confirmation after a complete scan, 1 for partial scan results (including
a successful cleanup following an unrelated partial scan), 2 for usage, scan-root
or cleanup errors, and 130 for interruption. Whole Scratch tasks, project source
roots and uncertain build folders have no removal action.

Before deleting selected environments or dependencies, the tool rechecks scanned
directory identity, symlink ancestors, mount boundaries, Git tracked files and
nested Git repositories. Detectable use by same-user processes blocks removal;
checks include working directories, open files, mapped files, command paths and
`VIRTUAL_ENV`. Inaccessible processes are reported before confirmation. These
checks are snapshots, not a lock against an application starting later: close
applications using the chosen folders first. Selections are checked again after
confirmation. The removal helper moves each folder into a private sibling
holding directory, verifies its identity, and uses descriptor-based recursive
removal. Failures stop the plan and identify any holding directory left for
inspection; prior completed removals cannot be undone.

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
record; `inspect` without an ID opens or emits the active board.

`start --no-claims` registers a blocked task without inventing a reservation.
New tasks return `task_token` once and a private `credential_file` outside the
repository. Prefix mutating commands with `AGENT_WORK_TOKEN_FILE=PATH` (or
forward `AGENT_WORK_TOKEN` in the worker environment). Status never exposes the
token. Active legacy tasks gain private credential files on migration and keep
lifecycle compatibility. Their owners can use that credential path to bind the
current client session and negotiate without closing the task.

```console
agent-work --json start --task "Repair parser" --no-claims --owner codex-parser
AGENT_WORK_TOKEN_FILE=CREDENTIAL agent-work --json request-claim TASK src/parser --message "Needed for assigned fix" --key parser-fix
agent-work --json inbox OWNER_TASK
AGENT_WORK_TOKEN_FILE=OWNER_CREDENTIAL agent-work --json respond OWNER_TASK REQUEST --revision 1 --decision yield --quiesced
agent-work --json request TASK REQUEST
agent-work --json check-write TASK src/parser/file.py
```

`broadcast` snapshots other active/waiting tasks in the same repository.
`request-claim` routes to all effective owners and emits a repository intent
notice. Owners can `yield`, `defer --until TIME`, `deny --message REASON`, or
`counter --path PATH`. Yield requires stopping every writer first. Multi-owner
requests transfer in one transaction after every owner accepts the same
revision. `revise-request` resets approvals; `cancel-request` releases temporary
pauses. Changed claims require review, not a stale approval. Deadlines, silence
and dead processes never grant ownership. Wait cycles appear in request output.

Broad claims retain explicit yielded exclusions. `check-write` checks effective
ownership and pending pauses; exit 3 refuses the write while reads remain
allowed. Exclusions persist when the recipient finishes, and require explicit
reacquisition. All cooperating agents must use the updated CLI; claims do not
enforce filesystem permissions or stop an existing background writer.

`inbox` is read-only with respect to message state; `ack TASK MESSAGE` records
acknowledgement without changing claims. `message TASK MESSAGE` shows each
recipient's queued/delivered/acknowledged state. Requests have a separate
pending/granted/denied/cancelled/needs-review lifecycle. Retry identical requests
or broadcasts with the same `--key`; reusing a key for different content fails.

The installer adds unfiltered lifecycle hooks for Codex/Claude and the Pi
`agency-work.ts` extension. Hooks bind tasks when they observe an authenticated
JSON start result, or use `session TASK --client CLIENT --session ID` explicitly.
Hooks deliver at the next prompt/tool/stop boundary; arbitrary idle TUIs remain
queued. Pi's local watcher steers active work and wakes idle sessions through
custom extension messages. Session switches stop the watcher.

Inbox hooks consume the full JSON event in chunks, replacing JSON strings
larger than 64 KiB (encoded) with `null` before parsing the bounded metadata. Image data
and large tool text therefore do not prevent session routing or delivery;
small authenticated registration records remain available even after images.
The retained JSON is limited to 1 MiB, and hook inputs are never stored.

`agent-work-watch --client CLIENT --session ID` streams durable inbox batches
as JSONL. It uses a private Unix datagram wake socket, with a fifteen-second
reconciliation fallback for missed wakeups. Consumers reply on stdin with
`{"delivered":"BATCH_ID"}` only after the client accepts the context. Unconfirmed
batches retry after their lease; delivered but unacknowledged messages retry
after five minutes. Stable message IDs make retries identifiable. Hooks mark
delivery after emitting context; that records adapter submission rather than
proof the model read or agreed with it. Each delivery contains at most eight
messages and 32 KiB of context, with actionable requests ahead of routine
notices. Longer notes are summarised with commands to inspect their full
records. Routine claim updates coalesce to the latest ownership snapshot;
replaced notices are `superseded`, without fabricating acknowledgement.

`agent-work-bridge` (Bun) supplies optional controlled transports:

```console
agent-work-bridge --client codex --session THREAD --url ws://127.0.0.1:4500
agent-work-bridge --client claude --session UUID -- --max-budget-usd 2
```

Codex mode connects to an explicitly selected loopback app-server, steers an
active turn and starts an idle one without model or permission overrides. A
`--token-file PATH` supplies listener authentication. The caller handles any
app-server approval requests emitted on stdout, sending JSON replies on stdin.
Claude mode launches a controlled `stream-json` worker, forwards client JSONL
on stdin/stdout, and confirms delivery only after replayed-input acknowledgement.
`--resume yes` is for exclusive control of an existing session, not attachment
to a working TUI. Bridge startup is explicit and can incur normal model costs
when it wakes a session. It never launches automatically from the ledger.

See [coordinate](../Skills/coordinate/SKILL.md) and the
[design and acceptance record](../Workshops/claim-routing.md), or use
`agent-work --help` for the CLI.

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

```sh
sudo-gui --message 'Restart the service to apply the new configuration.' -- \
  sudo systemctl restart example.service
```

The password dialog displays the summary followed by the exact shell-quoted
sudo command. Script workflows show the nested privileged command, rather than
only the outer script name. Absolute-path sudo calls that bypass the PATH proxy
recover their requesting process arguments through `/proc`; if those arguments
are inaccessible, the helper refuses authentication with a clear diagnostic.
`--prompt` remains an alias for `--message`.

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

## `agency-browser`

Attach Playwright MCP to an existing logged-in Chrome session, propose a named
control with Jev, and pace navigation or collection without OCR. See the
[browser-workflow skill](../Skills/browser-workflow/SKILL.md) for setup, current
Playwright schemas, review requirements, and private artifact storage.

`packet` extracts only explicitly reviewed link/button refs from a snapshot.
`choose` sends the goal, bounded context, and 1–32 candidate descriptions to
`browser-workflow/next-control`; `--dry-run` prints the exact request without a
provider call. Its output retains the reported charge, token usage, latency,
and hashes tying the proposal to the observation. `done` and `unsure` never
produce a click target. `click` takes a packet and choice, obtains a fresh
snapshot through the existing MCP session, validates the hashes, and performs
one reviewed click. It refuses changed observations and does not retry.

`call TOOL --arguments FILE --session FILE --origin URL` invokes a caller-chosen
MCP tool through a loopback endpoint. `get-json --url URL --allow-prefix URL/
--session FILE` issues one same-origin GET inside the supplied prefix using the
browser's existing session. Session files and outputs are private and belong
outside repositories; output parents must exist.

The shared `Pacer` defaults to a two-second minimum plus 0–2 seconds of uniform
jitter after completion, and one in-flight action per origin across processes.
All calls in a workflow must share `--pace-state` (default: XDG state under
`agency/browser/pacing`). `get-json` reports hosted HTTP 429/503 to it, honors
`Retry-After`, and persists exponential cooldowns. Long cooldowns and busy
origins defer the caller rather than blocking or replaying an action. Direct
clicks do not expose hosted response headers; inspect actual rate-limit
evidence before continuing. Pacing applies to logical operations, not every
page asset or unpaced request inside a custom browser script.

The runtime uses Python's standard library and Linux file locks. It currently
targets Linux; Windows and macOS browser attachment are unverified.

`download --url URL --destination NEW_PATH --download-directory CHROME_DIR
--filename NAME --expected-size BYTES --session FILE` waits for a newly completed
file in Chrome's configured download directory and verifies its size and SHA-256
while copying it to a private, exclusively created destination. It ignores old
and partial files and serializes the complete transfer under the origin's
pacing lock. The downloaded URL remains local. A missing or ambiguous completed
file defers the workflow; inspect it before another download.

`download-batch` runs a reviewed generic manifest through that same Chrome
transport. Chrome uses its existing credentials and follows normal download
redirects; Agency does not extract cookies or authentication tokens. The queue
is serialized and uses the shared origin pacer. No model call is made per file.
Keep the manifest, collection, and session outside Git in private directories.

```json
{
  "schema_version": 1,
  "allowed_origins": ["https://example.com"],
  "items": [
    {
      "id": "lecture-1",
      "url": "https://example.com/files/123/download",
      "filename": "Lecture 1.pdf",
      "expected_size": 1024,
      "path": "lectures/lecture-1.pdf"
    }
  ]
}
```

`filename` is the name Chrome actually saves, including any displayed name;
`path` is the relative path in the collection. Use distinct stable IDs and
destinations. Each item requires a known byte size and may include a lowercase
SHA-256 checksum in `sha256`. The manifest accepts 1–4096 items, at most 4 MiB,
and an explicit allowlist of initial HTTP(S) origins. Browser redirects follow
Chrome's normal behavior; the allowlist is not a redirect firewall. Paths
cannot escape the collection or traverse symlinks within it.

```console
agency-browser download-batch --manifest /PRIVATE/PLAN/downloads.json \
  --destination /PRIVATE/COLLECTION --download-directory /CHROME/DOWNLOADS \
  --session /PRIVATE/SESSION/session.json --progress
agency-browser download-batch --manifest /PRIVATE/PLAN/downloads.json \
  --destination /PRIVATE/COLLECTION --verify-only
```

Rerun the first command to verify completed files locally and continue the
queue. An append-only, mode-600 `.agency-downloads.jsonl` in the collection
retains resource identities, checksums, bytes, pacing waits, and sanitized
failure codes. Signed URL queries are omitted from the journal and may be
refreshed while the item's ID, URL origin/path, filename, size, and destination
stay the same. Use a new ID and destination for a different resource/version.
The journal preserves previous successful checksums even after failed checks.
One collection lock prevents overlapping batch runners.

Existing files require a matching manifest checksum or prior successful
receipt. Mismatched files are preserved and stop the queue. Missing files from
an interrupted transfer require inspection of Chrome's download state before
rerunning with `--retry-interrupted`; there is no automatic retry. Unknown
filenames/sizes, expired authentication, prompts, and stalled downloads also
require inspection. `--verify-only` makes no browser or provider calls and
records verification receipts. `--dry-run` validates the manifest and prints
counts without creating a collection or contacting Chrome. A fully completed
resume also needs no MCP session. Exit status is nonzero for an incomplete
batch; `--progress` writes only item IDs, status, and byte counts to stderr.
