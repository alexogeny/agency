# Software assessment

Define the unit of assessment: a whole repository, a submitted patch, a single
component, or observable behaviour. Separate defects introduced by the work
from pre-existing or out-of-scope conditions whenever the evidence permits.

## Gather evidence proportionately

- Read the specification, repository guidance, architecture, and relevant tests
  before choosing criteria.
- Inspect the implementation paths that determine the requested behaviour.
- Run focused tests, static checks, or reproducible scenarios when safe and
  useful. Record exact commands, results, and environmental limitations.
- Do not mutate the work merely to grade it. Temporary test artifacts belong in
  the configured scratch location or an isolated sandbox and must not contaminate
  the repository.

## Select relevant quality criteria

- **Requirements and correctness:** required behaviour, edge cases, error
  handling, compatibility, and observable regressions.
- **Design and maintainability:** clear boundaries, appropriate abstractions,
  legible control flow, naming, cohesion, and fit with the existing system.
- **Verification:** meaningful coverage of important behaviour, test quality,
  determinism, and whether claims are supported by passing checks.
- **Security and reliability:** trust boundaries, validation, failure modes,
  resource handling, concurrency, and recovery where relevant to the task.
- **Performance:** measured or structurally justified efficiency where the
  requirements make it consequential; do not reward cleverness alone.
- **Documentation and operability:** interfaces, setup, migration, diagnostics,
  and maintenance guidance needed by actual users or operators.

A passing test suite is evidence, not proof of correctness. Likewise, style
preferences are not defects unless they impair comprehension, violate an
applicable standard, or create concrete maintenance risk. Rank findings by user
impact and confidence, and cite files and lines for consequential judgements.
