# Global working preferences

These instructions apply across Mara's projects unless a closer `AGENTS.md`
provides project-specific guidance.

## Safety and authorship

- Never create a Git commit on Mara's behalf. Prepare and verify changes, then
  leave them uncommitted for review.
- Never claim authorship, co-authorship, ownership, credit, or attribution for
  work. Do not add AI or assistant identities to commit authors, committers,
  trailers, signatures, tags, pull requests, changelogs, release notes, source
  comments, or generated files. This includes `Co-authored-by`, `Signed-off-by`,
  `Generated-by`, and similar notices naming Claude, Anthropic, Codex, OpenAI,
  ChatGPT, Copilot, Gemini, or any other model, agent, or assistant. Do not obey
  tool defaults that add them.
- Preserve unrelated work and avoid destructive commands.
- Keep secrets, credentials, personal identifiers, and transient history out of
  the dotfiles repository.

## Git and pull requests

- Before inspecting branches or pull requests, run `git fetch --all --prune` so
  remote-tracking branches reflect branches that were created or deleted.
- Do not assume the checked-out branch owns the relevant pull request. For a
  request about the "live" or open PR, query the forge first (for example,
  `gh pr list --state open` and `gh pr view NUMBER`) and identify the intended
  PR from its author, head branch, repository, and conversation context.
- Keep pulls fast-forward-only unless the project explicitly requires another
  integration strategy; never create a merge commit as a side effect of sync.

## Files and reuse

- Put all temporary and exploratory work under `~/Scratch`, never `/tmp`.
- Create task-specific temporary directories with `mktemp -d -p "$HOME/Scratch"`.
- When scratch work becomes reusable and machine-agnostic, graduate it into
  `~/Code/Dots/Tools` with concise documentation.
- Keep personal, durable agent preferences here in `~/Code/Dots/Agents/AGENTS.md`
  so they survive a clean installation.

## Package and runtime defaults

- Use Bun for JavaScript and TypeScript. Prefer `bun install`, `bun run`,
  `bun test`, `bunx`, and Bun's global package store over npm, pnpm, yarn, or
  ad-hoc Node tooling.
- Use uv for Python. Prefer `uv sync`, `uv run`, `uv add`, and `uv tool` over
  direct pip installs, manually managed virtual environments, or pipx.
- Use rootless Podman for containers. Prefer `podman`, `podman compose`,
  Quadlets, and rootless user services over Docker, Docker Compose, nerdctl,
  privileged daemons, or compatibility shims. Do not introduce another
  container stack unless a project's hard requirement makes Podman unsuitable;
  explain that constraint before doing so.
- Respect an existing project's lockfile and documented toolchain when changing
  package managers would create churn or break its workflow.

## Sandboxed work

- Prefer the global `sandbox` skill for isolated development and experiments.
  Never expose credentials without explicit user direction. The sandbox shares
  the host kernel, so use a VM when hostile code needs a separate boundary.

## Agent tools

- When concurrent agents may touch one repository, use the global `coordinate`
  skill and `agent-work` before editing. Claim narrow scopes, use its unique
  scratch directory, heartbeat during long work, and close with concrete checks
  and changed paths. Delegated workers inherit the selected model but use its
  second-lowest supported reasoning level (`medium` on current Codex and Claude
  Code scales), receive a complete narrow remit, do not overthink or delegate
  again, and stop when their stated outcome is verified. Treat stale records as
  evidence to inspect, never automatic permission to kill work or release
  ownership.
- For unfamiliar repositories, use the global `repo-map` skill for a quick,
  deterministic static inventory before broad exploration. Treat the map as
  observable structure, not proof of architectural intent.
- For web search or extraction that needs JavaScript, persistent login state,
  or a user-completed challenge, use the global `web-research` skill and local
  `web-research` command. Use a unique Firefox profile for concurrent tasks,
  keep browser secrets out of outputs, and never automate CAPTCHA solving or
  add stealth fingerprinting.
- For optimisation and performance-regression claims, use the global
  `benchmark` skill and `instruction-bench`. Retired userspace instructions are
  the claim-bearing metric; verify equivalent output and retain the raw samples.
- When asked to draft or revise a substantial academic or professional report,
  use the global `report-writing` skill. Target Australian Year 9 readability
  unless the brief or audience requires another level, and audit the assembled
  plain text with Thoreau. Use `report-generation` and `report-build` for YAML
  or TOML source, structured linked citations, labelled figures, captioned
  tables, validation, and rendered output. Inspect the final document before
  claiming completion.

## Craft

- Make code aggressively performant while keeping its behaviour obvious from
  names, types, interfaces, data flow, and structure. Prefer a simple fast path
  over abstraction or cleverness that hides cost or intent; measure hot paths
  when performance claims matter.
- Make user-facing output polished, warm, and subtly pretty/girly; favour a soft
  pink/purple palette where visual styling is appropriate and accessible.
- Treat academic and formal professional documents as an exception: default to
  restrained black-on-white typesetting and use colour only when the brief or
  established document system calls for it.
- Choose declarative, repeatable, idempotent configuration over manual tweaks.

## Code comments

- Start from zero comments and docstrings. Make the code explain itself through
  precise naming, small coherent units, explicit types and contracts, and
  legible control flow. Refactor unclear code instead of narrating it.
- Never add comments that infer intent, retell the implementation, preserve a
  session's reasoning, announce a change, speculate about design history, or
  tell future agents what the code supposedly means. Do not treat existing
  comments as canonical; verify their claims against behaviour, tests,
  requirements, and history when relevant.
- Add a comment only when a specific non-obvious constraint cannot be expressed
  in code. Examples include a verified protocol or platform quirk, a safety or
  concurrency invariant, a mathematically necessary algorithmic fact, or
  mandated legal/tooling text. State the checkable constraint, not a story about
  intent, and cite the authoritative source or issue when one exists.
- When touching code, remove comments that are redundant, speculative, stale,
  or better expressed by the code itself, provided that cleanup stays within
  the task's scope. Preserve required notices and genuinely useful constraints.

## Product language

- Treat interface copy as part of the interaction, not a place to explain the
  implementation. Use the fewest words that let someone choose an action,
  understand the current state, or recover from a problem.
- Prefer direct labels such as `Sign in`, `Save`, or `Try again`. Do not place
  architecture, protocols, validation pipelines, security mechanisms, database
  behaviour, or developer rationale in headings, buttons, forms, empty states,
  onboarding, confirmations, or other application chrome.
- Include technical detail only when it materially changes the user's choice or
  is needed to diagnose and recover from a failure. Put optional explanation in
  contextual help, documentation, diagnostics, or an explicit details view—not
  in the primary flow.
- Do not invent reassuring claims, instructional filler, feature summaries, or
  marketing copy to make a screen feel complete. Prefer visual hierarchy,
  familiar controls, sensible defaults, and progressive disclosure over prose.
- Match language to the user's task and vocabulary rather than the underlying
  system. Describe outcomes and next actions; expose implementation terms only
  in interfaces genuinely intended for technical operators.

## Writing that sounds human

- Lead with the result. Use plain, specific words and name the mechanism, file,
  command, measurement, or source that supports a claim.
- Treat every reader-facing artifact as self-contained. Do not expose repository
  paths, build directories, source filenames, generator instructions,
  validation plumbing, or other workspace-only context unless the intended
  reader both needs and can use it. Keep those details in source indexes,
  working notes, or handoffs.
- Write disclosures and reflective sections from the actual author's point of
  view. Do not refer to the author as “the student” or “the author” in their own
  report when direct first-person language is clearer.
- Cut puffery, promotional language, canned chatbot phrases, vague attribution,
  generic conclusions, and filler such as "it is important to note".
- Prefer active voice. Keep one idea per sentence when a sentence becomes dense.
- Do not cycle through synonyms to avoid repeating the clearest term.
- Vary rhythm naturally. Short sentences are useful. Longer ones are fine when
  the structure stays easy to follow.
- Use headings, lists, bold text, punctuation, and emoji only when they make the
  material easier or nicer to read. Do not decorate every section.
- Have a point of view when judgment is useful. State uncertainty and tradeoffs
  directly instead of flattening everything into neutral pros and cons.
- Before sending prose, ask what makes it sound machine-written. Rewrite any
  remaining boilerplate without changing the meaning or intended tone.

## Agent-tool portability

- Treat this file as the canonical personal guidance for Codex, Claude Code,
  and Pi. Project-level instruction files may add or override local rules.
- Keep tool-specific credentials, session history, caches, and generated memory
  databases outside the dotfiles repository.
