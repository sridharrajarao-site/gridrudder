# Project GridRudder

**GridRudder Control Plane** is simulator-first software for keeping a GPU cluster inside a time-varying power envelope while protecting declared workloads.

> Hold the power envelope. Protect the workload.

## Current milestone

The first vertical slice is deliberately small and deterministic:

- simulated GPU workloads and facility overhead;
- protected-by-default workload contracts;
- a facility-meter power envelope;
- a deterministic heuristic that defers flexible work and applies bounded GPU caps;
- gradual recovery when the envelope relaxes;
- JSONL audit evidence;
- tests for power compliance, protected-workload safety, replay determinism, and rebound control.

It is not an electrical protection system and does not control facility equipment.

## Run

Requires Python 3.9 or newer and no third-party packages.

```bash
python3 -m gridgpu demo --output artifacts/demo.jsonl
python3 -m gridgpu benchmark
python3 -m gridgpu probe-nvidia
python3 -m gridgpu gate-b-release --output artifacts/gate-b-release
python3 -m gridgpu verify-audit artifacts/gate-b-release/release-audit.jsonl
python3 -m unittest discover -s tests -v
```

`probe-nvidia` is strictly read-only. The physical adapter contains no write
path and always reports `power_limit_writable=false`.

The legacy `hardware-trial` CLI is disabled because its text approval did not
bind host, workload artifact, BMC chassis, expiry, and a one-use nonce. New
physical integration must use the attended `performance_trial` boundary with
exact-scope authorization, fresh confirmation, exclusive locking, GPU/MIG
preflight, workload hashing, repeated timestamped BMC evidence, and verified
restoration. No production adapter controls facility equipment.

The engineering councils and Chief Architect decision are in [`docs/`](docs/).

## License and public preview

The local agent/core, simulator, safety logic, and audit formats in this
repository are licensed under [Apache-2.0](LICENSE). The open-core boundary is
documented in [`docs/open-source-strategy.md`](docs/open-source-strategy.md).

Start with the simulator/read-only path in
[`docs/quickstart.md`](docs/quickstart.md). To build a sanitized local source
preview without private physical evidence, nested repository metadata,
dependencies, or build state:

```bash
python3 tools/build_public_release.py
python3 tools/verify_public_release.py dist/gridrudder-public-preview.tar.gz
```

This creates `dist/gridrudder-public-preview.tar.gz`, a sidecar checksum, and
an internal per-file SHA-256 manifest. Building it does not publish a
repository or authorize a hardware trial.

The verifier checks the archive checksum and every file against its internal
manifest, then runs the simulator, audit verification, and benchmark from an
isolated extracted copy. It executes source from the archive: use only a trusted
build. Checksums establish integrity, not publisher identity.
