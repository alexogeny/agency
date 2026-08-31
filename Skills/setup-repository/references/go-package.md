# Go module baseline

## CI and package setup

The Go profile uses the declared Go version, downloads module dependencies once,
rejects files that `gofmt` would change, runs `go vet ./...`, and runs
`go test ./...`. Require committed `go.mod` and `go.sum` files and verify all
three checks from a clean checkout before applying the workflow.

Tailor module or workspace selection when `./...` is not the repository's real
test boundary. Add race detection, platform matrices, generated-code checks,
integration services, or staticcheck only when the project supports and runs
them locally. Keep expensive platform work separate from the stable `checks`
job required by the baseline ruleset.

The docs workflow runs a supplied strict generator or site builder and deploys
only its verified output directory.

## Publishing

Go modules are published by pushing an immutable semantic-version Git tag, not
by uploading through a generic registry workflow. The setup tool therefore
refuses a Go `publish` component. Verify the module path and version suffix,
create the version tag through the repository's authorised release process,
push it, and request the version through the public proxy when appropriate.
Follow the [official Go module publishing guide](https://go.dev/doc/modules/publishing/).

Compiled CLI archives, checksums, signatures, and GitHub Release assets are a
separate project-specific release concern. Do not confuse those artifacts with
publishing the Go module itself.
