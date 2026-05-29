-- Down: drop the W25/D3 per-section edit breakdown column.
ALTER TABLE engagement_edit_telemetry DROP COLUMN IF EXISTS section_edits;
