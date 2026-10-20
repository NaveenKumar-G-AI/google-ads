import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

// Run against `npm run dev` or a production `npm start` server.
// Supply PLAYWRIGHT_MODULE_PATH when playwright-core lives outside this project.
const modulePath = process.env.PLAYWRIGHT_MODULE_PATH;
const { chromium } = await import(modulePath ? pathToFileURL(modulePath).href : "playwright-core");
const base = process.env.MARKETING_TEST_URL || "http://127.0.0.1:3000";
const output = path.resolve(process.env.MARKETING_SCREENSHOTS || "../.cache/marketing-qa");
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  ...(process.env.BROWSER_EXECUTABLE ? { executablePath: process.env.BROWSER_EXECUTABLE } : {}),
});
const routes = ["/", "/product", "/for-agencies", "/for-brands", "/reporting", "/security", "/pricing", "/demo", "/recovery-review", "/terms", "/privacy", "/data-deletion", "/status"];
const failures = [];
const javascriptErrors = [];
const links = new Set();
const receivedEvents = [];
const unsolicitedProtectedRequests = [];
const screenshots = [];
const accessibility = [];
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
const page = await context.newPage();
// Cold local dev builds can exceed Playwright's 30s default on Windows.
page.setDefaultNavigationTimeout(120_000);
page.on("pageerror", (error) => javascriptErrors.push(error.message));
page.on("request", (request) => {
  if (/^\/(?:app|internal)(?:\/|$)/.test(new URL(request.url()).pathname)) unsolicitedProtectedRequests.push(request.url());
});
page.on("response", (response) => {
  if (new URL(response.url()).pathname === "/api/marketing/events") {
    receivedEvents.push({ status: response.status(), ...response.request().postDataJSON() });
  }
});
async function check(name, callback) {
  try { await callback(); console.log(`PASS ${name}`); }
  catch (error) { failures.push({ name, error: error.message }); console.error(`FAIL ${name}: ${error.message}`); }
}
async function screenshot(name) {
  const target = path.join(output, `${name}.png`);
  await page.evaluate(() => { window.scrollTo({ top: 0, behavior: "instant" }); });
  await page.screenshot({ path: target, fullPage: true, animations: "disabled" });
  screenshots.push(target);
  if (/^(home|demo)-\d+$/.test(name)) {
    const viewportTarget = path.join(output, `${name}-viewport.png`);
    await page.screenshot({ path: viewportTarget, fullPage: false, animations: "disabled" });
    screenshots.push(viewportTarget);
  }
}
async function assertNoOverflow() {
  const result = await page.evaluate(() => ({ viewport: window.innerWidth, width: document.documentElement.scrollWidth }));
  assert.ok(result.width <= result.viewport + 2, `Horizontal overflow: ${result.width}px in ${result.viewport}px viewport`);
}
async function auditAccessibility(name) {
  if (!process.env.AXE_SCRIPT) return;
  await page.addScriptTag({ path: process.env.AXE_SCRIPT });
  const { violations } = await page.evaluate(() => window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] } }));
  accessibility.push({ name, violations });
  await check(`WCAG accessibility ${name}`, async () => assert.equal(violations.length, 0, violations.map(({ id, nodes }) => `${id}: ${nodes.length} elements (details in results.json)`).join("; ")));
}
try {
  for (const route of routes) {
    await check(`public route ${route}`, async () => {
      const response = await page.goto(`${base}${route}`, { waitUntil: "networkidle" });
      assert.equal(response.status(), 200);
      assert.equal(await page.locator("main").count(), 1);
      assert.equal(await page.locator("h1").count(), 1);
      await assertNoOverflow();
      for (const href of await page.locator("a[href]").evaluateAll((nodes) => nodes.map((node) => node.getAttribute("href")))) {
        assert.notEqual(href, "#", "A link must have a real target");
        if (href.startsWith("/")) links.add(href);
        if (href.startsWith("#")) assert.ok(await page.locator(`[id="${href.slice(1)}"]`).count(), `Missing anchor ${href}`);
      }
      await screenshot(`desktop-${route === "/" ? "home" : route.slice(1)}`);
      if (!["/", "/demo"].includes(route)) await auditAccessibility(`${route.slice(1)}-1440`);
    });
  }
  await check("public local links and connection entry", async () => {
    for (const href of links) {
      const url = new URL(href, base);
      // Authenticated destinations are source-audited, not exercised without a session.
      if (url.pathname.startsWith("/app") || url.pathname === "/onboarding") continue;
      const response = await context.request.get(url.href);
      assert.ok(response.status() >= 200 && response.status() < 400, `${href} returned ${response.status()}`);
      if (url.hash) assert.ok((await response.text()).includes(`id="${decodeURIComponent(url.hash.slice(1))}"`), `Missing linked anchor ${href}`);
    }
    const response = await page.goto(`${base}/connect`, { waitUntil: "networkidle" });
    assert.equal(response.status(), 200);
    assert.equal(new URL(page.url()).pathname, "/signup");
    assert.ok((await page.locator("body").innerText()).includes("Google Ads connection is requested later"));
  });
  await check("signup and login have accessible fields without submitting credentials", async () => {
    for (const [route, emailLabel, autocomplete] of [["/signup", "Work email", "new-password"], ["/login", "Email", "current-password"]]) {
      const response = await page.goto(`${base}${route}`, { waitUntil: "networkidle" });
      assert.equal(response.status(), 200);
      assert.equal(await page.getByLabel(emailLabel, { exact: true }).getAttribute("type"), "email");
      assert.equal(await page.getByLabel("Password", { exact: true }).getAttribute("type"), "password");
      assert.equal(await page.getByLabel("Password", { exact: true }).getAttribute("autocomplete"), autocomplete);
      assert.ok((await page.locator('meta[name="robots"]').getAttribute("content")).includes("noindex"));
    }
  });
  for (const width of [1440, 1024, 768, 390]) {
    await check(`responsive home and tour ${width}px`, async () => {
      await page.setViewportSize({ width, height: 1000 });
      await page.goto(base, { waitUntil: "networkidle" });
      await assertNoOverflow();
      await screenshot(`home-${width}`);
      if ([1440, 390].includes(width)) await auditAccessibility(`home-${width}`);
      await page.goto(`${base}/demo`, { waitUntil: "networkidle" });
      await assertNoOverflow();
      await screenshot(`demo-${width}`);
      if ([1440, 390].includes(width)) await auditAccessibility(`demo-${width}`);
    });
    if (width !== 1440) {
      for (const route of routes.filter((route) => !["/", "/demo"].includes(route))) {
        await check(`responsive ${route} ${width}px`, async () => {
          await page.goto(`${base}${route}`, { waitUntil: "networkidle" });
          await assertNoOverflow();
          if (width === 390) {
            await screenshot(`mobile-${route.slice(1)}`);
            await auditAccessibility(`${route.slice(1)}-${width}`);
          }
        });
      }
    }
  }
  await check("mobile menu opens and closes with Escape", async () => {
    await page.goto(base, { waitUntil: "networkidle" });
    const toggle = page.getByRole("button", { name: "Open navigation", exact: true });
    await toggle.click();
    assert.equal(await page.getByRole("button", { name: "Close navigation", exact: true }).getAttribute("aria-expanded"), "true");
    const navigation = page.getByRole("navigation", { name: "Mobile navigation" });
    await navigation.getByRole("link", { name: "Product", exact: true }).focus();
    await page.keyboard.press("Escape");
    assert.equal(await page.getByRole("button", { name: "Open navigation", exact: true }).getAttribute("aria-expanded"), "false");
    assert.ok(await toggle.evaluate((node) => node === document.activeElement), "Escape must return focus to the navigation toggle");
  });
  await check("nine-step demonstration blocks protected intent and preserves $0 verified recovery", async () => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(`${base}/demo`, { waitUntil: "networkidle" });
    await page.locator(".m-page-hero").getByRole("link", { name: "See how Recovery works" }).click();
    assert.equal(new URL(page.url()).hash, "#product-tour");
    assert.equal(await page.locator("#product-tour").count(), 1);
    const story = page.locator(".m-tour-story");
    assert.equal(await page.getByRole("button", { name: "Previous tour step" }).isDisabled(), true);
    for (let step = 1; step <= 9; step++) {
      assert.ok((await story.innerText()).includes(`STEP ${step} OF 9`));
      assert.ok((await story.innerText()).includes("No live account is connected or changed"));
      if (step === 5) {
        assert.ok((await page.locator(".m-tour-scene").innerText()).includes("Action blocked"));
        assert.ok((await page.locator(".m-tour-scene").innerText()).includes("[roofing company]"));
        await screenshot("demo-blocked");
      }
      if (step < 9) await story.getByRole("button").last().click();
    }
    const verified = page.locator(".m-tour-scene .m-money-verified");
    assert.ok((await verified.innerText()).includes("$0"));
    assert.ok((await verified.innerText()).includes("Causal evidence pending"));
    assert.ok((await story.innerText()).includes("non-additive"));
    await screenshot("demo-completed");
    await page.getByRole("button", { name: "Replay story" }).click();
    assert.ok((await story.innerText()).includes("STEP 1 OF 9"));
  });
  await check("real browser telemetry reaches the first-party receiver", async () => {
    await page.waitForLoadState("networkidle");
    for (const event of ["pricing_open", "security_page_open", "product_tour_open", "product_tour_complete"]) {
      assert.ok(receivedEvents.some((record) => record.event === event && record.status === 204), `${event} was not accepted`);
    }
    for (const record of receivedEvents) {
      assert.ok(Object.keys(record).every((key) => ["event", "source", "status"].includes(key)));
    }
  });
  await check("no uncaught browser errors", async () => assert.deepEqual(javascriptErrors, []));
  await check("public pages never prefetch protected workspace routes", async () => assert.deepEqual(unsolicitedProtectedRequests, []));
} finally {
  await fs.writeFile(path.join(output, "results.json"), JSON.stringify({ base, generatedAt: new Date().toISOString(), failures, javascriptErrors, unsolicitedProtectedRequests, receivedEvents, localLinks: [...links], screenshots, accessibility }, null, 2));
  await browser.close();
}
if (failures.length) process.exitCode = 1;
else console.log(`All browser checks passed. Screenshots: ${output}`);
