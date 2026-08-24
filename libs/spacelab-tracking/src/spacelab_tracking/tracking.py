"""
tracking.py — Orquestra propagação + transformações de coordenadas para
produzir a informação final de rastreamento: onde o satélite está, e como
ele é visto a partir da estação terrestre configurada.

Este módulo é o "ponto de encontro" entre propagation.py e coordinates.py,
e é por aqui que os consumidores entram:

- o Station Manager chama `get_tracking_info()` a cada tick do laço de
  apontamento, para obter o az/el instantâneo;
- o TC Scheduler chama `predict_passes()` para saber quando cada satélite
  estará visível e decidir o que rastrear.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sgp4.api import Satrec

from . import config
from . import coordinates
from . import propagation


@dataclass
class TrackingInfo:
    satellite_name: str
    norad_id: int
    tle_epoch: datetime
    time_utc: datetime

    position_teme_km: tuple
    velocity_teme_km_s: tuple

    geodetic: coordinates.GeodeticPosition
    topocentric: coordinates.TopocentricPosition

    @property
    def is_visible(self) -> bool:
        return self.topocentric.elevation_deg > config.MIN_ELEVATION_DEG

    @property
    def status_label(self) -> str:
        return "VISIBLE" if self.is_visible else "BELOW HORIZON"


def get_tracking_info(
    satrec: Satrec,
    satellite_name: str,
    when: Optional[datetime] = None,
    station: Optional[dict] = None,
) -> TrackingInfo:
    """
    Calcula a informação completa de rastreamento para o instante `when`
    (padrão: agora, em UTC) e para a estação `station` (padrão:
    config.GROUND_STATION).
    """
    if when is None:
        when = datetime.now(timezone.utc)
    if station is None:
        station = config.GROUND_STATION

    prop_result = propagation.propagate(satrec, when)
    propagation.check_error(prop_result)

    position_ecef = coordinates.teme_to_ecef(
        prop_result.position_teme_km, prop_result.jd, prop_result.fr
    )
    geodetic = coordinates.ecef_to_geodetic(position_ecef)

    station_ecef = coordinates.geodetic_to_ecef(
        station["latitude_deg"], station["longitude_deg"], station["altitude_m"] / 1000.0
    )
    topocentric = coordinates.ecef_to_topocentric(
        position_ecef, station_ecef, station["latitude_deg"], station["longitude_deg"]
    )

    return TrackingInfo(
        satellite_name=satellite_name,
        norad_id=satrec.satnum,
        tle_epoch=propagation.satellite_epoch(satrec),
        time_utc=when.astimezone(timezone.utc),
        position_teme_km=prop_result.position_teme_km,
        velocity_teme_km_s=prop_result.velocity_teme_km_s,
        geodetic=geodetic,
        topocentric=topocentric,
    )


@dataclass
class SatellitePass:
    """Uma passagem visível completa: do nascer (AOS) ao ocaso (LOS)."""

    aos_time: datetime          # Acquisition Of Signal — satélite cruza a elevação mínima subindo
    aos_azimuth_deg: float

    culmination_time: datetime  # instante de elevação máxima na passagem
    max_elevation_deg: float
    culmination_azimuth_deg: float

    los_time: datetime          # Loss Of Signal — satélite cruza a elevação mínima descendo
    los_azimuth_deg: float

    @property
    def duration_seconds(self) -> float:
        return (self.los_time - self.aos_time).total_seconds()


def _elevation_at(satrec: Satrec, satellite_name: str, station: dict, when: datetime) -> float:
    return get_tracking_info(satrec, satellite_name, when=when, station=station).topocentric.elevation_deg


def _refine_crossing(
    satrec: Satrec, satellite_name: str, station: dict,
    t_before: datetime, t_after: datetime, threshold_deg: float,
    iterations: int = 20,
) -> datetime:
    """Bisseção: encontra o instante em que a elevação cruza `threshold_deg`,
    dado um par (t_before, t_after) que já sabemos "abraçar" a mudança de
    sinal. Funciona tanto para cruzamento subindo (AOS) quanto descendo
    (LOS) — só depende de sinais opostos nas duas pontas.
    20 iterações reduzem o intervalo original por um fator de ~10^6,
    equivalente a frações de milissegundo mesmo para um passo grosseiro
    de 30s — muito além do que a precisão do TLE justificaria refinar.
    """
    sign_before = _elevation_at(satrec, satellite_name, station, t_before) - threshold_deg
    lo, hi = t_before, t_after
    for _ in range(iterations):
        mid = lo + (hi - lo) / 2
        sign_mid = _elevation_at(satrec, satellite_name, station, mid) - threshold_deg
        if (sign_before < 0) == (sign_mid < 0):
            lo = mid
        else:
            hi = mid
    return lo + (hi - lo) / 2


def _refine_culmination(
    satrec: Satrec, satellite_name: str, station: dict,
    t_lo: datetime, t_hi: datetime,
    iterations: int = 25,
) -> datetime:
    """Busca áurea (golden-section search): encontra o instante de elevação
    máxima dentro de [t_lo, t_hi]. A elevação ao longo de uma passagem é
    unimodal (sobe até o pico, depois desce), então busca áurea converge
    de forma confiável sem precisar de derivadas.
    """
    invphi = (5 ** 0.5 - 1) / 2  # 1/phi ≈ 0.618

    a, b = t_lo, t_hi
    c = b - (b - a) * invphi
    d = a + (b - a) * invphi
    fc = _elevation_at(satrec, satellite_name, station, c)
    fd = _elevation_at(satrec, satellite_name, station, d)

    for _ in range(iterations):
        if fc > fd:
            b, d, fd = d, c, fc
            c = b - (b - a) * invphi
            fc = _elevation_at(satrec, satellite_name, station, c)
        else:
            a, c, fc = c, d, fd
            d = a + (b - a) * invphi
            fd = _elevation_at(satrec, satellite_name, station, d)

    return a + (b - a) / 2


def predict_passes(
    satrec: Satrec,
    satellite_name: str,
    station: Optional[dict] = None,
    start: Optional[datetime] = None,
    search_window_hours: float = 24.0,
    coarse_step_seconds: float = 30.0,
    min_elevation_deg: Optional[float] = None,
) -> list:
    """
    Previsão de passagens visíveis.

    Varre a janela [start, start + search_window_hours] em passos
    grosseiros de `coarse_step_seconds`, detecta as transições de
    elevação que caracterizam início (AOS) e fim (LOS) de uma passagem
    visível, e refina os instantes de AOS/LOS (bisseção) e de
    culminação/pico (busca áurea) em torno da amostra grosseira que os
    detectou.

    Por que essa abordagem em vez de resolver analiticamente: o SGP4 não
    tem uma forma fechada para "quando a elevação cruza X" — teria que
    ser feito numericamente de qualquer forma. Um passo grosseiro de 30s
    aliado a um refinamento numérico local é simples, robusto (não
    depende de derivadas do modelo orbital) e, mesmo rodando em um
    notebook comum, processa 24h de busca em uma fração de segundo — o
    SGP4 é muito barato computacionalmente; o verdadeiro limite de
    qualidade aqui é a precisão do TLE, não o custo da busca.

    Retorna uma lista de `SatellitePass`, em ordem cronológica. Pode ser
    vazia se não houver passagens visíveis na janela pesquisada.
    """
    if station is None:
        station = config.GROUND_STATION
    if start is None:
        start = datetime.now(timezone.utc)
    if min_elevation_deg is None:
        min_elevation_deg = config.MIN_ELEVATION_DEG

    step = timedelta(seconds=coarse_step_seconds)
    end = start + timedelta(hours=search_window_hours)

    passes: list = []

    prev_t = start
    prev_elev = _elevation_at(satrec, satellite_name, station, prev_t)

    # Estado da passagem em andamento (None quando estamos "abaixo do horizonte")
    aos_t: Optional[datetime] = None
    culmination_bracket_lo: Optional[datetime] = None
    max_elev_so_far = float("-inf")
    max_elev_t: Optional[datetime] = None

    t = start + step
    while t <= end:
        elev = _elevation_at(satrec, satellite_name, station, t)

        rising_crossing = prev_elev <= min_elevation_deg < elev
        falling_crossing = prev_elev > min_elevation_deg >= elev

        if rising_crossing:
            aos_t = _refine_crossing(satrec, satellite_name, station, prev_t, t, min_elevation_deg)
            max_elev_so_far = elev
            max_elev_t = t
            culmination_bracket_lo = prev_t

        elif aos_t is not None:
            if elev > max_elev_so_far:
                max_elev_so_far = elev
                max_elev_t = t

            if falling_crossing:
                los_t = _refine_crossing(satrec, satellite_name, station, prev_t, t, min_elevation_deg)
                culmination_t = _refine_culmination(
                    satrec, satellite_name, station,
                    culmination_bracket_lo or aos_t, t,
                )
                aos_info = get_tracking_info(satrec, satellite_name, when=aos_t, station=station)
                los_info = get_tracking_info(satrec, satellite_name, when=los_t, station=station)
                culm_info = get_tracking_info(satrec, satellite_name, when=culmination_t, station=station)

                passes.append(SatellitePass(
                    aos_time=aos_t,
                    aos_azimuth_deg=aos_info.topocentric.azimuth_deg,
                    culmination_time=culmination_t,
                    max_elevation_deg=culm_info.topocentric.elevation_deg,
                    culmination_azimuth_deg=culm_info.topocentric.azimuth_deg,
                    los_time=los_t,
                    los_azimuth_deg=los_info.topocentric.azimuth_deg,
                ))

                aos_t = None
                culmination_bracket_lo = None
                max_elev_so_far = float("-inf")
                max_elev_t = None

        prev_t, prev_elev = t, elev
        t += step

    return passes


def predict_next_pass(
    satrec: Satrec,
    satellite_name: str,
    station: Optional[dict] = None,
    start: Optional[datetime] = None,
    search_window_hours: float = 24.0,
) -> Optional[SatellitePass]:
    """Atalho sobre `predict_passes`: devolve só a próxima passagem, ou
    None se nenhuma for encontrada dentro de `search_window_hours`."""
    passes = predict_passes(
        satrec, satellite_name, station=station, start=start,
        search_window_hours=search_window_hours,
    )
    return passes[0] if passes else None
