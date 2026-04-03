CREATE TABLE IF NOT EXISTS export_artifact_cache (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  format_key TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  bytes BYTEA NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (session_id, format_key, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_export_cache_session ON export_artifact_cache (session_id);
