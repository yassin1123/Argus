# UX Flow — Argus v1

The single core flow, screen-by-screen, with state transitions and forbidden detours.

---

## The one core flow (drawn whole)

```
LOGIN (magic link)
   │
   ▼
PROJECT LIST
   │
   ├── [+ New project] ──► creates and enters new project
   │
   ▼
PROJECT WORKSPACE  ◄────── (default home for one project)
   │
   ├── Upload PDFs ─► sources index in background
   │       │
   │       ▼
   │   Sources reach status=ready
   │
   ├── Ask a question ─► QUESTION COMPOSER
   │       │
   │       ▼
   │   Submit ─► REPORT VIEWER (loading)
   │       │
   │       ├── Generation completes ─► REPORT VIEWER (cited report)
   │       │       │
   │       │       ├── Click [N] ─► SOURCE PANEL slides open
   │       │       │       │
   │       │       │       ├── Click another [N] ─► panel updates
   │       │       │       └── Close panel ─► return to single-pane
   │       │       │
   │       │       ├── Export ▾ ─► PDF or Markdown ─► file downloads
   │       │       │
   │       │       └── Back ─► PROJECT WORKSPACE
   │       │
   │       └── Refusal triggered ─► REPORT VIEWER (refusal state)
   │               │
   │               └── Action: rephrase OR upload more sources
   │
   ├── Open past report ─► REPORT VIEWER
   │
   └── Sign out ─► LOGIN
```

Five screens. One flow. No detours.

---

## State transitions per screen

### Login
- Idle → Submitting → Sent (calm "check your email" state)
- Returning user with valid session bypasses login entirely, lands on Project List

### Project list
- Loading (skeleton rows) → Loaded (rows or empty state)
- Loaded → "+ New project" → Project Workspace (fresh project, no sources)
- Loaded → click row → Project Workspace (existing project)

### Project workspace
- Loading → Loaded
- Loaded (no sources) → Upload PDFs → per-file pipeline runs in background
  - Per file: `uploading` → `parsing` → `indexing` → `ready` (or `error` / `skipped`)
- Loaded (sources ready, no questions yet) → "Ask a question" CTA visible
- Loaded (sources ready, questions exist) → Recent reports list visible
- Source row click → in-place PDF preview (does NOT navigate away)

### Question composer
- Empty textarea → typing → "Ask" enabled when text length > 0 AND ≥1 source is `ready`
- Submit → transitions directly to Report Viewer in loading state
- The composer never sits there with a spinner. Submit means transition.

### Report viewer
- Loading (skeleton paragraphs + staged caption) → Loaded OR Refusal OR Error
- Loaded → Citation click → Source Panel opens (slide-in, 200ms ease-out)
- Loaded → Export ▾ → format choice → file downloads → toast confirmation
- Loaded → Back → Project Workspace
- Refusal is rendered IN the report column. It is not a modal, not a toast, not an error.

### Source panel
- Closed by default. Opens with first citation click (animated once).
- Open → another citation click → content updates, no re-slide
- Open → ✕ or Esc → closes, returns to single-pane report

### Export
- Idle button → popover opens → format selected → "Export" → inline spinner → file downloads → popover closes → toast "Exported as report.pdf"

### Refusal
- Triggered when: retrieval top-1 score < 0.55 OR all generated claims fail verification
- Renders in place of the report body (replaces it, not overlay)
- Two next actions, both inline: rephrase the question OR upload more sources
- This is a successful state of the system, not an error. Visual treatment matches that.

---

## Cross-cutting transitions

### Session expired (anywhere in app)
Soft redirect to Login with caption: "Your session expired. Sign back in."

### Network drops during a long operation
Inline retry banner appears at the top of the affected surface. Never a full-page error. Never a modal.

### Tab loses focus during PDF upload
Background processing continues. When the user returns, source statuses have updated. No interruption, no "are you still there?" prompt.

### A source fails to index
That source's row shows the failure inline. Other sources continue. The user can retry or remove that one source.

---

## The one moment that must feel excellent

User clicks `[1]` in a report. Within 200ms:

1. The right pane slides in (0% width → 40% width)
2. The cited PDF page renders
3. The exact passage is highlighted with a soft `--verified` tint
4. The page auto-scrolls to center the highlight
5. A 1-second pulse on the highlight, then it settles

If this moment doesn't feel excellent, the rest of the design is wallpaper. This is the demo. This is the moment a consultant gasps. Engineer this with care.

---

## What this flow explicitly forbids

- ❌ Global search bar — consultants have ≤50 projects in v1, search is unnecessary chrome
- ❌ Notification center — no async events for users to track
- ❌ "Recent activity" feed — vanity, not useful
- ❌ Onboarding tour / coachmarks — the app is 5 screens, the user walks it once
- ❌ "Welcome back!" modals or feature announcement banners
- ❌ Team / sharing / invite flows
- ❌ Conversational follow-up — every question is its own self-contained report
- ❌ Tabs — anywhere. Tabs hide content.
- ❌ Dashboards or charts of any kind
- ❌ "Settings" page (no settings exist in v1 — sign out is in the user menu, that's it)

If you find yourself building any of the above, stop and re-read the product spec.

---

## Decision points the user faces (and how few there are)

| Where | Choice | Default |
|---|---|---|
| Login | enter email | (no default) |
| Project list | open existing OR create new | none |
| Project workspace | upload OR ask OR open report | upload (when empty) |
| Source row | preview, retry, remove | preview on click |
| Question composer | type and submit | (no default) |
| Report viewer | click citation, export, back | none |
| Source panel | navigate citations, close | close on Esc |
| Export | PDF or Markdown | PDF |

That's the entire decision space of v1. Eight choice points across the whole product. Hold the line.
