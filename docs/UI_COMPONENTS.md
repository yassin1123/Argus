# UI Components — Argus v1

Component inventory. Each entry: purpose, props, states, when to use, when not to use. Resolves against `DESIGN_SYSTEM.md` for tokens.

---

## Primitives

### Button

The only action element in the product.

**Variants:**
| Variant | Surface | Border | Text | Use for |
|---|---|---|---|---|
| `primary` | `--accent` filled | none | `--paper` | The one main action per surface |
| `secondary` | `--paper-card` | 1px `--ink-20` | `--ink-100` | Lower-priority actions next to primary |
| `ghost` | transparent | none | `--ink-80` | Tertiary actions, row-level actions on hover |
| `danger` | transparent | 1px `--unverified` | `--unverified` | Inside confirm modals only |

**Sizes:**
- `sm` — 32px tall, 12px horizontal padding (table-row actions)
- `md` — 40px tall, 16px horizontal padding (default)
- `lg` — 48px tall, 20px horizontal padding (auth screen, refusal screen — gravity moments)

**States:**
- Default
- Hover (10% darker on filled, `--paper-2` on ghost)
- Active (12% darker)
- Focus (2px focus ring, `--accent` at 30% opacity, 2px offset)
- Disabled (40% opacity, no pointer)
- Loading (replaces label with inline 14px spinner; width preserved to prevent layout jump)

**Don't:**
- Stack 3 button variants in one row
- Use icon-only buttons except for `✕` close
- Use uppercase labels
- Use sentence-case labels with emoji ("✨ Get started")

---

### TextField

Single-line input.

**Anatomy:** 1px `--ink-20` border, 6px radius, 12px horizontal padding, 40px tall. Plex Sans 14/20.

**States:**
- Default
- Focus (`--accent` border, no glow)
- Error (`--unverified` border + caption below)
- Disabled (40% opacity)

**Anatomy with label:**
```
Email                       (Plex Sans 12 ink-60 weight 500)
┌────────────────────────┐
│ you@firm.com           │
└────────────────────────┘
We'll send a one-time link  (Plex Sans 12 ink-60, optional helper)
```

**Don't:**
- Use placeholder as the only label (label must remain visible when field has content)
- Stack 5 of them in one form (v1 has very few forms — Login, Project rename. That's it.)

---

### Textarea

Multi-line input. Auto-grows.

**Default usage:** Question Composer.

**Anatomy:** 1px `--ink-20` border, 8px radius, 16px padding, 4 rows minimum, 12 rows maximum (then scrolls). **Plex Serif 17/28** — the question deserves the gravity of a serif.

**States:** same as TextField.

**Don't:**
- Use Plex Sans here. Always Serif. The user is composing a sentence to be answered carefully.
- Add character counters. The user knows how much they typed.

---

### DropZone

File drop region.

**Anatomy:** 1px dashed `--ink-20` border, 8px radius, `--paper-2` background. Center: copy + small Phosphor icon (`UploadSimple`, 24px, `--ink-60`).

**States:**
- Idle: dashed border, paper-2 background
- Drag-over: solid `--accent` border, `--paper-card` background, copy changes to "Drop to upload."
- Uploading: idle styling continues (rows below show progress)

**Sizes:**
- Compact: 96px tall (when sources already exist)
- Full: 240px tall (when project has zero sources)

**Don't:**
- Bounce or pulse. It's a calm receptacle.
- Use for any content type other than PDFs in v1.

---

### Toast

Bottom-right corner, 320px wide.

**Anatomy:** `--paper-card` background, 1px `--ink-10` border, 8px radius, `--shadow-2`. Optional 3px left rule for variant accent.

**Variants:**
- `info` — no left rule, `--ink-80` text
- `success` — `--verified` 3px left rule
- `error` — `--unverified` 3px left rule

**Behavior:**
- Auto-dismiss after 4s (info/success), 8s (with action button)
- Stack vertically if multiple, max 3 visible, oldest pushed up
- Action button is a ghost button to the right of the message

**Don't:**
- Use as primary feedback (errors that need user attention go inline, not in a toast)
- Use red. Errors use `--unverified` amber.

---

### Modal

Centered overlay.

**Anatomy:** 480px wide, `--paper-card` background, 10px radius, `--shadow-2`. Backdrop: `--ink-100` at 24% opacity. Header (Plex Sans 17/28 weight 500), body (Plex Sans 14/20), footer with `[Cancel]` `[Confirm]` right-aligned.

**Use only for:** destructive confirmations.

Examples:
- "Remove `msa.pdf`? Past reports that cite it stay intact."
- "Delete this project? All sources and reports will be permanently removed."

**Don't:**
- Use for forms (all v1 forms are inline or full-screen surfaces)
- Use as a navigation pattern (no "Settings" modal — there's no settings)
- Stack modals (one at a time, never nested)

---

### Popover

Anchored, contextual, smaller than a modal.

**Anatomy:** 240-320px wide, `--paper-card` background, 8px radius, `--shadow-2`. Anchored to the trigger element with a 4px offset.

**Use for:** Export format picker (the only popover in v1).

**Don't:**
- Use for menus longer than 4 items (use a side surface instead)
- Use for input forms

---

## Status indicators

### StatusPip

A 6px filled circle. Lives next to status text.

| Color | Meaning |
|---|---|
| `--verified` (forest) | Ready, healthy, complete |
| `--refuse` (gray) | In progress, neutral state |
| `--unverified` (amber) | Error, skipped, needs attention |

**Don't:**
- Use red. Even for hard errors.
- Use color alone. Always pair with text.

---

### LoadingSkeleton

Animated `--ink-10` placeholder bars.

**Behavior:** Mimics the shape of what's loading. Subtle pulse animation (opacity 0.6 → 1.0 → 0.6, 1.5s loop).

**Use for:** page-level loading (Project list rows, Project workspace sections, Report body).

**Don't:**
- Use spinners on page-level loads. Spinners only inside buttons.

---

## Composed components

### TopBar

Fixed top, 56px tall.

**Anatomy:** `--paper` background, 1px `--ink-10` bottom border. Wordmark left (Plex Serif 17 weight 600). User menu right.

**Variants:**
- Default (Project list, Project workspace, Report viewer)
- Back-only (Question composer): replaces wordmark with `[← Back to project]` link, no user menu
- Hidden (Login screen — wordmark renders centered above the auth card instead)

**Don't:**
- Add notification bells, search bars, or quick-action buttons. v1 has none.

---

### Sidebar

Left rail in Project Workspace.

**Anatomy:** 240px wide, `--paper-2` background, 1px `--ink-10` right border. Sections:
- Wordmark (top)
- "← All projects" link
- Project name (current)
- Anchor links: "Sources", "Reports" (scroll-spy active state highlights current section)

**Collapsible:** at <1024px viewport OR via toggle. Collapsed: 56px wide, icon-only.

**Don't:**
- Add a "+ New project" button here (it lives on the Project list page)
- Add nav for screens that don't exist (Settings, Team, Billing — none of these exist in v1)

---

### ProjectRow

List item on Project list page.

**Anatomy:**
```
Acme Corp — Q3 contract review                    (Plex Serif 17/28 ink-100)
Risk analysis for renegotiation                   (Plex Sans 14/20 ink-60)
12 sources · 4 reports · last asked 2 days ago    (Plex Mono 12 ink-60)
```

Rows separated by 1px `--ink-10` divider. Hover: `--paper-card` background, full row clickable.

**Don't:**
- Add avatars (no team in v1)
- Add status badges
- Add action buttons (delete is inside the project, with confirm)

---

### SourceListRow

List item in Project workspace Sources section.

**Anatomy:**
```
msa.pdf                          24 pages   ●  ✓ Ready
[filename Plex Serif 17]    [Plex Mono 12]  [pip + Plex Sans 14]
```

Hover: `--paper-card` background, hairline `--ink-10` rule above and below row, per-row actions appear right-aligned (`[Remove]`, `[Retry]` as ghost buttons).

**Status text:**
- `Uploading 38%` (with thin progress bar under row)
- `Parsing`
- `Indexing 64%`
- `✓ Ready` (with `--verified` pip)
- `Skipped — scanned PDF` (with `--unverified` pip + `[Remove]`)
- `Failed — try again` (with `--unverified` pip + `[Retry]` `[Remove]`)

**Don't:**
- Add file-type icons (everything is a PDF)
- Add thumbnail tiles (invites the 3-column grid AI-slop pattern)

---

### ReportRow

List item in Project workspace Reports section.

**Anatomy:**
```
What are the financial risks across these contracts?    (Plex Serif 17/28 ink-100, truncate)
2 days ago · 12 citations                                (Plex Mono 12 ink-60)
```

Or for refused reports:
```
What termination clauses apply to early exit?
6 hours ago · refused (insufficient evidence)            (Plex Mono 12 ink-60)
```

Hover: `--paper-card` background.

**Don't:**
- Show a snippet of the report body (the question is the title; click to read)
- Add a "share" or "copy" button

---

### CitationChip

Inline element in report body. The most important component in the product.

**Anatomy:**
- Text: `[N]` in Plex Mono 13
- Color: `--accent`
- No underline by default (the report text is the focus, citations are quiet markers)

**States:**
- Default: `[1]` in `--accent`, no background
- Hover: 4px radius `--accent-tint` background pill, underline appears, after 400ms a tooltip shows "msa.pdf — page 7"
- Active (this citation is currently open in the source panel): 16% accent background pill, persistent underline

**Behavior:**
- Click: opens or focuses Source Panel on this citation
- Cursor: `pointer`

**Don't:**
- Render as `(1)` or `^1` — `[N]` is consistent and machine-feel without being hostile
- Color them differently per source — every citation is the same accent
- Add icons inside the chip

---

### SourcePanel

Right pane of the Report Viewer. The "magic moment" surface.

**Anatomy:**
- 40% width default (resizable to 50% / 30%)
- 1px `--ink-10` left border (the resizer)
- `--paper-card` background

**Sub-components:**
- `SourcePanelHeader` (56px tall, `--paper-2` background): `[N]  filename — page X` in Plex Mono 12, with `↗ Open PDF` link and `✕` close button right-aligned
- `PdfPageRenderer` (fills the body): renders one page from `pdfjs-dist`
- `HighlightOverlay`: the cited passage gets `--verified` at 12% background fill + 3px solid `--verified` left rule
- `CitationNavigator` (48px tall, `--paper-2` background, 1px `--ink-10` top border): `‹ Prev citation     [N of M]     Next citation ›`

**Behavior:**
- Slides in 200ms ease-out on first citation click
- Subsequent citation clicks: content updates, no animation
- Highlight pulses 1s on first land, then settles
- Esc closes the panel

**Don't:**
- Add annotation tools
- Add a search input within the PDF (v2)
- Use yellow for the highlight (yellow = student notebook; we use `--verified` forest = mark of evidence)

---

### EmptyState

Centered block used when a list/section has no items.

**Anatomy:**
- 64px line drawing icon (Phosphor Regular weight, `--ink-60`) — match icon to context (`BookOpen` for projects, `FileArrowUp` for sources, etc.)
- Plex Serif 24/32 headline ("Start your first project.")
- Plex Sans 14/20 body ("A project is a set of source documents and the questions you ask of them.")
- Primary button below ("+ New project")
- 64-96px vertical padding above and below

**Don't:**
- Use stock illustrations
- Use emojis
- Skip the primary action — every empty state has a way forward

---

## Form patterns

### Single-field form (Login)
- Label above field (Plex Sans 12 ink-60 weight 500, optional)
- Field
- Helper text below (Plex Sans 12 ink-60, optional)
- Full-width primary button below the helper

### Inline edit (project name)
- Click name → becomes a TextField in place
- Esc cancels, Enter or blur saves
- No "Edit" pencil icon — the name itself is the affordance (cursor changes on hover)

### Confirm modal pattern
```
   Title (Plex Sans 17 weight 500)
   Body explaining consequence (Plex Sans 14/20 ink-80)

                    [ Cancel ]   [ Remove ]
                                  ↑ danger variant
```
- Body always names the specific item being removed
- Body explains the cascading effect ("Past reports that cite it stay intact")
- Primary action is on the right, danger variant
- Esc cancels

---

## What is NOT a component (intentionally absent in v1)

These are explicitly not in the kit. If you want to build one, push back to v2.

- `StatCard` / `KpiTile` — no dashboards in v1
- `Chart` (any kind) — no charts in v1
- `Avatar` — no team / sharing in v1
- `Tabs` — anywhere; tabs hide content
- `Carousel` — always slop
- `IconWithTooltipExplaining_Term` — the writing should be clear enough
- `Banner` / `AnnouncementBar` — nothing to announce
- `SearchBar` — 5 users, ≤50 projects, not needed
- `FilterChips` — no filters in v1
- `SortMenu` — newest-first by default everywhere, no sort selector
- `Pagination` — lists are short, no pagination
- `Breadcrumbs` — sidebar tells you where you are; no need
- `OnboardingStep` / `Coachmark` — the app is 5 screens
- `Confetti` / success animation — never
- `Notification` (push or in-app) — no async events to notify about
- `ShareModal` — no sharing in v1
- `ColorPicker` / theme switcher — one theme, light, that's it

If you find yourself reaching for any of the above, the spec is being violated.

---

## Voice and copy

### Buttons (verbs only)
✅ "Ask," "Export," "Upload PDFs," "Remove," "Sign out," "Try again"
❌ "Click here," "Submit," "Continue," "Got it!"

### Headlines (Plex Serif, confident, short)
✅ "Insufficient evidence in your sources."
✅ "Start your first project."
✅ "Check your email."
❌ "Welcome to Argus!"
❌ "Ready to get started?"
❌ "Oops!"

### Status text
✅ "✓ Ready" / "Indexing 64%" / "Failed — try again"
❌ "DONE" / "ERROR" / "PROCESSING..."

### Loading copy
✅ "Reading 3 sources..." / "Verifying citations..." / "Generating answer..."
❌ "Loading..." / "Please wait..." / "Working on it..."

### Error copy
✅ "We couldn't load your projects. Refresh, or try again in a minute."
❌ "Error 500: Internal Server Error"
❌ "Oops! Something went wrong."

### Forbidden words anywhere in product UI
- "Just" — apologetic ("just click here")
- "Simply" — condescending ("simply upload your files")
- "Awesome" / "Amazing" / "Powerful" — marketing
- "Powered by AI" / "AI-powered" — everything is, say nothing
- "Effortless" / "Seamless" — lies until proven
- "Insights" — we deliver claims with citations, not "insights"
- "Magic" — it's not magic, it's retrieval and verification
- Emojis — none in product UI

---

## Accessibility floor

Every component must satisfy:

- ✅ Body text contrast ≥ 4.5:1
- ✅ Focus ring on every interactive element (2px `--accent` 30% opacity, 2px offset)
- ✅ Keyboard nav: Tab order matches reading order, Esc closes panels/modals, Enter submits
- ✅ Touch targets ≥ 44px in any responsive view
- ✅ Real `<label>` elements (never placeholder-as-label)
- ✅ ARIA landmarks: `<nav>`, `<main>`, `<aside>` (source panel)
- ✅ Screen-reader text on icon-only buttons (`aria-label="Close source panel"` on ✕)
- ✅ Status communicated via text + color + pip — never color alone

If any component violates the floor, it does not ship.

---

## Component → screen map (where each is used)

| Component | Login | Projects | Workspace | Composer | Report | SourcePanel | Export | Errors |
|---|---|---|---|---|---|---|---|---|
| Button | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| TextField | ✓ | ✓ (rename) | ✓ (rename) | | | | | |
| Textarea | | | | ✓ | | | | |
| DropZone | | | ✓ | | | | | |
| Toast | | | ✓ | | ✓ | | ✓ | ✓ |
| Modal | | | ✓ (delete) | | ✓ (delete) | | | |
| Popover | | | | | ✓ (export) | | ✓ | |
| StatusPip | | | ✓ | | | | | |
| LoadingSkeleton | | ✓ | ✓ | | ✓ | ✓ | | |
| TopBar | | ✓ | ✓ | ✓ (back) | ✓ | | | |
| Sidebar | | | ✓ | | | | | |
| ProjectRow | | ✓ | | | | | | |
| SourceListRow | | | ✓ | | | | | |
| ReportRow | | | ✓ | | | | | |
| CitationChip | | | | | ✓ | | | |
| SourcePanel | | | ✓ (preview) | | ✓ (citation) | ✓ | | |
| EmptyState | | ✓ | ✓ | | | | | |

If a component doesn't appear in this map, it doesn't exist in v1.
