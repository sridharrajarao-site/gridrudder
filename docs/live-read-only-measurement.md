# Read-only live measurement seam

`LiveReadOnlyCollector` accepts a `CollectionRequest` and returns a WorkloadWindow;
wrap it with CompleteFreshCollector, then pass that wrapper to BenchmarkRunner.
Inject clocks, sleeper and a command runner explicitly. This module has no CLI.
It executes only pinned local NVIDIA UUID/power/driver queries and qualification's
FRU/DCMI reads. The runner receives fixed argv, a clean environment and a timeout
bounded by the acquisition budget and remaining collection deadline. It never
sets power limits or persistence mode and does not create a GPU workload itself.

NVIDIA and BMC reads are sequential. Each retained sample records their combined
acquisition duration; excessive skew rejects the collection. Meter UTC and elapsed
time describe acquisition start, not a fabricated simultaneous hardware reading.
FRU identity and both executable hashes are checked; NVIDIA responses and BMC
response digests/provenance are retained in memory. No result is labeled qualified.
DCMI may internally cache/average readings; real meter cadence and accuracy need
qualification before interpreting energy, regardless of polling cadence.

The start callback receives the complete job request and monotonic origin. It
must submit precisely those IDs and return promptly. The finish callback must
explicitly synchronize and drain all jobs, verify results, and supply every
outcome with times relative to that origin. Merely supplying metadata does not
prove GPU execution, completion or drain; these callbacks still need an actual
reviewed workload implementation. The measured window includes submission
overhead after the initial sample. All job completion times must fit the window.

After telemetry or workload failure, the collector becomes unavailable. It does
not drain outstanding work itself; the attended supervisor must do so. Callback
timeouts remain cooperative. Process kill/reboot recovery, durable evidence export,
authenticated approvals, external watchdog and actual hardware validation remain
unimplemented deployment gates. Tests inject fake responses and do not represent
physical measurements or compatibility evidence.
