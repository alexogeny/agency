# GitHub settings

## Audit the live repository

Resolve `OWNER/REPO` and the default branch first, then query each settings
surface. A 404 from the classic branch-protection endpoint does not mean the
branch is unprotected when repository rulesets are active.

```console
gh repo view OWNER/REPO --json nameWithOwner,defaultBranchRef,description,homepageUrl,visibility,hasIssuesEnabled,hasProjectsEnabled,hasWikiEnabled,hasDiscussionsEnabled,deleteBranchOnMerge,mergeCommitAllowed,rebaseMergeAllowed,squashMergeAllowed
gh api repos/OWNER/REPO/rulesets
gh api repos/OWNER/REPO/actions/permissions
gh api repos/OWNER/REPO/actions/permissions/workflow
gh api repos/OWNER/REPO/environments
gh api repos/OWNER/REPO/pages
gh label list --repo OWNER/REPO --limit 100 --json name,color,description
gh api repos/OWNER/REPO/private-vulnerability-reporting
```

Read each matching ruleset by ID. Inspect workflow files and their real job
names before deciding which status contexts to require.

## Preview every forge mutation

GitHub does not offer a common dry-run switch for these settings. Build the
preview from the audit reads instead: normalise the current response and the
exact proposed request body, compare them field by field, and show the human
each `create`, `change`, `remove`, and `unchanged` action before sending a
mutation. Include the endpoint, repository, ruleset or environment ID, old
value, new value, and recovery action.

Classify anything that can block pushes or deployments, remove a merge method,
disable a collaboration feature, change workflow permissions, or replace a
ruleset as high risk. Treat an unobserved required status context, unexpected
bypass removal, default-branch mismatch, or destructive environment policy as
critical and stop. There is no forge equivalent of the local `keep` policy:
omit a conflicting endpoint from the proposed mutation set and report that
no-op explicitly. Never interpret a successful local `repository-setup`
dry-run as approval for live GitHub changes.

## Apply reversible baseline settings

When authorised, prefer squash-only linear history, automatic branch deletion,
read-only default workflow tokens, and no workflow-created pull-request
approvals:

```console
gh repo edit OWNER/REPO --delete-branch-on-merge \
  --enable-merge-commit=false --enable-rebase-merge=false \
  --enable-squash-merge=true
gh api --method PUT repos/OWNER/REPO/actions/permissions/workflow \
  -f default_workflow_permissions=read \
  -F can_approve_pull_request_reviews=false
```

Do not disable issues, discussions, projects, or the wiki merely because Wreath
does not use them. Match the target's actual contributor model. Derive the
description, homepage, and topics from its README and package metadata rather
than templating Wreath's values. Ensure the `bug` and `enhancement` labels exist
before issue forms reference them; preserve customised labels unless the user
asks to replace them.

Enable vulnerability alerts and private vulnerability reporting for a public
project when security hardening is in scope. If the rendered community config's
private advisory link is applied, private vulnerability reporting must be
enabled or that contact link must be omitted. Never query, print, copy, or
create repository secrets as part of this baseline.

## Apply the default-branch ruleset last

The rendered `github/main-ruleset.json` protects the default branch from
deletion and non-fast-forward updates, requires pull requests, squash merges,
linear history, and the `checks` job. It deliberately has no bypass actor and
requires zero approving reviews so a solo maintainer can merge a green PR.

Before activating it, confirm GitHub has observed the exact context on the
default branch:

```console
gh api repos/OWNER/REPO/commits/DEFAULT_BRANCH/check-runs \
  --jq '.check_runs[].name'
```

If `checks` is absent, leave the ruleset deferred until the workflow lands and
runs. Do not weaken the payload, invent a context, bypass the rule, or push
directly merely to make setup appear complete.

Find a ruleset named `main`. Create it with `POST repos/OWNER/REPO/rulesets` or
update its exact ID with `PUT repos/OWNER/REPO/rulesets/ID`, passing the reviewed
payload through `gh api --input`. Never create a duplicate because the list was
not inspected first. Read the resulting ruleset back by ID and compare its
conditions, enforcement, required contexts, merge methods, and bypass actors.

## Configure deployment surfaces only when used

For Pages, use GitHub Actions as the build type and restrict the `github-pages`
environment to the default branch. Confirm HTTPS enforcement and the published
URL after the first deployment.

For PyPI, create a `pypi` environment and restrict its deployment policy to the
release tag pattern used by the repository. Then configure a matching PyPI
Trusted Publisher with the exact owner, repository, `publish.yml` workflow, and
`pypi` environment. GitHub CLI cannot complete the PyPI-side registration;
report it as a manual external step rather than substituting a stored token.

For npm or crates.io, use the profile reference's protected environment name
and configure the corresponding trusted publisher on the registry. Those
registry-side registrations are also manual external steps. Go modules use
version tags and do not need a package-registry environment.

After every mutation, rerun the audit queries. Report the returned state, not
the command's zero exit code alone.
