# Contributing to GridRudder

GridRudder is lab-stage, safety-sensitive software. Contributions are welcome, but a merged change is not evidence that a hardware configuration is safe or supported.

## Start safely

Read [`docs/quickstart.md`](docs/quickstart.md) and begin with the simulator. Hardware discovery must be read-only. Do not run the attended hardware harness on production infrastructure.

## Propose a change

1. Open an issue describing the problem, safety impact, and intended scope. For vulnerabilities, follow [`SECURITY.md`](SECURITY.md) instead.
2. Keep changes small and include tests for normal, failure, stale-data, and restoration paths where relevant.
3. Run `python3 -m unittest discover -s tests -v` from the repository root.
4. Explain any new privilege, network access, telemetry, write action, dependency, or persistent state in the change description.
5. Update public interfaces, audit fields, compatibility limits, and operator instructions when behavior changes.

Contributors must have the right to submit their work. By contributing, you agree that your contribution is licensed under Apache-2.0 and certify it under the [Developer Certificate of Origin 1.1](https://developercertificate.org/). Add a sign-off to every commit with `git commit --signoff`; this appends `Signed-off-by: Name <email>` using your Git identity. The repository’s DCO check requires an author-matching sign-off on each pull-request commit. A sign-off is a contribution certification, not a GPG/SSH signature.

## Safety invariants

- Default to simulation or read-only observation.
- Never add a facility-equipment write path.
- Require explicit enablement, bounded values, exact device identity, attributable approval, durable audit output, and verified restoration for a GPU write.
- Fail closed on stale, missing, malformed, or conflicting telemetry.
- Do not treat GPU-reported watts as proof of whole-server power response.
- Do not add credentials, private customer data, raw production telemetry, or identifying hardware artifacts to commits.

## Reviews and compatibility claims

Maintainers may require an architecture and safety review before merging control, policy, audit, or adapter changes. Compatibility claims must identify the exact GPU, driver, operating system, server/BMC, meter source, workload, and test method. A result from one host does not generalize to a fleet.

Be respectful and follow [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

Release compatibility and support expectations are documented in
[`docs/versioning-and-releases.md`](docs/versioning-and-releases.md),
[`docs/compatibility.md`](docs/compatibility.md), and [`SUPPORT.md`](SUPPORT.md).
