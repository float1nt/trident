from __future__ import annotations

from app.flow_loader import FlowLoader
from app.redis_consumer import RedisStreamMessage
from app.window_buffer import BufferedFlow, WindowBuffer


def _item(message_id: str) -> BufferedFlow:
    message = RedisStreamMessage("suricata:cic_flow", message_id, {})
    record = FlowLoader(session_id="s1", feature_profile="compact").load(message)
    return BufferedFlow(message=message, record=record)


def test_window_buffer_emits_fixed_size_windows() -> None:
    buffer = WindowBuffer(window_size=2)

    windows = buffer.add_many([_item("1-0"), _item("2-0"), _item("3-0")])

    assert len(windows) == 1
    assert windows[0].window_index == 1
    assert len(windows[0].items) == 2
    assert buffer.buffered_count == 1


def test_window_buffer_flushes_remainder() -> None:
    buffer = WindowBuffer(window_size=3)
    buffer.add_many([_item("1-0")])

    window = buffer.flush()

    assert window is not None
    assert window.window_index == 1
    assert len(window.items) == 1
    assert buffer.buffered_count == 0
