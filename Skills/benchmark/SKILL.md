---
name: benchmark
description: Design, run, and report reproducible software performance comparisons using retired userspace instructions as the primary evidence. Use for optimisation claims, before/after benchmarks, complexity measurements, or performance regression checks; do not use wall time, cycles, IPC, or throughput as proof.
---

# Benchmark retired work

Use the installed `instruction-bench` command and make retired userspace
instructions the claim-bearing metric. Wall time may help diagnose a run, but
it does not establish an optimisation. Do not use cycles, IPC, frequency, or
throughput as substitute evidence.

## Define the comparison

State the hypothesis, exact workload, baseline, candidate, expected output,
relevant input size, and why the two arms are behaviourally equivalent. Use
separate worktrees or explicit feature modes when comparing source states.
Rebuild changed native artifacts and prove the measured command loads them
before collecting evidence.

Create a TOML spec in the task's scratch directory:

```toml
name = "specific operation and workload"
cpu = 2
runs = 7
warmups = 2
output_equivalence = "exact"

[baseline]
label = "before"
cwd = "/absolute/path/to/baseline"
command = ["uv", "run", "python", "bench.py", "--size", "10000"]

[candidate]
label = "after"
cwd = "/absolute/path/to/candidate"
command = ["uv", "run", "python", "bench.py", "--size", "10000"]
```

Each command must emit stable, meaningful equivalence evidence on stdout, or
name a stable `result_file`. Empty output is refused unless explicitly allowed.
Keep exact equivalence enabled. Use `per-arm` only when a separate retained
check proves the outputs equivalent despite different serialisations.

Inspect the plan, then retain the raw result:

```console
instruction-bench SPEC --dry-run
instruction-bench SPEC --output RESULTS.json
```

The tool pins both arms to the declared CPU, warms them, alternates run order,
counts `instructions:u`, verifies stable evidence, and records every sample,
median, range, median absolute deviation, commands, environment names, Git
state, CPU, kernel, Python, and perf version.

## Make only supported claims

- Prefer at least seven interleaved measured runs; increase the count when
  dispersion could change the conclusion.
- Validate the benchmark itself: exercise the expected output check and ensure
  the workload reaches the changed path.
- Compare equivalent inputs, outputs, runtime modes, dependencies, and build
  flags on the same CPU.
- For a complexity claim, measure several doubling sizes and include a same-size
  control. Report the observed instruction ratios, not a fitted label alone.
- Treat fewer retired instructions as fewer executed instructions—not proof of
  lower latency, energy, cycles, or cost.
- If noise, dirty states, rebuild uncertainty, output mismatch, or unsupported
  counters compromise the result, fix the experiment or report no conclusion.

Report medians, dispersion, absolute counts, percentage difference, workload,
machine/build facts, equivalence evidence, limitations, and the retained JSON
path. Never report a percentage that cannot be recomputed from raw samples.
