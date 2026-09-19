# Global working agreements

Canonical shared policy for Codex, Claude Code, and Pi across Mara's projects.
A closer project `AGENTS.md` may add or override local guidance.

## Authority and safety

- Complete the authorized request without repeated permission checks. Ask before
  material scope expansion, unapproved external actions, or irreversible choices
  not already authorized.
- Commit or push only when the current request explicitly authorizes the Git/PR
  lifecycle. That covers branch, commit, push, PR, and CI; force-pushing and
  merging always require explicit permission.
- Use only the configured human Git identity. Never add assistant attribution,
  authorship, sign-offs, generation notices, or similar credit anywhere.
- Preserve unrelated work. Never use `git checkout`, `git stash`,
  `git reset --hard`, or another command that could discard uncommitted work.
  Use scratch copies for clean-tree comparisons.
- Keep secrets, personal identifiers, session history, credentials, caches,
  generated memory databases, and tool runtime state outside the repository.

## Execution and verification

- Refresh remote state before branch or PR inspection. For GitHub, use `gh`
  authentication and HTTPS transfers; follow `babysit-pr` for the lifecycle.
  Identify a live PR by forge, repository, author, head, base, and conversation.
  Keep pulls fast-forward-only unless project guidance requires otherwise.
- Keep reusable scripts and reproducible task material under `~/Scratch`, scoped
  by project or task. Temporary outputs may use scoped temporary directories.
- Prefer Bun, uv, and rootless Podman; respect existing lockfiles and toolchains.
  Use `sandbox` for isolation, exposing only required paths and variables;
  genuinely hostile code needs a VM.
- Respect hardware and power constraints. Refresh `system-context` when stale.
  Before sustained high load on a laptop, especially on battery, state load and
  duration and obtain approval.
- For bug fixes and behaviour changes, write a focused test first and confirm
  the expected failure. Deliver test and fix together. Falsify checks that empty
  selection, caches, skips, or stale output could make pass misleadingly.
- Report passed, failed, skipped, and unavailable checks accurately. Never hide
  failures with `xfail`, `skip`, `noqa`, `type: ignore`, or widened exceptions.
  Configure genuine exceptions explicitly. Fix pre-existing failures only when
  small, safe, and in scope; otherwise report them.

## Skills and engineering

- Use named or clearly applicable skills; keep their procedures there.
  Use `repo-map` before broad exploration of unfamiliar repositories.
- Use `coordinate` and `agent-work` for durable, multi-session, or concurrent
  repository work: narrow write claims, heartbeats, and evidence at handoff.
  Reads need no claim. Promote reusable utilities and judgement through that
  workflow.
- Whenever writing or modifying executable code, use `performance-design`.
  Use `perf-diagnosis` for uncertain cost locations and `benchmark` for claims.
  Performance is a vector of measured resource costs, not an instruction-count
  contest; retain repeated, equivalent before/after evidence.
- Use Agency's web tool by default for substantive research; use native search
  for quick lookups or when unavailable. Follow `web-research` for source
  verification and direct citations. Never automate CAPTCHA solving or expose
  browser secrets.
- Use both `report-writing` and `report-generation` for report deliverables.
- Keep behaviour obvious, data flow simple, costs visible, names precise, and
  configuration declarative and idempotent. Add comments only for non-obvious,
  checkable constraints code cannot express; remove stale narrative in scope.

## Reader-facing work

- Lead with the result and concrete evidence. Use plain, active language;
  state uncertainty and trade-offs directly. Cut filler and generic conclusions.
- Make artifacts self-contained for their reader. Include working paths and
  implementation details only when useful to that reader.
- Keep interface copy focused on the task, state, next action, and recovery;
  move optional technical detail to help or diagnostics. Favour accessible,
  warm pink/purple visuals where appropriate; keep academic and formal
  professional documents restrained and mostly black on white.
