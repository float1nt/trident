ALTER TABLE ch_flow
    ADD COLUMN IF NOT EXISTS app_proto LowCardinality(String) DEFAULT 'unknown' AFTER protocol;
