-- Phase 2 / Week 5 / Day 4 — evidence_objects.metadata jsonb.
--
-- Day 4 needs first-class citation breadcrumbs for firm-library content:
-- the popover renders "📚 Firm Library — {title} ({category})" + section
-- on hover, and PDF/DOCX export footnotes need the same data.
--
-- Day 1's chunks table already carries metadata jsonb (firm_content_id,
-- title, category, intended_modes…). evidence_objects is the layer the
-- frontend reads. Without a metadata column there, the orchestrator
-- can't carry the firm-library breadcrumb across into the citation
-- payload — only source_title / source_url / source_type. The Day 4
-- spec called this out as a surface signal expecting "a thoughtful
-- extension, not a hack."
--
-- Schema is additive + nullable so existing rows are untouched.

ALTER TABLE evidence_objects
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
