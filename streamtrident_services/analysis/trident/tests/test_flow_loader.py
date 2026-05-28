from __future__ import annotations

import json

from app.flow_loader import FlowLoader
from app.redis_consumer import RedisStreamMessage


def test_loads_redis_fields_to_normalized_flow() -> None:
    loader = FlowLoader(session_id="s1", feature_profile="compact")
    message = RedisStreamMessage(
        stream="suricata:cic_flow",
        message_id="1710000000123-0",
        fields={
            "event_time": "2026-05-26T10:00:00Z",
            "src_ip": "10.0.0.1",
            "dst_ip": "10.0.0.2",
            "src_port": "12345",
            "dst_port": "443",
            "protocol": "TCP",
            "app_proto": "tls",
            "total_bytes": "1234",
            "features_json": "{\"bytes\":100}",
            "raw_event_json": "{\"source\":\"unit\"}",
        },
    )

    record = loader.load(message)

    assert record.flow_uid == "suricata:cic_flow:1710000000123-0"
    assert record.src_port == 12345
    assert record.dst_port == 443
    assert record.protocol == 6
    assert record.app_proto == "tls"
    assert record.total_bytes == 1234
    assert json.loads(record.features_json) == {"bytes": 100}
    assert record.record_version == 1710000000123
    assert record.to_clickhouse_row()["event_time"] == "2026-05-26 10:00:00.000"
    assert record.to_clickhouse_row()["app_proto"] == "tls"
    assert record.to_clickhouse_row()["total_bytes"] == 1234


def test_bad_features_json_falls_back_to_empty_object() -> None:
    loader = FlowLoader(session_id="s1", feature_profile="compact")
    message = RedisStreamMessage(
        stream="suricata:cic_flow",
        message_id="1710000000123-1",
        fields={"features_json": "{bad"},
    )

    record = loader.load(message)

    assert json.loads(record.features_json) == {}
    assert record.src_port == 0
    assert record.dst_port == 0
    assert record.app_proto == ""
    assert record.total_bytes == 0


def test_total_bytes_falls_back_to_cic_lengths() -> None:
    loader = FlowLoader(session_id="s1", feature_profile="compact")
    message = RedisStreamMessage(
        stream="suricata:cic_flow",
        message_id="1710000000123-2",
        fields={
            "raw_event_json": json.dumps(
                {
                    "cic": {
                        "totlen_fwd_pkts": 400,
                        "totlen_bwd_pkts": 600,
                    }
                }
            )
        },
    )

    record = loader.load(message)

    assert record.total_bytes == 1000


def test_total_bytes_falls_back_to_feature_bytes() -> None:
    loader = FlowLoader(session_id="s1", feature_profile="compact")
    message = RedisStreamMessage(
        stream="suricata:cic_flow",
        message_id="1710000000123-3",
        fields={"features_json": "{\"bytes\":100}"},
    )

    record = loader.load(message)

    assert record.total_bytes == 100
