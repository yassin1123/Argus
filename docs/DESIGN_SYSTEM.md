# Design System — Argus v1

The visual and tonal foundation. Print-quality, consultant-grade, calm. Every token here is a constraint that prevents AI-slop drift.

---

## Voice

- Print-quality. Editorial.
- Consultant-grade: calm, certain, evidence-first.
- No marketing language. No AI hype. No emojis. No gradients. No "AI" mentions in UI text.
- Refusals sound like a senior partner declining to bullshit, not an error.
- The product never apologizes for being slow. It is slow because it is careful. That's the brand.

If a UI string sounds like a SaaS landing page, rewrite it. If it sounds like the *Wall Street Journal* or a *Stripe* dashboard, you're close.

---

## Color

The palette is deliberately small. Off-white paper, near-black ink, one accent, two semantic states. That's it.

```
--paper        #FBFAF7   App background. Off-white, never pure #FFF.
--paper-2      #F4F2EC   Sidebar, secondary surfaces, raised toolbars.
--paper-card   #FFFFFF   Reading surface (the report itself, modals).
--ink-100      #0F0F0F   Primary text. Never pure #000.
--ink-80       #2B2B2B   Secondary text, body in chrome.
--ink-60       #5A5A5A   Tertiary text, captions, metadata.
--ink-40       #8A8A8A   Placeholder text.
--ink-20       #C8C8C5   Field borders, rules.
--ink-10       #E8E6E0   Subtle dividers, hover backgrounds.

--accent       #0F4C4A   Deep teal. Primary actions, citation links. Used SPARINGLY.
--accent-tint  rgba(15,76,74,0.08)   Citation hover, button hover.

--verified     #1F5C3D   Forest green. Citation verified, ready states.
--unverified   #8B6914   Muted amber. Caution, dropped claims, file errors.
--refuse       #5A5A5A   Neutral gray. Refusals are NOT red. Refusal is a feature.
```

**Forbidden colors:**
- Purple, violet, indigo of any kind
- Blue → purple gradients
- Pure white `#FFFFFF` as the app body background
- Pure black `#000000` for text
- Bright red for errors. We use `--unverified` amber instead.
- Lime / neon green. `--verified` is forest, not slack-online.

**Rule:** If you need a new color for a new state, you're probably wrong. The state should fit one of the existing five (ink, accent, verified, unverified, refuse).

---

## Typography

Family pair: **IBM Plex** (Serif + Sans + Mono). Free, professional, cohesive across three faces, recognizably "serious" without being academic. Used by IBM consulting — exactly the right vibe.

```
@import IBM Plex Serif (400, 500, 600)
@import IBM Plex Sans  (400, 500, 600)
@import IBM Plex Mono  (400, 500)
```

**Where each face is used:**

- **Plex Serif** — Report body, page headings, refusal headlines. Everywhere prose-with-gravity belongs.
- **Plex Sans** — UI chrome (buttons, labels, captions, nav). Anywhere you need neutral signage.
- **Plex Mono** — Citation tags `[1]`, page numbers, filenames in metadata, error codes. Anywhere a value is "machine-verifiable."

**Scale (16px base):**

```
--text-xs     12px / 16px    Captions, metadata
--text-sm     14px / 20px    UI labels, secondary body
--text-base   16px / 24px    UI default
--text-md     17px / 28px    Report body, list-item titles
--text-lg     20px / 28px    Subheadings
--text-xl     24px / 32px    Heading
--text-2xl    32px / 40px    Page heading
--text-3xl    44px / 52px    Refusal moment (the only place this size lives)
```

**Weights:** 400, 500, 600. That's it. No 700, no 800. Heaviness comes from size and color, not weight.

**Reading body geometry:** Plex Serif at `--text-md` (17px / 28px) on a max measure of 680px. This is the *Substack* / *WSJ* reading geometry, deliberately. Not a chat transcript.

**Heading rhythm:**
- Page heading uses Plex Serif `--text-2xl`, weight 500
- Section heading uses Plex Sans `--text-md`, weight 500, tracking +0.5
- The serif/sans rhythm tells the user "this is a document, not a screen"

**Forbidden type choices:**
- `system-ui`, `-apple-system`, `Inter`, `Roboto`, `Arial` as primary display/body. Pick a real typeface. Plex is the answer.
- More than two type families on screen at once (serif + sans + mono are one family system, not three families)

---

## Spacing

Base 4. Scale: `4, 8, 12, 16, 24, 32, 48, 64, 96`.

```
--space-1     4px
--space-2     8px
--space-3     12px
--space-4     16px
--space-6     24px    (default card padding)
--space-8     32px
--space-12    48px    (default page gutter, desktop)
--space-16    64px    (section gap)
--space-24    96px    (large empty-state vertical padding)
```

**Common rhythms:**
- Card padding: `--space-6` all around
- Page gutter (desktop): `--space-12`
- Vertical gap between major sections: `--space-16`
- Form-field gap: `--space-4`
- Inline gap (icon + label): `--space-3`

If you find yourself using a value that's not on this scale, you're winging it. Use the next value up or down.

---

## Radius

```
--radius-sm    4px     Citation chips (squared-ish, code-feel)
--radius-md    6px     Buttons, inputs (firm, not bubbly)
--radius-lg    8px     Cards
--radius-xl    10px    Modals
```

Nothing goes above 12px. No pill-shaped buttons. No rounded-full anything. Bubbly = AI slop.

---

## Borders & Elevation

```
--border-1     1px solid var(--ink-10)    Subtle dividers, default surfaces
--border-2     1px solid var(--ink-20)    Field borders, defined edges
```

One single elevation tier. We don't stack drop-shadows.

```
--shadow-1     0 1px 0 var(--ink-10)
                 (a hairline base — used on TopBar, button base)

--shadow-2     0 1px 2px rgba(15,15,15,0.04),
               0 8px 24px rgba(15,15,15,0.04)
                 (the only "raised" shadow — used on modal, toast, popover)
```

Anything more than this is too much. We get hierarchy from typography and color, not from shadow stacks.

---

## Motion

```
--ease         cubic-bezier(0.2, 0, 0, 1)    standard ease-out
--duration-1   150ms                          default
--duration-2   200ms                          panel transitions
--duration-3   1000ms                         the citation-highlight pulse (once)
```

**Rules:**
- 150ms default ease-out for hover, focus, button press
- Page transitions: opacity only, no slide
- Citation click → source panel opens: 200ms ease-out, content fades in + 8px upward translate
- PDF passage highlight: 1s pulse on first land, then settles
- **NEVER:** bounce, spring, emphasized motion, parallax, scroll-jacking
- This is consultant-grade. Things move because they have to, not because they can.

---

## Iconography

**Phosphor Icons**, Regular weight (1.5px stroke). Free, neutral, calm, comprehensive.

Sizes: 16px, 20px, 24px. Pick one per context — never mix sizes within the same row.

**Rules:**
- Icons are functional, never decorative
- No icons in colored circles (AI slop pattern #3 from the blacklist)
- No icons in section headers (the heading text says what the section is)
- Citation status uses a 6px filled circle (not a Phosphor icon — it's a status dot, not an icon)

---

## Layout primitives

**Two-pane split** (Report viewer):
- Default 60/40 (report / source panel)
- User-draggable resizer, snaps between 50/50 and 70/30
- Source panel hidden until first citation click

**Three-pane** (Project workspace, when source panel is open):
- Sidebar 240px (left, fixed)
- Main content (flex)
- Source panel 40% of remaining width (right, slide-in)
- At <1280px: sidebar collapses to 56px icon-only when source panel is open

**Single-column** (Login, Project list):
- Centered, 720px max
- 48px gutter on each side at desktop, 24px at <768px

**Reading measure:** 680px max for any prose. Cap it. Eyes hurt past that.

---

## Component density principles

- **Rows over cards** for any list. Cards are pre-2020 "let's add visual interest" thinking.
- **One job per region.** A region is sources, OR reports, OR settings — never two.
- **No redundant chrome.** If a button labels itself, no icon. If a section is obvious, no heading.
- **Captions earn their place.** A timestamp is useful; "Created by you" on your own thing is not.

---

## Voice & copy

### Buttons (verbs only)
✅ "Ask," "Export," "Upload PDFs," "Remove," "Sign out"
❌ "Click here," "Submit," "Continue"

### Headlines (Plex Serif, confident, short, no questions, no exclamations)
✅ "Insufficient evidence in your sources."
✅ "Start your first project."
❌ "Welcome to Argus!"
❌ "Ready to get started?"

### Loading copy (tell the user what's happening)
✅ "Reading 3 sources..." / "Verifying citations..."
❌ "Loading..." / "Please wait..."

### Error copy (apologize, never blame the user, always offer a next action)
✅ "We couldn't load your projects. Refresh, or try again in a minute."
❌ "Error 500: Internal Server Error"
❌ "Oops! Something went wrong."

### Forbidden words anywhere in the product
- "Just" (apologetic — "just click here")
- "Simply" (condescending — "simply upload your files")
- "Awesome" / "Amazing" / "Powerful" (marketing)
- "Powered by AI" / "AI-powered" (everything is — say nothing)
- "Effortless" / "Seamless" (lies until proven)
- "Insights" (we deliver claims with citations, not "insights")
- "Magic" (it's not magic, it's retrieval and verification)
- Emojis in product UI

### The refusal voice (the most important copy in the product)

Refusals are written like a senior partner declining to bullshit a junior. Calm, certain, helpful, never apologetic.

> "Insufficient evidence in your sources.
>
> You asked: 'What are the indemnification limits in the SOW?'
>
> Argus searched 3 sources but didn't find passages that support an answer to this question. Specifically: none of msa.pdf, nda.pdf, or employment-agreement.pdf contain SOW content.
>
> What to try:
> • Upload the SOW or the document containing those clauses
> • Rephrase to focus on indemnification in the contracts you have"

That tone, every time. The refusal is the brand.

---

## Accessibility floor (non-negotiable)

- All body text contrast ≥ 4.5:1 against its background
- Focus rings on every interactive element: 2px `--accent` at 30% opacity, 2px offset
- Keyboard nav: Tab order matches reading order; Esc closes panels/modals; Enter submits forms
- Touch targets ≥ 44px in any responsive view
- Form labels are real `<label>` elements, never placeholder-as-label
- Visited vs unvisited link distinction preserved (we don't have many links, but the rule stands)
- ARIA landmarks: `<nav>`, `<main>`, `<aside>` for the source panel
- Screen-reader text on icon-only buttons (the ✕ close button has `aria-label="Close source panel"`)

---

## What is forbidden by this design system

A short, blunt list to grep against during reviews:

- ❌ Purple/violet/indigo of any kind
- ❌ Gradients (especially blue→purple)
- ❌ Pure `#FFF` body or `#000` text
- ❌ More than 2 type families
- ❌ `Inter`, `Roboto`, `Arial`, `system-ui` as the primary face
- ❌ Decorative icons in colored circles
- ❌ 3-column feature grids (`icon → bold title → 2-line description × 3`)
- ❌ Centered everything
- ❌ Pill-rounded everything
- ❌ Drop-shadow stacks
- ❌ Bouncy/spring motion
- ❌ Emojis in UI
- ❌ "Powered by AI" copy
- ❌ Carousels
- ❌ Splash screens, intro animations, marketing interstitials in the app

If a screen contains any of these, it has drifted. Fix it before merging.
