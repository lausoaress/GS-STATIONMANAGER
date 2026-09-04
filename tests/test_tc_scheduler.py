from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from mgm8.application.pass_scheduler import PassSchedulerService, SchedulePassRequest
from mgm8.application.tc_scheduler import ScheduleTelecommandRequest, TCSchedulerService
from mgm8.domain.services import SchedulingConflictDetector
from mgm8.infrastructure.in_memory import (InMemoryOperationalEventRepository, InMemoryScheduledPassRepository,
                                             InMemoryScheduledTelecommandRepository,
                                             InMemorySchedulingConflictRepository)


def make_services():
    pass_repo = InMemoryScheduledPassRepository()
    events = InMemoryOperationalEventRepository()
    tc_repo = InMemoryScheduledTelecommandRepository()
    passes = PassSchedulerService(pass_repo, InMemorySchedulingConflictRepository(), events, SchedulingConflictDetector())
    tcs = TCSchedulerService(tc_repo, pass_repo, events)
    return passes, tcs, events


def _at(minutes: float) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def test_schedules_standalone_telecommand():
    _, tcs, events = make_services()

    result = tcs.schedule_telecommand(ScheduleTelecommandRequest(uuid4(), _at(30), frame_hex="40 7e 00 ff"))

    assert result.succeeded
    assert result.scheduled_telecommand.frame_hex == "407e00ff"
    assert len(tcs.list_telecommands()) == 1
    assert any(event.category == "tc_scheduling" for event in events.list_recent())


def test_rejects_invalid_frame_hex():
    _, tcs, _ = make_services()

    result = tcs.schedule_telecommand(ScheduleTelecommandRequest(uuid4(), _at(30), frame_hex="zzz"))

    assert not result.succeeded
    assert "hex" in result.reason.lower()
    assert tcs.list_telecommands() == []


def test_rejects_execute_at_outside_linked_pass_window():
    passes, tcs, _ = make_services()
    aos = _at(60)
    scheduled = passes.schedule_pass(SchedulePassRequest(uuid4(), aos, aos + timedelta(minutes=10), 437_000_000))

    result = tcs.schedule_telecommand(ScheduleTelecommandRequest(
        uuid4(), aos + timedelta(minutes=30), scheduled_pass_id=scheduled.scheduled_pass.id,
    ))

    assert not result.succeeded
    assert "outside" in result.reason.lower()


def test_accepts_execute_at_inside_linked_pass_window():
    passes, tcs, _ = make_services()
    aos = _at(60)
    scheduled = passes.schedule_pass(SchedulePassRequest(uuid4(), aos, aos + timedelta(minutes=10), 437_000_000))

    result = tcs.schedule_telecommand(ScheduleTelecommandRequest(
        uuid4(), aos + timedelta(minutes=4), scheduled_pass_id=scheduled.scheduled_pass.id,
    ))

    assert result.succeeded


def test_rejects_second_telecommand_within_guard_interval():
    _, tcs, _ = make_services()
    execute_at = _at(45)
    tcs.schedule_telecommand(ScheduleTelecommandRequest(uuid4(), execute_at))

    result = tcs.schedule_telecommand(ScheduleTelecommandRequest(uuid4(), execute_at + timedelta(seconds=2)))

    assert not result.succeeded
    assert len(result.conflicting_ids) == 1


def test_allows_second_telecommand_outside_guard_interval():
    _, tcs, _ = make_services()
    execute_at = _at(45)
    tcs.schedule_telecommand(ScheduleTelecommandRequest(uuid4(), execute_at))

    result = tcs.schedule_telecommand(ScheduleTelecommandRequest(uuid4(), execute_at + timedelta(seconds=30)))

    assert result.succeeded


def test_approval_workflow_gates_readiness():
    _, tcs, _ = make_services()
    result = tcs.schedule_telecommand(ScheduleTelecommandRequest(uuid4(), _at(-1), requires_approval=True))
    telecommand = result.scheduled_telecommand

    assert not telecommand.is_ready_for_execution
    assert tcs.list_due() == []  # past due, but not approved -> withheld
    assert telecommand in tcs.list_pending_approval()

    tcs.approve_telecommand(telecommand.id, "controller")

    assert telecommand.is_ready_for_execution
    assert telecommand.approved_by == "controller"
    assert tcs.list_due()  # now due and ready


def test_double_approval_is_rejected():
    _, tcs, _ = make_services()
    telecommand = tcs.schedule_telecommand(
        ScheduleTelecommandRequest(uuid4(), _at(5), requires_approval=True)
    ).scheduled_telecommand
    tcs.approve_telecommand(telecommand.id, "controller")

    with pytest.raises(ValueError):
        tcs.approve_telecommand(telecommand.id, "controller")


def test_cancel_telecommand():
    _, tcs, _ = make_services()
    telecommand = tcs.schedule_telecommand(ScheduleTelecommandRequest(uuid4(), _at(20))).scheduled_telecommand

    tcs.cancel_telecommand(telecommand.id)

    assert tcs.get_telecommand(telecommand.id).status.value == "Cancelled"
    assert tcs.list_due() == []


def test_cancel_missing_telecommand_raises_lookup_error():
    _, tcs, _ = make_services()

    with pytest.raises(LookupError):
        tcs.cancel_telecommand(uuid4())


def test_list_due_excludes_future_and_unapproved():
    _, tcs, _ = make_services()
    tcs.schedule_telecommand(ScheduleTelecommandRequest(uuid4(), _at(-1)))            # past, ready
    tcs.schedule_telecommand(ScheduleTelecommandRequest(uuid4(), _at(120)))           # future
    tcs.schedule_telecommand(ScheduleTelecommandRequest(uuid4(), _at(-2), requires_approval=True))  # past, unapproved

    due = tcs.list_due()

    assert len(due) == 1
