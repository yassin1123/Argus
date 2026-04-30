-- Phase 3: blob storage in object store, not DB.
-- New `source_blobs` row per uploaded source file. Original `uploaded_files.content`
-- column stays for backward-compat reads; new uploads write content='' and use blob_id.

CREATE TABLE IF NOT EXISTS source_blobs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id   UUID REFERENCES sessions(id) ON DELETE CASCADE,
    s3_key       TEXT NOT NULL UNIQUE,
    size_bytes   BIGINT NOT NULL DEFAULT 0,
    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    sha256       CHAR(64) NOT NULL,
    uploaded_by  UUID REFERENCES users(id) ON DELETE SET NULL,
    uploaded_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_source_blobs_session ON source_blobs(session_id);
CREATE INDEX IF NOT EXISTS idx_source_blobs_sha     ON source_blobs(sha256);

-- Link existing `uploaded_files` rows to their blob (nullable for legacy rows).
ALTER TABLE uploaded_files ADD COLUMN IF NOT EXISTS blob_id UUID REFERENCES source_blobs(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_uploaded_files_blob ON uploaded_files(blob_id);
