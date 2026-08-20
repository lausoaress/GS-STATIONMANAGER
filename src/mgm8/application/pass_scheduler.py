from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from mgm8.domain.models import EventSeverity, FrequencyTune, OperationalEvent, PassWindow, ScheduleStatus, ScheduledPass, SchedulingConflict, SchedulingResource
from mgm8.domain.ports import OperationalEventRepository, ScheduledPassRepository, SchedulingConflictRepository
from mgm8.domain.services import SchedulingConflictDetector


@dataclass(frozen=True)
class SchedulePassRequest:
    satellite_id: UUID
    aos: datetime
    los: datetime
    center_frequency_hz: int
    doppler_source: str | None = None
    max_elevation_degrees: float | None = None
    auto_execute: bool = True
    notes: str | None = None
    created_by: str | None = None


@dataclass(frozen=True)
class SchedulePassResult:
    succeeded: bool
    scheduled_pass: ScheduledPass | None = None
    conflicts: list[SchedulingConflict] = field(default_factory=list)


class PassSchedulerService:
    def __init__(self, pass_repository: ScheduledPassRepository, conflict_repository: SchedulingConflictRepository,
                 event_repository: OperationalEventRepository, conflict_detector: SchedulingConflictDetector) -> None:
        self.pass_repository = pass_repository
        self.conflict_repository = conflict_repository
        self.event_repository = event_repository
        self.conflict_detector = conflict_detector

    def schedule_pass(self, request: SchedulePassRequest) -> SchedulePassResult:
        window = PassWindow(request.aos, request.los)
        frequency = FrequencyTune(request.center_frequency_hz, request.doppler_source or "propagator")
        candidate = ScheduledPass(request.satellite_id, window, frequency, request.created_by, request.auto_execute,
                                  request.max_elevation_degrees, request.notes)
        existing = self.pass_repository.get_active_in_window(window.aos, window.los)
        resource = SchedulingResource.rf_chain_default()
        conflicts = self.conflict_detector.detect_conflicts(candidate, existing, resource)

        if conflicts:
            for conflict in conflicts:
                self.conflict_repository.add(conflict)
            self.event_repository.add(OperationalEvent(EventSeverity.WARNING, "scheduling",
                "Pass scheduling rejected due to RF resource conflict.", request.satellite_id, candidate.id,
                {"conflict_count": len(conflicts), "resource": resource.name}))
            return SchedulePassResult(False, conflicts=conflicts)

        self.pass_repository.add(candidate)
        self.event_repository.add(OperationalEvent(EventSeverity.INFO, "scheduling", "Satellite pass scheduled.",
            request.satellite_id, candidate.id, {"aos": window.aos.isoformat(), "los": window.los.isoformat(),
            "frequency_hz": frequency.center_frequency_hz}))
        return SchedulePassResult(True, candidate)

    def list_passes(self) -> list[ScheduledPass]:
        return self.pass_repository.list_all()

    def get_pass(self, pass_id: UUID) -> ScheduledPass | None:
        return self.pass_repository.get_by_id(pass_id)

    def cancel_pass(self, pass_id: UUID) -> ScheduledPass:
        scheduled_pass = self.pass_repository.get_by_id(pass_id)
        if scheduled_pass is None:
            raise LookupError(f"Pass {pass_id} not found.")
        scheduled_pass.cancel()
        self.pass_repository.update(scheduled_pass)
        self.event_repository.add(OperationalEvent(
            EventSeverity.INFO, "scheduling", "Satellite pass cancelled.",
            scheduled_pass.satellite_id, scheduled_pass.id,
            {"status": scheduled_pass.status.value},
        ))
        return scheduled_pass

    def list_events(self, limit: int = 50) -> list[OperationalEvent]:
        return self.event_repository.list_recent(limit)

    def list_conflicts(self, limit: int = 20) -> list[SchedulingConflict]:
        return self.conflict_repository.list_recent(limit)

    @staticmethod
    def pass_to_dict(scheduled_pass: ScheduledPass) -> dict[str, object]:
        return {
            "id": str(scheduled_pass.id),
            "satellite_id": str(scheduled_pass.satellite_id),
            "status": scheduled_pass.status.value,
            "aos": scheduled_pass.window.aos.isoformat(),
            "los": scheduled_pass.window.los.isoformat(),
            "center_frequency_hz": scheduled_pass.frequency.center_frequency_hz,
            "doppler_source": scheduled_pass.frequency.doppler_source,
            "auto_execute": scheduled_pass.auto_execute,
            "max_elevation_degrees": scheduled_pass.max_elevation_degrees,
            "notes": scheduled_pass.notes,
            "created_by": scheduled_pass.created_by,
            "created_at": scheduled_pass.created_at.isoformat(),
            "updated_at": scheduled_pass.updated_at.isoformat(),
        }
