# `web-research` command reference

Browser-backed operations use a real Firefox build and a persistent named
profile. Direct retrieval uses Bun's HTTP client. Neither path uses hosted
search, extraction, proxy, or model APIs.

## Search and extraction

```console
web-research search "QUERY" --engine auto --limit 10 --json --profile TASK
web-research search "QUERY" --engine duckduckgo --limit 10 --json --profile TASK
web-research search "QUERY" --engine brave --limit 10 --json --profile TASK
web-research search "QUERY" --engine bing --limit 10 --json --profile TASK
web-research search-batch queries.txt --output search.ndjson --resume --profile TASK
web-research scrape-batch search.ndjson --output pages.ndjson --resume --index --profile TASK
web-research retrieve URL... --json
web-research download URL \
  --output "$HOME/Scratch/TASK/file.pdf" \
  --output-root "$HOME/Scratch/TASK" \
  --profile TASK --expected-type pdf --json
web-research scrape URL --format markdown --profile TASK
web-research scrape URL --format json --include-frames --profile TASK
web-research scrape URL --format json --interaction-steps 2 \
  --scroll-steps 2 --capture-network-json --profile TASK
web-research search "QUERY" --json --profile TASK --profile-template current
web-research scrape URL --format json --index --profile TASK --ephemeral-profile --profile-template current
web-research scrape URL --format json --index --profile TASK
web-research scrape URL --output "$HOME/Scratch/TASK/page.md" --profile TASK
web-research snapshot URL --format png --output "$HOME/Scratch/TASK/page.png" --profile TASK
web-research snapshot URL --format pdf --output "$HOME/Scratch/TASK/page.pdf" --profile TASK
```

`scrape` and its `fetch` alias support `markdown`, `text`, `html`, and `json`.
JSON includes title, resolved and canonical URLs, publication and byline hints,
main text, Markdown, main HTML, discovered links, access state, capture count,
and evidence sources. A bounded allowlist of description, Open Graph, and
Twitter metadata plus sanitized `application/ld+json` is returned under
`structured`. It never includes cookies or browser storage.

Before output or indexing, the tool removes URL user information, fragments,
and query parameters shaped like tokens, credentials, signatures, sessions,
CAPTCHA challenges, or challenge solutions. The same normalization applies to
resolved URLs, canonical URLs, structured links, and links rendered into the
extracted Markdown and HTML. Empty code elements are omitted.

`--include-frames` adds text from same-origin child browsing contexts to JSON
output. Repeat `--frame-origin ORIGIN` to allow a specific additional origin.
Frame identities contain only origin and path; queries, HTML, and links are
omitted, while visible text remains untrusted. Skipped cross-origin and failed
frames remain explicit in the result.

`snapshot` captures the fully rendered page as a PNG or asks Firefox to print it
to PDF. Use it when layout, interactive rendering, or visual evidence matters.

`--wait-ms N` is the minimum post-navigation delay and defaults to 350
milliseconds. `--settle-ms N` is the additional adaptive stability budget and
defaults to 1.2 seconds. Stability includes the URL, title, text size, document
height, link count, and open shadow roots. `--navigation-timeout-ms` defaults to
45 seconds and navigation stops at interactive readiness rather than waiting
for every subresource. Automated commands remain headless by default.

`--scroll-steps N` performs at most N document-height scrolls, settling,
rechecking access, and capturing evidence after each. It defaults to zero.
Text, Markdown blocks, structured data, and links are deduplicated across
captures so virtualized content remains available after it leaves the DOM.
`--max-content-chars` bounds each of text, Markdown, and HTML at two million
characters; `--max-links` defaults to 2,000. Structured scripts are separately
bounded by count, depth, nodes, characters, array width, and object width. JSON
includes per-field truncation flags.

A visible login control is not automatically a hard wall. If substantial
public main, article, or feed content remains on a non-authentication URL, the
page is extracted with `access.state` set to `soft-login`. A non-dominant
challenge widget beside substantial public content is `soft-challenge`.
Authentication redirects and dominant challenges still require interaction.
Pages that expose a structural 429 or corroborating rate-limit message fail as
`origin rate limited` rather than being indexed as source content.

`--interaction-steps N` performs at most N semantic actions and defaults to
zero. Candidates are visible, enabled, non-form buttons, button roles, or
summaries with narrowly recognized dismiss, expand, read-more, or load-more
labels. JSON lists the action, bounded label, whether evidence changed, and
whether the action reached a hard gate. This does not accept consent, submit
forms, or follow arbitrary links.

`--capture-network-json` starts a Firefox BiDi response collector before each
navigation. It considers at most 24 same-origin response events, reads at most
12 successful JSON/GraphQL/API bodies, caps each encoded body at 128 KiB and
the retained total at 512 KiB, and bounds JSON depth, nodes, keys, arrays, and
strings. Credential-shaped keys and token-shaped URL parameters are removed.
Headers, cookies, request bodies, and non-JSON responses are not returned.

Extraction retries once after 500 milliseconds only when the first document is
entirely empty. If the second sample still has no text, Markdown, or links, the
command reports that the page did not expose extractable content rather than
returning a blank success or a DOM runtime error.

For repeated or larger research, use a stable task-specific profile. It retains
its own ordinary first-party cookies, cache, and site preferences, which avoids
presenting every query as a brand-new browser. Add `--profile-template current`
to seed that separate Agency profile from the default Firefox profile, or pass
an absolute Firefox profile directory. The tool reads only `prefs.js` and
accepts validated values for:

- `intl.accept_languages`;
- browser colour, content-theme and toolbar-theme preferences;
- browser UI density, tab-close warnings and URL trimming;
- full-page and site-specific zoom behaviour; and
- media autoplay defaults and blocking policy.

All other preferences are ignored. In particular, the template does not copy
cookies, storage, history, extensions, profile identifiers, proxy settings, UA
overrides, saved form data, or identity state. The installed Firefox and its
platform continue to supply the engine, user agent, available fonts, locale,
timezone, and rendering signals. The automated context normalizes the
automation-only `navigator.webdriver` value before site navigation.

Add `--ephemeral-profile` for isolated one-off work. The `--profile` name
becomes a readable prefix for a randomly suffixed temporary directory, which is
deleted after Firefox exits. The profile starts from Agency's clean preference
baseline, can use the same sanitized template, and does not preserve
authentication. Because a fresh profile can attract more challenges than a
stable profile, do not use it by default for a large sequence of searches.

Signal normalization must stay coherent with the actual browser and system; it
must not fabricate a named identity or contradictory device. It does not
authorize session copying, unattended CAPTCHA solving, or login/paywall bypass.

Search defaults to `auto`: it tries DuckDuckGo, Brave, then Bing when an earlier
provider is challenged, unavailable, or empty. All attempts share one Firefox
process and profile claim; challenged providers are not retried. Select one
engine explicitly when exact search-engine reproducibility matters. Stable
profiles and ordinary browser signals reduce needless challenge triggers, but
no browser can guarantee that a source will not require a human challenge.

## Resumable batch research

`search-batch` accepts one query per line, deduplicates exact queries, and
appends `agency/web-search-result/1` records. It validates an existing checkpoint
before `--resume`, skips successful or failed records by default, and does not
launch Firefox when nothing remains. `--retry-failures` retries failed records.
The run cap defaults to 1,000 pending queries and can be changed with
`--max-queries` up to 100,000.

All queries share one browser. A successful provider becomes preferred for the
next query. Ordinary failures receive an exponential query-count cooldown; a
challenge opens that provider's circuit for the rest of the run. Inter-query
pacing defaults to 1.5 seconds plus up to 500 milliseconds of deterministic
jitter. Every successful record includes the provider attempts and completion
time.

`scrape-batch` accepts newline URLs or successful `search-batch` NDJSON and
appends `agency/web-page-result/1` records. `--resume`, `--retry-failures`, and
`--max-pages` mirror discovery. Successful pages may be added to the local index
with `--index`. An origin that presents a challenge or login wall is circuit
broken for the run; later URLs from that origin remain pending while unrelated
origins continue. Inputs are round-robined by origin. Default pacing is 750
milliseconds plus up to 250 milliseconds of deterministic jitter globally and
at least 2 seconds between requests to the same origin; change the latter with
`--origin-delay-ms`. Soft gates do not open the origin circuit; hard gates and
rate-limit pages do.

If the input is search-result NDJSON and the source then presents a hard gate,
the page record has `outcome: "partial"`, a `hard-login`, `hard-challenge`, or
`rate-limited` constraint, and up to eight matching search-result evidence
records. Each
record retains its query, engine, title, sanitized URL, and snippet and remains
explicitly distinct from rendered source evidence. Plain URL inputs have no
discovery evidence to retain. `--retry-failures` retries both failed and partial
records; otherwise either kind counts as checkpointed.

## Direct HTTP evidence

`retrieve` processes up to 100 URLs sequentially and returns the
`agency/web-retrieval/1` contract. Each successful result records the requested
and final URLs, every redirect, HTTP status, content type, response size and
SHA-256 digest, retrieval timing, live/cache state, provider, and URL-safety
decision. Each failure records a stable kind and code, a human-readable message,
and whether retrying may help. The command exits non-zero if any item fails but
still returns every result.

The default five-megabyte response limit and 30-second per-URL deadline can be
changed with `--max-bytes` and `--timeout-ms`. Redirects default to ten and can
be bounded with `--max-redirects`. Private, loopback, link-local, and reserved
network addresses are blocked unless the current task explicitly authorises
`--allow-private`.

This command verifies transport and response identity; it does not render
JavaScript or infer what the response means. Use `scrape` for browser-rendered
content and apply domain interpretation as a separate step.

## Authenticated downloads

`download` uses normal Firefox navigation inside a dedicated persistent profile
when direct HTTP cannot carry the authenticated session. It requires an
absolute `--output`, an absolute `--output-root`, and a supported expected type
either inferred from the output extension or supplied with `--expected-type`.
The output parent must already exist inside the real output root.

The initiating URL is restricted to its own origin unless `--allow-origin`
states the expected origin. `--context-url` may open one same-origin page before
the transfer. Private addresses require explicit `--allow-private`. Firefox
redirects remain inside the browser and are not returned or logged.

Downloads default to a 25 MiB limit and a 60-second completion deadline. The
tool waits for `.part` files to disappear and the final size to stabilise,
checks PDF, ZIP, Office Open XML, PNG, JPEG, or GIF structure, and then renames
the temporary file atomically. Existing files are preserved unless `--replace`
is present, and validation failure never promotes the temporary file.

An expired session returns `interactive-login-required`; establish the session
with `web-research browser URL --profile TASK`, close that window, and retry.
Do not copy an ordinary Firefox profile or expose cookies, browser storage,
signed download destinations, or authentication headers.

## Mapping, crawling, and local search

```console
web-research map URL --limit 200 --json --profile TASK
web-research crawl URL --depth 2 --limit 50 --max-queue 1000 \
  --links-per-page 200 --delay-ms 750 --json --profile TASK
web-research local "SEARCH TERMS" --limit 10 --json
web-research stats
```

`map` returns unique same-origin links found on the page. `crawl` performs a
single-worker breadth-first crawl, follows only same-origin HTTP(S) links,
obeys `robots.txt`, and writes extracted pages to the local SQLite FTS index.
`scrape --index` adds one selected page. `local` queries only that retained
index and does not contact the network.

The crawler normalizes common tracking parameters before deduplication, bounds
the total queue with `--max-queue`, bounds unique additions from each page with
`--links-per-page`, and rejects URLs above `--max-query-params`. It holds one
prepared index connection, uses constant-time queue advancement, and reports
whether the frontier was truncated.

## Persistent interactive state

```console
web-research browser URL --profile TASK
```

This opens the named profile without extraction. Use it for a user-completed
login, consent screen, or challenge. Close the window before reusing that
profile from another command. The command now waits for the window to close so
the profile lock and process lifetime remain attached. `--detach` is available
only for an explicitly managed session. Profile locks prevent concurrent agent
commands from corrupting state.

Use `default` only for deliberately shared state. Concurrent work should use
task-specific names such as `inn700-policy` or `docs-audit-2`; do not include
personal data or secrets in profile names.

## Failure interpretation

- `interactive challenge required` means rerun visibly or prepare the profile
  interactively; it is not permission to bypass the challenge.
- `interactive login required` means the destination resolved to an
  authentication wall instead of usable content. Its redirect and token
  parameters are not printed.
- An empty `auto` search means all three engines returned no usable results.
  Inspect visibly before deciding that the query genuinely has no matches.
- Main-content extraction is heuristic. Compare against the rendered page for
  tables, footnotes, interactive figures, and unusually structured sites.
- Firefox PDF viewer pages may need a direct PDF-specific tool for complete
  text and layout inspection.
