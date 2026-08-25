-- Persist the per-upload archive inventory so the API can list and
-- serve individual files from the original radar zip without
-- re-walking the blob on every request. Populated by the
-- orchestrator after walk(); shape:
--   [
--     {"path": "...", "kind": "...", "dbname": "..."|null,
--      "size": 12345},
--     ...
--   ]
-- Unknown (coverage-canary) paths are stored with kind = null.
ALTER TABLE radar.uploads
    ADD COLUMN archive_files JSONB;
