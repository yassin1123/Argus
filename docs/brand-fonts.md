# Argus — Brand Fonts (Palette A)

The "Bloomberg / consulting deliverable" palette. This is what ships in the live UI.

---

## Type stack

| Role | Family | Source | Weight(s) |
|------|--------|--------|-----------|
| **Display / serif** | **DM Serif Display** | Google Fonts | 400 |
| **UI / sans** | **DM Sans** | Google Fonts | 400 · 500 · 600 · 700 |
| **Mono** | **JetBrains Mono** | Google Fonts | 400 · 500 |

All three are free and OFL-licensed.

---

## Where each font is used

| Surface | Family | Why |
|---------|--------|-----|
| Argus wordmark | DM Serif Display | Editorial weight; signals "deliverable" not "chatbot" |
| Recommendation headline | DM Serif Display | The single most important sentence — gets visual primacy |
| Section labels (uppercase) | DM Sans 600 | Small caps, tracked-out — reads as table of contents |
| Body / UI / forms | DM Sans 400/500 | Geometric humanist; works down to 11px |
| Token counters, durations, entailment scores | JetBrains Mono | Tabular nums; aligns columns visually |
| Pipeline timeline labels | DM Sans 500 | Compact medium weight |

---

## Sizing scale (consistent with the live app)

| Use | Size | Weight | Family |
|-----|------|--------|--------|
| Hero recommendation | 32–40px | 600 | DM Serif Display |
| Section headline | 18–20px | 500 | DM Serif Display |
| Subtle section label | 11px | 600 uppercase, 0.1em letter-spacing | DM Sans |
| Body text | 13–15px | 400 | DM Sans |
| Compact UI text | 11–12px | 400 | DM Sans |
| Numerics (durations, costs, scores) | inherit | 400 tabular-nums | JetBrains Mono |

---

## Color tokens that pair with these fonts

Defined in `frontend/app/globals.css`:

| Token | Use |
|-------|-----|
| `--text-primary` | Main body and headlines |
| `--text-secondary` | Subtitles, secondary labels |
| `--text-tertiary` | Captions, hint text, metadata |
| `--text-accent` | Brand accent (chips, highlights) |
| `--semantic-success` / `-warning` / `-danger` | Verdict colors on chips and dots |

---

## Loading the fonts (Next.js — already wired)

```tsx
// frontend/app/layout.tsx
import { DM_Sans, DM_Serif_Display } from "next/font/google";

const dmSans = DM_Sans({
  subsets: ["latin"],
  variable: "--font-dm-sans",
  weight: ["400", "500", "600", "700"],
});

const dmSerif = DM_Serif_Display({
  subsets: ["latin"],
  variable: "--font-dm-serif",
  weight: "400",
});

// Apply to <html>:
<html lang="en" className={`${dmSans.variable} ${dmSerif.variable}`}>
  <body className={`font-sans ${dmSans.className}`}>{children}</body>
</html>
```

JetBrains Mono is referenced by class name in `frontend/tailwind.config.ts`:

```ts
fontFamily: {
  sans: ["var(--font-dm-sans)", "system-ui", "sans-serif"],
  serif: ["var(--font-dm-serif)", "Georgia", "serif"],
  mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
}
```

---

## Loading the fonts (plain HTML — for static pages or marketing site)

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link
  href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=DM+Serif+Display&family=JetBrains+Mono:wght@400;500&display=swap"
  rel="stylesheet">

<style>
  :root {
    --font-sans: "DM Sans", system-ui, -apple-system, sans-serif;
    --font-serif: "DM Serif Display", Georgia, serif;
    --font-mono: "JetBrains Mono", ui-monospace, monospace;
  }

  body { font-family: var(--font-sans); }
  h1, h2, .display { font-family: var(--font-serif); }
  code, pre, .num { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
</style>
```

---

## Loading the fonts (Tailwind v4 / CSS-first config)

```css
@theme {
  --font-sans: "DM Sans", system-ui, sans-serif;
  --font-serif: "DM Serif Display", Georgia, serif;
  --font-mono: "JetBrains Mono", ui-monospace, monospace;
}
```

---

## Loading the fonts (Figma / design tools)

Free download links:
- **DM Sans** — https://fonts.google.com/specimen/DM+Sans
- **DM Serif Display** — https://fonts.google.com/specimen/DM+Serif+Display
- **JetBrains Mono** — https://fonts.google.com/specimen/JetBrains+Mono

In Figma: install via the Figma desktop app (auto-detects local fonts) or via the Google Fonts plugin.

---

## Brand tone the fonts encode

- **Confident, not promotional.** DM Serif Display has weight without ornament; says "this output deserves to be read carefully."
- **Calm density.** DM Sans is geometric enough to look modern but humanist enough to read at 11px without fatigue.
- **Auditable.** Tabular monospace numerals make every duration, score, and cost visually verifiable at a glance.

If a future surface needs a different feel (a marketing landing page, a slide deck), this stack still works — but DM Serif at hero size (60–80px) is the move that always pays off.
