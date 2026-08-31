# JavaScript and TypeScript package baseline

## CI and package setup

Use the `javascript` profile for JavaScript packages and `typescript` for
packages whose checked source is TypeScript. Both use Bun, require a committed
`bun.lock`, install once with `bun install --frozen-lockfile`, and run Prettier,
ESLint, and Bun tests. TypeScript additionally runs `tsc --noEmit`.

Before applying the workflow, declare Prettier and ESLint in locked development
dependencies, add project-appropriate ignore and configuration files, and run
the rendered commands locally. The TypeScript profile also needs TypeScript and
a checked `tsconfig.json`. Tailor generated-code, fixtures, build output, and
workspace scopes explicitly; a formatter silently scanning vendored output is
not a useful gate.

Use `--custom-checks` when the repository already exposes stable package scripts
such as `bun run lint`, `bun run format:check`, `bun run typecheck`, and
`bun test`. Preserve those scripts rather than bypassing project-specific
selection or workspace orchestration.

## Documentation and npm publishing

The docs workflow performs one frozen Bun install, runs the exact supplied
strict build command on pull requests, and deploys the supplied output only on
the default branch or manual dispatch.

The npm workflow checks out the exact GitHub Release tag, verifies it against
`package.json`, previews the tarball, and publishes with provenance from a
protected `npm` environment. It uses npm trusted publishing and stores no
long-lived registry token. Configure a matching trusted publisher on npm with
the exact owner, repository, workflow filename, and environment before a real
release. See [npm trusted publishers](https://docs.npmjs.com/trusted-publishers/).

Confirm the package's `files`, exports, build hooks, access level, and scoped
package policy from a local `npm pack --dry-run`. Monorepos and multiple
packages need a project-specific release matrix; do not apply the single-package
workflow unchanged.
