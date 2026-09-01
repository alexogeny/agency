# Web-research resilience decisions

Status: implemented feature record.

## Shipped

### Persistent provider and origin health

`search-batch` and `scrape-batch` keep health in a strict, append-only sidecar
next to the result checkpoint. Records bind the command, input digest, profile,
and profile mode. They retain the last attempt, outcome, consecutive failures,
latency, cooldown deadline, and a bounded `Retry-After` value.

Resume restores unexpired cooldowns before Firefox starts. Malformed and
future-version records fail validation. Success clears the relevant failure
state, unrelated origins continue, and profile rotation never acts as an
implicit retry strategy.

### Sanitized capture and offline replay

`scrape --format json --capture` and `scrape-batch --capture` store a sanitized,
bounded extraction input under the research data root. SHA-256-addressed
objects deduplicate identical inputs; separate manifests retain capture time,
sanitized URL identity, Firefox version, extraction options, evidence sources,
and truncation state.

`web-research replay CAPTURE_ID --json` verifies the manifest, object schema,
and content hash before rerunning extraction and fusion without Firefox or
network access. `capture-gc` previews retention changes by default and removes
unreferenced objects only with `--apply`.

The archive excludes headers, cookies, browser storage, request bodies, signed
or credential-bearing URL parameters, and challenge material. Arbitrary raw
DOM or browser-session replay is WONTDO because it would weaken this privacy
boundary and would not be deterministic.

### Field provenance and explainable quality

Extracted fields identify their bounded evidence source: rendered DOM, page
metadata, JSON-LD, frames, network JSON, or a search-result snippet. Quality is
reported as named observations with evidence and detail, including repeated
blocks, source-title disagreement, weak structured-only evidence, link-heavy
content, truncation, and search-snippet-only partial results. There is no opaque
scalar quality score.

### Deterministic rendered fixture

The feature tests serve a local JavaScript fixture and use the installed
Firefox to verify hydration and open-shadow-root extraction. This covers the
browser boundary without depending on a third-party site.

### Search and resume reliability

Search rejects unknown options, requires `--` before literal hyphen-leading
query terms, labels textual `site:` scope as best-effort, and provides a strict
repeatable `--domain` destination-host filter. One-shot searches use disposable
profiles unless a named profile is explicit.

Navigation retries are bounded and opt-in. A timed-out navigation retains
usable DOM or network evidence as a partial result with its failed stage, and
partial pages never enter the index. Batch inputs can grow only through
`--resume --append-input`, which verifies the previously accepted bytes as an
unchanged prefix and records the new input identity.

Thin content and low title/body topic overlap produce named observations with
concrete recovery actions. Capture-format validation includes a corrected
command.

## WONTDO

- Priority, authority, novelty, or cost scoring for the page frontier is
  WONTDO. Bounded FIFO and deterministic origin round-robin remain easier to
  inspect and reproduce.
- Leases, multi-worker batches, horizontal execution, parallelism, and
  concurrency are WONTDO. Search, scraping, and crawling remain single-worker,
  preserving profile ownership and per-origin pacing without distributed
  coordination.
- A maintained live-site smoke matrix is WONTDO, whether manual, scheduled,
  advisory, or blocking. Third-party availability and markup will not become a
  release gate or recurring test obligation. Live checks remain task-scoped
  research evidence, not feature tests.
- Raw headers, cookies, browser storage, request bodies, signed URLs, and
  challenge material in captures are WONTDO.
- An opaque aggregate quality score is WONTDO. Reviewers get the contributing
  observations and provenance instead.
