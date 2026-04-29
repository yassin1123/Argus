# Capture Guide — Argus Screenshots

This guide walks through capturing the screenshots referenced in [`README.md`](../../README.md). Two paths:

- **Automatic** — run `node tools/capture_screenshots.js` (uses Playwright; ~30 seconds).
- **Manual** — follow the shot list below in any browser.

Both paths assume `make demo` is running and the seeded engagements are loaded.

---

## Pre-flight

```bash
make demo                              # bring up stack with seeded engagements
open http://localhost:3000             # confirm three demo engagements visible
```

The Germany-vs-France engagement should already be `complete` and clickable.

**Browser viewport:** 1440 × 900 (matches all SVG placeholders). Use Chrome's DevTools device toolbar set to "Responsive" with 1440×900 if your physical screen is smaller.

---

## Shot list

| # | File | Viewport | URL / state | What to capture |
|---|------|----------|-------------|-----------------|
| 1 | `hero.png` | 1440×900 | `/` | Homepage with three seeded engagements visible. This is the hero image for the README. |
| 2 | `composer.png` | 1440×900 | `/` | Same homepage, but with the composer card focused — type *"Should we enter Germany or France?"* into the input. |
| 3 | `intake.png` | 1440×900 | `/sessions/{new-id}/intake` | After creating a new session, the intake Q&A flow with 2-3 questions visible. |
| 4 | `processing-sse.png` | 1440×900 | `/sessions/{processing-id}` | A session mid-processing. Several agents have completed (planner, researcher), one is in progress (analyst). Token counter visible. |
| 5 | `workspace-finished.png` | 1440×900 | `/sessions/11111111-1111-4111-8111-111111111111` (Germany vs France) | Three-column workspace, **Answer** tab active. Recommendation card visible. |
| 6 | `evidence-graph.png` | 1440×900 | Same session, **Graph** tab | Swim-lane graph with claim/evidence/source nodes. Click claim `c1` to highlight its supporting evidence — captures the "money shot" for the README. |
| 7 | `trust-rail.png` | 720×900 (right column only) | Same session, Answer tab | Crop to the right rail showing confidence label, verification summary, caveats preview, unsupported-claims badge. |
| 8 | `audit-panel.png` | 1440×900 | Same session, **Audit** tab | Audit panel showing claim-by-claim verdicts, including the weak-flagged `c4`. |
| 9 | `exported-pdf.png` | (PDF page) | Click **Export → PDF** in trust rail | First page of the rendered consulting memo. Use a screenshot tool on the opened PDF, or use `pdftoppm` to convert the first page. |

For the case study folder also capture (or copy) `evidence-graph.png` and the audit / sources screenshots into [`docs/case-studies/germany-vs-france/screenshots/`](../case-studies/germany-vs-france/screenshots/).

---

## Automatic capture (recommended)

```bash
# One-time install (Playwright is dev-only — kept out of the main image)
cd tools
npm init -y
npm install playwright
npx playwright install chromium

# Capture all 9 screenshots
node capture_screenshots.js
```

Outputs land in [`docs/screenshots/`](.). The script reuses the seeded session id so it works headless against `make demo`.

---

## Manual capture tips

- Use **Chrome DevTools** for consistent viewport sizing — set a 1440×900 device profile.
- **Disable autofill**: it can render greyed text on inputs that looks broken.
- **Clear the "no API key" warning** if it shows up: in demo mode the seeded engagement is `complete`, so this should never trigger on the workspace pages.
- For trust-rail close-ups, screenshot the full page first then crop to ~720×900 around the right column. This keeps fonts crisp.
- For PDF screenshots, **render at 144 DPI** (`pdftoppm -r 144 final-report.pdf out`) — 72 DPI looks blurry.

---

## Updating the README

The README references each file by its filename in [`docs/screenshots/`](.). Once the real PNGs land, the placeholder SVGs are silently overridden — no README edits needed.

To keep filenames stable, **don't rename**. If you want to add a new screenshot, add a new filename and reference it explicitly.

---

## When to recapture

Re-capture all screenshots when any of these change:
- Color tokens in `frontend/app/globals.css` or `frontend/tailwind.config.ts`
- Workspace layout in `frontend/app/sessions/[id]/page.tsx`
- The Germany-vs-France fixture in `backend/tests/fixtures/germany_vs_france/`
- Trust-rail or evidence-graph component logic

Otherwise, screenshots can stay as-is across small edits.
