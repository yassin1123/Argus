-- Phase 4: chunk-level data model.
-- Every citation should reference a chunk with rich metadata (page, slide,
-- timestamp, section_heading), not a coarse evidence_object.
--
-- Strategy: introduce `chunks` as the new home for ingestion. Phase 6 (hybrid
-- retrieval) and Phase 7 (writer rewrite) will migrate the pipeline to read
-- from this table. For now, ingestion dual-writes (chunks + legacy embeddings).

CREATE TABLE IF NOT EXISTS chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    blob_id         UUID REFERENCES source_blobs(id) ON DELETE SET NULL,
    source_file_id  UUID REFERENCES uploaded_files(id) ON DELETE SET NULL,

    -- Plain content + sha256 hash for dedupe.
    content         TEXT NOT NULL,
    content_hash    CHAR(64) NOT NULL,

    -- Embedding (1536-dim for text-embedding-3-small).
    embedding       vector(1536),

    -- Source type drives which chunker produced this chunk.
    source_type     TEXT NOT NULL DEFAULT 'web',  -- pdf | transcript | web | csv | json | knowledge

    -- Order within the source (0-indexed).
    position        INT NOT NULL DEFAULT 0,

    -- Type-specific location metadata (nullable: only one of these is set per chunk).
    page            INT,                  -- pdf: 1-indexed page
    slide           INT,                  -- deck: 1-indexed slide
    timestamp_str   TEXT,                 -- transcript: "[00:12:34]" or speaker timecode
    speaker         TEXT,                 -- transcript: "Speaker A"
    section_heading TEXT,                 -- pdf/web: nearest heading text

    -- Display labels: filename and url for the source.
    source_filename TEXT NOT NULL DEFAULT '',
    source_url      TEXT,

    -- Trust tier (Phase 5 lets the user override; default inferred from source_type).
    trust_level     TEXT NOT NULL DEFAULT 'web_general',

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunks_session            ON chunks(session_id);
CREATE INDEX IF NOT EXISTS idx_chunks_session_source     ON chunks(session_id, source_file_id);
CREATE INDEX IF NOT EXISTS idx_chunks_session_page       ON chunks(session_id, page);
CREATE INDEX IF NOT EXISTS idx_chunks_content_hash       ON chunks(content_hash);
-- Vector index will be added in Phase 6 once we have meaningful row counts:
-- CREATE INDEX idx_chunks_embedding ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
