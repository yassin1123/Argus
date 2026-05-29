-- Migration 051 — Phase 5 / Week 25 / Day 3: per-section edit breakdown.
--
-- W24/D3 stored the engagement-level edit churn (words_same/added/removed +
-- edit_fraction). W25/D3 adds the section-level breakdown so the pilot can
-- answer "WHICH sections get edited most" — the synergy estimate? the
-- recommendation? the framework? — which tells us where the drafts fall
-- short.
--
-- section_edits is { "<section_path>": { same, added, removed, edit_fraction } }.
-- Counts + a 0..1 fraction per section. STILL no prose — the W20 privacy
-- line holds in production (we store how much changed + where, never what).

ALTER TABLE engagement_edit_telemetry
    ADD COLUMN IF NOT EXISTS section_edits JSONB NOT NULL DEFAULT '{}'::jsonb;
