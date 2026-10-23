import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { stripTypeScriptTypes } from "node:module";

const root = new URL("../", import.meta.url);
const dataModule = (source) => `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
async function sourceModule(file, imports = {}) {
  let source = stripTypeScriptTypes(await fs.readFile(new URL(file, root), "utf8"));
  for (const [name, url] of Object.entries(imports)) source = source.replaceAll(`"${name}"`, JSON.stringify(url));
  return dataModule(source);
}
const state = { calls: [], events: [], result: { data: { session: {}, user: { identities: [{}] } }, error: null }, fail: false };
globalThis.__recoveryAuthTest = state;
const client = dataModule(`export async function createClient() { const s=globalThis.__recoveryAuthTest; return { auth: new Proxy({}, {get: (_, method) => async (...args) => { s.calls.push({method,args}); if(s.fail) throw new Error('private-provider-detail'); return s.result; }}) }; }`);
const navigation = dataModule(`export function redirect(path) { const e=new Error('NEXT_REDIRECT'); e.destination=path; throw e; }`);
const nextServer = dataModule(`export const NextResponse={redirect: (url, init={}) => { const headers=new Headers(init.headers); headers.set('location',String(url)); return new Response(null, {status:307,headers}); }};`);
const nextHeaders = dataModule(`export async function headers() { return new Headers({origin:'https://untrusted.example'}); }`);
const analytics = dataModule(`export function recordMarketingEvent(event) { globalThis.__recoveryAuthTest.events.push(event); }`);
const originModule = await sourceModule("lib/auth-navigation.ts");
const imports = { "@/lib/supabase/server": client, "@/lib/auth-navigation": originModule, "next/navigation": navigation, "next/server": nextServer, "next/headers": nextHeaders, "@/lib/marketing-analytics-server": analytics };
const { authSiteOrigin } = await import(originModule);
const { GET } = await import(await sourceModule("app/api/auth/callback/route.ts", imports));
const { signIn } = await import(await sourceModule("app/(auth)/login/actions.ts", imports));
const { signUp } = await import(await sourceModule("app/(auth)/signup/actions.ts", imports));
const saved = Object.fromEntries(["NODE_ENV", "NEXT_PUBLIC_SITE_URL", "NEXT_PUBLIC_SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY"].map((name) => [name, process.env[name]]));
const originalError = console.error;
const logs = [];
console.error = (...values) => logs.push(values.join(" "));
async function destination(action) {
  try { await action(); assert.fail("Expected framework redirect"); }
  catch (error) { assert.equal(error.message, "NEXT_REDIRECT"); return error.destination; }
}
const form = new FormData();
form.set("email", "new-user@example.com");
form.set("password", "test-password-long-enough");
try {
  process.env.NODE_ENV = "production";
  process.env.NEXT_PUBLIC_SITE_URL = "https://app.example.com/";
  process.env.NEXT_PUBLIC_SUPABASE_URL = "https://test.supabase.co";
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY = "synthetic-key-not-used-for-network";
  assert.equal(authSiteOrigin(" https://app.example.com/ ", "https://untrusted.example"), "https://app.example.com");
  for (const value of [undefined, "", "https://user:secret@app.example.com", "https://app.example.com/path", "https://app.example.com?x=1", "https://app.example.com#x", "http://remote.example", "javascript:alert(1)", "https://app.example.com\\@other.example"]) {
    assert.throws(() => authSiteOrigin(value, "https://untrusted.example"));
  }
  assert.equal(authSiteOrigin(undefined, "http://localhost:3000", false), "http://localhost:3000");
  assert.equal(await destination(() => signIn(form)), "/onboarding");
  state.result = { data: { session: null }, error: { message: "private-provider-detail" } };
  assert.match(await destination(() => signIn(form)), /^\/login\?error=/);
  state.fail = true;
  assert.match(await destination(() => signIn(form)), /^\/login\?error=/);
  state.fail = false;
  const request = (query) => new Request(`http://internal-container:10000/api/auth/callback${query}`);
  for (const query of ["", "?error=denied", "?code=expired"]) {
    const response = await GET(request(query));
    assert.equal(response.status, 307);
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal(response.headers.get("referrer-policy"), "no-referrer");
    assert.match(response.headers.get("location"), /^https:\/\/app\.example\.com\/login\?error=/);
    assert.ok(!response.headers.get("location").includes("expired"));
  }
  state.fail = true;
  assert.match((await GET(request("?code=test"))).headers.get("location"), /\/login\?error=/);
  state.fail = false;
  state.result = { data: { session: {}, user: { identities: [{}] } }, error: null };
  const confirmed = await GET(request("?code=test"));
  assert.equal(confirmed.headers.get("location"), "https://app.example.com/onboarding");
  assert.equal(confirmed.headers.get("cache-control"), "no-store");
  assert.equal(confirmed.headers.get("referrer-policy"), "no-referrer");
  state.result = { data: { session: null, user: { identities: [{}] } }, error: null };
  assert.match(await destination(() => signUp(form)), /^\/login\?message=/);
  const signupCall = state.calls.findLast(({ method }) => method === "signUp");
  assert.equal(signupCall.args[0].options.emailRedirectTo, "https://app.example.com/api/auth/callback");
  assert.equal(state.events.filter((event) => event === "signup_completed").length, 1);
  state.result = { data: { session: null, user: { identities: [] } }, error: null };
  await destination(() => signUp(form));
  assert.equal(state.events.filter((event) => event === "signup_completed").length, 1);
  state.fail = true;
  assert.match(await destination(() => signUp(form)), /^\/signup\?error=/);
  delete process.env.NEXT_PUBLIC_SITE_URL;
  assert.equal((await GET(request("?code=test"))).status, 503);
  assert.ok(logs.every((line) => !line.includes("private-provider-detail")));
  console.log("PASS authentication actions, confirmation failures, trusted redirect origin and event truth");
} finally {
  console.error = originalError;
  for (const [name, value] of Object.entries(saved)) value === undefined ? delete process.env[name] : process.env[name] = value;
  delete globalThis.__recoveryAuthTest;
}
