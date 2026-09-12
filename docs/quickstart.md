# Safe quickstart

GridRudder defaults to simulation and read-only inspection. Nothing in this quickstart authorizes a hardware write.

## Requirements

- Python 3.9 or newer.
- No third-party Python packages for the simulator and tests.
- A copy of this repository on a development machine.

Run commands from the `grid-to-gpu` directory.

## 1. Run the simulator

```bash
python3 -m gridgpu demo --output artifacts/demo-local.jsonl
python3 -m gridgpu benchmark
```

The demo creates local JSONL audit evidence. Inspect it before continuing; do not commit a run artifact until it has passed the sanitation checklist.

## 2. Run the tests

```bash
python3 -m unittest discover -s tests -v
```

## 3. Verify an audit artifact

```bash
python3 -m gridgpu verify-audit artifacts/demo-local.jsonl
```

## 4. Optional read-only NVIDIA probe

On a machine with NVIDIA tooling installed:

```bash
python3 -m gridgpu probe-nvidia
```

The probe is intended to be read-only and reports whether a power limit appears writable; it does not change that limit. Review its output for host identifiers before sharing it.

## Attended performance boundary: separate path

Stop here for normal evaluation. The legacy `hardware-trial` CLI is disabled. It must not be copied, re-enabled, or treated as a next quickstart step.

New physical integrations must use the library-level `performance_trial` boundary and supply reviewed adapters; there is intentionally no general-purpose hardware CLI. Before developing an integration, complete [`design-partner-pilot.md`](design-partner-pilot.md), [`hardware-gate-checklist.md`](hardware-gate-checklist.md), and the organization’s own change approval. The boundary requires exact-scope authorization, fresh attended confirmation, exclusive locking, exact GPU and chassis identity, workload hashing, repeated timestamped independent-meter evidence, durable audit output, and verified restoration. An operator must remain able to stop and restore the host.

GridRudder does not control facility equipment and is not an electrical protection system or an autonomous production controller.
