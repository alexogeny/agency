---
name: benchmark
description: Design, run, and report reproducible software performance comparisons using direct metrics for the resource claimed. Use for optimisation claims, before/after benchmarks, complexity measurements, or performance regressions; retired instructions measure executed CPU work but do not veto measured memory, allocation, copying, I/O, latency, or throughput wins.
---

# Benchmark the claimed resource

Choose the primary metric from the resource named by the hypothesis. Retired
userspace instructions are evidence of executed CPU work, not a universal
optimisation score or veto. Use direct measures for other claims:

- cumulative bytes and operation counts for allocation, copying, transfers, and
  I/O;
- phase-matched RSS or PSS for resident footprint;
- latency distributions for latency and completed work per fixed interval for
  throughput.

A material improvement in one resource remains a real result when instructions
are flat or change only slightly. Report relevant regressions instead of hiding
them or collapsing unlike resources into one score. Do not infer an unmeasured
latency, energy, or monetary benefit.

For `malloc`/`free` or `memcpy`/`memmove` claims, use a runtime-appropriate
profiler or instrumented workload that records cumulative bytes and calls.
State the interception boundary: symbol interposition can miss inlined or
compiler-generated allocation and copying.

## Define the comparison

State the hypothesis, exact workload, baseline, candidate, primary metric,
expected output, relevant input size, and why the two arms are behaviourally
equivalent. Use separate worktrees or explicit feature modes when comparing
source states. Rebuild changed native artifacts and prove the measured command
loads them before collecting evidence.

Create a TOML spec in the task's scratch directory. Workloads or profilers can
write runtime-specific metrics such as allocator traffic or copied bytes to the
arm's `metrics_file`:

```toml
name = "parse representative input"
cpu = 2
runs = 7
warmups = 2
output_equivalence = "exact"
primary_metric = "allocated_bytes"

[[metrics]]
name = "allocated_bytes"
source = "json"
key = "allocated_bytes"
unit = "bytes"
direction = "lower"
method = "runtime allocator profiler cumulative allocated bytes"

[[metrics]]
name = "instructions"
source = "perf"
event = "instructions:u"
unit = "instructions"
direction = "lower"

[baseline]
label = "before"
cwd = "/absolute/path/to/baseline"
command = ["uv", "run", "python", "bench.py", "--size", "10000"]
metrics_file = "metrics.json"

[candidate]
label = "after"
cwd = "/absolute/path/to/candidate"
command = ["uv", "run", "python", "bench.py", "--size", "10000"]
metrics_file = "metrics.json"
```

For observed peak process-tree memory, use a `procfs` metric with `field =
"rss"` or `field = "pss"`, `unit = "bytes"`, and a suitable
`sample_interval_ms`. Sampling can miss very short peaks; lengthen the workload
or emit a direct runtime metric rather than reporting a missed sample as zero.
RSS counts shared pages in every process, while PSS apportions them. State which
one answers the claim and compare the same lifecycle phase. Emit a JSON metric
when the claim needs steady-state or phase-specific memory rather than the
built-in observed peak.

Each command must emit stable, meaningful equivalence evidence on stdout, or
regenerate a declared `result_file` during every run. Stale result files and
empty output are refused. Keep exact equivalence enabled. Use `per-arm` only
when a separate retained check proves equivalent outputs despite different
serialisations. JSON metrics require a concise `method` retained in the result.

Inspect the plan, then retain the raw result:

```console
resource-bench SPEC --dry-run
resource-bench SPEC --output RESULTS.json
```

`resource-bench` pins both arms to the declared CPU, warms them, alternates run
order, and records every sample with commands, environment names, Git state,
machine facts, output equivalence, units, collection methods, absolute deltas,
and relative deltas. The legacy `instruction-bench` name remains a compatibility
entry point and preserves its instruction-only result schema when no metrics
are declared.

## Make only supported claims

- Prefer at least seven interleaved measured runs; increase the count when
  dispersion could change the conclusion.
- Validate the benchmark itself: exercise the expected output check and ensure
  the workload reaches the changed path and the metric measures the named cost.
- Compare equivalent inputs, outputs, lifecycle phases, runtime modes,
  dependencies, build flags, and collector configuration on the same machine.
- For a complexity claim, measure several doubling sizes and include a same-size
  control. Report observed ratios in the resource claimed.
- Treat fewer retired instructions as less executed CPU work, fewer allocated
  bytes as less allocator traffic, and lower PSS as a smaller apportioned
  resident footprint. Do not substitute one statement for another.
- If noise, dirty states, rebuild uncertainty, output mismatch, stale metric
  files, missed samples, or unsupported counters compromise the result, fix the
  experiment or report no conclusion.

Report medians, dispersion, absolute and percentage differences, workload,
machine/build facts, equivalence evidence, collection method, limitations,
material regressions, and the retained JSON path. Never report a percentage
that cannot be recomputed from raw samples.
