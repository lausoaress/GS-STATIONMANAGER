from datetime import datetime
from uuid import UUID

from mgm8.domain.models import OperationalEvent, ScheduledPass, SchedulingConflict


class InMemoryScheduledPassRepository:
    def __init__(self) -> None:
        self.passes: dict[UUID, ScheduledPass] = {}

    def get_by_id(self, pass_id: UUID) -> ScheduledPass | None:
        return self.passes.get(pass_id)

    def get_active_in_window(self, start: datetime, end: datetime) -> list[ScheduledPass]:
        return [
            item for item in self.passes.values()
            if item.is_active_for_scheduling and item.window.aos < end and start < item.window.los
        ]

    def get_due(self, as_of: datetime) -> list[ScheduledPass]:
        return sorted((item for item in self.passes.values() if item.status.value == "Scheduled"
                       and item.auto_execute and item.window.aos <= as_of < item.window.los), key=lambda item: item.window.aos)

    def add(self, scheduled_pass: ScheduledPass) -> None:
        self.passes[scheduled_pass.id] = scheduled_pass

    def list_all(self) -> list[ScheduledPass]:
        return sorted(self.passes.values(), key=lambda item: item.window.aos, reverse=True)

    def update(self, scheduled_pass: ScheduledPass) -> None:
        if scheduled_pass.id not in self.passes:
            raise KeyError(f"Pass {scheduled_pass.id} not found.")
        self.passes[scheduled_pass.id] = scheduled_pass


class InMemorySchedulingConflictRepository:
    def __init__(self) -> None:
        self.conflicts: list[SchedulingConflict] = []

    def add(self, conflict: SchedulingConflict) -> None:
        self.conflicts.append(conflict)

    def list_recent(self, limit: int = 20) -> list[SchedulingConflict]:
        return sorted(self.conflicts, key=lambda item: item.detected_at, reverse=True)[:limit]


class InMemoryOperationalEventRepository:
    def __init__(self) -> None:
        self.events: list[OperationalEvent] = []

    def add(self, event: OperationalEvent) -> None:
        self.events.append(event)

    def list_recent(self, limit: int = 50) -> list[OperationalEvent]:
        return sorted(self.events, key=lambda item: item.occurred_at, reverse=True)[:limit]
