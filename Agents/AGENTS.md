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

- For multi-step work, maintain `agent-work todo` as the durable checklist.
  Read `todo list` before starting or resuming; record the full requested outcome,
  acceptance criteria, and concrete child obligations before implementation.
  Link the responsible execution with `--work-task WORK_ID`. Update the checklist
  at stage boundaries, after steering, before compaction, and before handoff.
  Memory, chat plans, and scratch notes are not the task ledger. See `coordinate`.
- Delegation must include the parent/child todo IDs. Workers update their own
  items with evidence; the parent reconciles every child and integration check.
  Keep unfinished work open across sessions. Record a real blocker and next step
  when blocked; pause or cancel only on the user's instruction. Before claiming
  completion, run `agent-work todo check TODO_ID` and inspect its actual result.
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
- Use `decision-routing` for repeated, bounded semantic choices with inspected
  evidence, such as test ordering, failure triage, requirement coverage, research
  screening, and claim review. Skip obvious or deterministic choices; there is
  no per-turn quota. Labels remain advisory and grant no action or retention
  permission. Follow its per-profile evaluation guidance before reducing review.
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
- Whenever creating or changing any UI, use `interface-design`. Write concise,
  declarative labels, actions, and relevant state. Include instructions only
  when needed to choose, act, meet a prerequisite, or recover from an error.
  Remove slogans, atmospheric taglines, feature narration, obvious privacy
  reassurances, and prose explaining the app's premise or how it works.
- When asked to remove a control, remove it and its obsolete copy. Do not
  replace it with prose about the removed setting, its absence, or new defaults.
- For new web UI, default to React, Tailwind, and Radix. Respect an existing
  stack or explicit user choice. Choose layout, typography, density, and colour
  for the task and content; prescribe no universal accent or visual theme.
  Keep academic and formal professional documents restrained and mostly black
  on white.
