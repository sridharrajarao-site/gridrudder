# Read-only rented-server qualification runbook

Owner: hardware integration engineer  
Approval: Chief Architect for evidence interpretation; rental owner for access  
Scope: NVIDIA board telemetry and independent BMC whole-host watts only

## Safety boundary

This procedure must not invoke `nvidia-smi -pl`, `nvidia-smi -pm`, IPMI chassis
control, raw IPMI commands, power-cycle operations, facility controls, or the
disabled legacy `hardware-trial` CLI. Stop if a requested permission includes a
write capability that is not necessary for the two documented read queries.

## Before connection

1. Record the rental/order identifier without copying passwords, tokens, public
   IP addresses, or personal billing data into the repository.
2. Obtain the expected host identity, BMC FRU chassis serial, GPU UUID, meter ID,
   and physical boundary. Confirm whether redundant PSUs are both represented.
3. Confirm the host is isolated from production workloads and no other tenant is
   sharing its meter boundary.
4. Confirm synchronized UTC time and record the synchronization source/status.
5. Copy the reviewed code by immutable revision. Run the complete local suite.
6. Complete Gate 0 in `hardware-gate-checklist.md` and name the attending operator.

## Collector configuration

Use absolute executable paths. `BmcPowerObserver` accepts only a regular,
non-symlink executable owned by the configured trusted UID and rejects a binary
that is group/world writable or changes hash during collection. Its only allowed
queries are:

- `ipmitool fru print 0` for the expected chassis serial.
- `ipmitool dcmi power reading` for instantaneous whole-host watts.

`NvidiaPowerObserver` is read-only and queries GPU identity, driver version,
power, limit visibility, and related telemetry without a mutation flag. Pin and
record its executable provenance. Configure a fresh source epoch for this run.

Prepare an absolute-path JSON configuration that validates against
`docs/read-only-qualification.schema.json`. It contains identities, executable
paths, sampling/alignment policy, and an approved overhead calibration only; it
must contain no hostname for remote access, SSH setting, password, token, or BMC
network credential.

From a local shell on the qualified rented host, and only after Gate 0 inputs
have been reviewed, run:

```bash
python3 -m gridgpu.qualification_cli \
  --config /absolute/reviewed/qualification-config.json \
  --output /absolute/new/evidence/qualification-packet.json
```

The output path must not already exist. The serializer creates it mode `0600`,
fsyncs canonical JSON, and includes a SHA-256 digest over the complete packet.
Exit code 0 means the configured alignment checks accepted the evidence; exit
code 2 means a packet was retained but qualification was not accepted. Any
exception is a failed collection, never permission to proceed.

## Attended collection

1. Start with three samples at an architect-approved interval; do not run a GPU
   workload or change a power setting.
2. For every sample, collect BMC and GPU readings close enough to meet the
   configured alignment policy.
3. Require exact host, chassis, meter and GPU identity on every collection.
4. Require GOOD quality, synchronized time, increasing sequence, current data,
   acceptable ingest latency, and the approved physical boundary.
5. Feed validated observations to `collect_read_only_qualification`; retain the
   returned packet and alignment reasons whether accepted or rejected.
6. Stop on identity mismatch, executable change, stale/unsynchronized evidence,
   duplicate/regressed sequence, command error, BMC alarm, GPU/driver reset, or
   evidence-storage failure. Do not “fix” a failed run by weakening policy.

## Evidence handling

Retain the code revision, configuration without secrets, executable hashes,
host/chassis/GPU/meter identities, timestamps, raw responses, qualification
packet, validation policy, alignment report, operator, and start/end time. Hash
the packet and anchor its final digest outside the rented host. Treat public IPs,
credentials, vendor account data, and customer workload identifiers as secrets.

## Exit and rollback

Read-only collection changes no GPU or BMC state. Stop the collector, verify no
process remains, copy and verify evidence, remove temporary access material, and
confirm final rental lifecycle/billing separately. A successful Gate 0 result
permits evidence review only; it does not authorize a physical write.

## Exact remaining steps before a write GO

1. Close the read-only shadow/alignment finding in Review 0003 with retained real
   data and architect-approved tolerances.
2. Build a separately reviewed least-privilege physical adapter using pinned
   executables and an explicit allowlist containing only one UUID and bounded
   `set power limit` operation. Persistence changes should remain unnecessary.
3. Implement authenticated, expiring, exact-scope approval and a durable one-use
   nonce registry independent of a caller-selected audit log.
4. Integrate GPU temperature, throttle reasons, ECC/driver health, MIG state,
   workload identity/SLO, emergency stop, and an independent restoration path.
5. Prove audit-before-mutation, partial-command failure, timeout, interruption,
   wrong-target rejection, controller contention, and restoration evidence using
   the exact release artifact.
6. Execute the smallest attended action only after Gate 1 and Gate 2 are signed
   by the Chief Architect and rental/site owner. Automatic operation remains out
   of scope.
