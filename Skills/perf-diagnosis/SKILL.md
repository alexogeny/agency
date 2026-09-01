---
name: perf-diagnosis
description: Diagnose software hot paths and supported CPU performance events with perf counters or profiles. Use for profiling and causal investigation; use benchmark instead for optimisation or regression claims.
---

# Diagnose performance behaviour

Use the installed `perf-diagnose` command for non-claim-bearing investigation.
Check available events before selecting hardware-specific counters:

```console
perf-diagnose events --contains cache
perf-diagnose stat --event instructions:u --event cache-misses:u \
  --output counters.json --json -- COMMAND...
perf-diagnose record --event cycles:u --output profile.data \
  --manifest profile.json -- COMMAND...
```

Pin with `--cpu` when the workload and machine make that appropriate. Keep the
workload bounded on a laptop and obtain approval before sustained high-load
profiling. Verify that the command reaches the suspected path and that selected
events are supported; an unsupported or multiplexed event is a limitation, not
a zero.

Counters and profiles from a single diagnostic run help locate work; they do
not establish an improvement. Use the `benchmark` skill and `resource-bench`
for repeated, interleaved comparisons with equivalent output. Choose the
claim-bearing metric from the resource at issue: instructions for executed CPU
work, RSS/PSS for resident footprint, or an instrumented direct metric for
allocation, copying, I/O, transfers, latency, or throughput.

Report the command, CPU, events, unsupported counters, profile or JSON path,
hot symbols or hypotheses, and the next discriminating check.
