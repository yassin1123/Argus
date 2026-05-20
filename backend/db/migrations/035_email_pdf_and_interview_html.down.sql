-- Rollback for 035: restore the W10/D2 (migration 033) artifact_type
-- + format check constraint without email/pdf or interview_guide/html.

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
            ('email', 'html'), ('email', 'md'),
            ('interview_guide', 'md'), ('interview_guide', 'pdf')
        )
    );

COMMIT;
