-- Phase 5: source library + manual trust classification.
-- A "source" in the user's mental model = one row in uploaded_files.
-- We give each one a trust_level (defaults inferred from file_type) and a
-- scope (engagement = only one eng sees it; firm = visible across the firm's
-- engagements as a pinnable Library entry).

ALTER TABLE uploaded_files
    ADD COLUMN IF NOT EXISTS trust_level TEXT NOT NULL DEFAULT 'web_general'
        CHECK (trust_level IN ('firm_vetted', 'credible_external', 'web_general', 'contested'));

ALTER TABLE uploaded_files
    ADD COLUMN IF NOT EXISTS scope TEXT NOT NULL DEFAULT 'engagement'
        CHECK (scope IN ('engagement', 'firm'));

ALTER TABLE uploaded_files ADD COLUMN IF NOT EXISTS notes TEXT NOT NULL DEFAULT '';
ALTER TABLE uploaded_files ADD COLUMN IF NOT EXISTS source_url TEXT;

-- Backfill: pdf/csv/json/url-uploaded files get firm-vetted as a sensible default;
-- url-fetched stays web_general.
UPDATE uploaded_files
SET trust_level = CASE
    WHEN file_type IN ('pdf', 'csv', 'json') THEN 'firm_vetted'
    WHEN file_type = 'url' THEN 'web_general'
    ELSE trust_level
END
WHERE trust_level = 'web_general' AND file_type IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_uploaded_files_scope ON uploaded_files(scope);
CREATE INDEX IF NOT EXISTS idx_uploaded_files_session_scope ON uploaded_files(session_id, scope);
