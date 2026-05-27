ALTER TABLE ch_flow
    ADD COLUMN IF NOT EXISTS total_bytes UInt64 DEFAULT 0 AFTER app_proto;
