ALTER TABLE ch_flow
    ADD COLUMN IF NOT EXISTS payload_sample_b64 String DEFAULT '' AFTER source_flow_id,
    ADD COLUMN IF NOT EXISTS payload_sample_bytes UInt32 DEFAULT 0 AFTER payload_sample_b64,
    ADD COLUMN IF NOT EXISTS payload_original_bytes UInt64 DEFAULT 0 AFTER payload_sample_bytes,
    ADD COLUMN IF NOT EXISTS payload_truncated UInt8 DEFAULT 0 AFTER payload_original_bytes,
    ADD COLUMN IF NOT EXISTS payload_direction LowCardinality(String) DEFAULT '' AFTER payload_truncated;
