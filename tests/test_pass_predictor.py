from datetime import datetime, timedelta, timezone
from uuid import uuid4

from mgm8.application.pass_predictor import DiscoverPassesRequest, PassPredictionService
from mgm8.application.pass_scheduler import PassSchedulerService
from mgm8.domain.models import GroundStationLocation, PassPrediction, TLE, TrackingPoint
from mgm8.domain.services import SchedulingConflictDetector
from mgm8.infrastructure.in_memory import (InMemoryOperationalEventRepository, InMemoryScheduledPassRepository,
                                             InMemorySchedulingConflictRepository)

ISS_TLE = TLE(
    line1="1 25544U 98067A   24080.53237268  .00016942  00000-0  30588-3 0  9990",
    line2="2 25544  51.6396 193.2647 0005852 108.9591 251.2216 15.49607995446243",
    name="ISS (ZARYA)",
)
LOCATION = GroundStationLocation.spacelab_ufsc()


class FakePropagator:
    def __init__(self, predictions: list[PassPrediction]) -> None:
        self._predictions = predictions
        self.calls: list[tuple] = []

    def predict_passes(self, tle, location, start, end, min_elevation_degrees=5.0):
        self.calls.append((start, end, min_elevation_degrees))
        return [item for item in self._predictions if start <= item.aos <= end]

    def track(self, tle, location, at):
        return TrackingPoint(at, 180.0, 45.0, 800.0, -3.0)

    def sample_track(self, tle, location, start, end, step_seconds=1.0):
        return [self.track(tle, location, start)]


def _prediction(offset_minutes: float, duration_minutes: float = 8.0, max_el: float = 40.0) -> PassPrediction:
    aos = datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)
    los = aos + timedelta(minutes=duration_minutes)
    return PassPrediction(
        aos=aos,
        los=los,
        peak=aos + timedelta(minutes=duration_minutes / 2),
        max_elevation_degrees=max_el,
        aos_azimuth_degrees=120.0,
        peak_azimuth_degrees=200.0,
        los_azimuth_degrees=280.0,
        catalog_number=25544,
    )


def _service(predictions: list[PassPrediction]) -> tuple[PassPredictionService, PassSchedulerService]:
    scheduler = PassSchedulerService(
        InMemoryScheduledPassRepository(),
        InMemorySchedulingConflictRepository(),
        InMemoryOperationalEventRepository(),
        SchedulingConflictDetector(),
    )
    predictor = PassPredictionService(FakePropagator(predictions), scheduler, scheduler.event_repository)
    return predictor, scheduler


def test_preview_passes_filters_by_horizon():
    predictor, _ = _service([_prediction(30), _prediction(60 * 30)])

    previews = predictor.preview_passes(ISS_TLE, LOCATION, horizon_hours=24.0)

    assert len(previews) == 1
    assert previews[0].catalog_number == 25544


def test_discover_schedules_predicted_passes():
    predictor, scheduler = _service([_prediction(30), _prediction(120)])

    result = predictor.discover_and_schedule(DiscoverPassesRequest(
        satellite_id=uuid4(), tle=ISS_TLE, center_frequency_hz=437_200_000, location=LOCATION,
    ))

    assert len(result.scheduled) == 2
    assert len(scheduler.list_passes()) == 2
    assert all(item.created_by == "propagator" for item in scheduler.list_passes())


def test_discover_skips_already_known_passes_on_second_run():
    satellite_id = uuid4()
    predictor, scheduler = _service([_prediction(45)])
    request = DiscoverPassesRequest(
        satellite_id=satellite_id, tle=ISS_TLE, center_frequency_hz=437_200_000, location=LOCATION,
    )

    predictor.discover_and_schedule(request)
    second = predictor.discover_and_schedule(request)

    assert len(second.duplicates) == 1
    assert len(second.scheduled) == 0
    assert len(scheduler.list_passes()) == 1


def test_discover_reports_conflicts_for_overlapping_predictions():
    predictor, scheduler = _service([
        _prediction(30, duration_minutes=20),
        _prediction(40, duration_minutes=20),
    ])

    result = predictor.discover_and_schedule(DiscoverPassesRequest(
        satellite_id=uuid4(), tle=ISS_TLE, center_frequency_hz=437_200_000, location=LOCATION,
    ))

    assert len(result.scheduled) == 1
    assert len(result.conflicts) == 1
    assert result.conflicts[0].conflicts


def test_discover_emits_summary_event():
    predictor, scheduler = _service([_prediction(30)])

    predictor.discover_and_schedule(DiscoverPassesRequest(
        satellite_id=uuid4(), tle=ISS_TLE, center_frequency_hz=437_200_000, location=LOCATION,
    ))

    propagation_events = [event for event in scheduler.list_events() if event.category == "propagation"]
    assert len(propagation_events) == 1
