---
name: performance-design
description: Design or refactor software to do less work, move less data, and keep hot paths small. Use for explicit performance work before profiling or benchmark claims; do not use for ordinary cleanup without a cost objective.
---

# Design efficient execution

Start with the workload, input sizes, common case, resource boundary, and
behaviour that must remain equivalent. Prefer the highest-leverage change in
this order:

1. Skip work.
2. Do work fewer times or in fewer passes.
3. Touch less memory and keep access sequential.
4. Batch I/O, calls, transfers, and synchronisation.
5. Reduce individual instruction cost only after the larger costs are controlled.

Read [references/patterns.md](references/patterns.md) when choosing or reviewing
an implementation strategy. Apply only the patterns supported by the workload
and language runtime; do not remove useful abstraction or add caches by habit.

Preserve observable behaviour with focused tests. Use `perf-diagnosis` when the
cost location is uncertain. Use `benchmark` for before-and-after, regression,
complexity, throughput, latency, or other performance claims. Code inspection
can motivate a hypothesis but cannot establish an improvement.
