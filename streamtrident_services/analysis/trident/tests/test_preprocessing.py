from __future__ import annotations

import json

from app.flow_loader import FlowLoader
from app.redis_consumer import RedisStreamMessage
from app.runtime.preprocessing import preprocess_records


def test_preprocessing_applies_missing_flags_and_compact_profile() -> None:
    message = RedisStreamMessage(
        "suricata:cic_flow",
        "1-0",
        {
            "protocol": "UDP",
            "features_json": json.dumps(
                {
                    "Flow Bytes/s": "Infinity",
                    "FWD Init Win Bytes": -1,
                    "Bwd Header Length": 42,
                    "ignored": 123,
                }
            ),
        },
    )
    record = FlowLoader(session_id="s1", feature_profile="compact_stats_no_env").load(message)

    rows, report = preprocess_records([record], feature_profile="compact_stats_no_env")

    features = json.loads(rows[0].features_json)
    assert features["Flow Bytes/s"] == 0.0
    assert features["flow_bytes_s_missing_flag"] == 1.0
    assert features["FWD Init Win Bytes"] == 0.0
    assert features["Bwd Header Length"] == 42.0
    assert "ignored" not in features
    assert report["rules"]["is_non_tcp"] == 1


def test_preprocessing_can_drop_all_zero_rows() -> None:
    message = RedisStreamMessage("suricata:cic_flow", "1-0", {"features_json": "{}"})
    record = FlowLoader(session_id="s1", feature_profile="compact_stats_no_env").load(message)

    rows, report = preprocess_records([record], feature_profile="compact_stats_no_env", drop_all_zero=True)

    assert rows == []
    assert report["dropped_rows"] == 1
