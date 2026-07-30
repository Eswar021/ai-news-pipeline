import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";

import {
  capabilities,
  catalog,
  comparison,
  configFiles,
  runs,
} from "./fixtures/browser-data.mjs";

const port = 4174;
const base = `http://127.0.0.1:${port}`;
const vite = spawn(
  process.execPath,
  [path.resolve("node_modules/vite/bin/vite.js"), "--host", "127.0.0.1", "--port", String(port), "--strictPort"],
  { cwd: process.cwd(), stdio: ["ignore", "pipe", "pipe"] },
);
let viteError = "";
vite.stderr.on("data", (chunk) => { viteError += String(chunk); });

async function waitForServer() {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    if (vite.exitCode !== null) throw new Error(viteError || `Vite exited ${vite.exitCode}`);
    try {
      const response = await fetch(base);
      if (response.ok) return;
    } catch {
      // The server is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("Timed out waiting for the fixture UI server");
}

function json(route, value, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(value),
  });
}

async function installRoutes(page) {
  await page.route("**/api/catalog", (route) => json(route, catalog));
  await page.route("**/api/runs", (route) => json(route, { runs }));
  await page.route("**/api/compare/runs?*", (route) => json(route, comparison));
  await page.route("**/control/jobs", async (route) => {
    if (route.request().method() === "GET") return json(route, { active_job: null, jobs: [] });
    return json(route, { job: { id: "job_fixture", status: "queued", run_id: "run_fixture_new" } });
  });
  await page.route("**/control/capabilities", (route) => json(route, capabilities));
  await page.route("**/control/plans/preview", async (route) => {
    const requested = JSON.parse(route.request().postData() || "{}");
    const runId = requested.run_id || "run_fixture_new";
    const order = ["collect", "content", "voiceover", "visuals"];
    const target = order.indexOf(requested.target_stage || "content");
    const end = requested.run_to_stage ? order.indexOf(requested.run_to_stage) : target;
    const stages = requested.operation === "new" ? order.slice(0, target + 1) : order.slice(target, end + 1);
    return json(route, {
      plan: { ...requested, run_id: runId, profile: requested.profile || "fixture_daily", environment: requested.environment || "dev" },
      run_id: runId,
      commands: stages.map((stage) => ({ stage, display: `python3 -m src.pipeline.orchestration.runner ${stage} --run-id ${runId}` })),
      risk_notes: ["Fixture provider calls may occur.", "Live mode reloads current authoring YAML."],
      requires_provider_confirmation: stages.includes("content"),
      requires_final_confirmation: (requested.target_stage === "voiceover" && requested.synthesis_mode === "final") || (requested.target_stage === "visuals" && !requested.skip_render),
    });
  });
  await page.route("**/control/config/files", (route) => json(route, { files: configFiles }));
  await page.route("**/control/config/file?*", (route) => json(route, {
    path: new URL(route.request().url()).searchParams.get("path") || "workbench.yaml",
    text: "default_run_profile: fixture_daily\ndefault_environment: dev\n",
    sha256: "a".repeat(64),
    size: 64,
  }));
  await page.route("**/control/config/revisions?*", (route) => json(route, { revisions: [] }));
}

let browser;
try {
  await waitForServer();
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const browserErrors = [];
  page.on("console", (entry) => {
    if (entry.type() === "error") browserErrors.push(entry.text());
  });
  page.on("pageerror", (error) => browserErrors.push(error.message));
  await installRoutes(page);
  await page.goto(base, { waitUntil: "networkidle" });

  await assertPageFits(page, "desktop Run Desk");
  await assertVisible(page, "h2", "Run desk");
  await assertVisible(page, ".currentRunLead h3", "Fixture Daily");
  await page.locator("nav.globalNav").getByRole("button", { name: "New run" }).click();
  await assertVisible(page, "h2", "New run");
  await page.waitForSelector(".commandSequence code");
  assert.match(await page.locator(".commandSequence").innerText(), /src\.pipeline\.orchestration\.runner collect/);
  assert.equal(await page.getByRole("tab", { name: "New pipeline" }).getAttribute("aria-selected"), "true");
  await assertPageFits(page, "desktop New Run");

  await page.locator("nav.globalNav").getByRole("button", { name: "Compare" }).click();
  await page.locator(".comparisonPicker").getByRole("button", { name: "Compare", exact: true }).click();
  await assertVisible(page, ".moduleMatrix", "Script generation");
  await page.getByRole("button", { name: "Script" }).click();
  await assertVisible(page, ".diffBlock", "Right narration");
  await assertPageFits(page, "desktop comparison");

  await page.locator("nav.globalNav").getByRole("button", { name: "Config" }).click();
  await page.waitForSelector(".yamlEditor");
  assert.match(await page.locator(".yamlEditor").inputValue(), /default_run_profile/);
  await page.keyboard.press("Tab");
  assert.notEqual(await page.evaluate(() => document.activeElement?.tagName), "BODY");
  await assertPageFits(page, "desktop Config Studio");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator("nav.globalNav").getByRole("button", { name: "Run desk" }).click();
  await assertVisible(page, "h2", "Run desk");
  await assertPageFits(page, "mobile Run Desk");
  await page.locator("nav.globalNav").getByRole("button", { name: "New run" }).click();
  await assertVisible(page, "h2", "New run");
  await assertPageFits(page, "mobile New Run");

  const temp = await mkdtemp(path.join(os.tmpdir(), "run-desk-browser-"));
  await page.screenshot({ path: path.join(temp, "mobile-new-run.png"), fullPage: true });
  assert.deepEqual(browserErrors, []);
  process.stdout.write("browser smoke: desktop/mobile Run Desk, New Run, Compare, Config, keyboard focus passed\n");
} finally {
  if (browser) await browser.close();
  vite.kill("SIGTERM");
}

async function assertVisible(page, selector, text) {
  const locator = page.locator(selector).filter({ hasText: text }).first();
  await locator.waitFor({ state: "visible" });
  assert.equal(await locator.isVisible(), true);
}

async function assertPageFits(page, label) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  const offenders = overflow > 0
    ? await page.evaluate(() => Array.from(document.querySelectorAll("*"))
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return { tag: element.tagName, className: String(element.className), left: Math.round(rect.left), right: Math.round(rect.right), width: Math.round(rect.width) };
      })
      .filter((rect) => rect.right > window.innerWidth + 1 || rect.left < -1)
      .sort((left, right) => right.right - left.right)
      .slice(0, 5))
    : [];
  assert.ok(overflow <= 0, `${label} has ${overflow}px horizontal overflow: ${JSON.stringify(offenders)}`);
}
