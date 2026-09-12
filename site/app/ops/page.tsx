import type { Metadata } from "next";
import { env } from "cloudflare:workers";
import { requireChatGPTUser } from "../chatgpt-auth";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Pilot operations — GridRudder",
  robots: { index: false, follow: false },
  openGraph: { images: [] }, twitter: { images: [] },
};

export default async function Operations() {
  const user = await requireChatGPTUser("/ops");
  const owner = (env as unknown as Record<string, unknown>).PILOT_OPERATOR_USER_ID;
  if (typeof owner !== "string" || !owner || owner !== user.userId) {
    return <main className="legal"><a href="/">GridRudder</a><h1>Restricted operations.</h1><p>Your account is signed in, but operator access has not been granted. No pilot records are available here.</p><p>Your site-specific account ID: <code>{user.userId}</code></p><p>The site owner must verify this ID before configuring operator access.</p></main>;
  }
  return <main className="legal"><a href="/">GridRudder</a><h1>Pilot operations.</h1><p>Review the latest 100 requests using the protected, uncached endpoint below. Requests older than 90 days are excluded from review.</p><p><a href="/api/ops/pilots">Open current pilot requests</a></p><section><h2>Retention cleanup</h2><div><p>This permanently removes only requests older than 90 days. It does not delete current requests. Scheduled cleanup is not configured; run this during the monthly retention review.</p><form action="/api/ops/pilots" method="post"><label><input type="checkbox" name="confirm" value="delete-expired" required/> I confirm permanent deletion of expired requests.</label><p><button type="submit">Delete requests older than 90 days</button></p></form></div></section></main>;
}
