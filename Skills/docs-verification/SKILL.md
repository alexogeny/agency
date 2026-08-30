---
name: docs-verification
description: Verify that README instructions, tutorials, and named fenced code examples execute as documented. Use for documentation correctness, not ordinary prose editing or link checking alone.
---

# Verify executable documentation

Test the instructions a reader actually sees. Preserve command order, defaults,
filenames, working directories, and stated prerequisites. Use a fresh scoped
workspace so unmentioned local state cannot make an example pass.

For named Markdown fences, create a TOML manifest in the task's scratch
directory and run the installed `docs-exec` command:

```toml
schema_version = 1
root = "/absolute/project/path"

[[case]]
name = "quick start"
document = "docs/quick-start.md"
files = { "app.py" = "app.py", "test_app.py" = "test_app.py" }
command = ["uv", "run", "pytest", "-q", "test_app.py"]
```

```console
sandbox -- docs-exec MANIFEST.toml --output RESULTS.json --json
```

Each `files` entry maps an extracted path to the fence's `title=` value. Commands
are argument arrays, never shell fragments. `docs-exec` supplies
`DOCS_EXEC_PROJECT_ROOT` and `DOCS_EXEC_CASE_DIR` to each case.

For prose-only command sequences, rehearse the literal documented commands in
the same sandbox and retain concise output. Falsify the check by altering one
expected value or command so a skipped example, empty selection, or stale build
cannot masquerade as success. Report each case, the exact failure point, any
environment-specific adaptation, and the retained result path.
