-- Migration 044 — Phase 4 / Week 19 / Day 1: payload version history.
--
-- Audit (W19/D1): no centralized version table exists. W9 stores
-- ``pre_accept_payload_snapshot`` inline on ``section_deepening_runs``
-- (feature-specific); ``export_artifacts.payload_snapshot`` freezes
-- a point-in-time view at artifact-generation. Neither is a
-- coherent history. Per the W19/D1 spec's option-2 path (create the
-- formal table when versioning is ad-hoc), we add a new
-- ``payload_versions`` table here and backfill v1 for every
-- existing session that already has a reports row.
--
-- One row per (session_id, version_number). The full payload
-- snapshot is JSONB so the version reader can show the historical
-- shape regardless of subsequent column drift on the ``reports``
-- table. ``changed_section_paths`` is populated by the W19/D1
-- diff helper at create-time (empty list for INITIAL).
--
-- We DO NOT migrate the W9 inline snapshots into this table — those
-- are owned by the W9 acceptance flow and will keep flowing through
-- the W19/D1 service (W9 wiring lands in this same commit). The
-- backfill below ensures every existing engagement has a v1
-- baseline so the history reader never shows "no versions" for a
-- live engagement.

BEGIN;

CREATE TABLE IF NOT EXISTS payload_versions (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id                  UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    firm_id                     UUID NOT NULL REFERENCES firms(id),
    version_number              INTEGER NOT NULL,
    payload_snapshot            JSONB NOT NULL,
    change_type                 TEXT NOT NULL,
    change_summary              TEXT,
    changed_section_paths       JSONB NOT NULL DEFAULT '[]'::jsonb,
    review_state_at_version     TEXT,
    created_by                  UUID REFERENCES users(id),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT payload_versions_change_type_check CHECK (
        change_type IN ('initial', 'section_deepening', 'manual_edit',
                         'review_revert', 'restore')
    ),
    UNIQUE (session_id, version_number)
);

-- The hot read: "newest versions for this session" (history reader).
CREATE INDEX IF NOT EXISTS idx_payload_versions_session
    ON payload_versions(session_id, version_number DESC);


-- Backfill v1 for every existing session-with-reports row. The
-- snapshot is the flattened "what every other service sees as
-- payload" shape: base reports columns + consulting_payload
-- subkeys merged at the top level. Sessions without a reports row
-- get nothing (no history to baseline).
INSERT INTO payload_versions
    (session_id, firm_id, version_number, payload_snapshot,
     change_type, change_summary, changed_section_paths,
     review_state_at_version, created_by, created_at)
SELECT
    r.session_id,
    s.firm_id,
    1,
    (
      -- Build the flattened payload shape that core.versioning
      -- writes for new versions.
      COALESCE(r.consulting_payload, '{}'::jsonb)
      || jsonb_build_object(
            'recommendation',  r.recommendation,
            'confidence_level', r.confidence_level,
            'summary',         r.summary,
            'key_reasons',     r.key_reasons,
            'risks',           r.risks,
            'counterarguments', r.counterarguments,
            'next_steps',      r.next_steps,
            'sources',         r.sources,
            'caveats',         r.caveats
         )
    ),
    'initial',
    'Backfilled at W19/D1 from the live reports row',
    '[]'::jsonb,
    s.review_state,
    s.created_by_user_id,
    COALESCE(r.created_at, NOW())
  FROM reports r
  JOIN sessions s ON s.id = r.session_id
 WHERE NOT EXISTS (
       SELECT 1 FROM payload_versions pv
        WHERE pv.session_id = r.session_id
   );

COMMIT;
