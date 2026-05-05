ALTER TABLE reports ADD COLUMN IF NOT EXISTS consulting_payload JSONB DEFAULT '{}';
