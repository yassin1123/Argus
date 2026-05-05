CREATE TABLE IF NOT EXISTS pipeline_events (
  id BIGSERIAL PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,
  stage TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  duration_ms INT,
  model_used TEXT,
  retry_count INT NOT NULL DEFAULT 0,
  token_in INT,
  token_out INT,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_pipeline_events_session_id_created
  ON pipeline_events (session_id, id);
