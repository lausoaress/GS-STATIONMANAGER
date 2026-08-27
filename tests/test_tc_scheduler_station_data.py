"""Testes da montagem do detalhe de satélite do painel.

As funções cobertas aqui são as que decidem o que o operador vê: como os
telecomandos de uma passagem são separados entre "ainda vai sair" e "já saiu",
e o que acontece com um comando que ainda não tem passagem. Nada aqui toca no
banco — a consulta em si é SQL, e testá-la contra um Postgres de mentira só
provaria que o SQLAlchemy sabe montar strings.
"""

from datetime import datetime, timezone

from tc_scheduler import station_data


def _pass_row(pass_id=1):
    when = datetime(2026, 8, 25, 3, 12, tzinfo=timezone.utc)
    return {
        "id": pass_id,
        "aos_time": when,
        "los_time": when,
        "culmination_time": when,
        "max_elevation_deg": 77.1,
        "status": "planned",
        "status_message": None,
    }


def _telecommand(tc_id, status, command_type="PING", priority=5):
    return {"id": tc_id, "command_type": command_type, "status": status, "priority": priority}


def test_pass_detail_splits_pending_from_sent():
    detail = station_data._pass_detail(
        _pass_row(),
        [_telecommand(1, "pending"), _telecommand(2, "queued"), _telecommand(3, "sent")],
    )

    assert [tc["id"] for tc in detail["pending"]] == [1, 2]
    assert [tc["id"] for tc in detail["sent"]] == [3]
    assert detail["telecommand_count"] == 3


def test_pass_detail_counts_queued_as_pending():
    """'queued' é o que o Scheduler marca ao comprometer a passagem: tem hora
    para sair, mas ainda não saiu."""
    detail = station_data._pass_detail(_pass_row(), [_telecommand(1, "queued")])

    assert len(detail["pending"]) == 1
    assert detail["sent"] == []


def test_pass_detail_ignores_terminal_statuses_in_both_columns():
    """Confirmado e falho são histórico do comando, não fila nem voo."""
    detail = station_data._pass_detail(
        _pass_row(), [_telecommand(1, "confirmed"), _telecommand(2, "failed")]
    )

    assert detail["pending"] == []
    assert detail["sent"] == []
    assert detail["telecommand_count"] == 2


def test_satellite_to_dict_reports_untrackable_without_orbital_data():
    row = {
        "id": 1, "name": "Catarina-A1", "code": "SAT-OBS-001", "status": "maintenance",
        "norad_id": None, "is_trackable": False, "azimuth_deg": None, "elevation_deg": None,
        "range_km": None, "is_visible": False, "status_message": None, "checked_at": None,
    }

    result = station_data._satellite_to_dict(row, None)

    assert result["is_trackable"] is False
    assert result["next_pass"] is None
    assert result["elevation_degrees"] is None


def test_station_to_dict_exposes_configured_coordinates():
    result = station_data._station_to_dict(
        {"name": "Estação", "latitude_deg": -27.6, "longitude_deg": -48.5, "altitude_m": 10.0}
    )

    assert result == {
        "name": "Estação",
        "latitude_degrees": -27.6,
        "longitude_degrees": -48.5,
        "altitude_m": 10.0,
    }


def test_refresh_result_carries_the_source_on_success():
    satellite = {"name": "FloripaSat-1", "code": "SAT-001", "norad_id": 44885}

    result = station_data._refresh_result(satellite, "updated", None, source="omm")

    assert result["status"] == "updated"
    assert result["source"] == "omm"
    assert result["message"] is None


def test_refresh_result_carries_the_reason_on_failure():
    """A falha de um satélite precisa chegar à tela: revalidar é ir à rede, e
    a rede falha de formas que o operador tem de conseguir ler."""
    satellite = {"name": "ISS", "code": "SAT-ISS", "norad_id": 25544}

    result = station_data._refresh_result(satellite, "failed", "CelesTrak indisponível")

    assert result["status"] == "failed"
    assert result["message"] == "CelesTrak indisponível"
    assert result["source"] is None
