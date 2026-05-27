from __future__ import annotations

from dataclasses import dataclass

from .flow_loader import FlowRecord
from .redis_consumer import RedisStreamMessage


@dataclass(frozen=True, slots=True)
class BufferedFlow:
    message: RedisStreamMessage
    record: FlowRecord


@dataclass(frozen=True, slots=True)
class FlowWindow:
    window_index: int
    items: list[BufferedFlow]


class WindowBuffer:
    def __init__(self, window_size: int) -> None:
        self.window_size = max(1, int(window_size))
        self._items: list[BufferedFlow] = []
        self._window_index = 0

    def add_many(self, items: list[BufferedFlow]) -> list[FlowWindow]:
        windows: list[FlowWindow] = []
        self._items.extend(items)
        while len(self._items) >= self.window_size:
            self._window_index += 1
            window_items = self._items[: self.window_size]
            self._items = self._items[self.window_size :]
            windows.append(FlowWindow(self._window_index, window_items))
        return windows

    def flush(self) -> FlowWindow | None:
        if not self._items:
            return None
        self._window_index += 1
        items = self._items
        self._items = []
        return FlowWindow(self._window_index, items)

    @property
    def current_window_index(self) -> int:
        return self._window_index

    @property
    def buffered_count(self) -> int:
        return len(self._items)
