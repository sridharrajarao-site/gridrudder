import { PilotForm } from "./pilot-form";

const proof = [
  ["100% reported", "GPU utilization in session telemetry"],
  ["156.22 → 124.37 W", "GPU power under load"],
  ["291 → 260 W", "Independent BMC server power"],
  ["195 / 195", "Trial-build software tests passed"],
];

export default function Home() {
  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <nav aria-label="Main navigation">
        <a className="brand" href="#top" aria-label="GridRudder home"><span>GR</span> GRIDRUDDER</a>
        <div className="navlinks"><a href="#proof">Evidence</a><a href="#pilot">Pilot</a><a href="#faq">FAQ</a></div>
        <a className="navcta" href="#intake">Apply for pilot <span aria-hidden="true">↗</span></a>
      </nav>
      <main id="main">
        <section className="hero" id="top">
          <h1 className="sr-only">GridRudder — Make every watt work</h1>
          {/* The static campaign asset avoids image-proxy hydration failures in the current worker runtime. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img className="hero-card" src="/og.png" alt="GridRudder: Make every watt work. A supervised control loop connects the power grid to GPU servers." width={2048} height={1080} loading="eager" fetchPriority="high" />
          <p className="lede">GridRudder coordinates GPU power with real infrastructure conditions, with operator approval and measured verification at every step.</p>
          <div className="actions"><a className="primary" href="#intake">Apply for a supervised pilot <span aria-hidden="true">→</span></a><a className="textlink" href="#proof">Review the evidence ↓</a></div>
        </section>

        <section className="proof" id="proof">
          <div className="sectionhead"><span>01 / PHYSICAL EVIDENCE</span><h2>Measured independently<br/>through the server BMC.</h2><p>One attended bare-metal session in September 2026 on a server identified in session records as an NVIDIA RTX 2060 Super. Session telemetry reported 100% GPU utilization while a human-approved power-limit change was applied and reversed.</p></div>
          <div className="metrics">{proof.map(([value,label], i) => <article key={label}><small>0{i+1}</small><strong>{value}</strong><p>{label}</p></article>)}</div>
          <p className="note"><span aria-hidden="true">●</span> The evidence artifact records the power measurements and restoration. GPU model and utilization come from attended session records, not the artifact itself. This is early evidence, not a fleet-wide performance claim; application throughput was not benchmarked.</p>
        </section>

        <section className="how dark" id="how">
          <div className="sectionhead light"><span>02 / CONTROL BOUNDARIES</span><h2>Power action stays<br/>inside a guarded loop.</h2></div>
          <div className="steps">
            <article><b>01</b><h3>Observe</h3><p>Read BMC server power, GPU telemetry, workload state, and external power signals.</p></article>
            <article><b>02</b><h3>Recommend</h3><p>Evaluate explicit policies, workload priorities, floors, and rollback conditions.</p></article>
            <article><b>03</b><h3>Approve</h3><p>An operator reviews each proposed change. The pilot does not grant autonomous control.</p></article>
            <article><b>04</b><h3>Verify</h3><p>Apply the bounded action, measure the physical response, audit it, and restore safely.</p></article>
          </div>
        </section>

        <section className="detail-grid">
          <article id="pilot"><span>03 / PILOT SCOPE</span><h2>What the attended pilot includes</h2><ul><li>Read-only environment and capability discovery</li><li>Agreed GPU power-limit range and stop conditions</li><li>Operator-approved test sequence and rollback</li><li>GPU plus independent BMC power capture</li><li>Evidence report and compatibility findings</li></ul></article>
          <article><span>04 / ARCHITECTURE</span><h2>Control stays local and explicit</h2><p>A host-side agent reads telemetry and executes only allowed actions. Policy evaluates proposals. Independent BMC data verifies whole-server response. An append-only record ties every recommendation, approval, action, observation, and restoration together.</p><div className="boundary"><b>Signal</b><i>→</i><b>Policy</b><i>→</i><b>Human</b><i>→</i><b>Agent</b><i>→</i><b>BMC proof</b></div></article>
          <article><span>05 / CURRENT LIMITS</span><h2>What we have not proven yet</h2><ul><li>Only one GPU and one server/BMC implementation tested</li><li>No multi-GPU, multi-node, or scheduler integration claim</li><li>No application-throughput or SLA result from this trial</li><li>No unattended production control</li><li>No fleet-scale savings estimate</li></ul></article>
          <article><span>06 / OPEN SOURCE</span><h2>Apache 2.0 is the intended agent license</h2><p>We intend to release the local agent, collectors, safety guards, simulator, and audit format under Apache 2.0. The repository is not public yet, so no source distribution or open-source release is currently available.</p></article>
        </section>

        <section className="method">
          <div><span>07 / METHODOLOGY</span><h2>Evidence, not inference.</h2></div>
          <ol><li><b>Baseline.</b> Warm GPU load and capture timestamped GPU and BMC readings.</li><li><b>Intervention.</b> Reduce the GPU power limit from 175 W to 125 W under attended control.</li><li><b>Observation.</b> Record GPU power at 124.37 W and independent server power at 260 W.</li><li><b>Recovery.</b> Restore the original 175 W limit and confirm the system returns to the prior state.</li></ol>
          <p>Software verification at the physical trial: 195 automated tests passed. The current suite has 203 tests; that later count is not part of the physical trial evidence. Hardware figures are observations from the single attended session above, not generalized savings guarantees.</p>
        </section>

        <section className="intake" id="intake">
          <div><span>DESIGN PARTNER INTAKE</span><h2>Test it on infrastructure<br/>that matters.</h2><p>Tell us enough to assess hardware fit. We use these details only to evaluate and respond to the pilot request. Our documented monthly process removes requests older than 90 days; you may request earlier deletion.</p><p className="email-fallback">Prefer email? <a href="mailto:pilot@gridrudder.com">pilot@gridrudder.com</a></p></div>
          <PilotForm />
        </section>

        <section className="faq" id="faq">
          <span>08 / FAQ</span><h2>Direct answers.</h2>
          <div className="questions">
            <details><summary>Does GridRudder control production autonomously?</summary><p>No. The current offer is an attended, operator-approved pilot with explicit limits and rollback.</p></details>
            <details><summary>Does 100% utilization mean identical useful work?</summary><p>No. It means the GPU reported 100% utilization during this trial. We did not measure application throughput, tokens per second, or job completion time.</p></details>
            <details><summary>Where did the server-power measurement come from?</summary><p>From the rented physical server’s independent BMC telemetry, separate from NVIDIA’s GPU-reported power.</p></details>
            <details><summary>Is GridRudder open source today?</summary><p>Not yet. Apache 2.0 is the intended license for the local agent and core safety components; the repository has not been published.</p></details>
            <details><summary>What access does a pilot require?</summary><p>Root access to the agreed bare-metal host, a supported NVIDIA power-limit interface, and readable timestamped BMC power telemetry.</p></details>
          </div>
        </section>
      </main>
      <footer><a className="brand" href="#top"><span>GR</span> GRIDRUDDER</a><p><a href="mailto:pilot@gridrudder.com">pilot@gridrudder.com</a></p><p><a href="/privacy">Privacy</a></p><p>POWER-AWARE COMPUTE, VERIFIED.</p><p>© 2026 GRIDRUDDER<br/><a className="arivai-endorsement" href="https://arivaigroup.com">An <b>ARIVAI</b> company</a></p></footer>
    </>
  );
}
