-- Phase 2 / Week 6 / Day 1 — layered consulting-mode overrides.
--
-- Built-in modes still ship in code (backend/config/consulting_modes.yaml).
-- Firms can override or define new modes via firm_modes; one-off engagement
-- tweaks live in engagement_mode_overrides.
--
-- Resolution order at runtime: built-in <- firm_modes <- engagement_mode_overrides
-- Field-level merge semantics live in core/consulting_modes/resolver.py.
--
-- base_mode is intentionally TEXT, not a foreign key into a built-in modes
-- table, because built-ins live in YAML and we don't want a built-in
-- rename/retire to orphan a firm override row.

CREATE TABLE IF NOT EXISTS firm_modes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id     UUID NOT NULL REFERENCES firms(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    base_mode   TEXT,
    config      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by  UUID REFERENCES users(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    retired_at  TIMESTAMPTZ,
    UNIQUE (firm_id, name)
);

CREATE INDEX IF NOT EXISTS idx_firm_modes_active
    ON firm_modes(firm_id) WHERE retired_at IS NULL;

CREATE TABLE IF NOT EXISTS engagement_mode_overrides (
    session_id  UUID PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    firm_id     UUID NOT NULL REFERENCES firms(id) ON DELETE CASCADE,
    mode_name   TEXT NOT NULL,
    config      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by  UUID REFERENCES users(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
