-- Phase 7: LLM cost tracking — every LiteLLM call records here.

CREATE TABLE IF NOT EXISTS llm_calls (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id        UUID REFERENCES sessions(id) ON DELETE SET NULL,
    user_id           UUID REFERENCES users(id) ON DELETE SET NULL,
    task_kind         TEXT,                      -- planner | researcher | analyst | critic | verifier | writer | structured_grounder | etc.
    model             TEXT NOT NULL,
    provider          TEXT NOT NULL DEFAULT 'openai',
    prompt_tokens     INT NOT NULL DEFAULT 0,
    completion_tokens INT NOT NULL DEFAULT 0,
    total_tokens      INT NOT NULL DEFAULT 0,
    usd_cost          NUMERIC(10, 6) NOT NULL DEFAULT 0,
    latency_ms        INT NOT NULL DEFAULT 0,
    success           BOOLEAN NOT NULL DEFAULT true,
    error_kind        TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_llm_calls_session ON llm_calls(session_id);
CREATE INDEX IF NOT EXISTS idx_llm_calls_user    ON llm_calls(user_id);
CREATE INDEX IF NOT EXISTS idx_llm_calls_created ON llm_calls(created_at);
