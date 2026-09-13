# Qualification before cap execution

`validate_qualification_packet` checks an absolute local packet whose complete
file SHA-256 is bound into the approved recipe. It verifies the canonical packet
digest, accepted qualification/alignment, exact host/chassis/GPU/meter identities,
physical boundary, at least three ordered fresh observations, source quality,
nested source bindings, and current NVIDIA/BMC executable hashes.

Call both before constructing the runnable hardware path and immediately before
the cap. Default freshness is 900 seconds, with a hard maximum of 3600 seconds.
Longer trials require fresh qualification and new approval, not bypassing expiry.
The metrology review ID is an explicit operator attestation tied to the approved
recipe. It is not an independently authenticated calibration certificate. Hashes
bind approved bytes; a caller can fabricate data and hashes before approval.

This gate does not rerun alignment math or prove the original collector ran on
the physical machine. The reviewer must inspect the retained raw evidence,
calibration/boundary, meter cadence and independent qualification results. Current
clock synchronization, workload isolation and hardware compatibility still need
verification on the rental before approving a trial.
