CREATE TABLE IF NOT EXISTS pg_collection_settings (
    session_id VARCHAR(256) PRIMARY KEY,
    settings_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
