# Safe quickstart

GridRudder defaults to simulation and read-only inspection. Nothing in this quickstart authorizes a hardware write.

## Requirements

- Python 3.9 or newer.
- No third-party Python packages for the simulator and tests.
- A copy of this repository on a development machine.

Run commands from the repository or extracted source root: the directory
containing `gridgpu/` and `README.md`. The public clone is named `gridrudder`;
the source archive extracts to `gridrudder-public-preview`.

This preview runs directly from source. It does not require `pip install`,
root access, a GPU, or a rental for simulation.

## 1. Run the simulator

```bash
python3 -m gridgpu demo --output artifacts/demo-local.jsonl
python3 -m gridgpu benchmark
```

The demo creates a local JSONL simulation trace. This trace is not the
hash-chained audit format consumed by `verify-audit`. Inspect it before
continuing; do not commit a run artifact until it has passed the sanitation
checklist.

## 2. Run the tests

```bash
python3 -m unittest discover -s tests -v
```

## 3. Generate and verify a synthetic audit artifact

```bash
python3 -m gridgpu gate-b-release --output artifacts/gate-b-local
python3 -m gridgpu verify-audit artifacts/gate-b-local/release-audit.jsonl
```

The output directory must be new; choose a different name for each run.
Gate B checks simulated scenarios and does not establish hardware readiness.

## 4. Optional read-only NVIDIA probe

On a machine with NVIDIA tooling installed:

```bash
python3 -m gridgpu probe-nvidia
```

The probe is strictly read-only and always reports `power_limit_writable=false`;
it does not test or change power limits. Review its output for host identifiers
before sharing it.

## Attended performance boundary: separate path

Stop here for normal evaluation. The legacy `hardware-trial` CLI is disabled. It must not be copied, re-enabled, or treated as a next quickstart step.

New physical integrations must use the library-level `performance_trial` boundary and supply reviewed adapters; there is intentionally no general-purpose hardware CLI. Before developing an integration, complete [`design-partner-pilot.md`](design-partner-pilot.md), [`hardware-gate-checklist.md`](hardware-gate-checklist.md), and the organization’s own change approval. The boundary requires exact-scope authorization, fresh attended confirmation, exclusive locking, exact GPU and chassis identity, workload hashing, repeated timestamped independent-meter evidence, durable audit output, and verified restoration. An operator must remain able to stop and restore the host.

GridRudder does not control facility equipment and is not an electrical protection system or an autonomous production controller.
