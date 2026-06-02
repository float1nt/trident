ALTER TABLE pg_collection_settings
    ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL DEFAULT 1;

ALTER TABLE pg_collection_settings
    ADD COLUMN IF NOT EXISTS last_apply_json JSONB;

ALTER TABLE pg_collection_settings
    ADD COLUMN IF NOT EXISTS last_apply_at TIMESTAMPTZ;
