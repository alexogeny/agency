---
name: babysit-pr
description: Turn an existing dirty worktree into a pushed pull request and supervise its checks until CI is green or a concrete blocker needs user input. Use when the user explicitly asks for the full branch, commit, push, PR, and CI lifecycle; do not use for PR prose alone or ordinary code review.
---

# Babysit a pull request

Take the in-scope work from the current tree to a reviewable pull request with
green CI. The request must authorise commits, pushes, forge changes, and CI
supervision; otherwise stop before the first unauthorised mutation.

## Preserve authorship and work

- Review every tracked and untracked change before staging it. Treat staged,
  unstaged, and untracked content as separate evidence until all three have
  been inspected.
- Preserve unrelated work. Never reset, stash, discard, overwrite, or quietly
  include it. Stage explicit paths when any dirty path is outside the PR.
- Use a short declarative branch name that describes the actual change. Follow
  the repository's established branch and commit conventions when they exist.
- Use only the configured human Git identity. Stop if `user.name` or
  `user.email` is missing or appears to identify an assistant, model, bot, or
  automation account.
- Never add assistant attribution, co-authorship or sign-off trailers,
  generation notices, or similar credit in commits, source, PR text, tags, or
  metadata.
- Never force-push, merge the PR, rewrite published commits, or change its base
  without explicit permission.
- Use `gh` for GitHub authentication, repository and PR inspection, PR writes,
  and CI supervision. Use Git for local history and HTTPS transfers authenticated
  by `gh`; do not try an SSH remote first.
- Report skipped checks, warnings, partial inspection, authentication failures,
  and unavailable services accurately.

## Inspect the repository and forge

Read the applicable agent guidance, contribution documentation, PR template,
and documented validation commands. Determine the repository, remote, default
branch, current branch, and whether a matching open PR already exists; never
assume the checked-out branch owns the intended PR.

Inspect the configured remote and human identity locally, then check GitHub CLI
authentication before any fetch or push:

```sh
git remote -v
git config --get user.name
git config --get user.email
gh auth status --hostname github.com
gh repo view --json nameWithOwner,defaultBranchRef
```

For GitHub, use the verified `OWNER/REPO` and actual remote name to refresh over
HTTPS with the `gh` credential helper from the outset, even when the saved
remote uses SSH. Repeat for each relevant GitHub remote. These command-local
options leave the user's remote and credential configuration unchanged:

```sh
git -c credential.helper= \
  -c credential.helper='!gh auth git-credential' \
  fetch --prune https://github.com/OWNER/REPO.git \
  '+refs/heads/*:refs/remotes/REMOTE/*'
```

Then inspect the refreshed checkout and forge:

```sh
git status --short
git diff --stat
git diff --check
git diff
git diff --cached
gh pr list --state open
```

Inspect the contents of every untracked path too. Use an appropriate viewer for
binary or generated files rather than treating a summary as a review. Query an
existing PR with `gh pr view` and match its repository, author, head, base, and
conversation context.

If `gh` authentication is unavailable, report that blocker without falling back
to SSH or printing credentials. Never print token or credential-helper output.
For GitHub Enterprise, use the verified host in both `gh` and HTTPS commands.
For another forge, use its configured authentication flow instead of `gh`.

## Validate the proposed change

Run the repository's documented checks plus focused tests for the changed
behaviour. Use the declared package manager and toolchain. Run:

```sh
git diff --check
```

Inspect all added lines and new files for secrets, personal identifiers,
assistant attribution, generated-by notices, and accidental transient history.
Do not print suspected secrets. Fix only in-scope failures. Record exact passed,
failed, skipped, and unavailable checks for the PR and final report.

## Create the branch and commit

For a new PR, create the declarative branch before staging. For an existing PR,
verify its actual head branch and published history instead of creating a new
one. Never move unrelated changes merely to make branch creation convenient.

```sh
git switch -c TYPE/declarative-change-name
```

Use `git add --all` only when every dirty path has been reviewed and belongs in
the PR. Otherwise stage the verified paths explicitly. Then inspect the exact
commit candidate:

```sh
git add --all
git diff --cached
git diff --cached --check
git diff --cached --stat
git commit -m 'TYPE: describe the actual outcome'
git log -1 --format='format:%H%n%an <%ae>%n%s%n%b'
git status --short
```

Derive the commit type and subject from the change and repository convention;
do not assume a performance change. Confirm the resulting author, body, and
trailers before pushing.

## Push and create or update the PR

Push through the same GitHub CLI authentication path used for fetch, without
changing the stored remote:

```sh
git -c credential.helper= \
  -c credential.helper='!gh auth git-credential' \
  push https://github.com/OWNER/REPO.git \
  HEAD:refs/heads/BRANCH
```

Use the `pr-writing` skill to derive the title and body from the actual diff,
repository conventions, commits, and verified results. Put any temporary body
file in the task's unique directory under `~/Scratch`, never in the worktree.
Determine the real default branch rather than assuming `main`.

For a new PR:

```sh
gh pr create \
  --repo OWNER/REPO \
  --base DEFAULT_BRANCH \
  --head BRANCH \
  --title 'TYPE: concrete outcome' \
  --body-file /home/USER/Scratch/TASK/pr-body.md
```

For an existing PR:

```sh
gh pr edit NUMBER --repo OWNER/REPO --title 'TYPE: concrete outcome' \
  --body-file /home/USER/Scratch/TASK/pr-body.md
```

Verify the remote state:

```sh
gh pr view NUMBER \
  --json author,baseRefName,headRefName,headRefOid,title,url,statusCheckRollup
```

## Supervise CI

Watch checks until they finish:

```sh
gh pr checks NUMBER --repo OWNER/REPO --watch --interval 10
```

For failures or stale status, identify the relevant run and inspect only the
needed details:

```sh
gh run view RUN_ID --repo OWNER/REPO --json status,conclusion,jobs,url
gh run view RUN_ID --repo OWNER/REPO --log-failed
```

Fix in-scope failures, rerun focused local checks, create a new commit, push,
and resume watching. Do not amend or otherwise rewrite a pushed commit. Stop
when required CI is green or a concrete blocker requires user input. A timeout,
outage, permission failure, unrelated failure, or required product decision is
a blocker to report, not a reason to invent success or broaden the change.

## Finish

Report the PR URL, branch, commit SHA, Git author, local checks, remote CI
results, skips or warnings, and final worktree status. Distinguish remaining
unrelated changes from the committed PR content.
