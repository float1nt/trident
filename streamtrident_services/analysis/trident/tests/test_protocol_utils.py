from __future__ import annotations

from app.page_queries import _traffic_log_item
from app.protocol_utils import (
    is_meaningful_app_proto,
    main_protocol_sql,
    resolve_flow_protocol_from_row,
    resolve_flow_protocol_name,
    transport_protocol_name,
)


def test_is_meaningful_app_proto_rejects_placeholders() -> None:
    assert is_meaningful_app_proto("unknown") is False
    assert is_meaningful_app_proto("NONE") is False
    assert is_meaningful_app_proto("-") is False
    assert is_meaningful_app_proto("") is False
    assert is_meaningful_app_proto("tls") is True


def test_resolve_flow_protocol_name_prefers_app_proto_then_transport() -> None:
    assert resolve_flow_protocol_name(app_proto="tls", protocol=6) == "TLS"
    assert resolve_flow_protocol_name(app_proto="unknown", protocol=6) == "TCP"
    assert resolve_flow_protocol_name(app_proto="", protocol=17) == "UDP"
    assert resolve_flow_protocol_name(app_proto=None, protocol=1) == "ICMP"


def test_transport_protocol_name_maps_tcp_udp() -> None:
    assert transport_protocol_name(6) == "TCP"
    assert transport_protocol_name(17) == "UDP"


def test_traffic_log_item_resolves_tcp_from_numeric_protocol() -> None:
    item = _traffic_log_item(
        {
            "flow_uid": "f1",
            "src_ip": "10.0.0.1",
            "dst_ip": "10.0.0.2",
            "src_port": 1234,
            "dst_port": 80,
            "event_time": "2026-05-27 10:00:00",
            "total_bytes": 100,
            "app_proto": "unknown",
            "protocol": 6,
        }
    )

    assert item["protocol"] == "TCP"


def test_main_protocol_sql_falls_back_when_app_proto_is_unknown() -> None:
    sql = main_protocol_sql()
    assert "lower(app_proto) NOT IN ('unknown'" in sql
    assert "protocol = 6, 'TCP'" in sql
