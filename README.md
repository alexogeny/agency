# 🎀 Mara's agency

A small, declarative bootstrap for a fresh CachyOS/Arch workstation.

## Bootstrap

```sh
git clone <your-repository-url> /path/to/agency
cd /path/to/agency
./install.sh --dry-run
./install.sh
```

The dry run resolves hardware, existing files, backups, hook merges, Git
migration, packages, and services without requesting sudo or changing the
machine. Review it before running the installer without `--dry-run`.

The checkout may live anywhere; every managed link is resolved from the
installer's actual directory. Before replacing a regular file or directory
with a link, the installer moves it into a timestamped tree under
`~/.local/state/agency/backups`. Existing links need no backup, and links that
already point at this checkout are left alone.

`~/Scratch` is the canonical reusable scratch directory. If an older
`~/scratch` exists and `~/Scratch` does not, the installer renames it in place.
If both exist, it moves non-conflicting top-level entries into `~/Scratch`
without overwriting anything; conflicting names remain under `~/scratch` for
manual review.

The installer is safe to rerun. It installs native packages, selects stable Rust,
links tracked user configuration, and installs the machine-wide Firefox policy.
Personal Git identity is read from `~/.config/git/identity` (intentionally not
tracked). If that file is absent, the installer imports an existing global Git
name, email, and signing key. Existing regular global configuration is retained
as `~/.config/git/local`, then the repository defaults are linked at both Git
global config locations so they remain authoritative without losing local
credential helpers or other machine-specific settings.

Durable Codex preferences live in `Agents/AGENTS.md` and are linked to the global
instruction locations used by Codex, Claude Code, and Pi. Runtime databases,
authentication, and conversation history remain local and untracked.

Codex and Claude Code receive a short, live hardware and power summary when a
session starts or resumes. The shared `system-context` probe identifies laptops,
AC or battery state, battery percentage, CPU and memory capacity, and locally
available NVIDIA or AMD KFD device nodes. This is hardware context, not a claim
that a compatible compute runtime is installed. Its guidance is advisory:
ordinary local validation remains available, while sustained ML training, broad
benchmarks, large builds, and similar high-load jobs require an explicit load
estimate and approval on laptops. Existing agent hook settings are merged
rather than replaced and are copied into the timestamped backup tree before
modification.

The installer asks for `sudo` once and refreshes that authorization until it
finishes. Agent CLIs install through Bun under `~/.bun`, so they never need root
access. Bun is the default for JavaScript/TypeScript and uv for Python. Node is
installed only as a runtime compatibility dependency for vendor CLI launchers;
npm is not used.

## What it manages

- Developer tools: uv, Bun, GitHub CLI, GitLab CLI, rustup + stable Rust
- Rootless, daemonless Podman with pasta networking and Compose installed by uv;
  Docker and nerdctl frontends are deliberately removed
- Performance/debugging: btop, bottom, hyperfine, perf, strace, lsof, sysstat,
  iotop-c, powertop, bandwhich, dust, fd, ripgrep, jq
- 1Password desktop and CLI through their AUR packages
- Firefox privacy/telemetry defaults and automatic uBlock Origin + 1Password
  extension installation, plus KDE Plasma browser integration
- Strict encrypted DNS: Cloudflare Families DoH in Firefox and system-wide DoT
  through systemd-resolved (`1.1.1.3`, malware + adult-content filtering)
- Hardware-aware Firefox profile tuning, a rose-coloured Fish/Starship shell,
  and LAVD automatic scheduling for responsive mixed workloads
- Codex CLI, Claude Code, and Pi, with one portable global guidance file
- Session-start hardware and battery guidance for Codex and Claude Code
- Single-attempt KDE sudo authorization for approved agent-run local workflows
- Legible Git defaults and a soft pink command-line colour palette
- A symlinked global Git ignore file and weekly discard through `fstrim.timer`
- Shared agent rules and a Git hook preventing AI attribution trailers
- `gcl owner/repo` and `gpl` helpers for safe clone-or-update Git workflows
- Cross-agent global skills for coordination, deterministic repository mapping,
  instruction benchmarking, local Firefox web research, report writing and
  generation, sandboxing, assessment, supervised remote work, prose auditing,
  and release writing, pull-request writing, creation, and CI supervision
- Desktop power policy: never suspend, dim displays after 15 minutes, turn them
  off after 30, and set DDC/CI brightness to 100% only on non-laptop hardware

## Layout

```text
config/       files linked into ~/.config
Agents/       portable global guidance and coordinated worker profiles
Skills/       portable global skills shared by coding agents
firefox/      machine policy and profile preferences
scripts/      focused install helpers
system/       scheduler and encrypted DNS configuration
Tools/        reusable utilities promoted from ~/Scratch
install.sh    idempotent entry point
```

Review the scripts before running them on another machine. Firefox must be
restarted after installation; `about:policies` shows the active policy. Strict
system DoT deliberately has no plaintext fallback. Networks that block TCP 853
will therefore need a temporary override or a VPN before DNS works.

`fstrim.timer` runs weekly and asks each mounted filesystem to discard only
where its block device advertises support. The Optane boot disk already uses
Btrfs `discard=async`; keeping the timer enabled is harmless and ensures any
mounted SSDs, including the PNY NVMe, receive periodic full-filesystem trim.

On desktop hardware, system sleep, suspend, hibernate, and hybrid-sleep targets
are masked while display power saving remains active through Plasma PowerDevil.
On laptops, those targets stay available and a portable AC/battery policy is
selected instead. Chassis type and system batteries are both checked before the
installer chooses a profile or changes display brightness.
