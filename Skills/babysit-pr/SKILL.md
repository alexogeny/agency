---
name: babysit-pr
description: Turn an existing dirty worktree into a pushed pull request and supervise its checks until CI is green or a concrete blocker needs user input. Use when the user explicitly asks for the full branch, commit, push, PR, and CI lifecycle; do not use for PR prose alone or ordinary code review.
---

# Babysit a pull request

Take in-scope dirty work through branch, commit, push, PR, and CI supervision.
The request must authorize that lifecycle. Never force-push, merge, rewrite
published commits, or change the PR base without explicit permission.

## Inspect and authenticate

Read local guidance, contribution docs, PR templates, and validation commands.
Check the configured human identity and GitHub authentication before transfers:

```sh
git remote -v
git config --get user.name
git config --get user.email
gh auth status --hostname github.com
gh repo view --json nameWithOwner,defaultBranchRef
```

Stop if identity is missing or identifies an assistant/bot. Never add assistant
attribution or generation notices. Use `gh` for forge operations and its
credential helper for Git HTTPS transfers **from the outset**, even when the
saved remote uses SSH. Do not try SSH first or change saved configuration.
For each relevant remote, substitute its verified owner, repository, and name:

```sh
git -c credential.helper= \
  -c credential.helper='!gh auth git-credential' \
  fetch --prune https://github.com/OWNER/REPO.git \
  '+refs/heads/*:refs/remotes/REMOTE/*'
```

Use the verified host for GitHub Enterprise; use the configured authentication
flow for other forges. If authentication fails, report it without SSH fallback
or printing tokens/helper output.

```sh
git status --short
git diff --stat
git diff
git diff --cached
gh pr list --state open
```

Inspect every untracked file too, with appropriate viewers for binary/generated
content. Match an existing PR by repository, author, head, base, and conversation
using `gh pr view`; never infer ownership from the checkout. Preserve unrelated
work without resetting, stashing, overwriting, or including it.

## Validate and commit

Run documented checks and focused tests for changed behaviour, plus
`git diff --check`. Inspect additions for secrets, personal identifiers,
assistant attribution, and transient history without printing suspected secrets.
Fix only in-scope failures; record passes, failures, skips, and unavailable checks.

For a new PR, create a declarative branch following repository conventions:

```sh
git switch -c TYPE/declarative-change-name
```

For an existing PR, verify its actual head and published history. Do not move
unrelated changes to facilitate branching. Stage reviewed paths explicitly;
`git add --all` is appropriate only when every dirty path belongs in the PR.
Inspect the exact candidate before committing:

```sh
git diff --cached
git diff --cached --check
git diff --cached --stat
git commit -m 'TYPE: describe the actual outcome'
git log -1 --format='format:%H%n%an <%ae>%n%s%n%b'
git status --short
```

Verify author, body, and trailers before pushing:

```sh
git -c credential.helper= \
  -c credential.helper='!gh auth git-credential' \
  push https://github.com/OWNER/REPO.git HEAD:refs/heads/BRANCH
```

## Create or update the PR

Use [pr-writing](../pr-writing/SKILL.md) for the actual diff and verified checks.
Keep the temporary body file in the task's `~/Scratch` directory. Determine
the real default branch, then create or update the identified PR:

```sh
gh pr create --repo OWNER/REPO --base DEFAULT_BRANCH --head BRANCH \
  --title 'TYPE: concrete outcome' --body-file /home/USER/Scratch/TASK/pr-body.md
```

```sh
gh pr edit NUMBER --repo OWNER/REPO --title 'TYPE: concrete outcome' \
  --body-file /home/USER/Scratch/TASK/pr-body.md
```

Verify the remote head and metadata:

```sh
gh pr view NUMBER --repo OWNER/REPO \
  --json author,baseRefName,headRefName,headRefOid,title,url,statusCheckRollup
```

## Supervise CI

```sh
gh pr checks NUMBER --repo OWNER/REPO --watch --interval 10
```

For failed or stale checks, inspect the relevant run:

```sh
gh run view RUN_ID --repo OWNER/REPO --json status,conclusion,jobs,url
gh run view RUN_ID --repo OWNER/REPO --log-failed
```

Use [decision-routing](../decision-routing/SKILL.md) with `failure` for an
unfamiliar redacted diagnostic and `scope` for a potentially expanding repair.
Labels guide investigation; they cannot pass checks or authorize scope changes.

Fix in-scope failures, rerun focused checks, add a new commit, push, and resume
watching. Stop only when required CI is green or a concrete blocker needs user
input. Report outages, permissions, unrelated failures, and product decisions
without inventing success or broadening scope.

Report PR URL, branch, commit SHA, Git author, local checks, remote CI, warnings,
and final worktree state, distinguishing unrelated work from PR content.
