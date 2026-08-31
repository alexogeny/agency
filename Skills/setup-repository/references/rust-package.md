# Rust package baseline

## CI and package setup

The Rust profile installs the declared toolchain with rustfmt and Clippy,
fetches locked dependencies once, verifies formatting, denies Clippy warnings
across targets and features, and tests all features against `Cargo.lock`.
Confirm that the repository commits a lockfile under its package policy and
that the all-features combination is supported before applying the defaults.

Use `--custom-checks` for workspace-aware package selection, feature matrices,
minimum-supported Rust versions, doctests, or repositories that deliberately
test without a lockfile. Do not weaken Clippy or broaden feature combinations
merely to make a generic template fit. The docs workflow runs only the supplied
strict command and deploys its verified output directory.

## crates.io publishing

The publishing workflow checks out the exact GitHub Release tag, compares it to
the single package reported by Cargo metadata, inspects `cargo package --locked`,
obtains a short-lived crates.io credential through the official trusted
publishing action, and runs `cargo publish --locked` from a protected
`crates-io` environment. Configure the matching crates.io trusted publisher
before releasing. The authentication action documents the current OIDC flow:
[rust-lang/crates-io-auth-action](https://github.com/rust-lang/crates-io-auth-action).

The generic workflow intentionally fails its version check for a workspace with
multiple packages. Tailor package ordering, tag conventions, ownership,
`publish = false` members, and partial-release recovery from repository evidence
instead of guessing. Never test the workflow by publishing a real throwaway
version because registry versions are permanent.
