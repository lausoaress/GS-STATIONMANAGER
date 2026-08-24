"""Propagação orbital SGP4 e previsão de passagens para a estação SpaceLab.

Reexporta a superfície que os consumidores usam, para que eles não precisem
conhecer a organização interna dos módulos:

    from spacelab_tracking import get_orbital_data, build_satellite, get_tracking_info
"""

from .celestrak import (
    OrbitalData,
    from_tle_lines,
    get_orbital_data,
    load_tle_file,
)
from .coordinates import GeodeticPosition, TopocentricPosition
from .propagation import build_satellite, propagate, satellite_epoch
from .tracking import (
    SatellitePass,
    TrackingInfo,
    get_tracking_info,
    predict_next_pass,
    predict_passes,
)

__all__ = [
    "GeodeticPosition",
    "OrbitalData",
    "SatellitePass",
    "TopocentricPosition",
    "TrackingInfo",
    "build_satellite",
    "from_tle_lines",
    "get_orbital_data",
    "get_tracking_info",
    "load_tle_file",
    "predict_next_pass",
    "predict_passes",
    "propagate",
    "satellite_epoch",
]
