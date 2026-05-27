from __future__ import annotations

from ..flow_loader import FlowRecord
from ..persistence.ch_flow_repository import AssignmentUpdate, ChFlowRepository
from .online_engine import FlowAssignment


class AssignmentWriter:
    def __init__(self, repository: ChFlowRepository) -> None:
        self.repository = repository

    def write(self, records: list[FlowRecord], assignments: list[FlowAssignment], *, window_index: int) -> int:
        records_by_uid = {record.flow_uid: record for record in records}
        updates = [
            AssignmentUpdate.from_record(records_by_uid[assignment.flow_uid], assignment, window_index=window_index)
            for assignment in assignments
            if assignment.flow_uid in records_by_uid
        ]
        return self.repository.insert_assignments(updates)
