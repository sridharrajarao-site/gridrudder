# Design-partner intake questionnaire

Use this questionnaire offline during qualification. There is no submission endpoint. Do not collect passwords, private keys, access tokens, payment data, or production credentials in this document.

The machine-readable companion is [`design-partner-intake.schema.json`](design-partner-intake.schema.json).

## Organization and authority

1. Organization and primary technical contact.
2. Who owns the test host, and who can authorize this evaluation?
3. Who will attend the trial and who can order an immediate stop?
4. Is the host non-production, or what approved maintenance window applies?

## Hardware and software

5. Server manufacturer/model, BMC type/firmware, operating system, kernel, NVIDIA driver, GPU model/count, and GPU UUIDs. Classify UUIDs as sensitive identifiers.
6. Does `nvidia-smi` report supported minimum/default/maximum power limits for each test GPU?
7. What timestamped whole-server watts source is available: Redfish, IPMI DCMI, or metered PDU? What resolution, interval, clock, credentials model, and known accuracy apply?
8. What privileges can be granted under least privilege? Do not place credentials in the answer.

## Workload contract

9. What representative, interruptible workload will run?
10. Which measurable latency, throughput, error, completion-time, health, and priority guardrails must never be breached?
11. What baseline duration and repeated-run method produce a fair comparison?

## Change and recovery

12. What exact lower cap and original upper cap are approved?
13. What existing automation could issue a conflicting GPU command?
14. What are the emergency stop, state restoration, host recovery, and escalation procedures?
15. What evidence proves the original state and workload health were restored?

## Data handling and success

16. Which telemetry fields may GridRudder process, where may they be stored, who may access them, and when must they be deleted?
17. May sanitized compatibility facts or aggregate results be published? Consent must be separate and revocable before publication.
18. What independently measured power response, workload outcome, audit completeness, and fault-recovery result would make the pilot useful?
19. What would require the pilot to stop immediately?

Answers qualify a supervised evaluation only; they do not authorize access, installation, hardware writes, publication, or a later pilot stage.
