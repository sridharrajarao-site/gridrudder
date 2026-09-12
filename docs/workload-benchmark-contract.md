# Useful-work measurement contract

`gridgpu.workload_benchmark` prepares hardware-independent measurement validation.
It does not run a real GPU workload or independently establish energy savings.

Pass a `BenchmarkRunner` as the `workload_runner` of
`run_attended_performance_trial`. The injected collector receives phase,
repetition and authorized duration, and returns a `WorkloadWindow`. Use the
same SHA-256 workload manifest in the trial and each window; the manifest should
pin code, model/data hashes, dependency versions, seed, shapes, batch size,
precision and output-validation tolerance. Hash validation establishes identity,
not proof that a collector executed the declared workload.

Each job must be a fixed amount of comparable work. Record unique IDs, monotonic
start/end offsets and explicit output-validation success. Synchronize GPU work
before recording completion; launch time is not completion time. Drain outstanding
jobs within the measured window. If jobs extend past it, reject the window and
repeat with a collector that stops admission early enough. Do not omit failed jobs.

Meter samples must come from the authorized whole-server meter/chassis and span
the actual window at three or more increasing times. UTC and elapsed offsets
must agree within 100 milliseconds. This is a consistency check, not a guarantee
of sensor sampling resolution or metering accuracy. The existing trial validator
integrates watts over time using trapezoids. Zero/nonfinite energy is rejected.

The report retains completed and failed counts, completed-job throughput,
successful-job mean and nearest-rank p95 latency, whole-server joules and joules
per completed job. Energy includes the entire window, including idle time and
failed attempts; failed jobs never increase the denominator. An all-failed or
empty window has undefined efficiency and is rejected. A runner with any job
errors raises immediately, retaining its failed measurement for diagnosis so the
attended trial can execute its restoration path.

Warmup is validated but excluded from results. `validate_comparison` requires
every baseline/capped/restored repetition exactly once, at least two repetitions,
one manifest and zero errors. Persist runner measurements alongside the trial
audit result: the existing WorkSample interface retains work and energy but does
not itself serialize latency and error details. Interpret per-window results and
restoration drift before making claims. Hardware collection, metering precision,
representative workloads and real-world repeatability still need validation.
