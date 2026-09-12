import type { Metadata } from "next";
import Link from "next/link";
import { env } from "cloudflare:workers";
import { requireChatGPTUser } from "../chatgpt-auth";
export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Pilot operations — GridRudder", robots: { index: false, follow: false }, openGraph: { images: [] }, twitter: { images: [] } };
export default async function Operations() {
  const user = await requireChatGPTUser("/ops");
  const owner = (env as unknown as Record<string, unknown>).PILOT_OPERATOR_USER_ID;
  if (typeof owner !== "string" || !owner || owner !== user.userId) {
    return <main className="legal"><Link href="/">GridRudder</Link><h1>Restricted operations.</h1><p>Your account is signed in, but operator access has not been granted. No pilot records are available here.</p><p>Your site-specific account ID: <code>{user.userId}</code></p><p>The site owner must verify this ID before configuring operator access.</p></main>;
  }
  let records: Record<string, unknown>[] = [];
  let unavailable = false;
  try {
    const result = await env.DB.prepare("SELECT id, name, email, organization, environment, goal, created_at FROM pilot_requests WHERE created_at >= datetime('now', '-90 days') ORDER BY id DESC LIMIT 100").all();
    records = result.results;
  } catch { unavailable = true; }
  return <main className="legal"><Link href="/">GridRudder</Link><h1>Pilot operations.</h1><p>Latest 100 requests from the last 90 days. Only your authorized account can review these records.</p>
    {unavailable ? <p role="alert">Pilot records are unavailable. Refresh to try again.</p> : records.length === 0 ? <p>No current pilot requests.</p> : records.map(record => <section key={String(record.id)}><h2>{String(record.organization)}</h2><div><p><strong>{String(record.name)}</strong> · {String(record.email)}</p><p>{String(record.environment)} · {String(record.created_at)} UTC</p><p>{String(record.goal)}</p></div></section>)}
    <section><h2>Retention cleanup</h2><div><p>This permanently removes only requests older than 90 days. It does not delete current requests. Scheduled cleanup is not configured; run this during the monthly retention review.</p><form action="/api/ops/pilots" method="post"><label><input type="checkbox" name="confirm" value="delete-expired" required/> I confirm permanent deletion of expired requests.</label><p><button type="submit">Delete requests older than 90 days</button></p></form></div></section></main>;
}
