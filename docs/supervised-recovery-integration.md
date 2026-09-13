# Supervised recovery integration seam

Wrap the reviewed PowerControl in `JournaledPowerControl` and pass that wrapper
as `run_attended_performance_trial(control=...)`. The recovery intent must bind
the same host, GPU, target, captured original limit and authorization digest.
Its mandatory `verify_intent` callback must verify that exact binding against the
active attended authorization. The existing trial still owns authorization,
audit-before-write, workload checks and its exclusive host/GPU lock.

The wrapper verifies the original during preflight, fsyncs a new intent before
the cap, and closes the journal only after exact original-limit readback.
Repeated restoration requests after closure only verify unchanged state; they
do not issue another write. A failed cap remains recoverable. A journal failure
never authorizes a cap, and closure uncertainty remains an error even if hardware
has been restored. Exact readback intentionally rejects rounding differences that
the outer trial may tolerate. Resolve supported precision during qualification.

For process-loss recovery, `reconcile_attended_once` reads the expected journal,
acquires the same host/GPU lock and rechecks it. The caller must independently
prove the original process and all its workload children are gone. Recovery
requires an exact intent digest, an unexpired approval, a fresh typed operator
confirmation, and atomic verification/consumption of the approval nonce. Only one
restoration callback is attempted; fresh source/device-bound observations must
then prove the original before durable closure. Already closed records are
historical records, not current-device health guarantees.

The restore callback receives the complete intent and must be an OS-enforced
broker restricted to that GPU and captured original limit. A newly constructed
NVIDIA experiment adapter cannot simply preflight a capped GPU and rediscover the
original; the original must come from trusted journal and approval records.

The time budget is cooperative, checked after injected calls return. This is
neither a running OS watchdog nor a hard interrupt. No hardware CLI, background
daemon, remote transport or automatic recovery is enabled. Required deployment
work remains: independently supervised process lifecycle, kill/reboot detection,
bounded broker I/O, workload-child draining, protected persistent journal inventory,
fresh authenticated observations, durable approval nonce storage, crash/restore
testing on the actual server, and an independent attended emergency procedure.
The tests simulate loss of in-memory wrapper state; they do not establish behavior
under SIGKILL, kernel panic, host power loss or real GPU/driver failures.
