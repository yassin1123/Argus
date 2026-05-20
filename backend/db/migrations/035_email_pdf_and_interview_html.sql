-- Migration 035 — widen the export_artifacts (artifact_type, format)
-- check constraint so the W13/D2 email/pdf and W13/D4
-- interview_guide/html combinations are accepted.
--
-- The W10 migration 033 baseline allowed:
--   memo/html, memo/pdf, memo/docx,
--   one_pager/html, one_pager/pdf,
--   deck/pptx, deck/pdf,
--   excel_model/xlsx,
--   email/html, email/md,
--   interview_guide/md, interview_guide/pdf
--
-- W13/D2 added email/pdf; W13/D4 added interview_guide/html. Both are
-- registered against the exporter registry; this migration closes the
-- DB-side gap so generate_artifact stops failing the check constraint.

BEGIN;

ALTER TABLE export_artifacts
    DROP CONSTRAINT IF EXISTS export_artifact_type_format_valid;

ALTER TABLE export_artifacts
    ADD CONSTRAINT export_artifact_type_format_valid CHECK (
        (artifact_type, format) IN (
            ('memo', 'html'), ('memo', 'pdf'), ('memo', 'docx'),
            ('one_pager', 'html'), ('one_pager', 'pdf'),
            ('deck', 'pptx'), ('deck', 'pdf'),
            ('excel_model', 'xlsx'),
            ('email', 'html'), ('email', 'md'), ('email', 'pdf'),
            ('interview_guide', 'md'), ('interview_guide', 'html'), ('interview_guide', 'pdf')
        )
    );

COMMIT;
