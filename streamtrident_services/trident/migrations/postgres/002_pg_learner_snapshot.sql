CREATE TABLE IF NOT EXISTS pg_learner_snapshot (
    snapshot_id VARCHAR(128) PRIMARY KEY,
    session_id VARCHAR(256) NOT NULL,
    learner_name VARCHAR(512) NOT NULL,
    snapshot_version BIGINT NOT NULL,
    window_index BIGINT,
    snapshot_reason VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    profile_json JSONB,
    metric_json JSONB,
    rule_json JSONB,
    topology_json JSONB,
    risk_score DOUBLE PRECISION,
    risk_band VARCHAR(32),
    risk_reason TEXT,
    threshold DOUBLE PRECISION,
    model_state_hash VARCHAR(128)
);

