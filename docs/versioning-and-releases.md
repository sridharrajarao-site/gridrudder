# Versioning and release policy

## Status

GridRudder currently uses a `0.x` development version. A GitHub tag or source archive is not a production-readiness declaration, hardware certification, or authorization to run an attended trial.

## Version scheme

Use Semantic Versioning for the open repository:

- `MAJOR`: incompatible public API, command, configuration, audit-schema, or evidence-format changes after 1.0.
- `MINOR`: backward-compatible capability or material behavior additions. Before 1.0, a minor version may include breaking changes when release notes and migration steps identify them prominently.
- `PATCH`: backward-compatible fixes and documentation corrections that do not broaden privilege or hardware scope.

The package version in `gridgpu/__init__.py`, release tag `vX.Y.Z`, archive name, and release notes must agree. Do not reuse or move a published tag.

## Release classes

- Development preview (`0.x`): simulator/read-only evaluation; no production support.
- Release candidate (`X.Y.Z-rc.N`): immutable candidate for review; not the default recommendation.
- Stable API (`1.0+`): requires a separate architect decision, documented compatibility commitments, migration policy, security-response operations, and production-readiness evidence. None exists today.

## Required release evidence

1. Clean required CI and DCO checks on the exact commit.
2. Version consistency and release notes listing behavior, security, schema, compatibility, and migration changes.
3. A public-package build whose sidecar and internal per-file manifests verify.
4. Secret/PII scan of files and reachable history; private physical evidence and build/deployment state excluded.
5. Dependency/license review and known-vulnerability review.
6. Architect approval for changes to privilege, hardware actuation, safety invariants, audit schemas, or public evidence claims.
7. A signed or GitHub-attested release artifact. Until signing is configured and verified, mark artifacts as unsigned.

## Compatibility and deprecation

Before 1.0, keep compatibility where practical but document every break. Announce deprecation in release notes and runtime output when possible before removal. Version audit and evidence schemas independently when a consumer needs to interpret historical records. Never rewrite immutable evidence to match a new schema.

Only the current default branch is eligible for best-effort security fixes until maintainers publish a supported-version table. A future commercial support policy must remain separate from this source-release policy.
