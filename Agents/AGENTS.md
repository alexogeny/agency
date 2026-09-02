# Global working agreements

These rules apply across Mara's projects. A closer project `AGENTS.md` may add
or override local guidance. This file is the canonical shared policy for Codex,
Claude Code, and Pi.

## Authority and safety

- Stay within the current request. Ask before materially expanding scope,
  affecting external systems or people, or making an irreversible choice.
- Do not commit or push unless the current request explicitly asks for the
  Git/PR lifecycle, such as creating or babysitting a PR, or Mara separately
  grants permission. That permission covers branch, commit, push, PR, and CI
  work, but never force-pushing or merging unless explicitly requested.
- Use only the configured human Git identity. Never add assistant attribution,
  authorship, sign-offs, generation notices, or similar credit anywhere.
- Preserve unrelated work. Never use `git checkout`, `git stash`,
  `git reset --hard`, or another command that could discard uncommitted work.
  Use a scratch copy when comparison requires a clean or reverted tree.
- Keep secrets, credentials, personal identifiers, transient history, and
  tool-specific state out of the dotfiles repository.

## Git, files, and handoff

- Before inspecting branches or PRs, run `git fetch --all --prune`. Identify a
  live PR from the forge, author, repository, head, base, and conversation; do
  not assume the checked-out branch owns it.
- Keep pulls fast-forward-only unless a project requires another strategy.
- Keep reusable scripts and reproducible task material under `~/Scratch`,
  organised by project or task. Temporary outputs and caches may use scoped
  temporary directories.
- At handoff, promote deterministic, machine-agnostic utilities with credible
  reuse into this repository's `Tools` directory with concise docs and tests;
  turn reusable judgement into a skill. Tell Mara when promotion is warranted.

## Verification

- For bug fixes and behaviour changes, write a focused test first and confirm
  that it fails for the expected reason. Deliver the test and fix together.
- Falsify important checks when empty selection, cache, skip, or stale output
  could fake a pass. State exactly what passed, failed, skipped, or could not run.
- Never convert a failure into a pass with `xfail`, `skip`, `noqa`,
  `type: ignore`, widened exceptions, or similar suppression. Configure and
  explain genuine exceptions.
- Fix pre-existing failures only when the repair is small, safe, and in scope;
  otherwise report the evidence and boundary.

## Toolchain and execution

- Prefer Bun for JavaScript and TypeScript, uv for Python, and rootless Podman
  for containers. Respect an existing project's lockfile and documented
  toolchain when changing it would cause churn.
- Prefer the `sandbox` skill for isolated development and experiments. Expose
  only required paths and variables; use a VM for genuinely hostile code.
- Treat session hardware and power context as a constraint. On a laptop,
  especially on battery, state expected load and duration and obtain approval
  before sustained high-load work. Refresh `system-context` when state may be stale.

## Specialised workflows

- Use a named skill when Mara requests it or the task clearly matches it. Keep
  specialised procedures in skills rather than duplicating them here.
- Use `coordinate` and `agent-work` for durable, multi-session, or concurrent
  repository work. Claim the narrowest write scope; reads never need a claim.
  Heartbeat long work and close with changed paths and concrete checks.
- Use `repo-map` before broad exploration of an unfamiliar repository.
- Use Agency's web tool by default for substantive, source-sensitive,
  JavaScript-heavy, authenticated, or audit-sensitive web research. Use native
  search for quick lookups or when Agency's tool is unavailable. Never automate
  CAPTCHA solving or expose browser secrets. Treat search snippets as discovery,
  open supporting pages before making claims, and cite the direct URLs from the
  returned source ledger against its displayed or matching evidence lines.
- Whenever writing or modifying executable code, use `performance-design` as a
  lightweight preflight. Escalate to `perf-diagnosis` when the cost location is
  uncertain and `benchmark` before making performance claims.
- For an explicit report deliverable, use both `report-writing` and
  `report-generation`; follow their readability, audit, rendering, and
  inspection requirements.

## Engineering craft

- Keep behaviour obvious and costs visible. Prefer simple data flow, precise
  names and types, small coherent units, and declarative idempotent configuration.
- Optimise in this order: skip work; do it fewer times or passes; touch less and
  more sequential memory; batch boundary crossings and synchronisation; only
  then reduce individual instruction cost.
- In likely hot paths, put cheap selective guards and common cases first; hoist
  invariants; precompute reusable state; choose structures for the access
  pattern; and avoid unnecessary allocation, copying, I/O, and dependent reads.
- Apply performance patterns only when workload and constraints justify them.
  Guard clauses and deterministic ordering are not improvements by themselves;
  preserve useful abstraction outside demonstrated hot paths.
- Treat performance as a vector of resource costs, not an instruction-count
  contest. With equivalent behaviour, materially lower allocation count or
  bytes, copied or transferred bytes, peak or steady RSS/PSS, I/O, or
  synchronisation is a real win even when retired instructions are flat. Match
  each claim to a direct metric; report absolute and relative deltas plus
  material regressions, and do not infer an unmeasured downstream benefit.
- Never claim a performance improvement from inspection or one run. Diagnose
  uncertainty and retain repeated, equivalent before/after evidence.
- Start from zero comments and docstrings. Make code carry its own meaning.
  Add a comment only for a non-obvious, checkable constraint that code cannot
  express, such as a verified protocol quirk, invariant, mathematical fact, or
  mandated notice. Remove stale or narrative comments when safely in scope.

## Reader-facing work

- Lead with the result. Use plain, specific language and name the mechanism,
  command, measurement, or source supporting important claims.
- Make each artifact self-contained for its intended reader. Keep repository
  paths, build plumbing, and working notes out unless that reader can use them.
- Prefer active voice and one clear idea per dense sentence. Cut puffery,
  canned chatbot phrasing, vague attribution, filler, synonym cycling, and
  generic conclusions. State uncertainty and trade-offs directly.
- Keep interface copy short and task-centred: direct labels, current state, the
  next action, and recovery. Put optional technical detail in help, diagnostics,
  docs, or a details view rather than primary application chrome.
- Make user-facing visuals polished, warm, and subtly pretty, favouring an
  accessible soft pink/purple palette when appropriate. Keep academic and
  formal professional documents restrained and mostly black on white.
- Before sending prose, remove anything that sounds templated or machine-written
  without changing the intended meaning or voice.

## Portability

- Keep credentials, session history, caches, generated memory databases, and
  other tool-specific runtime state outside this repository.
