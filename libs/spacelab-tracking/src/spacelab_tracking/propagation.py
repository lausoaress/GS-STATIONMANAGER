"""
propagation.py — Construção do objeto SGP4 (Satrec) e propagação orbital.

Aceita dados orbitais tanto em OMM (dict) quanto em TLE clássico (2 linhas)
e devolve, em ambos os casos, o mesmo tipo de objeto (`Satrec`) para o
restante do sistema. Isso é o que permite ao resto do código ser agnóstico
ao formato de origem dos dados.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import NamedTuple

from sgp4.api import Satrec, jday, days2mdhms
from sgp4 import omm as sgp4_omm

from .celestrak import OrbitalData


class PropagationResult(NamedTuple):
    error_code: int
    position_teme_km: tuple    # (x, y, z) em km, referencial TEME
    velocity_teme_km_s: tuple  # (vx, vy, vz) em km/s, referencial TEME
    jd: float                  # dia juliano (parte inteira) do instante propagado
    fr: float                  # fração de dia juliano — jd+fr = data juliana completa


# Códigos de erro do SGP4 (ver código-fonte da biblioteca `sgp4`)
SGP4_ERROR_MESSAGES = {
    0: "sem erro",
    1: "excentricidade fora do intervalo válido (e >= 1 ou e < -0.001)",
    2: "movimento médio negativo após a propagação",
    3: "raio do perigeu < 1 Terra-raio (indício de decaimento orbital)",
    4: "semi-latus rectum negativo",
    5: "não usado",
    6: "raio orbital < 1 Terra-raio (decaimento / erro numérico)",
}


def build_satellite(orbital_data: OrbitalData) -> Satrec:
    """Constrói um Satrec a partir de OrbitalData, seja ele OMM ou TLE."""
    if orbital_data.source == "omm":
        fields = dict(orbital_data.omm)  # cópia defensiva
        # O CelesTrak normalmente inclui frações de segundo no EPOCH, mas
        # alguns provedores/exports OMM omitem — normaliza para o parser
        # da biblioteca sgp4, que exige o formato "%Y-%m-%dT%H:%M:%S.%f".
        if "." not in fields.get("EPOCH", ""):
            fields["EPOCH"] = fields["EPOCH"] + ".000000"
        sat = Satrec()
        sgp4_omm.initialize(sat, fields)
        return sat

    if orbital_data.source == "tle":
        return Satrec.twoline2rv(orbital_data.tle_line1, orbital_data.tle_line2)

    raise ValueError(f"Fonte de dados orbitais desconhecida: {orbital_data.source!r}")


def propagate(satrec: Satrec, when: datetime) -> PropagationResult:
    """
    Propaga a órbita para o instante `when` (deve ser timezone-aware).

    Retorna posição/velocidade no referencial TEME (True Equator, Mean
    Equinox of date) em km e km/s — é a saída nativa do SGP4, e ainda não
    é utilizável diretamente para latitude/longitude (ver coordinates.py).
    """
    if when.tzinfo is None:
        raise ValueError("`when` deve ser timezone-aware (use tzinfo=timezone.utc).")
    when_utc = when.astimezone(timezone.utc)

    jd, fr = jday(
        when_utc.year, when_utc.month, when_utc.day,
        when_utc.hour, when_utc.minute,
        when_utc.second + when_utc.microsecond / 1e6,
    )
    error_code, position, velocity = satrec.sgp4(jd, fr)
    return PropagationResult(error_code, position, velocity, jd, fr)


def check_error(result: PropagationResult) -> None:
    """Lança exceção legível se o SGP4 reportou erro na propagação.

    Erros normalmente indicam elementos orbitais numericamente inválidos
    para o instante pedido (ex.: satélite reentrou, ou o TLE está velho
    demais para o intervalo de tempo solicitado).
    """
    if result.error_code != 0:
        msg = SGP4_ERROR_MESSAGES.get(result.error_code, "erro desconhecido")
        raise RuntimeError(f"SGP4 error {result.error_code}: {msg}")


def satellite_epoch(satrec: Satrec) -> datetime:
    """Retorna o instante de epoch (validade nominal) do TLE/OMM em uso.

    Quanto mais distante o instante propagado estiver deste epoch, maior
    a incerteza da posição calculada.
    """
    year = satrec.epochyr + (2000 if satrec.epochyr < 57 else 1900)
    month, day, hour, minute, sec = days2mdhms(year, satrec.epochdays)
    whole_sec = int(sec)
    microsecond = int(round((sec - whole_sec) * 1e6))
    return datetime(year, month, day, hour, minute, whole_sec, microsecond, tzinfo=timezone.utc)
