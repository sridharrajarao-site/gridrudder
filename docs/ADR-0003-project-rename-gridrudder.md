# ADR-0003: Rename the project to GridRudder

Status: accepted

Date: 2026-09-12

## Decision

Rename the active project and product brand from **LoadHelm** to **GridRudder**. Use **GridRudder Control Plane** with the descriptor **supervised power orchestration for AI infrastructure**.

Keep the Python package name `gridgpu` for now. Renaming that internal API would create migration work without improving the customer-facing brand.

Preserve historical reviews, naming records, server identifiers, and hash-bound physical-trial evidence under their original LoadHelm names. They describe decisions and measurements made before this rename and must not be rewritten.

## Rationale

Independent marketing, enterprise-sales, and buyer councils selected GridRudder. The name conveys continuous course correction without claiming that the software owns the grid, generates electricity, or autonomously commands protected infrastructure. The descriptor makes the supervised operating model explicit.

## Naming system

- GridRudder Control Plane
- GridRudder Agent
- GridRudder Simulator
- GridRudder Safety Envelope
- GridRudder Load Governor

## Guardrails

- Do not describe GridRudder as an autonomous grid controller.
- Do not claim production readiness from the single-server physical trial.
- Complete formal trademark clearance before a major public launch.
- Treat domain registration as separate from trademark clearance.
