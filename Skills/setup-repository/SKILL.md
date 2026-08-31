---
name: setup-repository
description: Set up or improve GitHub-hosted Python, JavaScript, TypeScript, Go, and Rust repositories with Agency's CI, documentation deployment, trusted publishing, contribution templates, and repository settings. Use when asked to configure CI/CD, GitHub Actions, branch rules, Pages, publishing, issue forms, or repository hygiene; do not use merely to run existing checks or supervise an existing pull request.
---

# Set up a repository

Use Agency's repository profiles as a starting point, then fit them to the
target's declared toolchain and release model. Keep versioned repository files
separate from live GitHub settings so neither side silently implies authority
over the other.

## Inspect before rendering

Read the applicable agent guidance, package manifest, lockfile, contributor
documentation, existing `.github` tree, documented checks, docs builder,
package layout, and release history. Use `repo-map` for an unfamiliar
repository. Identify the GitHub repository and default branch from verified
remotes and `gh`, not from the directory name.

Choose one profile and read its reference before rendering:

- [Python](references/python-package.md)
- [JavaScript and TypeScript](references/javascript-package.md)
- [Go](references/go-package.md)
- [Rust](references/rust-package.md)

Audit live settings before proposing mutations. Read
[references/github-settings.md](references/github-settings.md) for the queries,
dry-run comparison, safe ordering, ruleset lifecycle, environments, and
verification. A request to improve repository settings authorises relevant
forge settings; ordinary local CI editing does not. Commits, pushes, pull
requests, merges, registry changes, and other external systems still require
their own authority.

Render only capabilities the repository genuinely has. CI commands must work
locally, Pages needs a strict docs build and known output directory, and
publishing needs a real distribution plus an intentional release trigger.

## Stage and review the bundle

Resolve `repository-setup` once with `command -v repository-setup`; this skill
contains templates, not a skill-local executable. Render into the coordinated
task's scratch directory, never directly over the target:

```console
task_scratch=/home/USER/Scratch/TASK
repository-setup render \
  --output "$task_scratch/repository-setup" \
  --project PROJECT --repository OWNER/REPO \
  --profile PROFILE --runtime-version VERSION \
  --branch DEFAULT_BRANCH \
  --docs-command 'STRICT DOCS COMMAND' \
  --docs-output OUTPUT_DIRECTORY --publish --json
```

Omit docs or publishing flags when unsupported. Python, JavaScript, TypeScript,
Go, and Rust profiles supply their documented default CI checks. Add checks
with repeated `--check NAME COMMAND`; use `--custom-checks` only when replacing
all defaults with repository-established commands.

Inspect every rendered file and the hashed `manifest.json`. The
`github/main-ruleset.json` payload is a reviewed forge input;
`repository-setup apply` never sends it to GitHub. The default bundle includes
CI, community templates, and that payload. For a narrower request, repeat
`--component` with only the authorised parts: `ci`, `community`,
`github-settings`, `docs`, or `publish`.

## Preview and apply local changes

Always dry-run the exact bundle, target, and conflict policy before applying:

```console
repository-setup apply "$task_scratch/repository-setup" TARGET \
  --dry-run --conflict abort --json
```

Read every action. `create` is low risk, `unchanged` does no work,
`conflict`/`replace` is high risk, and `unsafe` is critical. Show high or
critical actions, exact paths, and current/proposed hashes to the human before
continuing. The policies are deliberately explicit:

- `abort` is the default and writes nothing if any regular file differs.
- `keep` no-ops divergent regular files and may create non-conflicting files.
- `replace` overwrites divergent regular files and requires current, explicit
  human authorisation for the listed paths.

No policy may traverse a symlink or replace a directory or non-regular file;
those shapes are always blocked. A general request to set up CI does not by
itself authorise `replace`. After review, rerun without `--dry-run` using the
same policy and inspect the returned applied report.

## Validate both halves

Validate workflow syntax with `actionlint` when available, run the exact local
commands represented in CI, and falsify checks that could pass through empty
selection, cached output, or skipped capabilities. Confirm generated docs and
package artifacts exist at the paths workflows upload.

Versioned workflows must reach GitHub and complete successfully before a
ruleset requires their status contexts. Before any authorised forge mutation,
show a current-versus-proposed dry-run from live `gh` reads, including any
setting removal, environment restriction, or branch-lockout risk. Apply in the
GitHub reference's order, then read every setting back. Stop before a rule that
could lock the default branch when its required check has not been observed.

At handoff, distinguish files changed locally, settings changed remotely,
settings deliberately deferred, checks run, skipped capabilities, and manual
registry or Pages steps. Never imply that rendering a publishing workflow
configured a trusted publisher or released a package.
