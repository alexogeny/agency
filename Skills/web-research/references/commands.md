# `web-research` command reference

All live operations use a real Firefox build and a persistent named profile.
They do not use hosted search, extraction, proxy, or model APIs.

## Search and extraction

```console
web-research search "QUERY" --engine auto --limit 10 --json --profile TASK
web-research search "QUERY" --engine duckduckgo --limit 10 --json --profile TASK
web-research search "QUERY" --engine brave --limit 10 --json --profile TASK
web-research scrape URL --format markdown --profile TASK
web-research scrape URL --format json --index --profile TASK
web-research scrape URL --output "$HOME/Scratch/TASK/page.md" --profile TASK
web-research snapshot URL --format png --output "$HOME/Scratch/TASK/page.png" --profile TASK
web-research snapshot URL --format pdf --output "$HOME/Scratch/TASK/page.pdf" --profile TASK
```

`scrape` and its `fetch` alias support `markdown`, `text`, `html`, and `json`.
JSON includes title, resolved and canonical URLs, publication and byline hints,
main text, Markdown, main HTML, and discovered links. It never includes cookies
or browser storage.

`snapshot` captures the fully rendered page as a PNG or asks Firefox to print it
to PDF. Use it when layout, interactive rendering, or visual evidence matters.

Use `--wait-ms N` for pages that populate content after load. The default is 350
milliseconds and the maximum is 30 seconds. `--human-timeout N` controls the
visible-browser challenge wait; the default is 180 seconds.

Search defaults to `auto`: it tries DuckDuckGo, then Brave if DuckDuckGo is
challenged, unavailable, or empty. Select one engine explicitly when exact
search-engine reproducibility matters.

## Mapping, crawling, and local search

```console
web-research map URL --limit 200 --json --profile TASK
web-research crawl URL --depth 2 --limit 50 --delay-ms 750 --json --profile TASK
web-research local "SEARCH TERMS" --limit 10 --json
web-research stats
```

`map` returns unique same-origin links found on the page. `crawl` performs a
single-worker breadth-first crawl, follows only same-origin HTTP(S) links,
obeys `robots.txt`, and writes extracted pages to the local SQLite FTS index.
`scrape --index` adds one selected page. `local` queries only that retained
index and does not contact the network.

## Persistent interactive state

```console
web-research browser URL --profile TASK
```

This opens the named profile without extraction. Use it for a user-completed
login, consent screen, or challenge. Close the window before reusing that
profile from another command. Profile locks prevent concurrent agent commands
from corrupting state.

Use `default` only for deliberately shared state. Concurrent work should use
task-specific names such as `inn700-policy` or `docs-audit-2`; do not include
personal data or secrets in profile names.

## Failure interpretation

- “human challenge” means rerun visibly or prepare the profile interactively;
  it is not permission to bypass the challenge.
- An empty `auto` search means both engines returned no usable results. Inspect
  visibly before deciding that the query genuinely has no matches.
- Main-content extraction is heuristic. Compare against the rendered page for
  tables, footnotes, interactive figures, and unusually structured sites.
- Firefox PDF viewer pages may need a direct PDF-specific tool for complete
  text and layout inspection.
