import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { stripTypeScriptTypes } from "node:module";
import { NextRequest } from "next/server.js";
import ts from "typescript";
import { renderToStaticMarkup } from "react-dom/server";

const root = new URL("../", import.meta.url);
const dataUrl = source => "data:text/javascript;base64," + Buffer.from(source).toString("base64");
async function moduleUrl(file, imports = {}) {
  const original = await fs.readFile(new URL(file, root), "utf8");
  let source = file.endsWith(".tsx")
    ? ts.transpileModule(original, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
    : stripTypeScriptTypes(original, { mode: "strip" });
  source = source.replace('import "server-only";', "");
  for (const [specifier, target] of Object.entries(imports)) source = source.replaceAll('"' + specifier + '"', JSON.stringify(target));
  return dataUrl(source);
}
const originalFetch = globalThis.fetch;
const originalTimeout = AbortSignal.timeout;
const savedEnv = { NODE_ENV: process.env.NODE_ENV, RECOVERY_API_BASE_URL: process.env.RECOVERY_API_BASE_URL, NEXT_PUBLIC_SITE_URL: process.env.NEXT_PUBLIC_SITE_URL };
const state = { authenticated: true, claimsError: false, sessionError: false, authThrows: false, authThrowsAt: null, proxyClients: 0, proxyCookieChanges: false, calls: [], events: [] };
globalThis.__recoveryTransportTest = state;
const authUrl = dataUrl(`export async function createClient() {
  const s = globalThis.__recoveryTransportTest;
  const fail = step => { if (s.authThrowsAt === step) throw new Error("private auth detail"); };
  if (s.authThrows) throw new Error("private auth detail");
  fail("client");
  return { auth: {
    getClaims: async () => {
      fail("claims");
      return { data: { claims: s.authenticated ? { sub: "test-user" } : null }, error: s.claimsError ? new Error("private auth detail") : null };
    },
    getSession: async () => {
      fail("session");
      return { data: { session: s.authenticated ? { access_token: "private-test-token" } : null }, error: s.sessionError ? new Error("private auth detail") : null };
    },
  } };
}`);
const navUrl = dataUrl('export function redirect(url){const error=new Error("NEXT_REDIRECT");error.target=url;throw error;}');
const eventsUrl = dataUrl('export function recordMarketingEvent(...args){globalThis.__recoveryTransportTest.events.push(args)}');
const transportUrl = await moduleUrl("lib/recovery-api-transport.ts");
const transport = await import(transportUrl);
const navigationUrl = await moduleUrl("lib/auth-navigation.ts");
const imports = {
  "next/server": new URL("node_modules/next/server.js", root).href,
  "@/lib/supabase/server": authUrl,
  "@/lib/auth-navigation": navigationUrl,
  "@/lib/recovery-api-transport": transportUrl,
  "@/lib/marketing-analytics-server": eventsUrl,
  "next/navigation": navUrl,
};
const apiUrl = await moduleUrl("lib/recovery-api.ts", imports);
const api = await import(apiUrl);
const configExport = await import(await moduleUrl("app/api/security-data/export/route.ts", imports));
const reportDownload = await import(await moduleUrl("app/api/reports/[generationId]/[format]/route.ts", imports));
const publicDownload = await import(await moduleUrl("app/api/public-report/[token]/[format]/route.ts", imports));
const shares = await import(await moduleUrl("app/api/reports/[generationId]/shares/route.ts", imports));
const oauth = await import(await moduleUrl("app/api/google-ads/oauth/callback/route.ts", imports));
const ssrUrl = dataUrl(`export function createServerClient(_url, _key, options) {
  const s = globalThis.__recoveryTransportTest;
  s.proxyClients++;
  if (s.authThrowsAt === "client") throw new Error("private auth detail");
  return { auth: { getClaims: async () => {
    if (s.proxyCookieChanges) options.cookies.setAll([{ name: "sb-test", value: "rotated-private-cookie", options: { httpOnly: true, path: "/" } }]);
    if (s.authThrowsAt === "claims") throw new Error("private auth detail");
    return { data: { claims: null }, error: null };
  } } };
}`);
const proxy = await import(await moduleUrl("lib/supabase/proxy.ts", { ...imports, "@supabase/ssr": ssrUrl }));
const jsxUrl = new URL("node_modules/react/jsx-runtime.js", root).href;
const truthUiUrl = dataUrl(`import { jsx } from ${JSON.stringify(jsxUrl)};
  export default function Link(p) { return jsx("a", p); }
  export function AppShell(p) { return jsx("main", { children: p.children }); }
  export function PageHeader(p) { return jsx("h1", { children: p.title }); }
  export function EmptyState(p) { return jsx("p", { children: p.title }); }
  export function StatusBadge(p) { return jsx("span", { children: p.value }); }
`);
const truthContextUrl = dataUrl(`export async function resolveAppContext() {
  const account = { id: "account-id", descriptive_name: "Example advertiser" };
  const membership = { tenant_id: "tenant-id", role: "owner" };
  return { account, membership, me: { memberships: [membership], email: "operator@example.test" }, accounts: [account], portfolios: [], unreadCount: 0 };
}`);
const truthPage = await import(await moduleUrl("app/(dashboard)/app/business-truth/page.tsx", {
  ...imports,
  "react/jsx-runtime": jsxUrl,
  "next/link": truthUiUrl,
  "@/components/epic1/app-shell": truthUiUrl,
  "@/components/epic1/page-header": truthUiUrl,
  "@/components/epic1/empty-state": truthUiUrl,
  "@/components/epic1/status-badge": truthUiUrl,
  "@/lib/epic1/context": truthContextUrl,
  "@/lib/recovery-api": apiUrl,
  "@/lib/format": dataUrl('export const dateTime = value => value; export const label = value => value;'),
  "./actions": dataUrl('export const saveBusinessTruthAction = "/test-action";'),
}));
function backend(factory) {
  state.calls = [];
  globalThis.fetch = async (url, init) => {
    state.calls.push({ url, init });
    return factory(url, init);
  };
}
function request(path = "/", init) { return new NextRequest("https://web.example" + path, init); }
function shareRequest(headers = {}, body = '{"expires_days":14}') {
  return request("/api/reports/report-id/shares?tenant=tenant-id", {
    method: "POST", headers: { origin: "https://web.example", "content-type": "application/json", ...headers }, body,
  });
}
const shareParams = { params: Promise.resolve({ generationId: "report-id" }) };
const oauthRequest = () => new Request("http://internal-container/api/google-ads/oauth/callback?code=private-code&state=private-state");
const tests = [];
const test = (name, run) => tests.push({ name, run });

test("production origins fail closed without leaking configuration", () => {
  delete process.env.RECOVERY_API_BASE_URL;
  assert.throws(() => transport.recoveryApiOrigin(), e => e.code === "API_ORIGIN_MISSING");
  for (const value of ["https://user:secret@api.example", "http://api.example", "https://api.example/path", "https://api.example?key=secret", "https://api.example/#x", "https://api.example\\bad", "https://api.example\t/path"]) {
    assert.throws(() => transport.recoveryApiOrigin(value, true), e => e.code === "API_ORIGIN_INVALID" && !e.message.includes("secret"));
  }
  assert.equal(transport.recoveryApiOrigin("https://api.example///", true), "https://api.example");
  assert.equal(transport.recoveryApiOrigin(undefined, false), "http://127.0.0.1:8000");
  process.env.RECOVERY_API_BASE_URL = "https://api.example/";
  for (const path of ["https://other.example/", "//other.example/", "/v1\\other", "/v1#fragment"]) {
    assert.throws(() => transport.recoveryApiUrl(path), e => e.code === "API_PATH_INVALID");
  }
});

test("requests preserve explicit headers but forbid caching, redirects and token overrides", async () => {
  backend(() => Response.json({ ok: true }));
  assert.deepEqual(await transport.recoveryApiJson("/v1/test?q=value", {
    method: "POST", body: "{}", cache: "force-cache", redirect: "follow",
    headers: new Headers({ "Idempotency-Key": "one-attempt", Authorization: "untrusted-value" }),
  }, "session-token"), { ok: true });
  assert.equal(state.calls.length, 1);
  const { url, init } = state.calls[0];
  assert.equal(url, "https://api.example/v1/test?q=value");
  assert.equal(init.cache, "no-store");
  assert.equal(init.redirect, "error");
  assert.equal(init.headers.get("authorization"), "Bearer session-token");
  assert.equal(init.headers.get("idempotency-key"), "one-attempt");
  assert.ok(init.signal instanceof AbortSignal);
});

test("empty responses, malformed JSON and upstream details are handled honestly", async () => {
  backend(() => new Response(null, { status: 204 }));
  assert.equal(await transport.recoveryApiJson("/v1/test"), undefined);
  backend(() => new Response("<html>upstream diagnostic with secret</html>"));
  await assert.rejects(transport.recoveryApiJson("/v1/test"), e => e.code === "API_RESPONSE_INVALID" && !e.message.includes("secret"));
  const reference = "c47dba18-dfc4-4e47-b283-b4f17fa08f20";
  backend(() => new Response("database password is secret", { status: 503, headers: { "x-request-id": reference } }));
  await assert.rejects(transport.recoveryApiJson("/v1/test"), e => e.status === 503 && e.requestId === reference && !e.message.includes("secret"));
  backend(() => new Response("secret", { status: 400, headers: { "x-request-id": "secret" } }));
  await assert.rejects(transport.recoveryApiJson("/v1/test"), e => e.requestId === null && e.status === 400);
});

test("network failure and cancellation never retry a mutation", async () => {
  backend(() => { throw new Error("DNS/private-host/secret"); });
  await assert.rejects(transport.recoveryApiJson("/v1/mutation", { method: "POST", body: "{}" }), e => e.code === "API_UNREACHABLE" && !e.message.includes("private"));
  assert.equal(state.calls.length, 1);
  backend((_, init) => { assert.equal(init.signal.aborted, true); throw init.signal.reason; });
  await assert.rejects(transport.recoveryApiRequest("/v1/mutation", { method: "POST", signal: AbortSignal.abort() }), e => e.code === "API_TIMEOUT");
  assert.equal(state.calls.length, 1);
  AbortSignal.timeout = () => AbortSignal.abort(new DOMException("Timed out", "TimeoutError"));
  try {
    await assert.rejects(transport.recoveryApiRequest("/v1/mutation", { method: "POST" }), e => e.code === "API_TIMEOUT");
    assert.equal(state.calls.length, 2, "Each explicit call makes exactly one request");
  } finally { AbortSignal.timeout = originalTimeout; }
});

test("expired backend sessions redirect server pages and preserve Next control flow", async () => {
  backend(() => new Response("expired-secret", { status: 401 }));
  await assert.rejects(api.apiFetch("/v1/me"), e => e.target === "/login");
  state.authenticated = false;
  backend(() => { throw new Error("Must not fetch without auth"); });
  await assert.rejects(api.apiFetch("/v1/me"), e => e.target === "/login");
  assert.equal(state.calls.length, 0);
  state.authenticated = true;
  const redirectError = Object.assign(new Error("NEXT_REDIRECT"), { target: "/login" });
  assert.throws(() => transport.recoveryApiErrorMessage(redirectError), e => e === redirectError);
});

test("Business Truth distinguishes a verified empty history from failures and existing versions", async () => {
  const render = async () => renderToStaticMarkup(await truthPage.default({ searchParams: Promise.resolve({}) }));
  backend(() => Response.json([]));
  const empty = await render();
  assert.match(empty, /No Business Truth snapshot exists/);
  assert.match(empty, /Create Business Truth/);
  for (const status of [403, 404, 503]) {
    backend(() => new Response("private service detail", { status }));
    await assert.rejects(render(), error => error instanceof transport.RecoveryApiError && error.status === status);
  }
  backend(() => new Response("expired session", { status: 401 }));
  await assert.rejects(render(), error => error.target === "/login");
  backend(() => Response.json([{
    id: "truth-version-id", version: 2, business_name: "Confirmed advertiser business",
    truth_fingerprint: "abcdef0123456789", created_at: "2026-10-21T00:00:00Z",
    payload: {}, readiness: {}, changed_sections: [], offer_count: 1,
    non_offer_count: 0, intent_policy_count: 0, service_area_count: 0, protected_query_count: 0,
  }]));
  const existing = await render();
  assert.match(existing, /Confirmed advertiser business/);
  assert.match(existing, /Create a new Business Truth version/);
  assert.doesNotMatch(existing, /No Business Truth snapshot exists/);
});

test("proxy refresh outages preserve cookies and leave authorization to protected handlers", async () => {
  state.proxyClients = 0;
  state.authThrowsAt = "client";
  for (const path of ["/", "/product", "/demo", "/api/marketing/events"]) {
    assert.equal((await proxy.updateSession(request(path))).headers.get("x-middleware-next"), "1");
  }
  assert.equal(state.proxyClients, 0, "Public pages must not depend on an auth client");
  assert.equal((await proxy.updateSession(request("/onboarding"))).headers.get("x-middleware-next"), "1");
  state.authThrowsAt = "claims";
  state.proxyCookieChanges = true;
  const req = request("/api/export?tenant=tenant-id");
  const response = await proxy.updateSession(req);
  assert.equal(response.headers.get("x-middleware-next"), "1");
  assert.equal(req.cookies.get("sb-test").value, "rotated-private-cookie");
  assert.equal(response.cookies.get("sb-test").value, "rotated-private-cookie");
  assert.equal(response.cookies.get("sb-test").httpOnly, true);
  state.proxyCookieChanges = false;
  state.authThrowsAt = null;
  state.authenticated = false;
  backend(() => { throw new Error("No authorization is granted by proxy continuation"); });
  assert.equal((await configExport.GET(req)).status, 401);
  assert.equal(state.calls.length, 0);
  state.authenticated = true;
});

test("private downloads require claims and return sanitized errors without attachment headers", async () => {
  const req = request("/api/export?tenant=tenant-id");
  state.claimsError = true;
  backend(() => { throw new Error("Must not fetch without claims"); });
  assert.equal((await configExport.GET(req)).status, 401);
  assert.equal(state.calls.length, 0);
  state.claimsError = false;
  backend(() => new Response("database-password", { status: 403 }));
  const result = await reportDownload.GET(req, { params: Promise.resolve({ generationId: "report-id", format: "pdf" }) });
  assert.equal(result.status, 403);
  assert.equal(result.headers.get("content-disposition"), null);
  assert.equal((await result.json()).code, "API_HTTP_403");
  backend(() => new Response('{"safe":"configuration"}', { headers: { "content-type": "application/json" } }));
  const exported = await configExport.GET(req);
  assert.equal(exported.status, 200);
  assert.match(exported.headers.get("content-disposition"), /attachment/);
  assert.equal(state.calls[0].init.headers.get("authorization"), "Bearer private-test-token");
});

test("authenticated routes report auth outages without exposing credentials or sending a mutation", async () => {
  const routes = [
    () => configExport.GET(request("/api/export?tenant=tenant-id")),
    () => reportDownload.GET(request("/api/report?tenant=tenant-id"), { params: Promise.resolve({ generationId: "report-id", format: "pdf" }) }),
    () => shares.POST(shareRequest(), shareParams),
  ];
  backend(() => { throw new Error("Must not fetch when authentication fails"); });
  for (const invoke of routes) {
    for (const step of ["client", "claims", "session"]) {
      state.authThrowsAt = step;
      const result = await invoke();
      assert.equal(result.status, 503);
      assert.equal(result.headers.get("content-disposition"), null);
      assert.equal(result.headers.get("cache-control"), "no-store");
      const body = await result.json();
      assert.equal(body.code, "AUTH_UNAVAILABLE");
      assert.equal(JSON.stringify(body).includes("private"), false);
    }
    state.authThrowsAt = null;
    for (const key of ["claimsError", "sessionError"]) {
      state[key] = true;
      assert.equal((await invoke()).status, 401);
      state[key] = false;
    }
  }
  assert.equal(state.calls.length, 0);
});

test("report downloads preserve artifacts and reject partial bodies", async () => {
  backend(() => new Response(new Uint8Array([0, 1, 2]), { headers: { "content-type": "application/pdf", "x-artifact-sha256": "test-digest" } }));
  const result = await reportDownload.GET(request("/api/report?tenant=tenant-id"), { params: Promise.resolve({ generationId: "report-id", format: "pdf" }) });
  assert.deepEqual([...new Uint8Array(await result.arrayBuffer())], [0, 1, 2]);
  assert.equal(result.headers.get("x-artifact-sha256"), "test-digest");
  backend(() => new Response(new ReadableStream({ start(controller) { controller.error(new Error("private socket diagnostic")); } })));
  const failed = await publicDownload.GET(request(), { params: Promise.resolve({ token: "share/token?private", format: "csv" }) });
  assert.equal(failed.status, 502);
  assert.equal((await failed.json()).code, "API_DOWNLOAD_INTERRUPTED");
  assert.equal(state.calls[0].init.headers.has("authorization"), false);
  assert.match(state.calls[0].url, /share%2Ftoken%3Fprivate/);
});

test("share mutation rejects CSRF and invalid JSON without touching the backend", async () => {
  backend(() => { throw new Error("Must not fetch rejected input"); });
  assert.equal((await shares.POST(shareRequest({ origin: "https://attacker.example" }), shareParams)).status, 403);
  assert.equal((await shares.POST(shareRequest({ "content-type": "text/plain" }), shareParams)).status, 415);
  assert.equal((await shares.POST(shareRequest({}, "{broken"), shareParams)).status, 400);
  assert.equal(state.calls.length, 0);
});

test("share mutation returns an actual created capability or an honest failure", async () => {
  backend(() => Response.json({ token: "actual-share-token" }, { status: 201 }));
  const created = await shares.POST(shareRequest(), shareParams);
  assert.equal(created.status, 201);
  assert.equal((await created.json()).token, "actual-share-token");
  assert.equal(state.calls.length, 1);
  backend(() => Response.json({}));
  const missing = await shares.POST(shareRequest(), shareParams);
  assert.equal(missing.status, 502);
  assert.equal((await missing.json()).code, "API_RESPONSE_INVALID");
});

test("OAuth authentication outages do not consume callback codes or claim success", async () => {
  state.events = [];
  backend(() => { throw new Error("Must not fetch when authentication fails"); });
  for (const step of ["client", "claims", "session"]) {
    state.authThrowsAt = step;
    const result = await oauth.GET(oauthRequest());
    const target = new URL(result.headers.get("location"));
    assert.equal(target.origin, "https://web.example");
    assert.equal(target.pathname, "/onboarding");
    assert.match(target.searchParams.get("oauth_error"), /sign-in could not be verified/);
    assert.equal(target.href.includes("private"), false);
    assert.equal(result.headers.get("cache-control"), "no-store");
    assert.equal(result.headers.get("referrer-policy"), "no-referrer");
  }
  state.authThrowsAt = null;
  for (const key of ["claimsError", "sessionError"]) {
    state[key] = true;
    assert.equal((await oauth.GET(oauthRequest())).headers.get("location"), "https://web.example/login");
    state[key] = false;
  }
  assert.equal(state.calls.length, 0);
  assert.equal(state.events.length, 0);
});

test("OAuth uses public origin and never exposes or replays a failed callback", async () => {
  state.events = [];
  backend(() => new Response("private code private-state", { status: 401 }));
  assert.equal((await oauth.GET(oauthRequest())).headers.get("location"), "https://web.example/login");
  assert.equal(state.calls.length, 1);
  backend(() => { throw new Error("secret-provider-detail"); });
  const failed = await oauth.GET(oauthRequest());
  const target = new URL(failed.headers.get("location"));
  assert.equal(target.origin, "https://web.example");
  assert.equal(target.pathname, "/onboarding");
  assert.ok(target.searchParams.get("oauth_error"));
  assert.equal(target.href.includes("secret"), false);
  assert.equal(state.events.length, 0);
  assert.equal(state.calls.length, 1);
});

test("OAuth requires a complete receipt and blocks external stored return paths", async () => {
  state.events = [];
  for (const payload of [{}, null, { tenant_id: "tenant-id", discovery_job: { job_id: "job-id" }, return_path: "//attacker.example" }, { tenant_id: "tenant-id", discovery_job: { job_id: "job-id" }, return_path: "/\\attacker.example" }]) {
    backend(() => Response.json(payload));
    const target = new URL((await oauth.GET(oauthRequest())).headers.get("location"));
    assert.equal(target.origin, "https://web.example");
    assert.ok(target.searchParams.get("oauth_error"));
  }
  assert.equal(state.events.length, 0);
  backend(() => Response.json({ tenant_id: "tenant-id", discovery_job: { job_id: "job-id" }, return_path: "/onboarding" }));
  const success = await oauth.GET(oauthRequest());
  const target = new URL(success.headers.get("location"));
  assert.equal(target.origin, "https://web.example");
  assert.equal(target.searchParams.get("tenant"), "tenant-id");
  assert.equal(target.searchParams.get("discovery_job"), "job-id");
  assert.equal(target.searchParams.has("oauth_error"), false);
  assert.equal(state.events[0][0], "oauth_connected");
  assert.equal(success.headers.get("referrer-policy"), "no-referrer");
});

try {
  process.env.NODE_ENV = "production";
  process.env.RECOVERY_API_BASE_URL = "https://api.example";
  process.env.NEXT_PUBLIC_SITE_URL = "https://web.example";
  for (const { name, run } of tests) {
    await run();
    console.log("PASS " + name);
  }
  console.log(tests.length + " Recovery API transport and route regression checks passed.");
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
} finally {
  globalThis.fetch = originalFetch;
  AbortSignal.timeout = originalTimeout;
  delete globalThis.__recoveryTransportTest;
  for (const [key, value] of Object.entries(savedEnv)) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
}
