from datetime import datetime, timedelta, timezone
from uuid import uuid4

from mgm8.application.pass_scheduler import PassSchedulerService, SchedulePassRequest
from mgm8.domain.services import SchedulingConflictDetector
from mgm8.infrastructure.in_memory import (InMemoryOperationalEventRepository, InMemoryScheduledPassRepository,
                                             InMemorySchedulingConflictRepository)


def make_service():
    passes = InMemoryScheduledPassRepository()
    conflicts = InMemorySchedulingConflictRepository()
    events = InMemoryOperationalEventRepository()
    return PassSchedulerService(passes, conflicts, events, SchedulingConflictDetector()), conflicts, events


def test_schedules_pass_when_rf_window_is_available():
    service, _, events = make_service()
    aos = datetime.now(timezone.utc) + timedelta(hours=1)

    result = service.schedule_pass(SchedulePassRequest(uuid4(), aos, aos + timedelta(minutes=8), 437_200_000, created_by="operator"))

    assert result.succeeded
    assert result.scheduled_pass is not None
    assert result.conflicts == []
    assert len(events.events) == 1


def test_rejects_overlapping_pass_and_records_conflict():
    service, conflicts, _ = make_service()
    aos = datetime.now(timezone.utc) + timedelta(hours=1)
    service.schedule_pass(SchedulePassRequest(uuid4(), aos, aos + timedelta(minutes=10), 437_200_000))

    result = service.schedule_pass(SchedulePassRequest(uuid4(), aos + timedelta(minutes=5), aos + timedelta(minutes=15), 437_300_000))

    assert not result.succeeded
    assert len(result.conflicts) == 1
    assert len(conflicts.conflicts) == 1
