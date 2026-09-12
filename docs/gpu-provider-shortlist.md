# Low-Cost Physical GPU Test Shortlist

Research date: 2026-08-30  
Decision owner: Chief Architect  
Scope: A supervised test of host-level NVIDIA power caps (`nvidia-smi -pl`) with an independent AC-power measurement path.

## Executive recommendation

**Do not buy or rent anything yet.** First obtain either (a) a successful preflight command transcript on the exact machine, or (b) written confirmation from an authorized provider representative covering every item in the preflight questionnaire below.

The recommended order is:

1. **A borrowed or returnable local desktop with one supported NVIDIA card plus an independent plug meter.** This is the only low-cost option where we can confidently own the host driver, obtain real administrator privilege, isolate the load, and independently meter the whole machine.
2. **A true single-tenant hourly bare-metal server, conditional on written confirmation of power-limit permission and a provider-supplied BMC/PDU telemetry feed.** “Root,” “dedicated GPU,” or PCIe passthrough is not sufficient evidence by itself.
3. **Container/VM GPU clouds for shadow telemetry and workload experiments only.** Treat power-cap writes and independent host/PDU power as unavailable until a provider proves otherwise in writing and via preflight.

The key fact is from NVIDIA: `nvidia-smi -pl` requires root/administrator privilege, the requested value must be inside the device-reported minimum and maximum, and the operation is only supported on compatible devices. [NVIDIA NVSMI documentation](https://docs.nvidia.com/deploy/nvidia-smi/index.html)

Container root is not host root. A cloud shell displaying `root@container` does not establish authority over the host NVIDIA driver, and GPU telemetry from NVML/NVSMI is not an independent host or PDU measurement.

## What qualifies for the experiment

An option is eligible only when all of the following are true:

- We control or are expressly authorized to use the host-level NVIDIA management interface.
- `nvidia-smi -q -d POWER` reports a finite minimum, maximum, default, and current power limit for the exact GPU.
- A supervised test can set a lower valid limit and restore the original limit.
- The provider permits repeated changes for engineering experiments and will not treat them as abuse.
- We can measure AC power independently of GPU telemetry—at host inlet, smart plug, BMC power sensor, or metered PDU outlet.
- Independent samples can be exported with timestamps at adequate cadence and aligned with workload/GPU telemetry.
- The GPU is not MIG-partitioned, shared, or remapped in a way that makes board-level power attribution ambiguous.
- The test has a local kill/restore path and no production tenant workload.

## Comparison

| Route | Likelihood of usable `-pl` | Independent host/PDU meter | Cost shape | Setup effort | Decision |
|---|---|---|---|---|---|
| Local used/borrowed desktop GPU | High when we own host and exact board supports it | Easy: inline AC meter or networked plug meter | Upfront hardware, then local electricity | Medium | **Preferred first physical test** |
| Hourly true bare metal | Plausible, never assume | Rarely advertised; must request BMC/PDU/API | Hourly or monthly rental | Medium/high vendor coordination | **Conditional shortlist** |
| GPU VM with passthrough | Uncertain; guest root may still lack host management authority | Usually no independent machine/outlet feed | Hourly | Low | Shadow unless preflight passes |
| Container GPU cloud | Low | No customer-controlled independent meter in normal product | Low hourly, broad availability | Low | **Shadow-only default** |
| Serverless/model endpoint | Effectively none | None | Per-second/request | Low | Not suitable |

Pricing is volatile and inventory-specific. The figures below are provider-published snapshots, not offers or approvals for this test.

## Route A — Local one-GPU lab

### Verified facts

- NVIDIA documents power draw queries and `-pl`; setting the limit requires administrator privilege and must remain within the exact device's reported bounds. [NVIDIA NVSMI documentation](https://docs.nvidia.com/deploy/nvidia-smi/index.html)
- NVIDIA documents continuous power queries, including `power.draw` and `power.limit`. [NVIDIA useful NVSMI queries](https://nvidia.custhelp.com/app/answers/detail/a_id/3751)
- A Shelly Plug US Gen4 has a built-in instantaneous power meter, local API/interface options, and a 120 V / 15 A input/output rating. The official store listed it at $24.99 when researched, but it was out of stock. Its page distinguishes the 1,800 W rating as resistive-load maximum; a workstation is an electronic load, so suitability and electrical headroom must be confirmed rather than inferred from 1,800 W. [Shelly product specification](https://us.shelly.com/products/shelly-plug-us-gen4-black), [Shelly API documentation](https://shelly-api-docs.shelly.cloud/gen2/Devices/Gen4/ShellyPlugUSG4/)
- An APC NetShelter Metered-by-Outlet PDU provides remote outlet-level monitoring, but this is a rack/datacenter option rather than the lowest-cost desktop path. [APC official product family](https://www.apc.com/us/en/product-range/61796-netshelter-meteredbyoutlet-rack-pdus/)
- A P3 Kill A Watt P4400 can show voltage, current, watts, VA, frequency, power factor, and accumulated energy, but its normal display is not an automated timestamped API feed. [P3 manual](https://www.p3international.com/manuals/p4400_manual.pdf)

### Candidate hardware

For the first experiment, model performance is secondary. Prefer a desktop PCIe NVIDIA GPU that:

- already exists in a team member's machine or can be borrowed;
- exposes writable min/max power limits under Linux;
- has enough cooling and PSU headroom at the default limit;
- is returnable if its board/firmware rejects power-limit writes;
- is not a laptop GPU; laptop firmware commonly changes or removes management behavior.

Candidate families to inspect—not yet purchase—are used RTX 3060 12 GB, RTX 3070/3080, RTX 3090 24 GB, or workstation cards already on hand. Board-partner firmware matters, so a family name alone does not prove `-pl` support. A 3060-class card is adequate for the control-loop experiment; a 3090 adds memory and a larger measurable power swing but materially increases PSU, cooling, electrical, and acquisition requirements.

### Questions that remain unverified

- Does the exact board serial/firmware expose writable min/max limits on the intended Linux driver?
- Can the original cap be restored without driver reload or reboot?
- Does the selected meter provide timestamped readings at the cadence and accuracy we need?
- Is the chosen plug/meter approved for the workstation's electronic load and continuous current with adequate safety margin?
- Is the home/office circuit known, grounded, uncongested, and appropriate for the maximum system draw?

### Local lab recommendation

Borrow first. If borrowing is impossible, source a returnable complete workstation or used GPU only after the seller supplies exact model/board identity. Do not construct a high-power 3090/4090 rig merely to validate software. Have a qualified person review PSU, cabling, circuit, meter rating, cooling, and fire safety before load testing.

## Route B — Hourly or short-term bare metal

These are **leads for written preflight, not verified compatible providers**.

### SwissGPU

Verified on its official pricing page:

- It describes rentals as full dedicated physical servers and says billing stops when the server is powered off.
- Published examples at research time included RTX 4080 at CHF 0.20/hour plus CHF 0.30/kWh, RTX 3090 at CHF 0.25/hour plus CHF 0.30/kWh, and RTX 4090 at CHF 0.40/hour plus CHF 0.30/kWh. [SwissGPU pricing](https://www.swissgpu.ch/pricing)

Not verified:

- Host administrator/root authority over the NVIDIA driver.
- Permission for `nvidia-smi -pl` or NVML device-control calls.
- Access to an independent BMC, inlet, or PDU power series; energy-based billing is not proof that customers receive raw samples.
- Sampling cadence, accuracy, timestamps, retention, or export API.
- Whether the server is reimaged, pass-through virtualized, or managed in a way that restricts driver control.

Status: **Best published low-hourly-cost bare-metal lead; contact before account funding.**

### OpenRelay

Verified on its official product page:

- It advertises dedicated GPUs via VFIO passthrough, full root SSH access, per-second billing, no minimum term, RTX 3090 from $0.18/hour, and RTX 4090 from $0.29/hour at research time. [OpenRelay GPU rental](https://openrelay.inc/rent-gpu)

Not verified:

- “Full root” appears in combination with VFIO passthrough; it does not state that the customer controls the physical host's NVIDIA driver.
- Power-limit changes are neither expressly permitted nor demonstrated.
- No independent host/PDU meter feed, cadence, or API is documented on the cited page.
- Exact isolation and board-power attribution when CPU/host resources are virtualized or aggregated.

Status: **Low-price preflight lead, but likely guest-root rather than host-control until proven.**

### GPU Mart hourly/dedicated

Verified on its official pricing page:

- It advertises full root access and hourly offerings, including an RTX 2060 dedicated server starting around $0.277/hour/$0.22 promotional at research time and higher-end dedicated configurations. [GPU Mart hourly pricing](https://www.gpu-mart.com/pricing-hourly)

Not verified:

- Which listed offerings are physical-host bare metal versus VPS/passthrough.
- Whether root includes NVIDIA driver control and `-pl` permission.
- Whether the exact RTX 2060 board exposes a sufficiently useful writable range.
- Whether independent BMC/PDU metering is available.

Status: **Ask for exact low-cost physical configuration and command transcript.**

### DigitalOcean Bare Metal GPUs

Verified on official documentation:

- DigitalOcean describes its Bare Metal GPUs as dedicated single-tenant servers, including standalone and multi-node configurations; provisioning is contact-led. [DigitalOcean Bare Metal GPU documentation](https://docs.digitalocean.com/products/bare-metal-gpus/how-to/)

Not verified:

- Low-cost single-GPU availability, price, host-root control, `-pl` policy, or independent PDU/BMC export.

Status: **Architecturally relevant but unlikely to be the cheapest first experiment; query only if a trial/credit is offered.**

### Lambda private cloud / supercluster

Verified on official documentation:

- Lambda's private-cloud documentation explicitly states single-tenant bare-metal nodes and administrator/root access to compute nodes. [Lambda private-cloud security posture](https://docs.lambda.ai/private-cloud/security-posture/)

Not verified:

- This evidence applies to private cloud, not Lambda's ordinary on-demand GPU VMs.
- No cited official source confirms customer permission to change power limits or exposes an independent PDU stream.
- Private cloud is not positioned as a cheap one-GPU hourly test.

Status: **Useful future design-partner reference, not the first budget test.**

## Route C — Container and VM GPU clouds

### Runpod Pods

Verified on official documentation:

- Pods are containerized GPU/CPU environments; templates are container images, and Runpod documents that a reserved GPU is assigned to a Pod while it runs. [Runpod Pods overview](https://docs.runpod.io/pods/overview), [Runpod GPU assignment behavior](https://docs.runpod.io/pods/troubleshooting/zero-gpus)
- Runpod documentation showing `docker exec -u root` establishes root inside a container, not root on the physical host. [Runpod Docker commands](https://docs.runpod.io/tutorials/introduction/containers/docker-commands)

Not verified:

- Host-level `nvidia-smi -pl` is allowed or technically exposed.
- A customer can access the host driver, BMC, PSU, or metered PDU.
- GPU power telemetry is independently attributable to facility/host AC power.

Status: **Good for telemetry parser, workload generator, scheduler, and read-only shadow tests; not approved for the physical control-loop claim.**

### Vast.ai

Vast.ai is often considered for inexpensive GPU containers, but this research did not find a current official document explicitly granting physical-host NVIDIA power-limit writes or independent host/PDU metering to renters.

Status: **Shadow-only unless support provides written answers and the exact instance passes preflight. Marketplace host variability makes instance-level confirmation essential.**

### Lambda On-Demand Cloud

Verified on official documentation:

- Lambda describes on-demand instances as GPU-backed Linux virtual machines with several single-GPU instance types. [Lambda On-Demand overview](https://docs.lambda.ai/public-cloud/on-demand/)
- Lambda's optional guest agent collects GPU/VRAM utilization and sends metrics to its backend. [Lambda guest-agent documentation](https://docs.lambda.ai/public-cloud/guest-agent/)

Not verified:

- VM administrator access can issue host-driver power-limit writes.
- Customer-visible metrics constitute independent host/PDU power measurements.
- Provider policy permits repeated power cap changes.

Status: **VM/shadow candidate, not a verified actuation platform.**

### Why container/VM clouds rank last for this test

They may be the cheapest place to exercise our workload scheduler and read `nvidia-smi`, but those are different tests. Our physical hypothesis needs two independent paths:

```text
Controller -> host NVIDIA driver -> physical GPU power cap
Independent host/PDU meter -> observed AC response
```

A container that reads board telemetry provides neither proof of host control nor an independent AC measurement.

## Provider preflight questionnaire

Send this exact questionnaire to sales/support and require a written response tied to the exact SKU, region, and tenancy model.

### Tenancy and control

1. Is this an entire physical host allocated only to us, a VM with PCIe/VFIO passthrough, or a container?
2. Are any GPU, CPU, PSU, BMC, or driver resources shared with another tenant?
3. Is MIG, vGPU, SR-IOV, or another partitioning layer enabled?
4. Do we receive administrator/root access to the **physical host OS that owns the NVIDIA kernel driver**, not only guest/container root?
5. May we install/choose the NVIDIA driver, reboot the host, and use NVML device-control calls?

### Required power-cap permission

6. Does your acceptable-use and support policy expressly allow repeated `nvidia-smi -i <id> -pl <watts>` calls for engineering tests?
7. Will you provide a pre-rental transcript, or a refundable preflight window, showing these commands on the exact offered machine?

```text
nvidia-smi -L
nvidia-smi --query-gpu=index,uuid,name,pci.bus_id,power.draw,power.limit,power.default_limit,power.min_limit,power.max_limit --format=csv
sudo -n nvidia-smi -i 0 -pl <VALID_LOWER_VALUE>
nvidia-smi --query-gpu=index,power.limit --format=csv
sudo -n nvidia-smi -i 0 -pl <ORIGINAL_DEFAULT_VALUE>
```

8. Are any BMC, firmware, driver, daemon, scheduler, or provider policies able to overwrite the cap during the rental?
9. Does a cap persist across process exit, container restart, driver reset, and host reboot? Which behavior does the provider support?
10. What exact GPU manufacturer, board model, VBIOS, driver version, physical topology, and min/default/max limit will be supplied?

### Independent measurement

11. Can we access timestamped whole-host AC input power from a BMC, PSU, branch meter, or metered PDU outlet?
12. Is that measurement independent of NVML/`nvidia-smi`, and what physical boundary does it cover?
13. What are its units, sample cadence, timestamp source/timezone, stated accuracy, resolution, latency, gaps policy, and retention?
14. Can raw samples be exported by documented API, Redfish, SNMP, IPMI, CSV, or webhook?
15. Is the host's outlet/PSU feed dedicated to our physical machine, and are redundant PSUs both included?
16. Can provider staff validate the feed against the machine serial and our test timestamps?

### Operations, safety, and commercial terms

17. What are the provider's maximum permitted power, thermal, duration, and ramp limits?
18. How do we restore the default if our process, SSH session, or instance fails?
19. Is there BMC/remote console access and a provider-assisted emergency restore path?
20. Can we run synthetic loads and repeated cap/recovery cycles without triggering abuse or cryptocurrency-mining controls?
21. Is the preflight refundable, and is billing truly suspended on stop or only on destroy?
22. Are storage, IPv4, energy, taxes, egress, setup, minimum-term, and support charges separate?
23. May engineering results name the provider, hardware, and measured behavior publicly?
24. Who is the named technical contact during the supervised test window?

An answer of “dedicated GPU,” “full root,” “you can run `nvidia-smi`,” or “power metrics are visible” is incomplete.

## Acceptance transcript before spending

The exact candidate must pass a supervised, low-risk preflight:

1. Record host/server serial alias, GPU UUID, board name, VBIOS, driver, and default/min/max cap.
2. Start independent host/PDU logging and verify synchronized timestamps.
3. Record idle baseline at the original cap.
4. Start a bounded synthetic workload at low intensity.
5. Set one valid cap modestly below default.
6. Confirm the requested/current cap changed and independently observed AC draw responds.
7. Stop the workload and restore the exact original cap.
8. Confirm restoration using both NVIDIA and independent-meter paths.
9. Export raw logs and preserve them in the audit evidence packet.

Any permission error, missing writable range, unexplained provider override, ambiguous GPU sharing, inability to restore, or absent independent meter is a **no-go for actuation testing**. The machine may still be used for read-only shadow work.

## Purchase/rental decision

### Preferred near-term path

1. Ask the team, a local university lab, or a friendly small datacenter for a borrowed Linux workstation with a desktop NVIDIA GPU and written permission to test power caps.
2. Validate the exact device with the read-only preflight commands.
3. Select a properly rated, safety-reviewed independent meter with an exportable local interface; use a metered PDU if the host exceeds ordinary plug/circuit constraints.
4. Run the hardware gate checklist before enabling writes.

### Parallel provider outreach

Send the questionnaire to SwissGPU, OpenRelay, GPU Mart, and one established bare-metal provider. Ask each for the lowest-cost single-GPU configuration and a refundable two-hour preflight. Do not place a non-refundable deposit or load account credit until both host-level `-pl` authority and independent host/PDU metering are confirmed.

### Final no-spend rule

**No purchase and no rental is authorized from this shortlist alone.** Provider pages verify product descriptions and price snapshots, but none of the shortlisted remote providers publicly verifies the complete combination we need: permitted host-level power-cap writes on the exact SKU plus timestamped independent host/PDU power export. Written provider confirmation and command-level preflight are mandatory.
