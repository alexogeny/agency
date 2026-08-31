---
name: performance-design
description: Review the execution cost of executable code being written or modified, and design explicit performance work to do less work, move less data, and keep hot paths small. Use as a lightweight preflight for every code change; deepen it for optimisation work.
---

# Design efficient execution

## Run the routine preflight

For every executable-code change, treat efficiency as a design constraint from
the first draft rather than a later cleanup. Before implementation:

- Inspect the surrounding call sites enough to identify expected input sizes,
  repetition, the common path, allocations, and I/O, FFI, database, network,
  or synchronisation boundaries.
- Choose the simplest design that avoids obvious repeated work, excess data
  movement, needless allocation, poor asymptotic behaviour, and tiny repeated
  boundary crossings.
- Preserve correctness, scope, and legibility. Do not invent a hot path or add
  caching, concurrency, specialised structures, or cleverness without a
  workload-supported reason.

Before handoff, recheck new loops, allocations, and boundary calls for
accidental repeated work. For routine changes, stop there: no profile or
benchmark is required, and the preflight does not justify a performance claim.

## Deepen performance work

When performance is an objective or the visible costs could materially affect
the workload, start with the input sizes, common case, resource boundary, and
behaviour that must remain equivalent. Prefer the highest-leverage change in
this order:

1. Skip work.
2. Do work fewer times or in fewer passes.
3. Touch less memory and keep access sequential.
4. Batch I/O, calls, transfers, and synchronisation.
5. Reduce individual instruction cost only after the larger costs are controlled.

Read [references/patterns.md](references/patterns.md) when choosing or reviewing
an implementation strategy for this deeper work. Apply only the patterns
supported by the workload and language runtime; do not remove useful
abstraction or add caches by habit.

Preserve observable behaviour with focused tests. Use `perf-diagnosis` when the
cost location is uncertain. Use `benchmark` for before-and-after, regression,
complexity, throughput, latency, or other performance claims. Code inspection
can motivate a hypothesis but cannot establish an improvement.
