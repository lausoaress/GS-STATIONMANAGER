"""
coordinates.py — Transformações de referencial.

Cadeia de conversões implementada:

    TEME (saída do SGP4)
        │  rotação pelo ângulo GMST (Greenwich Mean Sidereal Time)
        ▼
    ECEF / ECF (Earth-Centered, Earth-Fixed)
        │  fórmula de Bowring (iterativa) sobre o elipsoide WGS84
        ▼
    Geodésica (latitude, longitude, altitude)

    ECEF (satélite) + ECEF (estação)
        │  rotação para o referencial local ENU (East-North-Up) da estação
        ▼
    Topocêntrico (azimute, elevação, distância)

Todas as distâncias internas são em quilômetros; graus são usados apenas
nas interfaces de entrada/saída das funções.

Observação sobre precisão: a rotação TEME→ECEF aqui feita usa apenas o
GMST (ângulo de rotação da Terra), ignorando o movimento do polo (polar
motion) e as pequenas correções de nutação/precessão de curtíssimo prazo
que separam TEME de um referencial verdadeiramente inercial. Esse erro
residual é da ordem de metros — desprezível frente à própria incerteza
do TLE/SGP4, que é tipicamente de 1 a alguns km.
"""

from __future__ import annotations

import math
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Elipsoide WGS84
# ---------------------------------------------------------------------------
WGS84_A = 6378.137            # semi-eixo maior (km)
WGS84_F = 1 / 298.257223563   # achatamento
WGS84_E2 = 2 * WGS84_F - WGS84_F ** 2  # excentricidade ao quadrado

# Velocidade angular da Terra (rad/s), IERS. Usada para converter a velocidade
# do referencial (quase) inercial TEME para o referencial girante ECEF: sem o
# termo -omega x r, a taxa de variacao da distancia sairia com um erro da
# ordem de centenas de m/s perto do horizonte.
EARTH_ROTATION_RAD_S = 7.2921159e-5

# Velocidade da luz no vacuo (km/s), para o desvio Doppler.
SPEED_OF_LIGHT_KM_S = 299_792.458


class GeodeticPosition(NamedTuple):
    latitude_deg: float
    longitude_deg: float
    altitude_km: float


class TopocentricPosition(NamedTuple):
    azimuth_deg: float     # 0°=Norte, 90°=Leste, medido no sentido horário
    elevation_deg: float   # 0°=horizonte, 90°=zênite
    range_km: float        # distância em linha reta estação→satélite


def gmst_rad(jd: float, fr: float) -> float:
    """Greenwich Mean Sidereal Time, em radianos, para a data juliana jd+fr.

    Usa a aproximação polinomial padrão (IAU, referenciada a J2000.0),
    precisa a menos de ~0.1 segundo de arco — muito além do que qualquer
    incerteza do TLE justificaria explorar.
    """
    jd_full = jd + fr
    t = (jd_full - 2451545.0) / 36525.0  # séculos julianos desde J2000.0

    gmst_deg = (
        280.46061837
        + 360.98564736629 * (jd_full - 2451545.0)
        + 0.000387933 * t ** 2
        - (t ** 3) / 38710000.0
    )
    gmst_deg %= 360.0
    return math.radians(gmst_deg)


def teme_to_ecef(position_teme_km: tuple, jd: float, fr: float) -> tuple:
    """Rotaciona um vetor de posição de TEME para ECEF pelo ângulo GMST.

    Esta é uma rotação simples em torno do eixo Z (o eixo de rotação da
    Terra), pois TEME e ECEF compartilham a mesma origem e o mesmo eixo Z;
    a diferença entre eles é justamente a rotação diária da Terra.
    """
    x, y, z = position_teme_km
    theta = gmst_rad(jd, fr)
    c, s = math.cos(theta), math.sin(theta)

    x_ecef = x * c + y * s
    y_ecef = -x * s + y * c
    z_ecef = z
    return (x_ecef, y_ecef, z_ecef)


def teme_to_ecef_velocity(
    velocity_teme_km_s: tuple, position_ecef_km: tuple, jd: float, fr: float
) -> tuple:
    """Converte a velocidade de TEME para ECEF.

    Duas parcelas: a mesma rotacao pelo angulo GMST aplicada a posicao, e o
    termo `-omega x r` que aparece porque o ECEF gira junto com a Terra. Sem o
    segundo termo, a componente radial da velocidade (usada no Doppler e no
    range rate) ficaria errada por centenas de m/s.
    """
    vx, vy, vz = velocity_teme_km_s
    theta = gmst_rad(jd, fr)
    c, s = math.cos(theta), math.sin(theta)

    vx_rot = vx * c + vy * s
    vy_rot = -vx * s + vy * c
    vz_rot = vz

    x_ecef, y_ecef, _ = position_ecef_km
    w = EARTH_ROTATION_RAD_S
    return (vx_rot + w * y_ecef, vy_rot - w * x_ecef, vz_rot)


def range_rate_km_s(
    satellite_ecef_km: tuple, satellite_velocity_ecef_km_s: tuple, station_ecef_km: tuple
) -> float:
    """Taxa de variacao da distancia estacao->satelite (km/s).

    Negativa enquanto o satelite se aproxima, positiva quando se afasta. A
    estacao esta parada no ECEF, entao so entra a velocidade do satelite.
    """
    dx = satellite_ecef_km[0] - station_ecef_km[0]
    dy = satellite_ecef_km[1] - station_ecef_km[1]
    dz = satellite_ecef_km[2] - station_ecef_km[2]
    rng = math.sqrt(dx * dx + dy * dy + dz * dz)
    if rng == 0.0:
        return 0.0
    vx, vy, vz = satellite_velocity_ecef_km_s
    return (dx * vx + dy * vy + dz * vz) / rng


def ecef_to_geodetic(position_ecef_km: tuple) -> GeodeticPosition:
    """Converte ECEF (km) para latitude/longitude/altitude sobre o WGS84.

    Usa o método iterativo clássico (poucas iterações bastam para
    convergência sub-milimétrica, dado o achatamento pequeno da Terra).
    """
    x, y, z = position_ecef_km
    lon = math.atan2(y, x)

    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - WGS84_E2))  # chute inicial

    for _ in range(6):
        sin_lat = math.sin(lat)
        n = WGS84_A / math.sqrt(1 - WGS84_E2 * sin_lat ** 2)
        alt = p / math.cos(lat) - n
        lat = math.atan2(z, p * (1 - WGS84_E2 * n / (n + alt)))

    sin_lat = math.sin(lat)
    n = WGS84_A / math.sqrt(1 - WGS84_E2 * sin_lat ** 2)
    alt = p / math.cos(lat) - n

    return GeodeticPosition(math.degrees(lat), math.degrees(lon), alt)


def geodetic_to_ecef(latitude_deg: float, longitude_deg: float, altitude_km: float) -> tuple:
    """Converte latitude/longitude/altitude (WGS84) para ECEF (km).

    Usado para posicionar a estação terrestre no mesmo referencial do
    satélite, permitindo depois calcular o vetor relativo entre os dois.
    """
    lat = math.radians(latitude_deg)
    lon = math.radians(longitude_deg)
    sin_lat = math.sin(lat)
    n = WGS84_A / math.sqrt(1 - WGS84_E2 * sin_lat ** 2)

    x = (n + altitude_km) * math.cos(lat) * math.cos(lon)
    y = (n + altitude_km) * math.cos(lat) * math.sin(lon)
    z = (n * (1 - WGS84_E2) + altitude_km) * sin_lat
    return (x, y, z)


def ecef_to_topocentric(
    satellite_ecef_km: tuple,
    station_ecef_km: tuple,
    station_latitude_deg: float,
    station_longitude_deg: float,
) -> TopocentricPosition:
    """Calcula azimute, elevação e distância do satélite visto da estação.

    Passos:
    1. Vetor relativo satélite−estação em ECEF.
    2. Rotação desse vetor para o referencial local ENU (East-North-Up)
       da estação, que depende apenas da latitude/longitude dela.
    3. Azimute = ângulo do vetor no plano horizontal, medido do Norte
       para o Leste; Elevação = ângulo acima do plano horizontal local.
    """
    dx = satellite_ecef_km[0] - station_ecef_km[0]
    dy = satellite_ecef_km[1] - station_ecef_km[1]
    dz = satellite_ecef_km[2] - station_ecef_km[2]

    lat = math.radians(station_latitude_deg)
    lon = math.radians(station_longitude_deg)
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    sin_lon, cos_lon = math.sin(lon), math.cos(lon)

    east = -sin_lon * dx + cos_lon * dy
    north = -sin_lat * cos_lon * dx - sin_lat * sin_lon * dy + cos_lat * dz
    up = cos_lat * cos_lon * dx + cos_lat * sin_lon * dy + sin_lat * dz

    rng = math.sqrt(dx * dx + dy * dy + dz * dz)
    azimuth = math.degrees(math.atan2(east, north)) % 360.0
    elevation = math.degrees(math.asin(up / rng))

    return TopocentricPosition(azimuth, elevation, rng)
