---
name: comment-audit
description: Audit code comments and Python docstrings for empty separators, decorative section labels, and historical change narration. Use for requested comment hygiene or focused cleanup, not as a generic code-quality gate.
---

# Audit comments and docstrings

Run the installed `comment-audit` command before editing:

```console
comment-audit . --git-visible --json
comment-audit PATH... --fail-on-findings
```

The scanner uses Python tokenisation and AST docstring detection, plus
line-comment scanning for common shell, configuration, JavaScript, TypeScript,
Go, Rust, Ruby, Java, and C-family files. It reports three narrow heuristics:
empty comments, decorative section comments, and historical narration.

Treat every finding as a review prompt. Preserve licences, generated-file
markers, protocol constraints, safety or concurrency invariants, public API
documentation, and tooling directives. Remove or refactor a comment only when
the user requested changes and the code can carry the meaning more clearly.
Never turn the audit into an automatic deletion pass.

Report files scanned, findings by category, false positives or preserved
constraints, edited paths when authorised, and focused tests for changed code.
