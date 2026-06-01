from __future__ import annotations

from collections.abc import Callable

from ..flow_loader import FlowRecord
from ..persistence.ch_flow_repository import AssignmentUpdate, ChFlowRepository
from .online_engine import FlowAssignment


class AssignmentWriter:
    def __init__(self, repository: ChFlowRepository) -> None:
        self.repository = repository

    def write(
        self,
        records: list[FlowRecord],
        assignments: list[FlowAssignment],
        *,
        window_index: int,
        should_keep_payload: Callable[[FlowAssignment], bool] | None = None,
    ) -> int:
        records_by_uid = {record.flow_uid: record for record in records}
        updates: list[AssignmentUpdate] = []
        for assignment in assignments:
            record = records_by_uid.get(assignment.flow_uid)
            if record is None:
                continue
            if should_keep_payload is not None and not should_keep_payload(assignment):
                record = record.without_payload()
            updates.append(AssignmentUpdate.from_record(record, assignment, window_index=window_index))
        return self.repository.insert_assignments(updates)
