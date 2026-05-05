# Screen Specs — Argus v1

Nine screens, specified to the level an engineer can build them without asking. Format per screen: Purpose, Layout, Components, Empty/Loading/Error states, Can/Cannot, UX rules.

All visual references resolve against `DESIGN_SYSTEM.md`.

---

## 1. Login

### Purpose
Get a recognized user into the app. Nothing more.

### Layout
Centered card on `--paper` background. 420px wide. Vertically centered in the viewport. Wordmark above the card.

```
                  ┌─────────────────────┐
                  │       ARGUS         │   (wordmark, Plex Serif 17, weight 600)
                  └─────────────────────┘

           ┌─────────────────────────────────────────┐
           │                                         │
           │   Sign in                               │   (Plex Serif 24, weight 500)
           │   We'll send a one-time link to your    │   (Plex Sans 14, ink-60)
           │   email. No passwords.                  │
           │                                         │
           │   ┌────────────────────────────────┐   │
           │   │ you@firm.com                   │   │   (TextField, 40px tall)
           │   └────────────────────────────────┘   │
           │                                         │
           │   [   Send magic link   ]              │   (Button primary, full-width)
           │                                         │
           │   By continuing you agree to our        │   (Plex Sans 12, ink-60)
           │   Terms and Privacy Policy.             │
           │                                         │
           └─────────────────────────────────────────┘
```

### Main components
`WordmarkLogo`, `Card`, `TextField` (email), `Button` (primary), `HelperText` (footer line).

### Empty state
This screen IS the empty state. No content beyond the form.

### Loading state
After submit, the button shows an inline 14px spinner and label changes to "Sending link...". The TextField is disabled.

### Error state
Inline error caption appears below the field in `--unverified` amber, Plex Sans 14:
> "We couldn't reach your inbox. Try again, or check the email address."

No red box. No alert icon. Just the caption.

### Confirmation state (post-submit)
Replace the entire card content with:

```
   ┌─────────────────────────────────────────┐
   │                                         │
   │   Check your email.                     │   (Plex Serif 24, weight 500)
   │                                         │
   │   Magic link sent to you@firm.com.      │   (Plex Sans 14, ink-80)
   │   Open it on this device to continue.   │
   │                                         │
   │   Didn't get it? [Try a different       │   (link, Plex Sans 14, accent)
   │   email]                                │
   │                                         │
   └─────────────────────────────────────────┘
```

### What the user CAN do
- Submit an email
- Open the magic link from their inbox

### What the user CANNOT do
- Sign in with Google / OAuth (not in v1)
- Reset a password (no passwords exist)
- Skip and view the app (no anonymous mode)
- See marketing content (no v1 marketing site exists yet)

### UX rules to prevent clutter
- Single column. One field. One button.
- No "Forgot password?" link (no passwords).
- No social login icons.
- No tagline or marketing copy. Just the function.
- No "Welcome back!" — assume nothing about who's arriving.

---

## 2. Project list

### Purpose
Resume an existing project, or start a new one.

### Layout
TopBar fixed (56px). Centered single column, max 720px wide, 48px gutters. Page content below the bar.

```
┌──────────────────────────────────────────────────────────────────┐
│ ARGUS                                              you@firm.com▾ │   (TopBar, 56px)
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│                                                                   │
│   Projects                                  [ + New project ]   │   (h1, Plex Serif 32 / button)
│                                                                   │
│   ───────────────────────────────────────────────────────────    │   (1px ink-10)
│                                                                   │
│   Acme Corp — Q3 contract review                                 │
│   Risk analysis for renegotiation                                │
│   12 sources · 4 reports · last asked 2 days ago                 │
│                                                                   │
│   ───────────────────────────────────────────────────────────    │
│                                                                   │
│   Stripe due diligence                                           │
│   Term sheet and SAFE comparison                                 │
│   8 sources · 1 report · last asked 6 hours ago                  │
│                                                                   │
│   ───────────────────────────────────────────────────────────    │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

Each row:
- Title: Plex Serif 17/28
- Description: Plex Sans 14/20, `--ink-60`
- Metadata caption: Plex Mono 12, `--ink-60`
- Hover: row gets `--paper-card` background, no border change
- Click: navigates to Project Workspace

### Main components
`TopBar`, `PageHeader`, `Button` (primary, secondary), `ProjectRow`, `EmptyState`, `LoadingSkeleton`.

### Empty state
Centered in the column, generous vertical padding (96px above and below):

```
              ┌───┐
              │ ▭ │      (small line drawing, 64px, Phosphor "BookOpen" Regular, ink-60)
              └───┘

         Start your first project.

   A project is a set of source documents and the questions
   you ask of them.

           [ + New project ]
```

### Loading state
Three skeleton rows of the same height as real rows. `--ink-10` placeholder bars for title (60% width), description (40% width), metadata (30% width).

### Error state
Centered:

> ## Something's off.
> We couldn't load your projects. Refresh, or try again in a minute.
>
> [ Retry ]

### What the user CAN do
- Click a project to enter its workspace
- Create a new project (button opens an inline modal: "Project name" + "Optional description" + Create)
- Sign out from the user menu in the TopBar

### What the user CANNOT do
- Delete a project from this list (destructive actions live INSIDE the project, with confirm)
- Reorder projects
- Filter projects (≤50, no need)
- Search projects (≤50, no need)
- Star / favorite / pin
- See analytics ("12 projects this month")
- See team members on a project (no teams in v1)

### UX rules to prevent clutter
- Rows, not cards. No 3-column grid of project tiles.
- No icons next to project names. The name carries itself.
- No status badges ("active", "archived"). v1 has no archive.
- One column. Default sort: newest activity first. No sort selector.
- Metadata caption is one line. If it overflows, truncate with ellipsis.

---

## 3. Project workspace

### Purpose
The home of one project. Where the user manages sources, asks questions, and revisits past reports.

### Layout
Three regions, left-to-right. Source panel only appears when a citation is clicked from a report (so this screen shows two regions in default state).

```
┌────────────┬──────────────────────────────────────────────────────┐
│ ARGUS      │                                                       │
│            │   Acme Corp — Q3 contract review                      │   (Plex Serif 32)
│ ← All      │   Risk analysis for renegotiation                     │   (ink-60)
│   projects │   ──────────────────────────────────────────────      │
│            │                                                       │
│ Acme Corp  │   Sources              [ + Upload PDFs ]              │
│ — Q3...    │                                                       │
│            │   msa.pdf                  24 pages · ✓ Ready         │
│ ▸ Sources  │   nda.pdf                   6 pages · ✓ Ready         │
│ ▸ Reports  │   sow-draft.pdf            18 pages · Indexing 64%    │
│            │   scanned-old.pdf           — · Skipped (scanned PDF) │
│            │                                                       │
│            │   ──────────────────────────────────────────────      │
│            │                                                       │
│            │   Reports                                             │
│            │                                                       │
│            │   What are the financial risks across these...        │
│            │   2 days ago · 12 citations                           │
│            │                                                       │
│            │   What termination clauses apply to early exit?       │
│            │   6 hours ago · refused (insufficient evidence)       │
│            │                                                       │
│            │   ──────────────────────────────────────────────      │
│            │                                                       │
│            │   [ + Ask a question ]                                │
│            │                                                       │
└────────────┴──────────────────────────────────────────────────────┘
```

Sidebar (240px):
- Wordmark top (Plex Serif 17 weight 600)
- "← All projects" link (Plex Sans 14, `--ink-60`)
- Project name (Plex Sans 14, weight 500, `--ink-100`)
- Sections list: "Sources", "Reports" (anchored scroll-spy)
- Collapses to 56px icon-only at <1024px or via toggle

Main column:
- Project header (name, description, rule)
- Sources section (heading + upload button + list)
- Reports section (heading + list)
- "+ Ask a question" CTA at the bottom of the column

### Main components
`Sidebar`, `ProjectHeader`, `SectionHeading`, `Button` (primary), `SourceListRow`, `ReportRow`, `EmptyState`.

### Empty state — no sources yet
Replace the sources list with a full-width drop zone (240px tall). Below it, a quiet caption: "Upload your first sources to start asking questions."

The Reports section is hidden until at least one source is `ready`.

### Empty state — sources ready, no reports yet
Reports section reads:

> No questions asked yet. Open Ask to start.
>
> [ Ask a question ]

### Loading state
Sources list and Reports list both render skeleton rows. Sidebar still navigates.

### Error state
Project-level fetch error: full-width banner at the top of the main column, `--paper-2` background, `--ink-80` text, Plex Sans 14:
> "Couldn't load this project. [Retry]"

### What the user CAN do
- Upload sources (drop zone or button)
- Click a source row to preview the PDF in a side panel (opens the same Source Panel from screen 7, but with no highlight)
- Retry a failed source
- Remove a source (with confirm modal: "Remove msa.pdf? Past reports that cite it stay intact.")
- Click "+ Ask a question" → Question Composer
- Open a past report → Report Viewer
- Rename project (click name, inline edit)
- Delete project (only via user menu inside this workspace, with strong confirm)
- Go back to Project list via "← All projects"

### What the user CANNOT do
- Drag-reorder sources (no order matters)
- Tag or annotate sources
- Group sources into folders
- Add notes to sources
- Share the project (no sharing in v1)
- Invite teammates (no teams in v1)

### UX rules to prevent clutter
- Sidebar collapses to icons under 1024px width.
- The main column is ONE column. Never split into a dashboard grid.
- No KPI tiles ("12 sources / 4 reports / 47 citations"). Counts live in row metadata captions.
- No charts. Never.
- No "Recent activity" feed.
- The "+ Ask a question" CTA appears in only ONE place — bottom of the main column. Not also in the sidebar. Not also in the header. One place.

---

## 4. PDF upload / source library

### Purpose
Get PDFs into the project. Show their indexing status. Recover from upload failures.

### Layout
Lives inside the Project Workspace main column, in the "Sources" section. Two parts:

1. **Drop zone** (top)
2. **Sources list** (below)

```
   Sources              [ + Upload PDFs ]

   ┌──────────────────────────────────────────────────┐
   │   Drag PDFs here, or [browse files]              │
   │   Up to 50 files. PDFs only. 50 MB per file.     │
   └──────────────────────────────────────────────────┘    (96px tall when sources exist)

   msa.pdf                  24 pages    ●  ✓ Ready
   nda.pdf                   6 pages    ●  ✓ Ready
   sow-draft.pdf            18 pages    ●  Indexing 64%
   employment-old.pdf        — pages    ●  Skipped — scanned PDF      [Remove]
   contract-bad.pdf          — pages    ●  Failed — try again         [Retry] [Remove]
```

When the project has zero sources, the drop zone expands to 240px tall and the Sources list is hidden.

### SourceListRow anatomy
- Filename: Plex Serif 17, weight 400, `--ink-100`
- Page count: Plex Mono 12, `--ink-60`, right-aligned
- Status pip: 6px filled circle. `--verified` (ready), `--refuse` (parsing/uploading), `--unverified` (error/skipped)
- Status text: Plex Sans 14, `--ink-80` (or `--unverified` for failed)
- Per-row actions appear on hover only, right-aligned, ghost buttons

Hover state: row gains `--paper-card` background, hairline `--ink-10` rule appears above and below.

### DropZone behavior
- Idle: dashed `--ink-20` border, `--paper-2` background
- Drag-over: solid `--accent` border, `--paper-card` background, copy changes to "Drop to upload."
- Uploading: idle styling continues; per-file rows below show progress in status column

### Main components
`DropZone`, `Button` (primary "+ Upload PDFs"), `SourceListRow`, `StatusPip`, `Button` (ghost: "Remove", "Retry"), `Modal` (delete confirm).

### Empty state
Drop zone full-size (240px tall). Caption inside it:

> "Drag PDFs here, or browse files.
> Up to 50 files. PDFs only. 50 MB per file."

### Loading / processing states
Per-row, replacing the status text:
- "Uploading 38%" (with a thin progress bar under the row, `--ink-10` track, `--accent` fill)
- "Parsing"
- "Indexing 64%"
- "✓ Ready"

### Error states (per row)
- "Skipped — scanned PDF" (`--unverified`, with `[Remove]` action)
- "Failed — try again" (`--unverified`, with `[Retry]` and `[Remove]` actions)
- "Too large (62 MB) — max is 50 MB" (`--unverified`, with `[Remove]`)
- "Encrypted — can't read" (`--unverified`, with `[Remove]`)

### What the user CAN do
- Drag-drop or browse to upload PDFs
- Click a source row to preview the PDF (in Source Panel, no highlight)
- Retry a failed file
- Remove a source (with confirm modal)
- See real-time per-file progress

### What the user CANNOT do
- Edit OCR / extracted text
- Annotate the PDF
- Re-order sources
- Tag / categorize sources
- Open the PDF in an external tab from this screen (preview in-app keeps page numbers consistent for citations)
- Upload non-PDF files (DOCX, XLSX, audio etc.)
- Upload password-protected PDFs (rejected with clear message)

### UX rules to prevent clutter
- One row per file. No file-type icons (everything is a PDF — redundant).
- No thumbnail tiles. Tiles invite the 3-column-grid AI-slop pattern.
- Failed and skipped files stay visible (so the user knows what didn't make it). They don't disappear silently.
- Per-row actions appear only on hover. No always-visible action buttons cluttering each row.
- Status uses TEXT first, color second. Colorblind users still understand "✓ Ready" vs "Failed".

---

## 5. Question composer

### Purpose
Write the one question Argus will answer with a cited report.

### Layout
Dedicated full-screen surface at `/projects/[id]/ask`. Replaces the workspace view entirely so there's nothing else to look at.

```
┌──────────────────────────────────────────────────────────────────┐
│ [← Back to project]                                               │   (TopBar variant)
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│                                                                   │
│                                                                   │
│      Ask a question.                                              │   (Plex Serif 32/40)
│                                                                   │
│      Argus will only answer with citations from this project's   │   (Plex Sans 14/20 ink-60)
│      sources. If your sources can't support an answer, Argus     │
│      will say so.                                                 │
│                                                                   │
│      ┌───────────────────────────────────────────────────────┐  │
│      │                                                       │  │
│      │  What do you want answered? Be specific.              │  │   (Plex Serif 17/28)
│      │                                                       │  │   (textarea, 4 rows min)
│      │                                                       │  │
│      └───────────────────────────────────────────────────────┘  │
│                                                                   │
│      3 sources will be searched: msa.pdf, nda.pdf, sow.pdf       │   (Plex Mono 12 ink-60)
│                                                                   │
│                                                  [   Ask   ]    │   (Button primary, right)
│                                                                   │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

Surface centered at 720px max width. Generous vertical breathing room (96px above heading, 64px between elements). The whole surface uses `--paper-2` background (subtly different from default `--paper`) to signal "this is a focused workspace".

### Main components
`TopBar` (back-only variant), `PageHeading`, `GuidanceCopy`, `Textarea` (autosizing, 4-12 rows), `SourceContextLine`, `Button` (primary).

### Empty state
This IS the empty state. Textarea has placeholder: *"What do you want answered? Be specific."*

### Loading state
On submit, the entire composer surface transitions out (200ms fade) and the Report Viewer's loading state takes over. The composer never sits there with a spinner.

### Error state — pre-submit validation
- If no sources are `ready`: an inline rule above the textarea, Plex Sans 14, `--unverified`:
  > "You need at least one ready source to ask a question."
  Ask button disabled.
- If textarea is empty: Ask button is just disabled, no message.

### Error state — submission failed
Returns to the composer with an inline banner at the top:
> "Couldn't send the question. Try again."
Textarea content preserved.

### What the user CAN do
- Type a question
- See which sources will be searched (the source context line lists all `ready` sources)
- Submit ("Ask")
- Cancel back to project workspace

### What the user CANNOT do
- Pick which subset of sources to include (project = scope, no per-question filter in v1)
- Pick a model
- Pick a "creativity / temperature" setting
- Pick an output format (PDF/Markdown is on the export, not the question)
- Save drafts
- Add follow-up questions in this surface (every question is its own report)
- See suggested questions / templates / examples

### UX rules to prevent clutter
- ONE textarea, ONE button. That's the whole surface.
- The guidance copy directly sets expectations: refusal is normal. This is intentional friction against "ChatGPT it" muscle memory.
- The textarea uses Plex Serif (not Plex Sans). The user is composing a sentence to be answered carefully — the serif gives it weight.
- The "Ask" button is right-aligned, not centered, not full-width. Subtle visual cue that this is a deliberate action, not a "go" button.

---

## 6. Report viewer

### Purpose
Read the cited answer. The product's main moment.

### Layout
Two-pane. Left pane (60%) = report. Right pane (40%) = source viewer (hidden by default until first citation click).

```
┌──────────────────────────────────────────────────┬─────────────────┐
│ [← Back to project]                  [⤓ Export ▾]│                  │
├──────────────────────────────────────────────────┤                  │
│                                                  │                  │
│  QUESTION                                        │                  │
│  What are the financial risks across these       │                  │
│  contracts?                                      │                  │
│                                                  │                  │
│  Findings                                        │   (source panel) │
│  (Plex Serif 32/40)                              │   hidden until   │
│                                                  │   first citation │
│  Three primary financial risks recur across the  │   click          │
│  reviewed contracts. First, msa.pdf imposes      │                  │
│  uncapped indemnification for IP breach[1],      │                  │
│  exposing Acme to unbounded liability...         │                  │
│                                                  │                  │
│  ───────────────────────────────────────────     │                  │
│  Unverified claims                               │                  │
│  These statements were generated but couldn't    │                  │
│  be grounded in your sources. They are not part  │                  │
│  of the report.                                  │                  │
│  • The contract was signed in March 2023         │                  │
│                                                  │                  │
│  generated 14s ago · 3 sources · 12 citations    │                  │
│                                                  │                  │
└──────────────────────────────────────────────────┴─────────────────┘
```

After first citation click, the right pane slides in:

```
┌──────────────────────────────────┬──────────────────────────────────┐
│ [← Back to project]  [⤓ Export ▾]│ [1]  msa.pdf — page 7      [✕]  │
├──────────────────────────────────┼──────────────────────────────────┤
│                                  │                                  │
│  QUESTION                        │   ┌──────────────────────────┐  │
│  What are the financial risks    │   │                          │  │
│                                  │   │  ...indemnification for  │  │
│  Findings                        │   │  IP breach is uncapped   │  │  ◄─ highlighted
│                                  │   │  and survives terminat...│  │     passage
│  Three primary financial risks   │   │                          │  │     (--verified
│  recur across the reviewed       │   │  Other clauses on page 7 │  │      tint)
│  contracts. First, msa.pdf       │   │                          │  │
│  imposes uncapped indemnific-    │   └──────────────────────────┘  │
│  ation for IP breach[1]...       │                                  │
│                                  │   ‹ Prev citation [1 of 12] Next ›
│                                  │                                  │
└──────────────────────────────────┴──────────────────────────────────┘
```

Reading column geometry: 680px max measure, Plex Serif 17/28, `--paper-card` surface.

### Main components
`ReportHeader` (back, export popover trigger), `QuestionEcho`, `ReportBody` (renders inline `CitationChip`s), `UnverifiedSection`, `ReportFooter` (provenance caption), `SourcePanel` (right pane), `Resizer` (between panes).

### CitationChip rendering
- Inline element: `[1]`, `[2]`, etc.
- Plex Mono 13, `--accent` color
- No underline by default
- Hover: 4px radius `--accent-tint` background pill, underline appears
- Hover after 400ms: small tooltip "msa.pdf — page 7"
- Click: opens or focuses Source Panel on that citation
- Active state: 16% accent background pill, indicates "this is the citation currently open in the source panel"

### Unverified claims section
Renders only if any claims were dropped. After the report body, a single `--ink-10` rule, then:

> ### Unverified claims
> These statements were generated but couldn't be grounded in your sources. They are not part of the report. They are listed here for your awareness.
> - The contract was signed in March 2023
> - Acme has 12 active SOWs

Italic Plex Serif 17, `--ink-60` color. Bullet list, no chips, no citations (because there aren't any — that's why they're unverified).

### Empty state
Never empty. If no report exists, the user wouldn't be on this page.

### Loading state
Skeleton paragraphs in the report column (varying-width `--ink-10` bars, 6 lines × ~3 paragraphs).

Top of column shows a staged caption that updates as the pipeline progresses:

```
   ●  Reading 3 sources...
   ●  Generating answer...
   ●  Verifying citations...
```

Each step's pip is `--refuse` (in progress), then `--verified` (done). Three faint pulse-dots, NOT a spinner.

### Error state
Centered in the report column:

> ## We couldn't generate this report.
> The model returned an unparseable response after 2 retries.
>
> [ Try again ]    [ Back to project ]

### Refusal state
See screen 9. Renders inside the report column, replacing the body.

### What the user CAN do
- Read the report
- Click any citation chip → opens Source Panel
- Drag the resizer between panes
- Export → PDF or Markdown
- Copy text (selection works normally)
- Go back to project workspace
- Open a different past report (by going back)

### What the user CANNOT do
- Edit the report
- Regenerate with the same question
- Ask a follow-up in the same view (separate question = separate report)
- Delete the report from this view (delete is in project workspace, with confirm)
- Share via link (no v1)
- Annotate / highlight / comment

### UX rules to prevent clutter
- Reading column has a real measure (680px ideal). No sidebars over text.
- No annotation layer. No comments. No reactions / emojis.
- Citations are the ONLY interactive element in the report body.
- Footer caption gives provenance ("generated 14s ago · 3 sources · 12 citations") — no badges, no trust scores in the body.
- The Question is rendered above the report once, in small Plex Sans caps as a label, then in Plex Serif 24 as the actual question text. Reads like a memo, not a chat.

---

## 7. Citation / source viewer (the magic moment)

### Purpose
Prove the citation. Show the user the exact passage in the original PDF.

### Layout
Right pane of the Report Viewer. Slides in on first citation click.

```
┌──────────────────────────────────────────────────┐
│ [1]  msa.pdf — page 7              [↗ Open PDF] [✕]│   (header, 56px, paper-2)
├──────────────────────────────────────────────────┤
│                                                  │
│   ┌────────────────────────────────────────┐   │
│   │                                        │   │
│   │  CONFIDENTIALITY AND IP                │   │
│   │                                        │   │
│   │  7.1 Each party shall...               │   │
│   │                                        │   │
│   │  ┃ 7.2 Indemnification for any breach  │   │   ◄── highlight (verified
│   │  ┃ of intellectual property warranties │   │       tint + 3px left rule)
│   │  ┃ shall be uncapped and shall survive │   │
│   │  ┃ termination of this Agreement.      │   │
│   │                                        │   │
│   │  7.3 The parties agree to...           │   │
│   │                                        │   │
│   └────────────────────────────────────────┘   │
│                                                  │
├──────────────────────────────────────────────────┤
│  ‹ Prev citation     [1 of 12]    Next citation ›│   (footer nav, 48px, paper-2)
└──────────────────────────────────────────────────┘
```

### Open animation (run ONCE on first open)
1. Right pane slides in from 0% width to 40% over 200ms ease-out
2. PDF page renders into the pane
3. Page auto-scrolls to center the highlighted passage
4. Highlight pulse: 1s ease-out, opacity 0 → 1 on the highlight tint, then settles

Subsequent citation clicks: no re-slide, just content updates (the page swaps, the highlight moves, no animation).

### Highlight styling
- Background: `--verified` at 12% opacity, covering the exact passage bounding boxes
- Left rule: 3px solid `--verified` at 100% opacity
- Color is forest green, NOT yellow. Yellow = student notebook. `--verified` = mark of evidence.

### Header
- Plex Mono 12 for `[1]  msa.pdf — page 7`
- "↗ Open PDF" link (Plex Sans 14, `--accent`) — opens full PDF in new browser tab
- ✕ button (24px, ghost) — closes the panel

### Footer (citation navigator)
- 48px tall, `--paper-2` background, 1px `--ink-10` top border
- Plex Sans 14, `--ink-60`
- Prev / Next arrows in `--accent` when enabled, `--ink-40` when disabled (first/last citation)
- "[N of M]" centered, Plex Mono 12, `--ink-80`

### Main components
`SourcePanelHeader`, `PdfPageRenderer` (uses `pdfjs-dist`), `HighlightOverlay`, `CitationNavigator`, `Button` (ghost ✕), `Link` (↗ Open PDF).

### Empty state
Not applicable. This view only exists in a citation context.

### Loading state
Pane opens immediately with header + skeleton page (a `--ink-10` placeholder rectangle with thin lines suggesting page content). PDF renders into it once fetched.

### Error state
Inside the pane, replacing the page:

> "Couldn't load this page from msa.pdf.
> [ Open full PDF in new tab ]   [ Try again ]"

### What the user CAN do
- Click any citation in the report — pane updates with new source/page
- Use Prev / Next to walk citations sequentially
- Close the pane with ✕ or Esc
- Open the full PDF in a new browser tab (for users who want to read context)
- Drag the resizer between report and source pane

### What the user CANNOT do
- Annotate the page
- Highlight additional passages
- Search within the PDF (v2)
- Print just this page (v2)
- Edit the source from this view

### UX rules to prevent clutter
- Header always shows `[N]  filename — page X`. Never just "Source 1."
- Animation runs ONCE per session per click. Subsequent navigation is instant.
- The highlight color is `--verified`. Never yellow, never blue, never red.
- One `↗ Open PDF` action only. No "Download," no "Share," no "Print."
- Citation nav is at the bottom and ALWAYS visible when the pane is open. It's the second-most-used control after closing.

---

## 8. Export state

### Purpose
Hand the report off to whatever the user uses next (deck, doc, email).

### Layout
Triggered by `[⤓ Export ▾]` button in the Report Viewer header. Opens a small popover (240px wide, anchored to button's bottom-right).

```
   ┌────────────────────────────────┐
   │  Export as                     │   (Plex Sans 14, weight 500)
   │  ────────                      │
   │                                │
   │  ◉  PDF                        │   (Plex Sans 14)
   │     Preserves citations and    │   (Plex Sans 12, ink-60)
   │     a source-list page         │
   │                                │
   │  ○  Markdown                   │
   │     Citations as inline refs   │
   │                                │
   │  ────                          │
   │                                │
   │     [ Cancel ]    [ Export ]   │
   └────────────────────────────────┘
```

### Main components
`Button` (with caret variant: "Export ▾"), `Popover`, `RadioGroup`, `Button` (primary "Export"), `Button` (ghost "Cancel"), `Toast` (post-export confirmation).

### States
- **Idle:** popover closed
- **Open:** popover visible, "PDF" pre-selected (default)
- **Exporting:** "Export" button shows inline 14px spinner, label changes to "Exporting..."
- **Done:** popover closes, file download begins, toast appears at bottom-right:
  > "Exported as report-acme-q3-financial-risks.pdf"
  > [Open]
  Toast auto-dismisses after 8 seconds (longer than usual because of the action).

### Loading state
Inline spinner inside the "Export" button. The rest of the popover stays interactive (you can still cancel).

### Error state
Toast appears (instead of file download):
> "Export failed. Try again."
> [Retry]
`--unverified` accent strip on left of toast.

### Export format details

**PDF export contains:**
- The full report body with inline citations (rendered as superscript `[1]`)
- A final page titled "Sources" listing every cited source/page:
  ```
  [1] msa.pdf, page 7
  [2] msa.pdf, page 12
  [3] nda.pdf, page 3
  ...
  ```
- Footer on every page: project name + report date

**Markdown export contains:**
- The full report with inline `[Source: msa.pdf, p.7]` citations
- A "## Sources" section at the end listing each unique source/page combination

### What the user CAN do
- Choose PDF or Markdown
- Cancel
- Export, then open the file via the toast action

### What the user CANNOT do
- Pick a custom template
- Pick which sections to include (the report IS the export — selection is the v2 conversation)
- Email directly from Argus
- Send to Notion / Drive / Slack (v2)
- Export to CSV / JSON (consultants don't want it; engineers can't be the buyer)
- Re-export from history (always re-trigger from the report)

### UX rules to prevent clutter
- Two formats only. PDF and Markdown.
- The popover has no "advanced options" disclosure. There are no advanced options.
- The default is PDF (matches the consultant workflow: send to client).
- No share-link, no email button. Argus is generation; distribution is the user's job.

---

## 9. Error / refusal states

### Purpose
Tell the user what Argus can't do, and why, in a way that increases trust rather than erodes it.

### Hierarchy (three distinct visual treatments)

| Type | When | Tone | Visual |
|---|---|---|---|
| **Refusal** | Argus can't ground an answer in the user's sources | Calm, certain, intentional | `--refuse` neutral, large Plex Serif headline |
| **Soft error** | Pipeline hiccup, retry will probably fix it | Corrective, fixable | `--unverified` amber accent, banner-shaped |
| **Hard error** | Something is genuinely broken | Apologetic, honest | `--ink-80`, modal-shaped, with error code |

### Refusal — "Insufficient evidence"

Renders inside the Report Viewer column, replacing the report body. NOT a modal. NOT a toast. The refusal IS the report.

```
                                  (96px top padding)


              Insufficient evidence in your sources.        (Plex Serif 44/52)


   You asked: "What are the indemnification limits in the   (Plex Sans 17/28 ink-80,
   SOW?"                                                     480px max measure)

   Argus searched 3 sources but didn't find passages that
   support an answer to this question. Specifically: none
   of msa.pdf, nda.pdf, or employment-agreement.pdf contain
   SOW content.


   What to try
   ───────────                                              (Plex Sans 14 ink-60 weight 500)

   • Upload the SOW or the document containing those        (Plex Sans 14/24 ink-80)
     clauses
   • Rephrase the question to focus on indemnification in
     the contracts you have


   [ ← Back to project ]    [ Ask a different question ]
```

**Tone:** A senior partner declining to bullshit a junior. Not an apology. Not an error.

**Visual rules:**
- `--refuse` gray accents only. Zero red. Zero amber.
- NO warning icon. NO error icon. The headline does the work.
- Optional subtle 16px Phosphor "ShieldCheck" icon in `--refuse` before the headline — but only if it doesn't read as defensive.
- The page footer caption ("generated 1s ago · 3 sources · 0 citations") is preserved. Provenance still matters.

### Soft error — pipeline hiccup

When an upstream call fails recoverably (OpenAI 429, Claude timeout, etc.). Renders in place of the report body OR as a banner at the top of an existing surface depending on context.

```
   ┌────────────────────────────────────────────────────┐
   │                                                    │
   │   We hit a snag generating this report.            │   (Plex Serif 24/32)
   │                                                    │
   │   The OpenAI embedding service didn't respond.     │   (Plex Sans 14/20 ink-80)
   │   This is usually transient.                       │
   │                                                    │
   │   [ Try again ]    [ Back to project ]             │
   │                                                    │
   └────────────────────────────────────────────────────┘
```

`--unverified` left rule (3px) on the surface.

### Hard error — something is broken

Used for unhandled exceptions or 500s.

```
   Argus is having a bad moment.                            (Plex Serif 32/40)

   We're not sure what went wrong. The team has been        (Plex Sans 14/20 ink-80)
   notified. You can try again, or come back in a few
   minutes.

   [ Reload ]    [ Back to project ]

   error code: ARG-7F2A                                     (Plex Mono 12 ink-60)
```

The error code is included so a beta user can paste it into the feedback Slack channel and you can grep your logs.

### Form / input errors (inline)

Inline below the affected field, in `--unverified` amber, Plex Sans 14, no red.

> "This file is too large (62 MB). Max is 50 MB per PDF."

### Toast errors (transient ops)

Bottom-right toast with `--unverified` accent strip on the left, Plex Sans 14:
> "Export failed. Try again."
> [Retry]

### Network drop (anywhere in app)

Inline banner at the top of the affected surface, `--paper-2` background, `--ink-80`, Plex Sans 14:
> "You're offline. Some actions are paused until you're back."

When connection returns, the banner morphs to:
> "Reconnected. Your changes are saved."
And dismisses after 3 seconds.

### Session expired (anywhere in app)

Soft redirect to Login with caption above the form:
> "Your session expired. Sign back in."

### Universal UX rules for error / refusal

- **Refusals look calm and intentional, not broken.**
- **Errors apologize honestly, never blame the user.** Never "Invalid input." Always "We couldn't read this — try a different file."
- **No exclamation marks** in any error or refusal text.
- **No "Oops!"**, no "Uh-oh!", no emojis.
- **Always offer a next action.** Never a dead end. "Try again" or "Back to project" minimum.
- **Never say "Internal Server Error"** or expose stack traces. Translate everything.
- **Refusals always cite which sources WERE checked.** This proves Argus did the work and didn't find ground — it's not laziness, it's epistemic honesty.

---

## Cross-screen consistency rules

These apply to every screen above:

1. **One CTA per surface.** If you have a primary action, the rest are secondary or ghost.
2. **Captions are Plex Mono 12.** Always. Across all screens.
3. **Body prose is Plex Serif.** Reports, refusals, headlines.
4. **UI chrome is Plex Sans.** Buttons, labels, navigation.
5. **Status uses text + color + a status pip.** Never color alone.
6. **Hover states never add chrome.** They change background or add an underline. They never reveal new buttons.
7. **Loading states tell the user what's happening.** "Reading 3 sources..." not "Loading..."
8. **Error and refusal copy never says sorry more than once.** Apology is a finite resource.
9. **Empty states have a primary action.** Always.
10. **Sidebar collapses, drawer doesn't open.** v1 has no slide-in drawers from any side except the source panel.
