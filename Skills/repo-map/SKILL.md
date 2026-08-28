---
name: repo-map
description: Build and use a fast deterministic static map when onboarding to an unfamiliar repository or locating its entrypoints, manifests, commands, modules, tests, dependency edges, and agent guidance. Use instead of generating speculative architecture prose or exhaustively listing files.
---

# Map a repository

Use the installed `repo-map` command before broad exploration when repository
guidance and direct file lookup do not already answer the task.

Generate the canonical JSON into the current coordinated task's scratch
directory, or another task-specific directory under `~/Scratch`:

```console
repo-map . --output "$SCRATCH/repo-map.json"
```

For a large monorepo, repeat `--scope PATH` to map only the relevant subtrees.
Use the terminal summary for orientation and query the JSON with `jq` or `rg`;
do not load a large inventory wholesale when a focused query will do.

The mapper selects Git-visible files, uses stable ordering, hashes file content,
and performs static parsing only. It never imports or executes repository code
and never accesses the network. Cached parse facts are keyed by content and do
not enter the output. Identical visible content and scope produce byte-identical
JSON with the same `tree_sha256`.

Use the map to find:

- applicable agent-instruction files;
- manifests, toolchains, declared commands, dependencies, and entrypoints;
- source languages, public Python symbols, imports, and test cases;
- documentation, workflow, test, lockfile, and source roles;
- precise paths and lines to inspect next.

The map records observable structure, not architectural intent or ownership.
Treat prose documentation and comments as claims to verify against code,
manifests, tests, history, and behaviour. Do not infer a relationship the map
does not establish. Refresh after the visible tree changes and compare
`tree_sha256` rather than relying on an earlier map.

Do not commit generated maps unless the project explicitly defines one as a
maintained artifact. Report the tree digest, scope, key entrypoints and commands,
relevant subsystem paths, parse gaps, and the map location.
