// Browser check of ?date= resolution against a built fixture site.
// Usage: node tests/e2e.cjs http://localhost:8000
const { chromium } = require("playwright");
const assert = require("assert");

// The URL may include the --base prefix the site was built with.
const BASE = (process.argv[2] || "http://localhost:8000").replace(/\/$/, "");
const PREFIX = new URL(BASE).pathname.replace(/\/$/, "");
const V1 = "20260115T120000Z", V2 = "20260601T083000Z";
const ESSAY = "/browse/essay/artII-S1-C1-3/ALDE_00013792/";
const NEW = "/browse/essay/artII-S1-C1-4/ALDE_00099999/";
const v = (ver, p) => p.replace("/browse/", `/browse/${ver}/`);

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  async function visit(path, wantPath, wantText, wantQuery) {
    await page.goto(BASE + path);
    if (wantPath) await page.waitForURL((u) => u.pathname === PREFIX + wantPath, { timeout: 5000 });
    if (wantText) assert.ok((await page.textContent("main")).includes(wantText), `${path}: main lacks ${wantText}`);
    if (wantQuery) {
      await page.waitForSelector("#cav-query:not([hidden])");
      const q = await page.textContent("#cav-query");
      assert.ok(q.includes(wantQuery), `${path}: query note "${q}" lacks "${wantQuery}"`);
    }
    console.log("ok", path, "->", new URL(page.url()).pathname + new URL(page.url()).search);
  }
  await visit(ESSAY, v(V2, ESSAY), "VERSION TWO");
  await visit(ESSAY + "?date=2026-03-01", v(V1, ESSAY), "VERSION ONE", "2026-03-01 23:59:59 UTC");
  assert.ok(page.url().endsWith("?date=2026-03-01"));
  await visit(v(V2, ESSAY) + "?date=2026-02", v(V1, ESSAY), "VERSION ONE", "Queried 2026-02");
  await visit(v(V1, ESSAY) + "?date=2027", v(V2, ESSAY), "VERSION TWO", "Queried 2027");
  await visit(v(V1, ESSAY), null, "VERSION ONE", "Newer version available");
  await visit(ESSAY + "?date=2025-12-31", ESSAY, null, "no archived version exists that early");
  await visit(NEW + "?date=2026-03-01", NEW, null, "no archived version as of 2026-03-01");
  await visit("/browse/", v(V2, "/browse/"), "Browse");
  await visit(ESSAY + "?date=junk", ESSAY, null, "not a recognized date");
  await browser.close();
  console.log("all ok");
})().catch((e) => { console.error(e); process.exit(1); });
