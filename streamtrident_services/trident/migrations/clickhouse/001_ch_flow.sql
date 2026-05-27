CREATE TABLE IF NOT EXISTS ch_flow (
    session_id String,
    flow_uid String,
    event_time DateTime64(3),
    ingest_time DateTime64(3) DEFAULT now64(3),
    src_ip String,
    dst_ip String,
    src_port UInt16,
    dst_port UInt16,
    protocol UInt16,
    feature_profile LowCardinality(String) DEFAULT 'compact_stats_no_env',
    features_json String DEFAULT '{}',
    assigned_learner String DEFAULT '',
    is_unknown UInt8 DEFAULT 0,
    window_index UInt64,
    pred_loss Nullable(Float64),
    threshold Nullable(Float64),
    assignment_meta String DEFAULT '',
    learner_snapshot_id String DEFAULT '',
    learner_snapshot_version UInt64 DEFAULT 0,
    mq_type LowCardinality(String),
    mq_topic String,
    mq_message_id String,
    source_flow_id String DEFAULT '',
    raw_event String DEFAULT '',
    record_version UInt64,
    record_stage LowCardinality(String) DEFAULT 'ingested'
)
ENGINE = ReplacingMergeTree(record_version)
PARTITION BY toYYYYMM(event_time)
ORDER BY (session_id, flow_uid);
