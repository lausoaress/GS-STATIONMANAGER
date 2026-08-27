"""Testes da API de leitura do TC Scheduler.

O que importa aqui é o contrato com o painel: os caminhos, os códigos de
status e o formato das respostas. O conteúdo em si é `station_data`, testado
à parte — por isso o dublê.

O teste que mais paga é o do 404: ele é a diferença entre "esse satélite não
existe" e "não deu para perguntar", e o cliente do outro lado depende dela.
"""

import pytest

from tc_scheduler.api import create_app


class FakeStationData:
    """Substitui o acesso ao banco: os testes são sobre a API, não sobre SQL."""

    def __init__(self, snapshot=None, detail=None, refresh=None, available=True):
        self._snapshot = snapshot or {"satellites": [], "database_available": True}
        self._detail = detail
        self._refresh = refresh or {"database_available": True, "results": [], "updated": 0}
        self._available = available
        self.refresh_calls = 0

    def snapshot(self):
        return self._snapshot

    def satellite_detail(self, code):
        if self._detail is None or self._detail.get("code") != code:
            return None
        return self._detail

    def refresh_orbital_data(self):
        self.refresh_calls += 1
        return self._refresh

    def is_available(self):
        return self._available


@pytest.fixture
def client_for():
    def build(station_data):
        app = create_app(station_data)
        app.config.update(TESTING=True)
        return app.test_client()

    return build


def test_health_reporta_banco_disponivel(client_for):
    response = client_for(FakeStationData(available=True)).get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "database_available": True}


def test_health_responde_mesmo_com_banco_fora(client_for):
    """A API estar de pé e o banco responder são fatos separados: o compose
    precisa poder distinguir "ainda subindo" de "subiu sem o Postgres"."""
    response = client_for(FakeStationData(available=False)).get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "database_available": False}


def test_station_devolve_o_snapshot(client_for):
    snapshot = {"satellites": [{"code": "SAT-001"}], "database_available": True}

    response = client_for(FakeStationData(snapshot=snapshot)).get("/api/station")

    assert response.status_code == 200
    assert response.get_json() == snapshot


def test_station_responde_200_com_banco_fora(client_for):
    """Banco fora do ar é um estado a mostrar na tela, não erro do cliente."""
    snapshot = {"satellites": [], "database_available": False}

    response = client_for(FakeStationData(snapshot=snapshot)).get("/api/station")

    assert response.status_code == 200
    assert response.get_json()["database_available"] is False


def test_satellite_devolve_o_detalhe(client_for):
    detail = {"code": "SAT-001", "name": "Alfa", "database_available": True}

    response = client_for(FakeStationData(detail=detail)).get("/api/satellite/SAT-001")

    assert response.status_code == 200
    assert response.get_json() == detail


def test_satellite_inexistente_e_404(client_for):
    """404 e não 200-com-nulo: é o que deixa o cliente distinguir "não existe"
    de "sem acesso" sem inspecionar o corpo."""
    response = client_for(FakeStationData()).get("/api/satellite/NAO-EXISTE")

    assert response.status_code == 404
    assert "error" in response.get_json()


def test_refresh_chama_a_revalidacao_e_so_por_post(client_for):
    station_data = FakeStationData(refresh={"database_available": True, "results": [], "updated": 3})
    client = client_for(station_data)

    assert client.get("/api/tle/refresh").status_code == 405
    assert station_data.refresh_calls == 0

    response = client.post("/api/tle/refresh")

    assert response.status_code == 200
    assert response.get_json()["updated"] == 3
    assert station_data.refresh_calls == 1
