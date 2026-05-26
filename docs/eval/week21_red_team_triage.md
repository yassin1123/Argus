# Week 21 / Day 4 — Hallucination red-team triage

**Catch rate:** 33 / 34 = **97.1%** against the tuned (W21/D3
reverted-to-W2/D3) thresholds + the new numeric-consistency probe.

**Numeric probe contribution this run:** +0 catches. The
heuristic verifier baseline already downgrades on numeric drift
via its conservative `_heuristic_llm_verdict`, so the probe had
nothing to add — but it remains wired as a hard veto for the
real-ensemble path, where a high-confidence LLM "supported"
verdict on a fabricated number is the most dangerous failure mode.

## Per-exploit catch rate

| Exploit | Caught / Total | Catch rate |
|---|---|---|
| magnitude_mismatch | 4 / 4 | 100% |
| misattribution | 3 / 4 | **75%** |
| temporal_drift | 4 / 4 | 100% |
| overclaim | 4 / 4 | 100% |
| fabricated_specific | 7 / 7 | 100% |
| plausible_but_absent | 3 / 3 | 100% |
| negation_flip | 4 / 4 | 100% |
| cherry_pick | 4 / 4 | 100% |

## Escape triage

### `rt_007` — misattribution (documented limitation)

> **Claim:** "The board chair endorsed the cost-out programme at the AGM."
> **Evidence:** "The CEO's AGM speech endorsed the cost-out programme. The chair's opening remarks focused on board renewal."
> **Verifier said:** `supported_high`

**Why it escapes.** The endorsement happened (the LLM judge sees
the supporting facts) and the topic matches. The chunk has both
"chair" and "endorsed" as tokens; the cross-encoder's gist signal
fires. The misattribution — that the wrong speaker is credited
— is a *semantic role* error the NLI signals don't attend to.

**Triage:** **document, not fix-now.** The mitigation library
prescribes:

> "Out-of-scope for threshold tuning — the LLM judge needs to
> attend to speaker / source attribution. Documented limitation;
> Week 22 prompt-tightening + an entity-attribution check would
> close it. NOT a threshold problem."

This is the right disposition. Loosening thresholds to catch
misattribution would catastrophically blow up false positives on
legitimate attribution-bearing claims. The fix is in the LLM
judge's prompt + a separate attribution-check probe (analogous
to the W21/D4 numeric probe but scoped to "did the speaker the
claim names actually say the thing?"). Carrying as a Week 22
roadmap item.

### All other exploit categories (100% catch rate)

Caught under the current W2/D3 thresholds + the conservative
`_heuristic_llm_verdict`. When the real cross-family ensemble
is wired (real_ensemble verifier), the numeric probe becomes
the load-bearing defence against fabricated-specific +
magnitude-mismatch escapes — those are exactly the cases where
a confident LLM judge would otherwise vote supported and the
probe vetoes.

## Carry-forward

  - **Misattribution** → Week 22: LLM prompt addition + a
    targeted entity-attribution probe modelled on the
    numeric-consistency probe (extract speaker entities from
    claim, require they're the speaker in the chunk).
  - **Negation flip** → 4/4 caught on this heuristic baseline,
    but production negation is subtler ("did not approve" inside
    an approval-context sentence). When real DeBERTa scores
    against real news/transcript chunks, watch this category in
    Week 22 regression.
  - **Cherry-pick** → 4/4 caught; partial mitigation already
    exists via the critic agent's pyramid-coherence check.
    Watch for regressions.
  - **Numeric probe** is shipped but contributed +0 catches
    here. It's the right defence for the real-ensemble path —
    don't remove it, just don't yet claim it's load-bearing
    against the heuristic baseline.

## Files

  - Adversarial set: [backend/eval/red_team/adversarial_cases.py](../../backend/eval/red_team/adversarial_cases.py)
  - Probe: [backend/eval/red_team/numeric_probe.py](../../backend/eval/red_team/numeric_probe.py)
  - Runner: [backend/eval/red_team/run_red_team.py](../../backend/eval/red_team/run_red_team.py)
  - Report: [backend/eval_runs/week21_red_team/escapes.json](../../backend/eval_runs/week21_red_team/escapes.json)
  - Tests: [backend/tests/test_red_team.py](../../backend/tests/test_red_team.py)
