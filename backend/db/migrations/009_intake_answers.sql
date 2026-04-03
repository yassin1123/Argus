-- Interactive intake: generated questions + user answers before full pipeline
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS intake_questions JSONB DEFAULT '[]'::jsonb;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS intake_answers JSONB DEFAULT '[]'::jsonb;
