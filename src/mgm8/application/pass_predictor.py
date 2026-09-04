"""Discover upcoming satellite passes from a TLE and feed them into scheduling.

The propagator is the station's own tracker (SGP4), so autonomous operation no
longer depends on an operator driving GPredict. Discovered passes are scheduled
through :class:`PassSchedulerService`, reusing its RF-conflict detection.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from mgm8.application.pass_scheduler import PassSchedulerService, SchedulePassRequest
from mgm8.domain.models import (
    EventSeverity,
    GroundStationLocation,
    OperationalEvent,
    PassPrediction,
    ScheduledPass,
    SchedulingConflict,
    TLE,
    utc_now,
)
from mgm8.domain.ports import OperationalEventRepository, Propagator

SCHEDULED = "scheduled"
CONFLICT = "conflict"
DUPLICATE = "duplicate"


@dataclass(frozen=True)
class DiscoverPassesRequest:
    satellite_id: UUID
    tle: TLE
    center_frequency_hz: int
    location: GroundStationLocation = field(default_factory=GroundStationLocation.spacelab_ufsc)
    horizon_hours: float = 24.0
    min_elevation_degrees: float = 5.0
    doppler_source: str = "propagator"
    auto_execute: bool = True
    created_by: str | None = None
    dedupe_tolerance_seconds: float = 60.0


@dataclass(frozen=True)
class DiscoveredPass:
    prediction: PassPrediction
    outcome: str
    scheduled_pass: ScheduledPass | None = None
    conflicts: list[SchedulingConflict] = field(default_factory=list)


@dataclass(frozen=True)
class DiscoverPassesResult:
    discovered: list[DiscoveredPass]

    @property
    def scheduled(self) -> list[DiscoveredPass]:
        return [item for item in self.discovered if item.outcome == SCHEDULED]

    @property
    def conflicts(self) -> list[DiscoveredPass]:
        return [item for item in self.discovered if item.outcome == CONFLICT]

    @property
    def duplicates(self) -> list[DiscoveredPass]:
        return [item for item in self.discovered if item.outcome == DUPLICATE]


class PassPredictionService:
    def __init__(
        self,
        propagator: Propagator,
        pass_scheduler: PassSchedulerService,
        event_repository: OperationalEventRepository,
    ) -> None:
        self.propagator = propagator
        self.pass_scheduler = pass_scheduler
        self.event_repository = event_repository

    def preview_passes(
        self,
        tle: TLE,
        location: GroundStationLocation,
        horizon_hours: float = 24.0,
        min_elevation_degrees: float = 5.0,
        start: datetime | None = None,
    ) -> list[PassPrediction]:
        start = start or utc_now()
        end = start + timedelta(hours=horizon_hours)
        return self.propagator.predict_passes(tle, location, start, end, min_elevation_degrees)

    def discover_and_schedule(self, request: DiscoverPassesRequest) -> DiscoverPassesResult:
        start = utc_now()
        end = start + timedelta(hours=request.horizon_hours)
        predictions = self.propagator.predict_passes(
            request.tle, request.location, start, end, request.min_elevation_degrees
        )

        known_passes = self.pass_scheduler.list_passes()
        discovered: list[DiscoveredPass] = []

        for prediction in predictions:
            if self._is_duplicate(prediction, request, known_passes):
                discovered.append(DiscoveredPass(prediction, DUPLICATE))
                continue

            result = self.pass_scheduler.schedule_pass(
                SchedulePassRequest(
                    satellite_id=request.satellite_id,
                    aos=prediction.aos,
                    los=prediction.los,
                    center_frequency_hz=request.center_frequency_hz,
                    doppler_source=request.doppler_source,
                    max_elevation_degrees=prediction.max_elevation_degrees,
                    auto_execute=request.auto_execute,
                    notes=(
                        f"Auto-discovered from TLE (catalog {prediction.catalog_number}); "
                        f"peak {prediction.max_elevation_degrees:.1f} deg."
                    ),
                    created_by=request.created_by or "propagator",
                )
            )

            if result.succeeded and result.scheduled_pass is not None:
                known_passes.append(result.scheduled_pass)
                discovered.append(DiscoveredPass(prediction, SCHEDULED, result.scheduled_pass))
            else:
                discovered.append(DiscoveredPass(prediction, CONFLICT, conflicts=result.conflicts))

        outcome = DiscoverPassesResult(discovered)
        self.event_repository.add(
            OperationalEvent(
                EventSeverity.INFO,
                "propagation",
                (
                    f"Pass discovery completed: {len(outcome.scheduled)} scheduled, "
                    f"{len(outcome.conflicts)} in conflict, {len(outcome.duplicates)} already known."
                ),
                request.satellite_id,
                None,
                {
                    "catalog_number": request.tle.catalog_number,
                    "horizon_hours": request.horizon_hours,
                    "min_elevation_degrees": request.min_elevation_degrees,
                    "predicted": len(predictions),
                },
            )
        )
        return outcome

    def _is_duplicate(
        self,
        prediction: PassPrediction,
        request: DiscoverPassesRequest,
        known_passes: list[ScheduledPass],
    ) -> bool:
        tolerance = timedelta(seconds=request.dedupe_tolerance_seconds)
        return any(
            existing.satellite_id == request.satellite_id
            and existing.is_active_for_scheduling
            and abs(existing.window.aos - prediction.aos) <= tolerance
            for existing in known_passes
        )

    @staticmethod
    def prediction_to_dict(prediction: PassPrediction) -> dict[str, object]:
        return {
            "aos": prediction.aos.isoformat(),
            "los": prediction.los.isoformat(),
            "peak": prediction.peak.isoformat(),
            "duration_seconds": round(prediction.duration_seconds, 1),
            "max_elevation_degrees": round(prediction.max_elevation_degrees, 2),
            "aos_azimuth_degrees": round(prediction.aos_azimuth_degrees, 1),
            "peak_azimuth_degrees": round(prediction.peak_azimuth_degrees, 1),
            "los_azimuth_degrees": round(prediction.los_azimuth_degrees, 1),
            "catalog_number": prediction.catalog_number,
        }

    @classmethod
    def discovered_to_dict(cls, discovered: DiscoveredPass) -> dict[str, object]:
        payload: dict[str, object] = {
            "outcome": discovered.outcome,
            "prediction": cls.prediction_to_dict(discovered.prediction),
        }
        if discovered.scheduled_pass is not None:
            payload["pass_id"] = str(discovered.scheduled_pass.id)
        if discovered.conflicts:
            payload["conflict_ids"] = [str(conflict.id) for conflict in discovered.conflicts]
        return payload
