"""Schedule and manage telecommand transmissions.

The MGM8 treats the telecommand payload as **opaque**: it stores the encoded
frame (``frame_hex``) and a reference to the definition, but never interprets
the command semantics -- that belongs to the TC Generator / ``mission_control``.
Validation here is structural and operational only:

* the frame, if given, must be valid hexadecimal within a size limit;
* a telecommand bound to a pass must fire inside that pass window;
* two telecommands may not transmit within a short guard interval of each other.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from mgm8.domain.models import (
    EventSeverity,
    OperationalEvent,
    ScheduleStatus,
    ScheduledTelecommand,
    utc_now,
)
from mgm8.domain.ports import (
    OperationalEventRepository,
    ScheduledPassRepository,
    ScheduledTelecommandRepository,
)

MAX_FRAME_BYTES = 4096


@dataclass(frozen=True)
class ScheduleTelecommandRequest:
    telecommand_definition_id: UUID
    execute_at: datetime
    scheduled_pass_id: UUID | None = None
    parameters: dict[str, object] = field(default_factory=dict)
    frame_hex: str | None = None
    priority: int = 5
    requires_approval: bool = False
    created_by: str | None = None
    guard_interval_seconds: float = 5.0


@dataclass(frozen=True)
class ScheduleTelecommandResult:
    succeeded: bool
    scheduled_telecommand: ScheduledTelecommand | None = None
    reason: str | None = None
    conflicting_ids: list[UUID] = field(default_factory=list)


def _normalize_frame_hex(frame_hex: str | None) -> str | None:
    if frame_hex is None:
        return None
    cleaned = frame_hex.strip().replace(" ", "").replace(":", "").lower()
    if not cleaned:
        return None
    if len(cleaned) % 2 != 0:
        raise ValueError("frame_hex must have an even number of hex digits.")
    try:
        bytes.fromhex(cleaned)
    except ValueError as error:
        raise ValueError("frame_hex is not valid hexadecimal.") from error
    if len(cleaned) // 2 > MAX_FRAME_BYTES:
        raise ValueError(f"frame_hex exceeds the {MAX_FRAME_BYTES}-byte limit.")
    return cleaned


class TCSchedulerService:
    def __init__(
        self,
        telecommand_repository: ScheduledTelecommandRepository,
        pass_repository: ScheduledPassRepository,
        event_repository: OperationalEventRepository,
    ) -> None:
        self.telecommand_repository = telecommand_repository
        self.pass_repository = pass_repository
        self.event_repository = event_repository

    def schedule_telecommand(self, request: ScheduleTelecommandRequest) -> ScheduleTelecommandResult:
        try:
            frame_hex = _normalize_frame_hex(request.frame_hex)
        except ValueError as error:
            return ScheduleTelecommandResult(False, reason=str(error))

        if request.priority < 1 or request.priority > 9:
            return ScheduleTelecommandResult(False, reason="priority must be between 1 and 9.")

        window_error = self._check_pass_window(request)
        if window_error is not None:
            return ScheduleTelecommandResult(False, reason=window_error)

        guard = timedelta(seconds=request.guard_interval_seconds)
        neighbours = self.telecommand_repository.list_active_between(
            request.execute_at - guard, request.execute_at + guard
        )
        if neighbours:
            conflicting_ids = [item.id for item in neighbours]
            self.event_repository.add(OperationalEvent(
                EventSeverity.WARNING, "tc_scheduling",
                "Telecommand scheduling rejected: another transmission is within the guard interval.",
                None, request.scheduled_pass_id,
                {"conflicting_ids": [str(item) for item in conflicting_ids],
                 "guard_interval_seconds": request.guard_interval_seconds},
            ))
            return ScheduleTelecommandResult(
                False, reason="Another telecommand is scheduled within the guard interval.",
                conflicting_ids=conflicting_ids,
            )

        telecommand = ScheduledTelecommand(
            telecommand_definition_id=request.telecommand_definition_id,
            execute_at=request.execute_at,
            scheduled_pass_id=request.scheduled_pass_id,
            parameters=dict(request.parameters),
            frame_hex=frame_hex,
            priority=request.priority,
            requires_approval=request.requires_approval,
            created_by=request.created_by,
        )
        self.telecommand_repository.add(telecommand)
        self.event_repository.add(OperationalEvent(
            EventSeverity.INFO, "tc_scheduling", "Telecommand transmission scheduled.",
            None, telecommand.scheduled_pass_id,
            {"telecommand_id": str(telecommand.id),
             "definition_id": str(telecommand.telecommand_definition_id),
             "execute_at": telecommand.execute_at.isoformat(),
             "requires_approval": telecommand.requires_approval,
             "frame_bytes": len(frame_hex) // 2 if frame_hex else 0},
        ))
        return ScheduleTelecommandResult(True, telecommand)

    def _check_pass_window(self, request: ScheduleTelecommandRequest) -> str | None:
        if request.scheduled_pass_id is None:
            return None
        scheduled_pass = self.pass_repository.get_by_id(request.scheduled_pass_id)
        if scheduled_pass is None:
            return f"Pass {request.scheduled_pass_id} not found."
        if not scheduled_pass.is_active_for_scheduling:
            return f"Pass {request.scheduled_pass_id} is not active for scheduling."
        if not scheduled_pass.window.aos <= request.execute_at <= scheduled_pass.window.los:
            return "execute_at is outside the linked pass window."
        return None

    def list_telecommands(self) -> list[ScheduledTelecommand]:
        return self.telecommand_repository.list_all()

    def list_for_pass(self, scheduled_pass_id: UUID) -> list[ScheduledTelecommand]:
        return self.telecommand_repository.list_for_pass(scheduled_pass_id)

    def get_telecommand(self, telecommand_id: UUID) -> ScheduledTelecommand | None:
        return self.telecommand_repository.get_by_id(telecommand_id)

    def cancel_telecommand(self, telecommand_id: UUID) -> ScheduledTelecommand:
        telecommand = self._require(telecommand_id)
        telecommand.cancel()
        self.telecommand_repository.update(telecommand)
        self.event_repository.add(OperationalEvent(
            EventSeverity.INFO, "tc_scheduling", "Telecommand transmission cancelled.",
            None, telecommand.scheduled_pass_id,
            {"telecommand_id": str(telecommand.id), "status": telecommand.status.value},
        ))
        return telecommand

    def approve_telecommand(self, telecommand_id: UUID, approved_by: str) -> ScheduledTelecommand:
        telecommand = self._require(telecommand_id)
        telecommand.approve(approved_by)
        self.telecommand_repository.update(telecommand)
        self.event_repository.add(OperationalEvent(
            EventSeverity.INFO, "tc_scheduling", "Telecommand transmission approved.",
            None, telecommand.scheduled_pass_id,
            {"telecommand_id": str(telecommand.id), "approved_by": telecommand.approved_by},
        ))
        return telecommand

    def list_due(self, as_of: datetime | None = None) -> list[ScheduledTelecommand]:
        moment = as_of or utc_now()
        return [
            item for item in self.telecommand_repository.get_due(moment)
            if item.is_ready_for_execution
        ]

    def list_pending_approval(self) -> list[ScheduledTelecommand]:
        return [
            item for item in self.telecommand_repository.list_all()
            if item.status is ScheduleStatus.SCHEDULED and item.requires_approval and item.approved_at is None
        ]

    def _require(self, telecommand_id: UUID) -> ScheduledTelecommand:
        telecommand = self.telecommand_repository.get_by_id(telecommand_id)
        if telecommand is None:
            raise LookupError(f"Telecommand {telecommand_id} not found.")
        return telecommand

    @staticmethod
    def telecommand_to_dict(telecommand: ScheduledTelecommand) -> dict[str, object]:
        return {
            "id": str(telecommand.id),
            "telecommand_definition_id": str(telecommand.telecommand_definition_id),
            "scheduled_pass_id": str(telecommand.scheduled_pass_id) if telecommand.scheduled_pass_id else None,
            "execute_at": telecommand.execute_at.isoformat(),
            "status": telecommand.status.value,
            "priority": telecommand.priority,
            "requires_approval": telecommand.requires_approval,
            "approved_by": telecommand.approved_by,
            "approved_at": telecommand.approved_at.isoformat() if telecommand.approved_at else None,
            "is_ready_for_execution": telecommand.is_ready_for_execution,
            "parameters": telecommand.parameters,
            "frame_bytes": len(telecommand.frame_hex) // 2 if telecommand.frame_hex else 0,
            "created_by": telecommand.created_by,
            "created_at": telecommand.created_at.isoformat(),
            "updated_at": telecommand.updated_at.isoformat(),
        }
