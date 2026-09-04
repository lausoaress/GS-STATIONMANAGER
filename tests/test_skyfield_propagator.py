from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("skyfield")

from mgm8.domain.models import GroundStationLocation, TLE
from mgm8.infrastructure.skyfield_propagator import SkyfieldPropagator

# ISS element set, epoch 2024-079 (~2024-03-19). Kept close to epoch so SGP4 stays accurate.
ISS_TLE = TLE(
    line1="1 25544U 98067A   24080.53237268  .00016942  00000-0  30588-3 0  9990",
    line2="2 25544  51.6396 193.2647 0005852 108.9591 251.2216 15.49607995446243",
    name="ISS (ZARYA)",
)
LOCATION = GroundStationLocation.spacelab_ufsc()
WINDOW_START = datetime(2024, 3, 19, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def propagator() -> SkyfieldPropagator:
    return SkyfieldPropagator()


def test_predicts_iss_passes_over_florianopolis(propagator: SkyfieldPropagator):
    passes = propagator.predict_passes(ISS_TLE, LOCATION, WINDOW_START, WINDOW_START + timedelta(days=3))

    assert passes, "ISS should have visible passes within 3 days of epoch"
    for prediction in passes:
        assert prediction.los > prediction.aos
        assert prediction.aos <= prediction.peak <= prediction.los
        assert 0.0 <= prediction.max_elevation_degrees <= 90.0
        assert prediction.catalog_number == 25544


def test_track_returns_look_angles_and_bounded_doppler(propagator: SkyfieldPropagator):
    first = propagator.predict_passes(ISS_TLE, LOCATION, WINDOW_START, WINDOW_START + timedelta(days=3))[0]

    point = propagator.track(ISS_TLE, LOCATION, first.peak)

    assert 0.0 <= point.azimuth_degrees < 360.0
    assert point.elevation_degrees > 0.0
    assert 300.0 < point.range_km < 4000.0
    # ISS Doppler on the 70 cm band peaks near +/-10 kHz; near culmination it is small.
    assert abs(point.doppler_shift_hz(437_200_000)) < 15_000.0


def test_sample_track_covers_the_pass(propagator: SkyfieldPropagator):
    first = propagator.predict_passes(ISS_TLE, LOCATION, WINDOW_START, WINDOW_START + timedelta(days=3))[0]

    points = propagator.sample_track(ISS_TLE, LOCATION, first.aos, first.los, step_seconds=15.0)

    assert len(points) >= 5
    assert abs(points[0].at - first.aos) < timedelta(seconds=1)
    assert max(pt.elevation_degrees for pt in points) >= first.max_elevation_degrees - 3.0
