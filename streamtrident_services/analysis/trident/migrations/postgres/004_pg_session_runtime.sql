CREATE TABLE IF NOT EXISTS pg_session_runtime (
    session_id VARCHAR(256) PRIMARY KEY,
    runtime_mode VARCHAR(32),
    cold_start_finalized BOOLEAN DEFAULT FALSE,
    cold_start_flow_count BIGINT DEFAULT 0,
    cold_start_windows_processed BIGINT DEFAULT 0,
    cold_start_finalize_reason VARCHAR(32),
    session_baseline_learner VARCHAR(512),
    baseline_learner_names JSONB,
    cold_start_stable_streak BIGINT DEFAULT 0,
    cold_start_finalized_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

