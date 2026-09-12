# Gate B Executable Coverage Specification

Status: Assurance baseline  
Authority: Chief Architect  
Implementation: `gridgpu/gates.py`

## Decision rule

Gate B is **GO only when every required scenario appears exactly once, reports `passed` as the boolean value `true`, has no unresolved findings, satisfies independent executable metric predicates, and supplies a primary trace whose verifier independently proves every required invariant**.

The evaluator fails closed on:

- absent required scenarios;
- duplicate scenario IDs;
- a failed, missing, or truthy-but-nonboolean pass claim;
- malformed result objects, metrics, findings, evidence, or identifiers;
- missing/non-finite metrics;
- metrics that contradict scenario semantics even when all producer booleans are true;
- missing or false producer invariant claims;
- missing primary trace digest, mismatched verifier digest, or verifier facts that do not independently prove the invariants;
- incomplete artifact/configuration/policy/input/raw-data provenance;
- an invalid audit-chain head hash;
- any non-empty finding.

An extra scenario is allowed only if it is itself well formed and has complete common evidence. The gate never selects between duplicates based on ordering.

## Producer-neutral result contract

The evaluator accepts a mapping or an ordinary object. It imports neither the current benchmark module nor a future fault-injection module.

Required fields:

```text
scenario_id (or kind)  non-empty string or string-valued Enum
passed                 exact boolean true
findings               empty list or tuple of non-empty strings
metrics                mapping of string -> finite numeric value
evidence               mapping described below
```

Evidence fields required for every result:

```text
artifact_version       non-empty release/build identity
configuration_digest   non-empty immutable configuration identity
policy_version         non-empty policy identity
input_digest           non-empty input/fixture identity
audit_head_hash        64 lowercase hexadecimal SHA-256 characters
raw_data_reference     non-empty reference to retained raw evidence
primary_trace_digest   sha256:<64 lowercase hexadecimal characters>
invariants             mapping of required invariant name -> exact boolean true
trace_verifier         independent verifier identity/version, matching trace digest, and facts
```

`trace_verifier` has this shape:

```json
{
  "verifier_id": "non-empty verifier implementation identity",
  "verifier_version": "version or artifact identity",
  "primary_trace_digest": "sha256:...same as evidence.primary_trace_digest...",
  "facts": {"required_invariant_name": true}
}
```

Producer `invariants` remain useful for discrepancy detection, but they are never sufficient. Every required invariant must also be exactly true in verifier facts bound to the same primary trace digest.

The hash-chain head proves consistency only relative to its retained/anchored context; the gate does not claim that an unkeyed local chain is adversary-immutable.

## Required coverage matrix

The executable source is authoritative for exact metric and invariant names. The required scenario IDs and purposes are:

| Scenario ID | Required behavior |
|---|---|
| `normal_constraint` | Feasible envelope is met after settling without protected-workload or policy-bound violation. |
| `infeasible_constraint` | Shortfall is explicitly quantified and no unsafe action occurs. |
| `rebound_recovery` | Recovery ceiling and ramp are respected without oscillation. |
| `stale_meter` | Stale data inhibits new actuation and produces an operator reason. |
| `meter_loss` | Mid-event authoritative-meter loss applies the approved existing-action policy and inhibits new action. |
| `meter_stale` | An injected stale-meter fault reaches safe hold with evidence. |
| `meter_duplicate` | Duplicate/replayed sequence is rejected without advancing state. |
| `meter_reorder` | Regressed/reordered sequence is rejected without advancing state. |
| `clock_jump` | Future/backward/unsynchronized time fails closed. |
| `optimizer_timeout` | Partial/timed-out plan is never executed. |
| `optimizer_invalid_output` | Malformed optimizer output is rejected and only the approved fallback is selected. |
| `scheduler_unavailable` | Unavailable scheduler state prevents workload mutation. |
| `scheduler_rejection` | A scheduler rejection is not treated as successful mutation. |
| `adapter_unavailable` | Failed/unknown actuation is never assumed successful. |
| `adapter_rejection` | Adapter rejection is not treated as successful actuation. |
| `audit_failure` | Failure to persist intent prevents mutation. |
| `controller_restart` | State is reconstructed; expired commands are not replayed; operator resume is required. |
| `split_brain` | Single writer/lease fencing prevents stale-controller commands. |
| `manual_conflict` | Manual/site control wins and automatic event is cancelled. |
| `interrupted_recovery` | A recovery interruption inhibits further increase and reaches recovery hold. |
| `protected_mislabel_attempt` | Mislabeling cannot bypass protected-workload enforcement. |

This matrix includes the four current standard benchmarks and every fault ID in the current canonical assurance fault matrix. A unit test of a low-level helper may contribute evidence, but the scenario result must represent an end-to-end contract at the correct boundary and retain its raw data. Adding a new canonical fault requires adding a corresponding gate requirement in the same architecture change; otherwise the gate specification is incomplete and remains NO-GO.

## Independent semantic predicates

`ScenarioRequirement.metric_predicates` contains executable rules owned by the gate specification, not by benchmark producers. Current rules require:

- normal constraint: positive sample coverage, zero maximum exceedance, and zero critical-cap actions;
- infeasible constraint: positive exceedance, explicit positive shortfall, positive shortfall record count, and shortfall equal to observed maximum exceedance;
- rebound recovery: positive recovery coverage, zero rebound exceedance, and non-negative peak power;
- stale meter: decision eligibility exactly zero and positive sample age;
- every fault: fault count exactly one and its forbidden-effect counter exactly zero.

The evaluator runs these rules after numeric/schema validation and accumulates all failures. A producer cannot make contradictory metrics pass by setting `passed` or invariants to true.

## Coverage evaluation

`evaluate_gate_b(results)` returns:

- `go`: final boolean;
- `reasons`: every observed NO-GO reason, not merely the first;
- `required_scenario_count`;
- `received_scenario_count` (unique valid IDs observed);
- `missing_scenario_ids` in stable sorted order.

The default requirements are immutable tuples of `ScenarioRequirement`. Tests or future architecture versions may pass a different requirement sequence explicitly, but release tooling must pin and record the gate-spec version. A requirement set containing duplicate or malformed requirements is itself a NO-GO.

## Interpretation of current benchmarks

Current `BenchmarkResult` objects expose `kind`, `passed`, `metrics`, and `findings`, so the evaluator can read their generic shape. They do not yet carry the required evidence mapping, and the current four scenarios do not cover the fault matrix. Passing the current benchmark command therefore remains useful engineering evidence but correctly produces **Gate B NO-GO** when evaluated against this specification.

## Release use

1. Run all deterministic standard and fault scenarios from a version-identified artifact.
2. Persist raw inputs, configuration, policy, audit log, and outputs.
3. Convert each producer result to the generic result contract without changing its measured values.
4. Evaluate the complete collection once.
5. Store the gate decision and reason list in the release evidence packet.
6. Treat any evaluator exception, malformed input, or incomplete result as NO-GO; do not manually reinterpret it as a pass.

Gate B authorizes only the simulator milestone. It does not authorize physical actuation or replace the separate hardware and shadow-pilot gates.
