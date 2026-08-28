# 🎀 Mara's dots

A small, declarative bootstrap for a fresh CachyOS/Arch workstation.

## Bootstrap

```sh
git clone <your-repository-url> ~/Code/Dots
cd ~/Code/Dots
./install.sh
```

The installer is safe to rerun. It installs native packages, selects stable Rust,
links tracked user configuration, and installs the machine-wide Firefox policy.
Personal Git identity is read from `~/.config/git/identity` (intentionally not
tracked); create it from the included example.

Durable Codex preferences live in `Agents/AGENTS.md` and are linked to the global
instruction locations used by Codex, Claude Code, and Pi. Runtime databases,
authentication, and conversation history remain local and untracked.

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

System sleep, suspend, hibernate, and hybrid-sleep targets are masked. Display
power saving remains active independently through Plasma PowerDevil. The power
installer detects laptop chassis types or a system battery before changing
brightness, making the same configuration safe to reuse on portable hardware.
