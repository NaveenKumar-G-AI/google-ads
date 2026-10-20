import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { stripTypeScriptTypes } from "node:module";
import { fileURLToPath } from "node:url";

// Run with Node 22.13+; the production modules are executed, not reimplemented.
const root = new URL("../", import.meta.url);
async function moduleUrl(file, imports = {}) {
  let source = stripTypeScriptTypes(await fs.readFile(new URL(file, root), "utf8"), { mode: "strip" });
  for (const [specifier, target] of Object.entries(imports)) source = source.replaceAll(`"${specifier}"`, JSON.stringify(target));
  return `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
}
const clientUrl = await moduleUrl("lib/marketing-analytics.ts");
const serverUrl = await moduleUrl("lib/marketing-analytics-server.ts", { "@/lib/marketing-analytics": clientUrl });
const routeUrl = await moduleUrl("app/api/marketing/events/route.ts", {
  "@/lib/marketing-analytics": clientUrl,
  "@/lib/marketing-analytics-server": serverUrl,
});
const { trackMarketingEvent } = await import(clientUrl);
const { recordMarketingEvent } = await import(serverUrl);
const { POST } = await import(routeUrl);

const originalInfo = console.info;
const originalFetch = globalThis.fetch;
const originalWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
const originalNavigator = Object.getOwnPropertyDescriptor(globalThis, "navigator");
const originalSiteUrl = process.env.NEXT_PUBLIC_SITE_URL;
const events = [];
const requests = [];
console.info = (line) => events.push(JSON.parse(line));

function request(payload, headers = {}) {
  return new Request("https://recovery.example/api/marketing/events", {
    method: "POST",
    headers: { Origin: "https://recovery.example", "Content-Type": "application/json", ...headers },
    body: typeof payload === "string" ? payload : JSON.stringify(payload),
  });
}
function setPreferences(value) {
  Object.defineProperty(globalThis, "navigator", { configurable: true, value });
}
function restore(name, descriptor) {
  if (descriptor) Object.defineProperty(globalThis, name, descriptor);
  else delete globalThis[name];
}

try {
  delete process.env.NEXT_PUBLIC_SITE_URL;
  const valid = { event: "hero_cta_click", source: "hero" };
  const accepted = await POST(request(valid));
  assert.equal(accepted.status, 204);
  assert.equal(accepted.headers.get("cache-control"), "no-store");
  assert.equal(events.length, 1);
  assert.deepEqual(Object.keys(events[0]).sort(), ["event", "source", "timestamp", "type", "version"]);
  assert.equal(events[0].event, valid.event);
  assert.equal(events[0].source, valid.source);

  const normalizedRequest = (headers = {}) => new Request("http://localhost:3000/api/marketing/events", {
    method: "POST",
    headers: { Host: "127.0.0.1:3000", Origin: "http://127.0.0.1:3000", "Sec-Fetch-Site": "same-origin", "Content-Type": "application/json", ...headers },
    body: JSON.stringify(valid),
  });
  assert.equal((await POST(normalizedRequest())).status, 204, "Next's normalized localhost URL must not reject the real browser host");
  assert.equal((await POST(normalizedRequest({ Origin: "http://localhost:3000" }))).status, 403);
  assert.equal((await POST(normalizedRequest({ Origin: "https://attacker.example", "X-Forwarded-Host": "attacker.example", "X-Forwarded-Proto": "https" }))).status, 403);
  assert.equal((await POST(normalizedRequest({ "Sec-Fetch-Site": "cross-site" }))).status, 403);
  for (const host of ["", "127.0.0.1:3000/path", "user@127.0.0.1:3000", "127.0.0.1:3000?query", "127.0.0.1:3000#fragment", "127.0.0.1:3000,attacker.example", "127.0.0.1 :3000", "127.0.0.1:99999", "127.0.0.1\\attacker.example"]) {
    assert.equal((await POST(normalizedRequest({ Host: host }))).status, 403, `Malformed host ${host} must fail closed`);
  }
  assert.equal((await POST(normalizedRequest({ Host: "[::1]:3000", Origin: "http://[::1]:3000" }))).status, 204);
  process.env.NEXT_PUBLIC_SITE_URL = "https://recovery.example";
  assert.equal((await POST(normalizedRequest({ Origin: "https://recovery.example" }))).status, 204, "Configured production origin overrides an internal proxy host");
  assert.equal((await POST(normalizedRequest())).status, 403);
  assert.equal((await POST(normalizedRequest({ Origin: "https://attacker.example", "X-Forwarded-Host": "attacker.example" }))).status, 403);
  for (const siteUrl of ["not a URL", "https://user@recovery.example", "javascript:alert(1)"]) {
    process.env.NEXT_PUBLIC_SITE_URL = siteUrl;
    assert.equal((await POST(normalizedRequest())).status, 403, "Malformed configuration must fail closed");
  }
  delete process.env.NEXT_PUBLIC_SITE_URL;

  const beforeRejections = events.length;
  for (const payload of [
    { event: "oauth_connected", source: "oauth_callback" },
    { event: "signup_completed", source: "signup" },
    { ...valid, email: "must-not-be-recorded@example.com" },
    { ...valid, source: "/app?tenant=private" },
    { event: "unknown_event" },
    [], null, "{not-json",
  ]) assert.equal((await POST(request(payload))).status, 400);
  assert.equal((await POST(request(valid, { Origin: "https://other.example" }))).status, 403);
  assert.equal((await POST(request(valid, { Origin: "" }))).status, 403);
  assert.equal((await POST(request(valid, { "Sec-Fetch-Site": "cross-site" }))).status, 403);
  assert.equal((await POST(request(valid, { "Content-Type": "text/plain" }))).status, 415);
  assert.equal((await POST(request(valid, { "Content-Length": "513" }))).status, 413);
  assert.equal((await POST(request(" ".repeat(513)))).status, 413);
  const streamed = new Request("https://recovery.example/api/marketing/events", {
    method: "POST", duplex: "half",
    headers: { Origin: "https://recovery.example", "Content-Type": "application/json" },
    body: new ReadableStream({ start(controller) { controller.enqueue(new Uint8Array(300)); controller.enqueue(new Uint8Array(300)); controller.close(); } }),
  });
  assert.equal((await POST(streamed)).status, 413);
  assert.equal(events.length, beforeRejections, "Rejected requests must not enter the event log");

  for (const headers of [{ DNT: "1" }, { "Sec-GPC": "1" }]) {
    assert.equal((await POST(request(valid, headers))).status, 204);
    recordMarketingEvent("oauth_connected", "oauth_callback", new Headers(headers));
  }
  assert.equal(events.length, beforeRejections, "Server opt-outs apply to browser and confirmed conversion events");
  recordMarketingEvent("oauth_connected", "oauth_callback", new Headers());
  assert.equal(events.at(-1).event, "oauth_connected");
  const beforeInvalidServerEvents = events.length;
  recordMarketingEvent("unrecognized", "hero");
  recordMarketingEvent("signup_completed", "tenant@example.com");
  assert.equal(events.length, beforeInvalidServerEvents);

  globalThis.fetch = (...args) => { requests.push(args); return Promise.resolve(new Response(null, { status: 204 })); };
  // Server rendering must not submit a browser event.
  trackMarketingEvent("hero_cta_click", "hero");
  assert.equal(requests.length, 0);
  Object.defineProperty(globalThis, "window", { configurable: true, value: {} });
  setPreferences({});
  trackMarketingEvent("hero_cta_click", "hero");
  assert.equal(requests.length, 1);
  assert.equal(requests[0][0], "/api/marketing/events");
  assert.equal(requests[0][1].credentials, "omit");
  assert.equal(requests[0][1].referrerPolicy, "no-referrer");
  assert.equal(requests[0][1].mode, "same-origin");
  assert.deepEqual(JSON.parse(requests[0][1].body), valid);
  for (const preference of [{ doNotTrack: "1" }, { globalPrivacyControl: true }, { msDoNotTrack: "1" }]) {
    setPreferences(preference);
    trackMarketingEvent("hero_cta_click", "hero");
  }
  assert.equal(requests.length, 1, "Browser opt-outs prevent network requests");
  setPreferences({});
  trackMarketingEvent("oauth_connected", "oauth_callback");
  trackMarketingEvent("hero_cta_click", "private-data");
  assert.equal(requests.length, 1);
  globalThis.fetch = () => { throw new Error("Networking disabled"); };
  assert.doesNotThrow(() => trackMarketingEvent("hero_cta_click", "hero"));
  console.info = () => { throw new Error("Log sink unavailable"); };
  assert.doesNotThrow(() => recordMarketingEvent("signup_completed", "signup"));
} finally {
  console.info = originalInfo;
  globalThis.fetch = originalFetch;
  restore("window", originalWindow);
  restore("navigator", originalNavigator);
  if (originalSiteUrl === undefined) delete process.env.NEXT_PUBLIC_SITE_URL;
  else process.env.NEXT_PUBLIC_SITE_URL = originalSiteUrl;
}
console.log(`Marketing receiver, privacy and failure-isolation checks passed (${fileURLToPath(root)})`);
