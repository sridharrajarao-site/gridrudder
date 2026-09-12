# Release Evidence Packaging

Implementation: `gridgpu/evidence.py`  
Scope: Simulator Gate B evidence; not physical-actuation authorization

## Purpose

Scenario producers are deliberately decoupled from the gate. `package_release_evidence` converts generic mapping/object results into the contract accepted by `evaluate_gate_b`, retains canonical raw output, binds it to release identities, and records that binding in the append-only audit log.

## Input contract

Each result supplies:

```text
scenario_id or kind   safe non-empty identifier (Enums are accepted)
passed                boolean
findings              list or tuple of non-empty strings
metrics               mapping of names to finite numeric values
invariants            non-empty mapping of names to booleans
```

Packaging also requires JSON-representable artifact, configuration, and input identities; a non-empty policy version; an output directory; and an `AuditLog`. It imports no benchmark or fault module.

## Packaging sequence

Before mutation, the packager normalizes every result, rejects duplicate IDs, and canonicalizes/hashes all supplied identities. It then performs this sequence for each scenario:

1. Serialize the raw scenario record as canonical JSON: UTF-8, sorted keys, compact separators, and no NaN or infinity.
2. Create `<scenario_id>.json` with exclusive-create semantics and mode `0600`; existing evidence is never overwritten.
3. Flush and `fsync` the raw file.
4. Append `release.scenario_evidence` to the audit log, including scenario, release digests, raw digest/reference, result, and invariants.
5. Verify the complete audit chain and read its head.
6. Require that the verified head is the record just appended. Concurrent/unexpected advancement is an error.
7. Return a Gate-B-compatible mapping containing metrics and evidence.

An audit append failure removes the newly created raw file because no audit record references it. Once audit append succeeds, the file is retained even if later verification fails; deleting it would make the durable audit reference false.

## Identity and data digests

Artifact, configuration, input, and raw records are hashed using SHA-256 over canonical JSON. Digests are formatted as `sha256:<lowercase hex>`, except the Gate B `audit_head_hash`, which is the raw 64-character chain hash required by the gate.

Canonical structured identities should contain enough information to reproduce the release, for example:

```json
{
  "artifact": {"version": "git-or-build-id", "files": {"path": "sha256:..."}},
  "configuration": {"scenario_set": "gate-b-v1", "control_interval_seconds": 5},
  "input": {"fixture_manifest": "sha256:...", "seed": 0}
}
```

Hashing a label proves only that exact label was supplied. Release tooling should hash an artifact manifest containing actual file digests, not merely a friendly version string.

## Filesystem safety

- Scenario IDs permit only letters, digits, dot, underscore, and hyphen; slash, absolute paths, whitespace prefixes, `.`/`..`, and traversal are rejected.
- Targets are formed only beneath the resolved configured directory.
- Files use `O_EXCL` and, where supported, `O_NOFOLLOW`.
- Existing raw evidence causes the complete call to stop before appending audit records.
- Duplicate scenario IDs are rejected before writes.
- NaN, infinity, non-string metric/invariant names, nonboolean invariants, and unsupported JSON objects are rejected.

The caller remains responsible for securing the parent directory, storage volume, backups, retention, and access permissions. A hostile administrator with directory and audit-log access is outside this local mechanism's protection.

## Local-chain limitation

The audit chain detects accidental/unauthorized modification, insertion, middle deletion, and reordering relative to the retained chain. It is an unkeyed local hash chain. An attacker able to rewrite the entire file can rebuild it, and clean tail deletion cannot be detected without an external anchor.

For partner or production evidence, periodically sign or publish the chain head to an independently controlled, append-only system and bind authenticated operator/service identities at ingress. The returned `audit_head_hash` must not be described as a digital signature or immutable external timestamp.

## Operational use

1. Create a new, access-controlled evidence directory for one release attempt.
2. Run scenarios from the identified artifact and collect generic results plus invariants.
3. Call `package_release_evidence` once with the complete result collection.
4. Pass returned mappings to `evaluate_gate_b`.
5. Retain raw JSON, audit JSONL, gate decision, artifact manifest, and any external head anchor as one evidence packet.
6. Never edit or reuse an existing scenario file. A rerun receives a new release/evidence directory and identity.

Packaging does not make a failed result pass. Findings and false invariants remain in the returned result, and Gate B correctly returns NO-GO.
