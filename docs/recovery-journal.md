# Durable intent and manual recovery readiness

`gridgpu.recovery_journal` is a hardware-free building block, not an OS watchdog
or automatic restoration service. It is not wired into the existing trial runner.

Use one new journal per trial in an existing trusted local directory. Intent binds
the exact trial, host, GPU, authorization digest, original/capped limits and UTC
time. `journal_then_actuate` writes and fsyncs intent and its directory before
invoking an explicitly injected action. Any write, durability or existing-file
failure prevents that callback. A callback failure leaves an unfinished intent.
The wrapper does not verify authorization itself; the attended orchestrator must
do that and must retain its host/GPU exclusive lock throughout the experiment.

On restart, enumerate the externally maintained trial inventory and inspect each
expected journal. A missing or corrupt journal blocks new actuation; absence is
never evidence of restoration. An open intent means the action may have happened,
even when the process crashed before issuing a command. Inject a fresh trusted
device observation with exact host/GPU identity. The pure planning helper requests
observation, attended restoration, or recording verified restoration. It issues no
hardware commands. Closure requires an original-limit observation at or after
intent time, then appends and fsyncs a chained closure record. The caller must
enforce observation freshness and provenance; a source ID is not authentication.
A closed record is historical evidence, not a claim about the current GPU state.
If closure writing or fsync fails, the call raises and that journal instance
refuses further reads or closure attempts because durability is uncertain. A torn
record also fails validation after reopening. A fully written but unsuccessfully
fsynced closure may still be readable by a new process; readable bytes cannot
establish that a previous fsync succeeded. Reconcile uncertain storage and obtain
fresh device observations rather than treating such an error as successful closure.

Records detect corruption and broken chaining. They do not resist a privileged
attacker rewriting the entire journal or deleting a tail; removal of closure leaves
the conservative unfinished state. Directory substitution, remote-filesystem
durability, disk failure, concurrent separate trial files, trusted observation
collection, immutable ownership and restart inventory remain deployment concerns.
Use trusted parent directories and an OS-enforced single active trial policy.

Still required before a hardware session: integrate with the actual trial and
broker, durably export metering/workload evidence, verify recovery under process
kill/reboot, and establish an independent attended restoration procedure.
