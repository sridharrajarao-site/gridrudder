# Naming Council: project codename recommendations

Status: Chief Architect decision, 2026-08-30

## Decision

The working codename is **Project LoadHelm** (pronounced **load-helm**).

Use **LoadHelm Control Plane** as the product placeholder in architecture diagrams and pilot material, with the descriptive subtitle **“grid-aware power control for AI clusters.”** Do not rename packages, repositories, or legal entities yet. The name must pass formal trademark, corporate-name, domain, and linguistic review before any public launch.

Recommended working tagline:

> Hold the power envelope. Protect the workload.

The Chief Architect selected LoadHelm because it tells an infrastructure buyer what the system does: it takes the helm of electrical load without implying that it controls protective equipment or operates the grid. It remains usable as the product expands from GPU power caps to schedulers, batteries, cooling, and multiple sites.

## Council and decision rule

The small council used four personas:

- **Brand Strategist:** optimize recall, differentiation, verbal identity, and future category expansion.
- **Power-Systems Expert:** prefer accurate load-control language and reject names that imply generation, protection, or utility authority we do not possess.
- **AI Infrastructure Engineer:** prefer a name credible in Kubernetes, Slurm, GPU, telemetry, and data-center contexts.
- **Skeptical Buyer:** reject hype, ambiguity, difficult spelling, and names that sound unsafe or unserious in a critical-infrastructure procurement meeting.

Each persona could veto a candidate for material technical misrepresentation or an obvious live-market collision. The Chief Architect had the final word.

## Twelve candidates

| Candidate | Pronunciation | Suggested tagline | Council rationale | Disposition / what to avoid |
|---|---|---|---|---|
| **LoadHelm** | load-helm | Hold the power envelope. Protect the workload. | “Load” is the shared word between utilities and computing; “helm” conveys supervised direction rather than raw switching. Strongest balance of clarity, authority, and extensibility. | **Selected working codename.** Avoid calling it an autonomous grid controller. “Helm” can suggest Kubernetes Helm, so always add the descriptive subtitle in early use. |
| **GridThrum** | grid-thrum | Keep compute in rhythm with the grid. | Distinctive and evocative of a steady machine hum; excellent internal codename and likely strong verbal identity. | Runner-up. Avoid using without an explanatory descriptor: “thrum” is memorable but does not say orchestration or load control. |
| **LoadChord** | load-chord | Make every megawatt work together. | Presents grid, facility, and GPU actions as coordinated notes. Exact-name screening found no obvious commercial match, and the metaphor supports multisystem orchestration. | Strong alternative. Avoid music-heavy branding that makes a safety-critical product feel whimsical. |
| **WattRelay** | watt-relay | From grid signal to verified GPU response. | Clearly communicates a signal moving between power and compute layers. Strong fit for the first utility-to-cluster integration product. | Good feature or protocol name. “Relay” has a precise protection meaning in power systems; never imply the software replaces protective relays. |
| **CurrentLayer** | current-layer | The control layer between power and compute. | “Current” carries both electrical and real-time meanings; “layer” accurately positions the product above existing schedulers and facility controls. | Viable but generic. It is already a common property/API term in mapping, CAD, and weather software, creating weak searchability. |
| **GridThread** | grid-thread | One control thread from grid to GPU. | Very clear cross-layer metaphor and strong technical tone. | **Reject for public use:** an existing Singapore business uses GridThread, according to a current company-technology profile. Do not spend brand equity here. |
| **WattBridge** | watt-bridge | Bridge power constraints to compute actions. | Immediately explains the cross-domain role. | **Reject:** WattBridge is an active energy company and independent power producer with a large operating portfolio; the collision is direct and sector-adjacent. [WattBridge](https://www.wattbridge.info/) |
| **ComputeCurrent** | compute-current | Compute that follows available power. | Elegant double meaning: electrical current plus the current state of compute. | **Reject:** Compute Current is already an active AI-infrastructure intelligence publication covering power, data centers, cooling, and silicon—almost exactly this audience. [Compute Current](https://www.computecurrent.com/) |
| **PowerEnvelope** | power-envelope | Stay inside the limit. | Technically exact for the MVP and easy for engineers and utilities to understand. | **Reject as a brand:** it is an established technical concept and the name of an E.ON grid-forecasting project. Keep it as a domain term only. [E.ON PowerEnvelope project listing](https://award.wiwo.de/bot/finalisten-2025/) |
| **CurrentLoom** | current-loom | Weave power and compute into one plan. | Warmer and more distinctive than conventional grid terminology; supports an orchestration story. | Reserve only. “Loom” may sound like analytics or data integration rather than deterministic control. |
| **GridLatch** | grid-latch | Set the limit. Hold the load. | Short, strong, and suggestive of holding an operating constraint. | Reserve only. “Latch” can imply a stuck state or low-level electrical component; the safety connotation may create needless technical objections. |
| **ComputeHelm** | compute-helm | Steer AI work within real power limits. | Clear to GPU buyers and extensible across accelerators and schedulers. | Reserve only. It underweights the grid and facility side, making the product sound like another crowded cluster scheduler. |

## Top-five scorecard

Scores are 1–5. For **collision risk**, 5 means the cleanest result in this limited screen; it does not mean legally available.

| Rank | Name | Memorability | Clarity | Credibility | Extensibility | Collision risk | Total / 25 |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | **LoadHelm** | 4 | 5 | 5 | 5 | 4 | **23** |
| 2 | **LoadChord** | 4 | 4 | 4 | 5 | 5 | **22** |
| 3 | **GridThrum** | 5 | 3 | 4 | 5 | 5 | **22** |
| 4 | **WattRelay** | 4 | 4 | 4 | 4 | 5 | **21** |
| 5 | **CurrentLayer** | 3 | 3 | 4 | 5 | 4 | **19** |

## Persona recommendations and agreement

### Brand Strategist

Preferred **GridThrum** for distinctiveness, but accepted **LoadHelm** because an unfamiliar category needs some self-explanation. Recommended keeping GridThrum as a future simulator or demo codename rather than discarding it.

### Power-Systems Expert

Preferred **LoadHelm**. “Load” is accurate at the meter boundary and does not claim the product owns the grid. Required the team to avoid “relay” in the master brand unless every buyer-facing explanation distinguishes orchestration from certified protection relays.

### AI Infrastructure Engineer

Preferred **LoadHelm**. It works for the current power-envelope controller and for later scheduler, accelerator, battery, and cooling adapters. Accepted the Kubernetes Helm association as manageable because the exact compound is distinct and the product descriptor resolves the ambiguity.

### Skeptical Buyer

Preferred **LoadHelm** over more poetic names. It sounds like infrastructure software, can be repeated accurately after one hearing, and makes no “AI magic” claim. Required a concrete subtitle and rejected names with obvious sector-adjacent occupants.

### Consensus

All four personas agreed to **Project LoadHelm** as the internal codename. They also agreed that selection as a codename is not authorization to launch the company or file a mark under this name.

## Collision screen

This was a fast, current web screen for exact names and close sector usage, not a registry-grade search:

- **LoadHelm:** no obvious exact-name energy, data-center, or AI company surfaced. One unrelated chemistry SDK uses `loadHelm` as a method for loading HELM molecular notation. That is a low but nonzero software-search collision.
- **GridThrum, LoadChord, and WattRelay:** no obvious exact-name company or product surfaced in the limited exact-name searches.
- **CurrentLayer:** no obvious exact company surfaced, but the term appears widely as a software property, making search ownership difficult.
- **GridThread:** an existing Singapore company was found in a commercial technology profile.
- **WattBridge:** direct energy-sector collision with an operating independent power producer. [WattBridge](https://www.wattbridge.info/)
- **ComputeCurrent:** direct AI-infrastructure media collision. [Compute Current](https://www.computecurrent.com/)
- **PowerEnvelope:** existing grid software/project terminology and an E.ON project name. [Best of Technology listing](https://award.wiwo.de/bot/finalisten-2025/)

Absence from ordinary web results is not evidence of availability. Before public adoption, counsel should search exact and confusingly similar marks in relevant classes and jurisdictions. The USPTO provides the official US trademark search entry point, but a professional clearance search must also consider common-law use and non-US markets. [USPTO trademark search](https://www.uspto.gov/trademarks/search)

## Naming guardrails

Avoid names and claims that:

- Say or imply **autonomous**, **self-driving**, or **AI-controlled grid**; the control path is deterministic and supervised.
- Suggest replacement of protective relays, utility SCADA, electrical safety systems, or certified facility controls.
- Lock the company to NVIDIA, GPUs, or one scheduler; the long-term product manages flexible compute and energy resources.
- Use vague AI suffixes such as `-GPT`, `-gen`, or `-mind`; they reduce critical-infrastructure credibility and age quickly.
- Overpromise outcomes such as “unlimited power,” “zero-grid data center,” or “guaranteed interconnection.”
- Lead with sustainability alone; the economic value is capacity, reliability, response, and verifiable control.
- Use the generic category phrase **grid-to-GPU** as a defensible brand. Keep it as explanatory language.

## Usage until legal clearance

Use this form in internal documents:

> **Project LoadHelm** — a supervised grid-aware control plane that keeps AI clusters inside verified power envelopes while protecting workload contracts.

Use `grid-to-gpu` for the existing repository and package paths. A rename would add coordination cost without increasing technical evidence. Revisit the public product and company name after the first external pilot, when the actual buyer, deployment boundary, and product scope are proven.
