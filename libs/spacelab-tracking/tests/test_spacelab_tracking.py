"""Testes da biblioteca de rastreamento.

Foco nas partes que diferem do script original de onde ela veio — cache por
NORAD ID e configuração por ambiente — mais checagens de sanidade física que
pegariam um erro de conversão de referencial.

Nenhum teste toca a rede: os que exercitam `get_orbital_data` substituem os
fetchers por dublês.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests

from spacelab_tracking import (
    OrbitalData,
    build_satellite,
    from_tle_lines,
    get_tracking_info,
    predict_passes,
)
from spacelab_tracking import celestrak, config, coordinates

# TLE real da ISS, capturado do CelesTrak em 2026-08-24. Fixo de propósito:
# os testes de física propagam perto deste epoch, então o resultado não muda
# com o passar do tempo nem depende da rede.
ISS_NAME = "ISS (ZARYA)"
ISS_LINE1 = "1 25544U 98067A   26236.17729445  .00008773  00000+0  16369-3 0  9990"
ISS_LINE2 = "2 25544  51.6333 323.5788 0007697  77.8713 282.3138 15.49600847582298"
ISS_EPOCH = datetime(2026, 8, 24, 4, 15, tzinfo=timezone.utc)

STATION = {
    "name": "Teste",
    "latitude_deg": -23.5505,
    "longitude_deg": -46.6333,
    "altitude_m": 760.0,
}


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Isola o cache num diretório temporário por teste."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        config, "orbital_data_cache_file",
        lambda norad_id: tmp_path / f"orbital_data_{norad_id}.json",
    )
    return tmp_path


def _sample(norad_id: int, fetched_at: float) -> OrbitalData:
    return OrbitalData(
        source="tle",
        fetched_at=fetched_at,
        tle_line1=ISS_LINE1,
        tle_line2=ISS_LINE2,
        satellite_name=f"SAT-{norad_id}",
    )


# --- Cache por NORAD ID -----------------------------------------------------
# É a diferença central em relação ao script original, que tinha um único
# arquivo de cache porque acompanhava um satélite só.

def test_cache_files_are_per_satellite(cache_dir):
    celestrak._save_cache(25544, _sample(25544, time.time()))
    celestrak._save_cache(43552, _sample(43552, time.time()))

    assert celestrak._load_cache(25544).satellite_name == "SAT-25544"
    assert celestrak._load_cache(43552).satellite_name == "SAT-43552"
    assert len(list(cache_dir.glob("orbital_data_*.json"))) == 2


def test_load_cache_returns_none_for_unknown_satellite(cache_dir):
    assert celestrak._load_cache(99999) is None


def test_load_cache_survives_corrupted_file(cache_dir):
    (cache_dir / "orbital_data_25544.json").write_text("{ isto nao e json valido")
    assert celestrak._load_cache(25544) is None


def test_fresh_cache_is_used_without_touching_network(cache_dir, monkeypatch):
    celestrak._save_cache(25544, _sample(25544, time.time()))

    def explode(*args, **kwargs):
        raise AssertionError("não deveria buscar na rede com cache fresco")

    monkeypatch.setattr(celestrak, "_fetch_omm_json", explode)
    monkeypatch.setattr(celestrak, "_fetch_tle", explode)

    assert celestrak.get_orbital_data(25544).satellite_name == "SAT-25544"


def test_stale_cache_is_used_when_network_fails(cache_dir, monkeypatch):
    """Degradação graciosa: um TLE velho é melhor do que nenhum dado."""
    stale = time.time() - (config.CACHE_MAX_AGE_HOURS + 10) * 3600
    celestrak._save_cache(25544, _sample(25544, stale))

    def offline(*args, **kwargs):
        raise requests.RequestException("sem rede")

    monkeypatch.setattr(celestrak, "_fetch_omm_json", offline)
    monkeypatch.setattr(celestrak, "_fetch_tle", offline)

    assert celestrak.get_orbital_data(25544).satellite_name == "SAT-25544"


def test_raises_when_no_network_and_no_cache(cache_dir, monkeypatch):
    def offline(*args, **kwargs):
        raise requests.RequestException("sem rede")

    monkeypatch.setattr(celestrak, "_fetch_omm_json", offline)
    monkeypatch.setattr(celestrak, "_fetch_tle", offline)

    with pytest.raises(RuntimeError, match="25544"):
        celestrak.get_orbital_data(25544)


def test_falls_back_to_tle_when_omm_fails(cache_dir, monkeypatch):
    def omm_broken(*args, **kwargs):
        raise ValueError("OMM indisponível")

    monkeypatch.setattr(celestrak, "_fetch_omm_json", omm_broken)
    monkeypatch.setattr(celestrak, "_fetch_tle", lambda n: _sample(n, time.time()))

    data = celestrak.get_orbital_data(25544)
    assert data.source == "tle"
    # E o resultado do fallback também é cacheado.
    assert celestrak._load_cache(25544) is not None


# --- Formato de fio ---------------------------------------------------------
# to_json/from_json é como o Scheduler entrega os dados orbitais ao Station
# Manager; se quebrar, o rastreamento autônomo para.

@pytest.mark.parametrize("source", ["tle", "omm"])
def test_orbital_data_json_roundtrip(source):
    original = OrbitalData(
        source=source,
        fetched_at=1_756_000_000.0,
        omm={"OBJECT_NAME": "ISS (ZARYA)"} if source == "omm" else None,
        tle_line1=ISS_LINE1 if source == "tle" else None,
        tle_line2=ISS_LINE2 if source == "tle" else None,
        satellite_name=ISS_NAME,
    )
    restored = OrbitalData.from_json(json.loads(json.dumps(original.to_json())))
    assert restored == original


# --- Validação de TLE -------------------------------------------------------

def test_from_tle_lines_accepts_valid_tle():
    data = from_tle_lines(ISS_LINE1, ISS_LINE2, ISS_NAME)
    assert data.source == "tle"
    assert data.satellite_name == ISS_NAME


@pytest.mark.parametrize(
    "line1, line2, expected",
    [
        (ISS_LINE2, ISS_LINE1, "linha 1 deve começar"),          # linhas trocadas
        (ISS_LINE1[:40], ISS_LINE2, "truncadas"),                 # linha cortada
        (ISS_LINE1, "2 43552" + ISS_LINE2[7:], "NORAD ID diverge"),  # satélites diferentes
    ],
)
def test_from_tle_lines_rejects_malformed_input(line1, line2, expected):
    with pytest.raises(ValueError, match=expected):
        from_tle_lines(line1, line2)


# --- Geometria absoluta -----------------------------------------------------
# Os testes de consistência interna mais abaixo NÃO pegam um sinal trocado na
# rotação TEME->ECEF: inverter o ângulo preserva a norma e o eixo Z, então
# altitude e latitude continuam certas e as passagens seguem internamente
# coerentes — só que nos horários e azimutes errados. Verificado por injeção
# de bug. Os testes desta seção fixam a geometria em termos absolutos.

def test_point_above_station_has_elevation_90():
    """'Diretamente acima' é ao longo da normal geodésica ao elipsoide, e não
    do raio geocêntrico: por causa do achatamento da Terra, as duas direções
    divergem em até ~0.19 graus fora do equador e dos polos."""
    import math

    lat, lon = STATION["latitude_deg"], STATION["longitude_deg"]
    station_ecef = coordinates.geodetic_to_ecef(lat, lon, STATION["altitude_m"] / 1000.0)

    la, lo = math.radians(lat), math.radians(lon)
    up = (math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la))
    overhead = tuple(station_ecef[i] + 500.0 * up[i] for i in range(3))

    topo = coordinates.ecef_to_topocentric(overhead, station_ecef, lat, lon)
    assert topo.elevation_deg == pytest.approx(90.0, abs=1e-9)
    assert topo.range_km == pytest.approx(500.0, abs=1e-9)


@pytest.mark.parametrize(
    "bearing_deg, expected_azimuth",
    [(0.0, 0.0), (90.0, 90.0), (180.0, 180.0), (270.0, 270.0)],
)
def test_azimuth_matches_compass_bearing(bearing_deg, expected_azimuth):
    """Um alvo deslocado para o norte geográfico tem azimute 0; para o leste,
    90. Pega eixos ENU trocados ou azimute medido no sentido anti-horário."""
    import math

    lat, lon = STATION["latitude_deg"], STATION["longitude_deg"]
    station_ecef = coordinates.geodetic_to_ecef(lat, lon, 0.0)

    # Vetores unitários ENU locais, em ECEF.
    la, lo = math.radians(lat), math.radians(lon)
    east = (-math.sin(lo), math.cos(lo), 0.0)
    north = (
        -math.sin(la) * math.cos(lo),
        -math.sin(la) * math.sin(lo),
        math.cos(la),
    )

    b = math.radians(bearing_deg)
    target = tuple(
        station_ecef[i] + 100.0 * (math.cos(b) * north[i] + math.sin(b) * east[i])
        for i in range(3)
    )

    topo = coordinates.ecef_to_topocentric(target, station_ecef, lat, lon)
    assert topo.azimuth_deg == pytest.approx(expected_azimuth, abs=1e-6)


def test_earth_rotates_eastward_under_a_fixed_inertial_point():
    """Ancora o SENTIDO da rotação TEME->ECEF, que é o que um sinal trocado
    quebra sem que nenhuma outra checagem perceba.

    Um ponto parado no referencial inercial deriva para OESTE no referencial
    da Terra (a Terra gira para leste), a ~15 graus por hora.
    """
    import math

    teme_point = (7000.0, 0.0, 0.0)  # sobre o equador, fixo no inercial
    jd = 2_461_276.5  # meia-noite juliana arbitrária

    lon_start = math.degrees(math.atan2(*reversed(
        coordinates.teme_to_ecef(teme_point, jd, 0.0)[:2]
    )))
    lon_1h = math.degrees(math.atan2(*reversed(
        coordinates.teme_to_ecef(teme_point, jd, 1.0 / 24.0)[:2]
    )))

    drift = (lon_1h - lon_start + 180.0) % 360.0 - 180.0  # normaliza p/ [-180, 180)
    assert drift == pytest.approx(-15.04, abs=0.1), (
        "longitude deveria DIMINUIR ~15.04 graus/hora (a Terra gira para leste); "
        "um valor positivo indica sinal invertido na rotação TEME->ECEF"
    )


def test_substellite_point_is_directly_overhead_itself():
    """A latitude/longitude geodésica calculada tem que ser exatamente o lugar
    de onde o satélite é visto no zênite. Amarra ecef_to_geodetic e
    ecef_to_topocentric uma na outra, em termos absolutos."""
    satrec = build_satellite(from_tle_lines(ISS_LINE1, ISS_LINE2, ISS_NAME))
    info = get_tracking_info(satrec, ISS_NAME, when=ISS_EPOCH, station=STATION)

    substellite = {
        "name": "sub",
        "latitude_deg": info.geodetic.latitude_deg,
        "longitude_deg": info.geodetic.longitude_deg,
        "altitude_m": 0.0,
    }
    seen_from_below = get_tracking_info(
        satrec, ISS_NAME, when=ISS_EPOCH, station=substellite
    )
    assert seen_from_below.topocentric.elevation_deg == pytest.approx(90.0, abs=0.01)
    assert seen_from_below.topocentric.range_km == pytest.approx(
        info.geodetic.altitude_km, abs=1.0
    )


# --- Sanidade física --------------------------------------------------------

def test_iss_altitude_is_in_low_earth_orbit():
    satrec = build_satellite(from_tle_lines(ISS_LINE1, ISS_LINE2, ISS_NAME))
    info = get_tracking_info(satrec, ISS_NAME, when=ISS_EPOCH, station=STATION)
    assert 300.0 < info.geodetic.altitude_km < 500.0


def test_geodetic_coordinates_stay_in_valid_range():
    satrec = build_satellite(from_tle_lines(ISS_LINE1, ISS_LINE2, ISS_NAME))
    for minutes in range(0, 95, 5):  # uma órbita completa da ISS (~92 min)
        info = get_tracking_info(
            satrec, ISS_NAME,
            when=ISS_EPOCH + timedelta(minutes=minutes),
            station=STATION,
        )
        assert -90.0 <= info.geodetic.latitude_deg <= 90.0
        assert -180.0 <= info.geodetic.longitude_deg <= 180.0
        assert 0.0 <= info.topocentric.azimuth_deg < 360.0
        assert -90.0 <= info.topocentric.elevation_deg <= 90.0


def test_iss_inclination_bounds_the_ground_track():
    """A ISS tem inclinação de 51.6 graus, então nunca sobrevoa latitudes
    além disso — uma checagem barata que pegaria eixos trocados."""
    satrec = build_satellite(from_tle_lines(ISS_LINE1, ISS_LINE2, ISS_NAME))
    latitudes = [
        get_tracking_info(
            satrec, ISS_NAME,
            when=ISS_EPOCH + timedelta(minutes=m),
            station=STATION,
        ).geodetic.latitude_deg
        for m in range(0, 95, 5)
    ]
    assert max(abs(lat) for lat in latitudes) <= 52.5


def test_predicted_passes_are_internally_consistent():
    satrec = build_satellite(from_tle_lines(ISS_LINE1, ISS_LINE2, ISS_NAME))
    passes = predict_passes(
        satrec, ISS_NAME, station=STATION,
        start=ISS_EPOCH, search_window_hours=24.0, min_elevation_deg=0.0,
    )

    assert passes, "a ISS deve ter passagens visíveis em 24h a partir de São Paulo"

    previous_los = None
    for p in passes:
        assert p.aos_time < p.culmination_time < p.los_time
        assert p.max_elevation_deg > 0.0
        # Uma passagem de LEO dura no máximo poucos minutos.
        assert 0 < p.duration_seconds <= 20 * 60
        # A culminação é o ponto mais alto: mais alta que as duas pontas.
        for edge in (p.aos_time, p.los_time):
            edge_elev = get_tracking_info(
                satrec, ISS_NAME, when=edge, station=STATION
            ).topocentric.elevation_deg
            assert p.max_elevation_deg >= edge_elev
        # E as passagens não se sobrepõem, em ordem cronológica.
        if previous_los is not None:
            assert p.aos_time > previous_los
        previous_los = p.los_time


def test_min_elevation_mask_filters_low_passes():
    """Subir a máscara de elevação só pode reduzir o conjunto de passagens."""
    satrec = build_satellite(from_tle_lines(ISS_LINE1, ISS_LINE2, ISS_NAME))
    kwargs = dict(station=STATION, start=ISS_EPOCH, search_window_hours=24.0)

    all_passes = predict_passes(satrec, ISS_NAME, min_elevation_deg=0.0, **kwargs)
    high_passes = predict_passes(satrec, ISS_NAME, min_elevation_deg=20.0, **kwargs)

    assert len(high_passes) <= len(all_passes)
    assert all(p.max_elevation_deg > 20.0 for p in high_passes)
