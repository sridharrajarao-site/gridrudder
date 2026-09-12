# Complete, fresh measurement collection

Pass a `CompleteFreshCollector` instance as `BenchmarkRunner(collector=...)`.
Its underlying collector accepts a `CollectionRequest`, including an immutable
tuple of expected job IDs and a cooperative monotonic deadline. The trusted
fixed-job scheduler supplies IDs before collection. Return exactly one outcome
per ID, including explicit failed outcomes. Missing, duplicate or extra outcomes
invalidate the window. Do not derive the expected list from successful results.

Injected aware UTC and monotonic clocks bind meter timestamps to this invocation
and reject a stale but internally chronological historical run. Clock disagreement,
early returns, deadline overruns and reused phase/repetition requests fail closed.
Any wrapper exception or interruption poisons the entire instance, including
attempts with a different phase or repetition. Explicit failed outcomes also
poison it while remaining available to BenchmarkRunner for error accounting.
There is no reset method. An operator must independently stop and drain outstanding
work before constructing another instance; construction itself proves no drain.
Existing BenchmarkRunner validation still handles outcome semantics, workload
hashes, meter identity, energy integration and window chronology.

This wrapper implements fixed submitted-job accounting, not a dynamic load
generator. The real collector must schedule that exact manifest, synchronize GPU
completion, validate results, sample the qualified independent BMC boundary and
ensure no omitted work remains running. The clocks and scheduler are trusted
injections, not authenticated evidence sources. Cross-process durable replay
protection and trustworthy host clock synchronization remain external requirements.

The deadline is cooperative and overrun is checked **after return**. This wrapper
does not interrupt blocked calls, stop workloads or recover after SIGKILL/host
failure. A supervised process boundary with bounded I/O and independently tested
restoration recovery remains required before a physical experiment. No hardware
or network access is added, and no live measurements are synthesized.
