from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from mgm8.domain.models import (
    GroundStationLocation,
    OperationalEvent,
    PassPrediction,
    ScheduledPass,
    ScheduledTelecommand,
    SchedulingConflict,
    TLE,
    TrackingPoint,
)


class ScheduledPassRepository(Protocol):
    def get_by_id(self, pass_id: UUID) -> ScheduledPass | None: ...
    def get_active_in_window(self, start: datetime, end: datetime) -> list[ScheduledPass]: ...
    def list_all(self) -> list[ScheduledPass]: ...
    def add(self, scheduled_pass: ScheduledPass) -> None: ...
    def update(self, scheduled_pass: ScheduledPass) -> None: ...


class ScheduledTelecommandRepository(Protocol):
    def get_by_id(self, telecommand_id: UUID) -> ScheduledTelecommand | None: ...
    def list_all(self) -> list[ScheduledTelecommand]: ...
    def list_for_pass(self, scheduled_pass_id: UUID) -> list[ScheduledTelecommand]: ...
    def list_active_between(self, start: datetime, end: datetime) -> list[ScheduledTelecommand]: ...
    def get_due(self, as_of: datetime) -> list[ScheduledTelecommand]: ...
    def add(self, telecommand: ScheduledTelecommand) -> None: ...
    def update(self, telecommand: ScheduledTelecommand) -> None: ...


class SchedulingConflictRepository(Protocol):
    def add(self, conflict: SchedulingConflict) -> None: ...
    def list_recent(self, limit: int = 20) -> list[SchedulingConflict]: ...


class OperationalEventRepository(Protocol):
    def add(self, event: OperationalEvent) -> None: ...
    def list_recent(self, limit: int = 50) -> list[OperationalEvent]: ...


class Propagator(Protocol):
    """Orbit propagation and look-angle computation for autonomous operation.

    This is the station's own satellite tracker; it replaces GPredict on the
    automation path (GPredict stays a manual / situational-awareness tool).
    """

    def predict_passes(
        self,
        tle: TLE,
        location: GroundStationLocation,
        start: datetime,
        end: datetime,
        min_elevation_degrees: float = 5.0,
    ) -> list[PassPrediction]: ...

    def track(self, tle: TLE, location: GroundStationLocation, at: datetime) -> TrackingPoint: ...

    def sample_track(
        self,
        tle: TLE,
        location: GroundStationLocation,
        start: datetime,
        end: datetime,
        step_seconds: float = 1.0,
    ) -> list[TrackingPoint]: ...
