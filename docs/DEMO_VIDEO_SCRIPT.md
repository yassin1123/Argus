# Demo Video Script — Argus (3:00)

**Format:** Loom screen recording with voice-over. 1440×900 browser, big enough for legible UI.
**Tone:** confident, factual, no hype words. ~150 words/min target — keep pace tight.
**Pre-record setup:** `make demo` running, seeded engagements visible at `localhost:3000`.

---

## 0:00–0:20 — The problem (no screen recording yet — talking head OR static title card)

> "Generic chatbots produce fluent prose that sounds confident while quietly mixing inference with facts and citing nothing you can audit. Consultants are slow and expensive. Argus is what sits in between — a multi-agent system that turns a strategic question into a verified, citation-backed report a client could take to a meeting."

**Visual:** Argus logo / hero card. Or just a black screen with title text.

---

## 0:20–0:40 — Pose the question

**Action:** screen recording starts. Homepage visible at `localhost:3000`.

> "Three demo engagements are pre-seeded. We'll walk through the first one — *'Should a B2B SaaS company prioritize Germany or France for its first European market entry?'* — but first, let me show what creating a new one looks like."

**Click:** the composer input. Type the question slowly enough to be visible.

> "Argus takes a strategic question, runs an intake step to capture constraints, then plans a research agenda."

**Click:** *Start.* If running with a real API key, the intake step appears. If demo mode, click into the seeded Germany-vs-France engagement instead.

---

## 0:40–1:00 — Document upload (skip if not running real mode)

**Action:** drag a PDF onto the composer (any market report).

> "Uploaded documents are chunked, embedded into pgvector, and merged with web search results at retrieval time. The pipeline doesn't differentiate between your data and the open web — both flow into the evidence catalog."

**If demo mode:** instead say *"Documents are optional — Argus falls back to web research if you don't upload anything."* and skip to the next section.

---

## 1:00–2:00 — The pipeline running live

**Action:** click into the Germany-vs-France engagement. (If you triggered a real run earlier, watch it process. Otherwise, the seeded session is already complete — narrate over the agent timeline in the audit panel.)

> "The pipeline is six stages. Planner breaks the question into research tasks. Researcher pulls evidence from documents and the web in parallel. Analyst synthesizes claims, each tied to specific evidence ids. Critic challenges the analysis and asks for revisions. Verifier re-checks every claim against the evidence catalog. Writer produces the final consulting-grade memo."

**Show:** SSE progress in `processing-sse.png` style. Token counter ticking. Per-stage timing.

> "Total run time: about 80 seconds for this question. About 15,000 tokens. All persisted — every agent's output, every evidence object, every verifier verdict."

---

## 2:00–2:40 — The deliverable + the evidence graph (the money shot)

**Click:** **Answer** tab.

> "The recommendation: run a 2-quarter pilot in Germany before committing build-out. Confidence: medium-high. Eight of nine claims supported by the verifier; one flagged weak."

**Click:** **Graph** tab — this is the hero shot.

> "Every claim is traceable. Six claims on the left, eight evidence objects in the middle, eight sources on the right. Click a claim — its supporting evidence and sources highlight; everything else dims. Click an evidence node — see the verbatim quote and a link to the source."

**Click:** claim `c1` to demonstrate highlighting.

> "Color-coded by verifier verdict: green for supported, amber for weak, red for unsupported. The amber claim — pilot success base rates — is supported only by an internal pattern, flagged as inference. The verifier caught it; the report's caveats banner surfaces it."

**Click:** **Audit** tab → expand a claim → show entailment score and evidence quote.

> "All of this — the verdicts, the entailment scores, the support type — sits in a `claim_support_rows` table joined to evidence objects and verifier output. Nothing is decoupled."

---

## 2:40–3:00 — Export + close

**Click:** **Export → PDF** in the trust rail.

> "Exported deliverables come in PDF, PPTX, or markdown memo, all content-hash cached so re-exports are free. This is what a client gets: a defensible, citation-backed recommendation with confidence and caveats made explicit, not buried."

**Show:** the rendered PDF first page.

> "Argus — full code at github.com/yassin1123/Argus. One-command demo: `make demo`."

**End screen:** repo URL + brief CV bullet.

---

## Recording tips

- Record at 1440×900 in a browser zoom-friendly state. **Don't** record at 4K — Loom compresses it badly.
- Run through the script once silently first to verify all click targets work.
- Re-record the entire video rather than splicing if you fluff a section under 30 seconds — splices show.
- Loom auto-captions are usually decent; review them for "Mittelstand", "pgvector", and "Bessemer" — those will mistranscribe.
- Total target: 3:00. Going past 3:30 loses recruiters; going under 2:30 looks light.

---

## What goes in the README

```markdown
## Demo

- **Live demo:** _<link — coming soon>_
- **3-minute walkthrough:** [https://www.loom.com/share/<id>](https://www.loom.com/share/<id>)
- **Example use case:** *"Should a SaaS company enter Germany or France first?"*
- **Full case study:** [`docs/case-studies/germany-vs-france/`](docs/case-studies/germany-vs-france/)
```

Replace `<id>` with the actual Loom share id once recorded.
