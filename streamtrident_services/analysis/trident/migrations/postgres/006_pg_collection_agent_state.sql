CREATE TABLE IF NOT EXISTS pg_collection_agent_state (
    session_id VARCHAR(256) NOT NULL,
    agent_name VARCHAR(256) NOT NULL,
    agent_url TEXT NOT NULL,
    reachable BOOLEAN NOT NULL DEFAULT FALSE,
    effective BOOLEAN NOT NULL DEFAULT FALSE,
    desired_revision BIGINT,
    effective_revision BIGINT,
    status_json JSONB,
    last_error TEXT,
    sampled_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (session_id, agent_name)
);
