ALTER TABLE ch_flow
    ADD COLUMN IF NOT EXISTS app_proto LowCardinality(String) DEFAULT 'unknown' AFTER protocol,
    ADD COLUMN IF NOT EXISTS total_bytes UInt64 DEFAULT 0 AFTER app_proto,
    ADD COLUMN IF NOT EXISTS payload_sample_b64 String DEFAULT '' AFTER source_flow_id,
    ADD COLUMN IF NOT EXISTS payload_sample_bytes UInt32 DEFAULT 0 AFTER payload_sample_b64,
    ADD COLUMN IF NOT EXISTS payload_original_bytes UInt64 DEFAULT 0 AFTER payload_sample_bytes,
    ADD COLUMN IF NOT EXISTS payload_truncated UInt8 DEFAULT 0 AFTER payload_original_bytes,
    ADD COLUMN IF NOT EXISTS payload_direction LowCardinality(String) DEFAULT '' AFTER payload_truncated,
    DROP COLUMN IF EXISTS raw_event,
    MODIFY TTL toDateTime(event_time) + INTERVAL 30 DAY DELETE,
    MODIFY SETTING deduplicate_merge_projection_mode = 'rebuild';

ALTER TABLE ch_flow
    ADD PROJECTION IF NOT EXISTS p_topology_host
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
    );

ALTER TABLE ch_flow
    ADD PROJECTION IF NOT EXISTS p_topology_endpoint_pair
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
    );

ALTER TABLE ch_flow MATERIALIZE PROJECTION IF EXISTS p_topology_host;

ALTER TABLE ch_flow MATERIALIZE PROJECTION IF EXISTS p_topology_endpoint_pair;
