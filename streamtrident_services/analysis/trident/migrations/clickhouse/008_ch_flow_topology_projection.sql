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
        ORDER BY (session_id, event_time, dst_ip, src_ip, flow_uid)
    );
