-- Initial schema for radar-analyst. All tables live in the `radar`
-- schema so the service can share a Postgres instance with other
-- tools without colliding on names. Application code fully
-- qualifies table references.

CREATE TABLE radar.uploads (
    id UUID PRIMARY KEY,
    filename TEXT NOT NULL,
    storage_url TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    sha256 TEXT NOT NULL,
    hostname TEXT,
    archive_timestamp TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE radar.jobs (
    id UUID PRIMARY KEY,
    upload_id UUID NOT NULL
        REFERENCES radar.uploads(id) ON DELETE CASCADE,
    state TEXT NOT NULL,
    phase TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error TEXT,
    ai_provider TEXT
);

CREATE TABLE radar.snapshots (
    upload_id UUID PRIMARY KEY
        REFERENCES radar.uploads(id) ON DELETE CASCADE,
    data JSONB NOT NULL
);

CREATE TABLE radar.findings (
    id UUID PRIMARY KEY,
    upload_id UUID NOT NULL
        REFERENCES radar.uploads(id) ON DELETE CASCADE,
    rule_id TEXT NOT NULL,
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT,
    evidence JSONB
);
CREATE INDEX findings_upload_severity
    ON radar.findings (upload_id, severity);
CREATE INDEX findings_upload_category
    ON radar.findings (upload_id, category);

CREATE TABLE radar.briefs (
    id UUID PRIMARY KEY,
    upload_id UUID NOT NULL
        REFERENCES radar.uploads(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    verdict TEXT,
    markdown TEXT NOT NULL,
    prompt_tokens INT,
    completion_tokens INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX briefs_upload_category
    ON radar.briefs (upload_id, category);
