import assert from "node:assert/strict";
import test from "node:test";

async function render(path = "/") {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}-${path}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request(`https://gridrudder.com${path}`, { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

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
