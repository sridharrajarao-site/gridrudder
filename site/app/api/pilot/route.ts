import { pilotRequests } from "../../../db/schema";
import { getDb } from "../../../db";
import { lt, sql } from "drizzle-orm";

const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export async function POST(request: Request) {
  try {
    const payload = await request.json() as Record<string, unknown>;
    if (typeof payload.website === "string" && payload.website) return Response.json({ ok: true }, { status: 201 });
    const name = typeof payload.name === "string" ? payload.name.trim() : "";
    const email = typeof payload.email === "string" ? payload.email.trim().toLowerCase() : "";
    const organization = typeof payload.organization === "string" ? payload.organization.trim() : "";
    const environment = typeof payload.environment === "string" ? payload.environment.trim() : "";
    const goal = typeof payload.goal === "string" ? payload.goal.trim() : "";
    if (!name || name.length > 100 || !emailPattern.test(email) || email.length > 254 || !organization || organization.length > 160 || !environment || environment.length > 80 || !goal || goal.length > 1200 || payload.consent !== "yes") {
      return Response.json({ error: "Please complete every field with valid information." }, { status: 400 });
    }
    const db = getDb();
    await db.delete(pilotRequests).where(lt(pilotRequests.createdAt, sql`datetime('now', '-90 days')`));
    await db.insert(pilotRequests).values({ name, email, organization, environment, goal });
    return Response.json({ ok: true }, { status: 201 });
  } catch {
    return Response.json({ error: "We couldn’t save the request. Please try again." }, { status: 500 });
  }
}
