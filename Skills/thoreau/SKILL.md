---
name: thoreau
description: Audit prose style and readability, detect document or image watermarks and provenance signals, or remove supported text marks with the local Thoreau CLI. Use when the user asks for prose diagnostics, LLM-register analysis, watermark checking, provenance scanning, or mark cleanup.
---

# Audit prose and watermarks with Thoreau

Use the installed `thoreau` CLI. It is deterministic and local except for the
explicit `scan-url` command. Keep style observations and provenance evidence
separate: style cannot establish authorship or model generation.

## Choose the operation

- For prose diagnostics, run `thoreau style TARGET --json`. Report readability,
  difficult sentences, passive voice, hedges, wordiness, and register as editing
  observations—not a provenance verdict. The reference baseline is academic
  biomedical English unless the output says otherwise.
- For a file or directory watermark/provenance check, run
  `thoreau scan TARGET --json`. In a repository, prefer `--git-visible` when the
  intended scope is tracked plus non-ignored work.
- Use `thoreau scan-url URL --max-pages N --json` only for an explicitly scoped
  same-origin website scan with network access.
- Enable statistical `--profile` tests only when the actual watermark scheme,
  tokenizer assumptions, and independently supplied key are known. They are
  not generic AI-text detectors.
- Use `thoreau image-detect IMAGE --key KEY --json` only for a claimed-key image
  check. Keep keys out of repositories and reports.

## Interpret evidence exactly

- `detected` establishes that an enabled self-checking frame, configured
  hypothesis test, or recognised provenance container matched. It does not
  authenticate an author.
- `suspicious` identifies an anomaly for review, not proof.
- A C2PA container finding does not mean its signature was validated.
- A clean scan means no enabled detector matched. It does not prove human
  authorship or absence of an unsupported watermark.
- Never combine unrelated evidence types into a synthetic confidence score.
  Preserve reported p-values, null hypotheses, family adjustments, evidence
  types, locations, and limitations.

## Changes require intent

Audits and scans are read-only. Do not add `--fix`, `--marks`, `clean`, `-o`, or
`--in-place` unless the user asks to change or clean the artifact. Prefer a new
output path over in-place editing, preserve the original, show the deterministic
changes, and re-scan the output.

`style --fix` performs only mechanical substitutions and optional target
retuning; it does not replace editorial judgement. `clean` cannot remove
statistical token-choice watermarks and deliberately leaves ambiguous authorial
formatting channels unchanged. Report those residual limits plainly.

Inspect `thoreau COMMAND -h` when selecting less common options or when the
installed interface differs from this skill.
