-- Phase 7: persist the StructuredAnswer alongside the report.

ALTER TABLE reports ADD COLUMN IF NOT EXISTS structured_answer JSONB;
