# Performance design patterns

Use the workload and constraints to choose among these patterns. This is a
decision aid, not a checklist that every implementation must satisfy.

## Avoid and reduce work

- Reject cheap, selective failure cases before expensive work.
- Put cheap and selective conditions first when short-circuiting can skip cost.
- Cache, memoise, deduplicate, or update incrementally when reuse is real and
  invalidation remains obvious.
- Hoist loop invariants; compile regexes, parse configuration, prepare queries,
  and build indexes outside the hot path.
- Combine traversals when it reduces material work without obscuring control
  flow or changing streaming behaviour.
- Exploit verified bounds, dense key ranges, or existing order with a simpler
  bounded algorithm.

## Move and allocate less

- Choose structures for the access pattern: sets or maps for membership and
  lookup, heaps for priority retrieval, compact arrays for dense hot data, and
  specialised indexes only when their workload justifies them.
- Avoid temporary collections, strings, objects, copies, boxing, and conversions
  in repeated paths. Reuse buffers only when ownership stays safe and legible.
- Keep the working set compact and related hot data close together. Minimise
  pointer chasing and dependent memory reads on the common path.
- Treat local lookup caching as runtime-specific; verify that the language and
  compiler do not already remove the cost.

## Cross fewer boundaries

- Batch database operations, network calls, syscalls, GPU work, FFI calls, and
  message transfers instead of issuing many tiny operations.
- Keep I/O, logging, locking, atomics, queues, and thread handoffs out of tight
  loops where possible. Give workers useful independent chunks.
- Keep the common path small. Move rare validation, reflection, dynamic
  dispatch, and exceptional cases aside only when measurement or scale makes
  their repeated cost material.

## Avoid false shortcuts

- Guard clauses are structural unless they skip expensive work.
- Deterministic order helps reproducibility and can improve locality or branch
  behaviour, but sorting first may cost more than it saves.
- Predictable branches, bitsets, lookup tables, and bit operations are useful
  when they fit the data model; do not trade obvious behaviour for cleverness.
- A smaller instruction count means less executed work. It does not by itself
  prove lower latency, energy use, or monetary cost.
- Flat instructions do not invalidate a directly measured reduction in
  allocation traffic, copied bytes, resident footprint, I/O, or transfers.
  Claim the resource actually measured and report important trade-offs.
