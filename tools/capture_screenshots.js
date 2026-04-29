/**
 * Capture all Argus screenshots in one shot.
 *
 * Prereqs:
 *   make demo                # stack running with seeded engagements
 *   cd tools && npm install playwright && npx playwright install chromium
 *
 * Run:
 *   node tools/capture_screenshots.js
 *
 * Outputs land in docs/screenshots/. Re-run anytime — files are overwritten.
 */

const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const ROOT = path.resolve(__dirname, "..");
const OUT_DIR = path.join(ROOT, "docs", "screenshots");
const CASE_STUDY_DIR = path.join(
  ROOT,
  "docs",
  "case-studies",
  "germany-vs-france",
  "screenshots"
);

const BASE = process.env.ARGUS_FRONTEND_URL || "http://localhost:3000";
const VIEWPORT = { width: 1440, height: 900 };

const GERMANY_FRANCE_ID = "11111111-1111-4111-8111-111111111111";

if (!fs.existsSync(OUT_DIR)) fs.mkdirSync(OUT_DIR, { recursive: true });
if (!fs.existsSync(CASE_STUDY_DIR)) fs.mkdirSync(CASE_STUDY_DIR, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function capture(page, url, file, opts = {}) {
  console.log(`  → ${file}`);
  await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
  await sleep(opts.settleMs ?? 1200);
  if (opts.click) {
    try {
      await page.click(opts.click, { timeout: 4000 });
      await sleep(opts.afterClickMs ?? 800);
    } catch (e) {
      console.warn(`    (click "${opts.click}" failed: ${e.message})`);
    }
  }
  const target = path.join(OUT_DIR, file);
  await page.screenshot({
    path: target,
    fullPage: opts.fullPage ?? false,
    clip: opts.clip,
  });
  if (opts.alsoCopyToCaseStudy) {
    fs.copyFileSync(target, path.join(CASE_STUDY_DIR, file));
  }
}

async function main() {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: VIEWPORT });
  const page = await context.newPage();

  console.log("Capturing Argus screenshots →", OUT_DIR);
  console.log("  base URL:", BASE);

  // 1. Hero (homepage with seeded engagements)
  await capture(page, `${BASE}/`, "hero.png");

  // 2. Composer focused
  await capture(page, `${BASE}/`, "composer.png", {
    click: 'textarea, input[type="text"]',
    afterClickMs: 400,
  });

  // 5. Workspace finished — Germany vs France, Answer tab
  await capture(page, `${BASE}/sessions/${GERMANY_FRANCE_ID}`, "workspace-finished.png", {
    settleMs: 2000,
    alsoCopyToCaseStudy: true,
  });

  // 6. Evidence graph tab
  await capture(page, `${BASE}/sessions/${GERMANY_FRANCE_ID}`, "evidence-graph.png", {
    settleMs: 2000,
    click: 'button[role="tab"]:has-text("Graph")',
    afterClickMs: 1500,
    alsoCopyToCaseStudy: true,
  });

  // 8. Audit tab
  await capture(page, `${BASE}/sessions/${GERMANY_FRANCE_ID}`, "audit-panel.png", {
    settleMs: 2000,
    click: 'button[role="tab"]:has-text("Audit")',
    afterClickMs: 1200,
    alsoCopyToCaseStudy: true,
  });

  // 7. Trust rail close-up (crop right column)
  await page.goto(`${BASE}/sessions/${GERMANY_FRANCE_ID}`, { waitUntil: "networkidle" });
  await sleep(1500);
  await page.screenshot({
    path: path.join(OUT_DIR, "trust-rail.png"),
    clip: { x: VIEWPORT.width - 360, y: 60, width: 360, height: VIEWPORT.height - 80 },
  });
  fs.copyFileSync(
    path.join(OUT_DIR, "trust-rail.png"),
    path.join(CASE_STUDY_DIR, "trust-rail.png")
  );
  console.log("  → trust-rail.png");

  // 3 + 4 + 9 require interactive states (mid-processing, intake, PDF) — hand-capture.
  console.log("");
  console.log("Manual captures still needed:");
  console.log("  • intake.png         — create a new session, screenshot intake Q&A");
  console.log("  • processing-sse.png — start a run, screenshot mid-pipeline");
  console.log("  • exported-pdf.png   — export PDF and screenshot first page");

  await browser.close();
  console.log("\nDone.");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
