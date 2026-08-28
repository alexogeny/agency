---
name: sandbox
description: Run development, experiments, builds, tests, or long-lived services in the local Bubblewrap sandbox when the user requests isolation or the task benefits from constrained filesystem, environment, process, or network access.
---

# Sandbox work

Use the installed `sandbox` command to create a scoped local environment. It
shares the host kernel, so use a VM instead when genuinely hostile code needs a
separate kernel boundary.

## Choose the boundary

- Start with `sandbox -- COMMAND...`. The current directory is writable;
  networking is disabled; other home files and inherited environment variables
  are unavailable.
- Add `--internet` only when the task needs outbound network access.
- Add `--ro PATH` for additional inputs and `--rw PATH` for additional output
  locations. Grant the narrowest useful paths.
- Add `--publish tcp:PORT` or `--publish udp:PORT` only when the user needs to
  reach a listening service from the host. Use `tcp:HOST:SANDBOX` to map
  different port numbers. Published ports bind to host loopback.
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
