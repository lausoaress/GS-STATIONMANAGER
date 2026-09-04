"""Propagator adapter backed by Skyfield's SGP4 implementation.

Kept isolated in the infrastructure layer: the domain and application layers
depend only on the :class:`mgm8.domain.ports.Propagator` protocol, so this is
the single module that imports ``skyfield`` / ``numpy``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mgm8.domain.models import GroundStationLocation, PassPrediction, TLE, TrackingPoint

_RISE, _CULMINATE, _SET = 0, 1, 2


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class SkyfieldPropagator:
    """Implements :class:`mgm8.domain.ports.Propagator`."""

    def __init__(self, timescale=None) -> None:
        try:
            from skyfield.api import load
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise ImportError(
                "SkyfieldPropagator requires the 'skyfield' package. "
                'Install it with: pip install "mgm8[propagation]"'
            ) from exc
        self._timescale = timescale or load.timescale()

    # -- Propagator port ---------------------------------------------------

    def predict_passes(
        self,
        tle: TLE,
        location: GroundStationLocation,
        start: datetime,
        end: datetime,
        min_elevation_degrees: float = 5.0,
    ) -> list[PassPrediction]:
        if end <= start:
            raise ValueError("end must be after start.")

        satellite = self._satellite(tle)
        site = self._site(location)
        t0 = self._timescale.from_datetime(_as_utc(start))
        t1 = self._timescale.from_datetime(_as_utc(end))

        times, events = satellite.find_events(
            site, t0, t1, altitude_degrees=min_elevation_degrees
        )

        predictions: list[PassPrediction] = []
        pending: dict[str, object] = {}
        for time, event in zip(times, events):
            altitude, azimuth, _ = (satellite - site).at(time).altaz()
            moment = time.utc_datetime()
            if event == _RISE:
                pending = {"aos": moment, "aos_az": azimuth.degrees}
            elif event == _CULMINATE:
                pending["peak"] = moment
                pending["peak_az"] = azimuth.degrees
                pending["max_el"] = altitude.degrees
            elif event == _SET and "aos" in pending:
                predictions.append(
                    PassPrediction(
                        aos=pending["aos"],  # type: ignore[arg-type]
                        los=moment,
                        peak=pending.get("peak", pending["aos"]),  # type: ignore[arg-type]
                        max_elevation_degrees=float(pending.get("max_el", min_elevation_degrees)),
                        aos_azimuth_degrees=float(pending["aos_az"]),  # type: ignore[arg-type]
                        peak_azimuth_degrees=float(pending.get("peak_az", pending["aos_az"])),
                        los_azimuth_degrees=float(azimuth.degrees),
                        catalog_number=tle.catalog_number,
                    )
                )
                pending = {}
        return predictions

    def track(self, tle: TLE, location: GroundStationLocation, at: datetime) -> TrackingPoint:
        satellite = self._satellite(tle)
        site = self._site(location)
        return self._point(satellite, site, self._timescale.from_datetime(_as_utc(at)))

    def sample_track(
        self,
        tle: TLE,
        location: GroundStationLocation,
        start: datetime,
        end: datetime,
        step_seconds: float = 1.0,
    ) -> list[TrackingPoint]:
        if end <= start:
            raise ValueError("end must be after start.")
        if step_seconds <= 0:
            raise ValueError("step_seconds must be positive.")

        satellite = self._satellite(tle)
        site = self._site(location)
        step = timedelta(seconds=step_seconds)

        points: list[TrackingPoint] = []
        cursor, stop = _as_utc(start), _as_utc(end)
        while cursor <= stop:
            points.append(self._point(satellite, site, self._timescale.from_datetime(cursor)))
            cursor += step
        return points

    # -- internals -------------------------------------------------------

    def _satellite(self, tle: TLE):
        from skyfield.api import EarthSatellite

        return EarthSatellite(tle.line1, tle.line2, tle.name or str(tle.catalog_number), self._timescale)

    def _site(self, location: GroundStationLocation):
        from skyfield.api import wgs84

        return wgs84.latlon(
            location.latitude_degrees,
            location.longitude_degrees,
            elevation_m=location.altitude_meters,
        )

    @staticmethod
    def _point(satellite, site, time) -> TrackingPoint:
        import numpy as np

        relative = (satellite - site).at(time)
        altitude, azimuth, _ = relative.altaz()
        position_km = relative.position.km
        velocity_km_s = relative.velocity.km_per_s
        range_km = float(np.linalg.norm(position_km))
        range_rate = float(np.dot(position_km, velocity_km_s) / range_km) if range_km else 0.0
        return TrackingPoint(
            at=time.utc_datetime(),
            azimuth_degrees=float(azimuth.degrees) % 360.0,
            elevation_degrees=float(altitude.degrees),
            range_km=range_km,
            range_rate_km_s=range_rate,
        )
