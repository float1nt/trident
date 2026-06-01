ALTER TABLE ch_flow
    MODIFY TTL toDateTime(event_time) + INTERVAL 30 DAY DELETE;
