# Python package baseline

## What the templates preserve

The CI template uses pull-request and default-branch triggers, read-only token
permissions, per-ref cancellation, one frozen uv sync, and a stable `checks`
job name. Its defaults run Ruff lint, Ruff formatting verification, ty, then
pytest, all without repeating the sync. The package must declare those tools in
its locked development dependencies and configure their real source and test
scope before the workflow is applied.

The docs template builds on pull requests and deploys only from the default
branch or a manual dispatch. Build and deploy are separate jobs; only deployment
receives Pages and OIDC write permissions. The upload directory must be the
actual clean-build output, not a path inferred from another project.

The publishing template builds the exact GitHub Release tag, uploads an
inspectable distribution artifact, and publishes through a protected `pypi`
environment with OIDC. It stores no API token and does not create tags or
releases. Releasing remains an explicit action outside this workflow.

Issue forms ask for actionable environment, reproduction, and problem evidence.
The pull-request template asks for observable behaviour, verification, and
repeated performance evidence when a speed claim exists.

## Tailor from repository evidence

- Derive the Python version from the supported runtime and existing CI policy.
  Use a matrix only when the package genuinely supports multiple interpreters.
- Prefer the Ruff, ty, and pytest defaults for a new baseline. If an established
  project uses different tools or wrapper commands, use `--custom-checks` and
  derive every replacement from project entry points, dependency groups,
  contributor docs, and successful local checks.
- Keep one environment installation when the checks share dependencies. Split
  jobs only for real platform, permission, service, or failure-isolation needs.
- Add service containers, native compilation, or system packages only when a
  clean local build proves they are required.
- Preserve repository-specific test runners. A wrapper that selects workers,
  markers, or capabilities is part of the test contract, not ceremony to
  replace with bare pytest.
- Treat skipped optional services as visible evidence. Do not turn a missing
  database, compiler, or docs tool into an apparently comprehensive pass.

For native wheels, multiple distributions, or companion packages, replace the
generic publish workflow with a project-specific cibuildwheel matrix and smoke
test every produced wheel before publication. Wreath's release workflow is a
reference for those invariants, not a safe drop-in: its companion ordering,
release branches, resumable tags, and force updates belong to Wreath alone.

Before enabling publishing, verify that `uv build` produces the intended sdist
and wheels from a clean tree, that package metadata names the requested
distribution, and that a `pypi` GitHub environment plus matching PyPI Trusted
Publisher will exist. PyPI versions are immutable; do not test publication by
uploading a real version.
