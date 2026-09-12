# Independent Primary-Trace Verification

`gridgpu.trace_verifier.verify_primary_trace` is the Gate B trust boundary for all four standard and seventeen fault scenarios. It never reads producer `passed`, `findings`, `metrics`, or `invariants`. It recomputes the exact gate metric names and invariant facts from canonical trace rows, inputs, configuration, raw facts, and injection/mutation ledgers.

The returned record contains verifier identity/version, scenario identity, derived metrics/facts, and a `sha256:` digest over the complete canonical primary-trace packet. Evidence packaging must store that digest as `primary_trace_digest` and copy the verifier identity, version, digest, and facts into `trace_verifier`.

Verification fails closed for an unknown or mismatched scenario, unsupported standard schema version or integrated-fault shape, non-canonical/non-finite data, missing/extra/reordered sample or stale-meter rows, discontinuous ledgers, missing/duplicate/unconsumed injections, injection identity/count conflicts, mutation rows not explained by the primary trace, raw-count contradictions, and forbidden post-fault mutation.

For standard scenarios the verifier recomputes envelope exceedance, shortfall magnitude/count, recovery power/rate/oscillation, protected-workload changes, policy cap bounds, and stale-meter eligibility from the raw rows. For faults it binds one consumed injection to the scenario, reconciles trace/session/mutation ledgers, and derives each containment fact from scenario-specific evidence and state transitions. A false derived fact remains false; the release gate will reject it even if every producer claim says true.

This verifier establishes deterministic semantic consistency for the current simulator trace schemas. Its unkeyed digest detects changes only when compared with a separately retained or anchored expected digest; it is not proof against an attacker who can replace both an artifact and all local evidence.
