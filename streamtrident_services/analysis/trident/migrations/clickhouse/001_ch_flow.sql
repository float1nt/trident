CREATE TABLE IF NOT EXISTS ch_flow (
    session_id String,
    flow_uid String,
    event_time DateTime64(3, 'UTC'),
    ingest_time DateTime64(3, 'UTC') DEFAULT now64(3, 'UTC'),
    src_ip String,
    dst_ip String,
    src_port UInt16,
    dst_port UInt16,
    protocol UInt16,
    app_proto LowCardinality(String) DEFAULT 'unknown',
    total_bytes UInt64 DEFAULT 0,
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
    payload_sample_b64 String DEFAULT '',
    payload_sample_bytes UInt32 DEFAULT 0,
    payload_original_bytes UInt64 DEFAULT 0,
    payload_truncated UInt8 DEFAULT 0,
    payload_direction LowCardinality(String) DEFAULT '',
    record_version UInt64,
    record_stage LowCardinality(String) DEFAULT 'ingested',
    PROJECTION p_topology_host
    (
        SELECT
            session_id,
            flow_uid,
            event_time,
            assigned_learner,
            src_ip,
            dst_ip,
            src_port,
            dst_port,
            protocol,
            app_proto,
            total_bytes,
            record_version
        ORDER BY (session_id, dst_ip, src_ip, event_time, flow_uid)
    ),
    PROJECTION p_topology_endpoint_pair
    (
        SELECT
            session_id,
            flow_uid,
            event_time,
            assigned_learner,
            src_ip,
            dst_ip,
            src_port,
            dst_port,
            protocol,
            app_proto,
            total_bytes,
            record_version
        ORDER BY (session_id, dst_ip, src_ip, event_time, dst_port, src_port, flow_uid)
    )
)
ENGINE = ReplacingMergeTree(record_version)
PARTITION BY toYYYYMM(event_time)
ORDER BY (session_id, flow_uid)
TTL toDateTime(event_time) + INTERVAL 30 DAY DELETE
SETTINGS deduplicate_merge_projection_mode = 'rebuild';
