---
name: sandbox
description: Run scoped local work through Agency's sandbox command, using Bubblewrap on Linux or Seatbelt through Sandbox Runtime on macOS, when the task needs constrained filesystem, environment, or network access.
---

# Sandbox work

Use the installed `sandbox` command. It selects Bubblewrap on Linux and native
Seatbelt through Anthropic Sandbox Runtime (`srt`) on macOS. Check `uname -s`
before choosing network or process-isolation options; do not install or invoke
`bwrap` on macOS. Both backends share the host kernel. Use a Linux VM when the
task needs Linux namespaces, Linux binaries, or a separate kernel boundary.

## Choose the boundary

- Start with `sandbox -- COMMAND...`. The current directory is writable;
  networking is disabled; other home files and inherited environment variables
  are unavailable.
- On Linux, add `--internet` when the task needs outbound network access.
- On macOS, grant destinations with `--allow-domain HOST` (repeatable), such as
  `sandbox --allow-domain pypi.org --allow-domain files.pythonhosted.org -- uv sync`.
  Networking goes through HTTP/SOCKS proxies; programs that ignore proxy settings
  remain blocked. `--internet` alone is rejected on macOS.
- Add `--ro PATH` for additional inputs and `--rw PATH` for additional output
  locations. Grant the narrowest useful paths.
- On Linux, add `--publish tcp:PORT` or `--publish udp:PORT` only when the user needs to
  reach a listening service from the host. Use `tcp:HOST:SANDBOX` to map
  different port numbers. Published ports bind to host loopback.
- macOS has no private PID, hostname, or mount namespace. `--name` and
  `--publish` require a Linux VM; the native backend does not silently emulate
  them or allow local listeners. Temporary HOME and TMPDIR are private per run.
  Apple marks `sandbox-exec` deprecated; if it or `srt` is unavailable, repair
  the declared dependency or select an approved VM. Never retry unsandboxed.
  SRT also protects shell, Git, and agent configuration filenames inside writable
  trees. Tests deliberately writing fixtures such as `.gitconfig` can therefore
  require a Linux VM; do not treat that denial as a missing package or weaken it
  automatically. Paths containing glob characters are rejected by this adapter.
- Use `--workspace PATH` to select a different working directory and
  `--workspace-ro` when the task should not modify it.
- Forward individual non-secret variables with `--env NAME`, or set controlled
  values with `--set-env NAME=VALUE`.

Never expose credential variables, SSH/GPG agent sockets, credential files, or
broad home directories unless the user explicitly requires that access. If a
tool normally installed under the home directory is unavailable, prefer its
system installation; otherwise expose only that tool's required directory and
set a narrow `PATH`.

## Run and report

Use `sandbox --dry-run -- COMMAND...` when the boundary needs review. Otherwise
run the scoped command directly and report the selected filesystem and network
boundary with the result. If setup fails, inspect `sandbox --help` and diagnose
the missing access rather than silently widening the sandbox.
