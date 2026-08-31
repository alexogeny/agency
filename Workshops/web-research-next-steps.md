# Workshop: resilient web research at corpus scale

Status: proposed follow-up to the bounded Firefox research tooling.

## Current baseline

`web-research` now has resumable search and page checkpoints, persistent and
ephemeral Firefox profiles, adaptive page settling, soft- and hard-gate
classification, bounded semantic interactions, container-aware scrolling,
rendered and structured evidence fusion, same-origin BiDi JSON capture, origin
interleaving, rate-limit circuits, and explicit partial search evidence.

The next stage should improve recovery, prioritisation, reproducibility, and
horizontal execution without making access constraints or incomplete evidence
invisible.

## Phase 1: persistent origin health

Move provider and origin health from process memory into a run checkpoint.
Record the last attempt, outcome class, consecutive failures, observed latency,
cooldown deadline, and any bounded `Retry-After` signal. Restore that state on
resume so a restarted batch does not immediately repeat a known challenge or
rate limit.

Keep profile affinity explicit. A research run should continue using the same
named profile for an origin unless the operator deliberately chooses another
profile. Profile rotation must not become an implicit retry strategy.

Acceptance:

- A resumed batch honours an unexpired origin cooldown without launching a
  browser for that origin.
- Successful evidence closes or decays the relevant failure state.
- A malformed or future-version health checkpoint fails validation instead of
  silently resetting limits.
- Unrelated origins continue while one origin cools down.

## Phase 2: content-addressed capture and offline replay

Store bounded extraction inputs outside the repository under the research data
root. A capture manifest should identify the sanitized final URL, capture time,
Firefox version, extraction options, response/body hashes, evidence sources,
and truncation state. Deduplicate immutable bodies by SHA-256.

Add an offline replay command that runs current extraction, fusion, and quality
logic against a retained capture without contacting the source. Keep browser
state, headers, cookies, request bodies, signed URLs, and challenge material out
of the archive.

Acceptance:

- Replaying the same capture is deterministic and performs no network access.
- Duplicate bodies occupy one content-addressed object.
- Missing objects and hash mismatches are reported as corrupt evidence.
- Retention limits can remove unreferenced objects without damaging live
  manifests.

## Phase 3: priority frontiers and evidence quality

Replace FIFO-only discovery with a bounded priority frontier. Rank candidates
using query relevance, source authority hints, path and query complexity,
novelty against the local index, expected extraction cost, and origin health.
Keep the scoring inputs and final priority in the checkpoint so ordering is
auditable and stable across resume.

Add field-level provenance and quality signals for rendered DOM, metadata,
JSON-LD, frames, network JSON, and search snippets. Quality should identify
boilerplate dominance, repeated cards, weak structured-only pages, stale search
snippets, and disagreements between evidence sources. It must not collapse an
uncertain page into an unexplained success or failure score.

Acceptance:

- A fixed frontier produces the same ordering across runs.
- The page and origin budgets remain hard limits regardless of priority.
- Every retained field identifies its evidence source and capture.
- Quality signals explain their contributing observations and preserve the raw
  bounded evidence needed for review.

## Phase 4: leased multi-worker execution

Partition large search and scrape checkpoints into atomic leases. Lease by
origin where profile state or pacing must be serial, and allow unrelated
origins to run on separate workers. Use append-only result records plus a small
lease ledger with owner, deadline, heartbeat, attempt, and completion identity.

Workers must not share a writable Firefox profile. A crashed or expired worker
may leave work eligible for a later lease, but its late result must not
overwrite the accepted completion. Keep one origin's rate and circuit state
coherent across workers.

Acceptance:

- Two workers cannot hold overlapping active leases.
- A late completion from an expired lease is retained as diagnostic evidence
  but cannot replace the accepted record.
- Killing one worker leaves completed checkpoints valid and pending work
  recoverable.
- Per-origin spacing is preserved when work moves between workers.

## Regression corpus

Build a small, reviewed fixture set alongside these phases. Cover hydrated
SPAs, open shadow roots, nested feed containers, disappearing virtualized
items, disclosure controls, consent and login overlays, hard authentication
redirects, rate limits, deleted/private pages, malformed JSON-LD, GraphQL
responses, redirects, and partial discovery evidence.

Prefer retained synthetic or locally served fixtures for deterministic CI.
Keep a separate, capped live smoke matrix for a few representative public
sites. Live failures should report drift; they should not make ordinary CI
depend on third-party availability.

## Delivery order

1. Persist origin health and its resume validation.
2. Add capture manifests and offline replay.
3. Establish field-level provenance before changing frontier ranking.
4. Add priority scheduling with deterministic fixture coverage.
5. Introduce leased workers only after single-worker checkpoints and origin
   health are replayable and stable.

Each phase should ship with focused fail-first tests, schema versioning,
bounded migration or refusal behaviour, command documentation, and a small live
smoke run. Performance claims require equivalent repeated measurements; scale
bounds and complexity should remain visible even when no performance claim is
made.
