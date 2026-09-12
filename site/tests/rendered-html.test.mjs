import assert from "node:assert/strict";
import test from "node:test";
import { handlePilotOperations } from "../app/ops/pilot-policy.mjs";
function operations(path, options = {}, bindings = {}) {
  const request = new Request(`https://gridrudder.com${path}`, options);
  const id = request.headers.get("oai-authenticated-user-id");
  return handlePilotOperations(request, id ? { userId: id } : null, bindings.PILOT_OPERATOR_USER_ID, bindings.DB);
}

async function render(path = "/", options = {}, bindings = {}) {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}-${path}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request(`https://gridrudder.com${path}`, { headers: { accept: "text/html" }, ...options }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) }, ...bindings },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("pilot operations fail closed without configured exact operator identity", async () => {
  const headers = { "oai-authenticated-user-id": "test-viewer", "oai-authenticated-user-email": "%@example.invalid" };
  for (const bindings of [{}, { PILOT_OPERATOR_USER_ID: "test-owner" }]) {
    const response = await operations("/api/ops/pilots", { headers }, bindings);
    assert.equal(response.status, 403);
    assert.match(response.headers.get("cache-control"), /no-store/);
  }
  assert.equal((await operations("/api/ops/pilots")).status, 403);
});

test("operator API requires identity, same-origin and explicit cleanup confirmation", async () => {
  let writes = 0;
  const bindings = { PILOT_OPERATOR_USER_ID: "test-owner", DB: { prepare(query) {
    return { all: async () => ({ results: [] }), run: async () => { writes++; assert.match(query, /created_at < datetime\('now', '-90 days'\)/); return { meta: { changes: 0 } }; } };
  } } };
  const headers = { "oai-authenticated-user-id": "test-owner", "oai-authenticated-user-email": "%@example.invalid" };
  const read = await operations("/api/ops/pilots", { headers }, bindings);
  assert.equal(read.status, 200);
  assert.deepEqual((await read.json()).requests, []);
  for (const origin of ["https://malicious.example", undefined]) {
    const response = await operations("/api/ops/pilots", { method: "POST", headers: { ...headers, ...(origin ? { origin } : {}) }, body: new URLSearchParams({ confirm: "delete-expired" }) }, bindings);
    assert.equal(response.status, 403);
  }
  const missing = await operations("/api/ops/pilots", { method: "POST", headers: { ...headers, origin: "https://gridrudder.com" }, body: new URLSearchParams() }, bindings);
  assert.equal(missing.status, 400);
  assert.equal(writes, 0);
  const confirmed = await operations("/api/ops/pilots", { method: "POST", headers: { ...headers, origin: "https://gridrudder.com" }, body: new URLSearchParams({ confirm: "delete-expired" }) }, bindings);
  assert.equal(confirmed.status, 200);
  assert.equal(writes, 1);
});

test("renders the approved proof-brief page and qualified evidence", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>GridRudder — Supervised GPU power orchestration<\/title>/i);
  assert.match(html, /GPU power\.[\s\S]*Under your control/i);
  assert.match(html, /156\.22[^<]*→[^<]*124\.37 W/i);
  assert.match(html, /291[^<]*→[^<]*260 W/i);
  assert.match(html, /Independent BMC whole-server observation/i);
  assert.match(html, /HISTORICAL OBSERVATION—NOT LIVE/i);
  assert.match(html, /Throughput was not measured/i);
  assert.match(html, /savings are not guaranteed/i);
  assert.match(html, /NO FACILITY WRITE ACCESS/i);
  assert.match(html, /NO AUTONOMOUS PRODUCTION CONTROL/i);
  assert.match(html, /Request a compatibility review/i);
  assert.match(html, /ATTENDED TEST ONLY/i);
  assert.match(html, /only after separate approval/i);
  assert.match(html, /The local agent, simulator, and safety tooling are available on GitHub/i);
  assert.match(html, /href="https:\/\/github\.com\/sridharrajarao-site\/gridrudder"/i);
  assert.match(html, /does not represent a hosted or fleet-control product/i);
  assert.doesNotMatch(html, /without sacrificing useful compute/i);
  assert.doesNotMatch(html, /Measured at the wall/i);
});

test("emits production metadata and accessible pilot/privacy paths", async () => {
  const response = await render();
  const html = await response.text();

  assert.match(html, /<link[^>]+rel="canonical"[^>]+href="https:\/\/gridrudder\.com\/?"/i);
  assert.match(html, /<meta[^>]+property="og:url"[^>]+content="https:\/\/gridrudder\.com\/?"/i);
  assert.match(html, /<meta[^>]+property="og:image"[^>]+content="https:\/\/gridrudder\.com\/og\.png"/i);
  assert.match(html, /<meta[^>]+name="twitter:card"[^>]+content="summary_large_image"/i);
  assert.match(html, /href="#main"[^>]*>Skip to content/i);
  assert.match(html, /<main[^>]+id="main"/i);
  assert.match(html, /READ-ONLY QUALIFICATION APPLICATION/i);
  assert.match(html, /pilot@gridrudder\.com/i);
  assert.match(html, /href="\/privacy"/i);
  assert.match(html, /monthly retention procedure removes requests older than 90 days/i);
  assert.match(html, /<input(?=[^>]*name="consent")(?=[^>]*required)[^>]*>/i);
  assert.match(html, /aria-live="polite"/i);
  assert.doesNotMatch(html, /role="status"/i);
});

test("renders the scoped pilot-intake privacy notice", async () => {
  const response = await render("/privacy");
  assert.equal(response.status, 200);
  const html = await response.text();

  assert.match(html, /<title>Privacy — GridRudder<\/title>/i);
  assert.match(html, /href="https:\/\/gridrudder\.com\/privacy"/i);
  assert.match(html, /Plain-language privacy/i);
  assert.match(html, /What we collect/i);
  assert.match(html, /Retention and deletion/i);
  assert.match(html, /older than 90 days/i);
  assert.match(html, /We do not sell pilot-intake information/i);
  assert.match(html, /pilot@gridrudder\.com/i);
});
