const responseHeaders = { "Cache-Control": "private, no-store", Vary: "Cookie, oai-authenticated-user-id", "X-Content-Type-Options": "nosniff" };
const allowedOrigins = new Set(["https://gridrudder.com", "https://gridrudder.sridhar-rajarao.chatgpt.site"]);
const json = (body, status = 200) => Response.json(body, { status, headers: responseHeaders });

export async function handlePilotOperations(request, user, ownerId, db) {
  if (!user || typeof ownerId !== "string" || !ownerId || user.userId !== ownerId) return json({ error: "Operator access required." }, 403);
  if (request.method === "GET") {
    try {
      const result = await db.prepare("SELECT id, name, email, organization, environment, goal, created_at FROM pilot_requests WHERE created_at >= datetime('now', '-90 days') ORDER BY id DESC LIMIT 100").all();
      return json({ requests: result.results, limit: 100, retentionDays: 90 });
    } catch { return json({ error: "Pilot records are unavailable. Try again later." }, 503); }
  }
  if (request.method !== "POST") return json({ error: "Method not allowed." }, 405);
  const origin = request.headers.get("origin");
  if (!origin || !allowedOrigins.has(origin) || origin !== new URL(request.url).origin) return json({ error: "Same-origin confirmation required." }, 403);
  try {
    const form = await request.formData();
    if (form.get("confirm") !== "delete-expired") return json({ error: "Explicit deletion confirmation required." }, 400);
    const result = await db.prepare("DELETE FROM pilot_requests WHERE created_at < datetime('now', '-90 days')").run();
    return json({ deleted: result.meta.changes, retentionDays: 90 });
  } catch { return json({ error: "Cleanup did not complete. Review records before retrying." }, 503); }
}
