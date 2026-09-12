import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Privacy — GridRudder",
  description: "How GridRudder handles design-partner pilot requests.",
  alternates: { canonical: "https://gridrudder.com/privacy" },
  openGraph: { title: "Privacy — GridRudder", description: "How GridRudder handles design-partner pilot requests.", url: "https://gridrudder.com/privacy", images: [] },
  twitter: { card: "summary", title: "Privacy — GridRudder", description: "How GridRudder handles design-partner pilot requests.", images: [] },
};

export default function Privacy() {
  return <main className="legal">
    <Link className="brand" href="/"><span>GR</span> GRIDRUDDER</Link>
    <p className="legal-label">PRIVACY / PILOT INTAKE</p>
    <h1>Plain-language privacy.</h1>
    <p className="legal-lede">This notice applies to information submitted through the GridRudder design-partner intake form.</p>
    <section><h2>What we collect</h2><p>Your name, work email, organization, GPU-environment category, pilot goal, consent, and submission time.</p></section>
    <section><h2>Why we collect it</h2><p>Only to evaluate pilot fit, respond to your request, and plan a supervised technical trial. Do not submit credentials, IP addresses, or other secrets.</p></section>
    <section><h2>Retention and deletion</h2><p>Our documented monthly retention procedure removes intake requests older than 90 days, with an additional cleanup attempt whenever a new request is saved. To request earlier deletion, email <a href="mailto:pilot@gridrudder.com">pilot@gridrudder.com</a> from the address used in the request.</p></section>
    <section><h2>Sharing</h2><p>We do not sell pilot-intake information. Service infrastructure may process it solely to operate the website and its managed database.</p></section>
    <section><h2>Questions</h2><p>Email <a href="mailto:pilot@gridrudder.com">pilot@gridrudder.com</a>.</p></section>
    <p className="legal-date">Effective September 12, 2026</p>
  </main>;
}
