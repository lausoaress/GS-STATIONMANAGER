"""Teste de integração: prova o pipeline completo Satellite Tracker -> GRS
Manager -> Station Manager -> rotor, com os dois serviços realmente
conversando por ZMQ (não em processo único, como os testes unitários de cada
lado em isolado).
"""

import socket
import threading
from dataclasses import dataclass

import pytest

zmq = pytest.importorskip("zmq")

from grs_manager.adapters.station_manager_zmq import StationManagerZmqClient  # noqa: E402
from grs_manager.rotctld.server import RotctldServer as GrsRotctldServer  # noqa: E402
from grs_manager.status.app import create_app  # noqa: E402
from mgm8.application.tracking_service import TrackingService  # noqa: E402
from mgm8.infrastructure.mock_rotor import MockRotor  # noqa: E402
from mgm8.rotor_zmq.server import RotorZmqServer  # noqa: E402


def send_lines(address, *lines):
    with socket.create_connection(address, timeout=2) as sock:
        sock.sendall(("\n".join(lines) + "\n").encode("ascii"))
        sock.settimeout(2)
        chunks = []
        try:
            while True:
                data = sock.recv(4096)
                if not data:
                    break
                chunks.append(data)
        except TimeoutError:
            pass
    return b"".join(chunks).decode("ascii").splitlines()


@dataclass
class Pipeline:
    grs_manager: GrsRotctldServer
    station_manager_endpoint: str


@pytest.fixture
def pipeline():
    station_manager = RotorZmqServer("tcp://127.0.0.1:0", TrackingService(MockRotor()))
    station_manager_thread = threading.Thread(target=station_manager.serve_forever, daemon=True)
    station_manager_thread.start()

    client = StationManagerZmqClient(station_manager.endpoint)
    grs_manager = GrsRotctldServer("127.0.0.1", 0, client)
    grs_manager_thread = threading.Thread(target=grs_manager.serve_forever, daemon=True)
    grs_manager_thread.start()

    yield Pipeline(grs_manager, station_manager.endpoint)

    grs_manager.shutdown()
    grs_manager.server_close()
    client.close()
    station_manager.stop()
    station_manager.close()


def test_set_and_read_position_through_both_hops(pipeline):
    responses = send_lines(pipeline.grs_manager.server_address, "P 123.0 45.0", "p", "q")

    assert responses[0] == "RPRT 0"
    assert responses[1:] == ["123.000000", "45.000000"]


def test_clamp_applies_at_station_manager_even_via_grs_manager(pipeline):
    responses = send_lines(pipeline.grs_manager.server_address, "P 400 -10", "p", "q")

    assert responses[0] == "RPRT 0"
    assert responses[1:] == ["360.000000", "0.000000"]


def test_dump_state_handshake_works_through_grs_manager(pipeline):
    responses = send_lines(pipeline.grs_manager.server_address, "\\dump_state", "q")

    assert responses[-1] == "done"
    assert responses[0] == "1"


def test_status_app_reflects_real_pipeline_health(pipeline):
    """O painel lê a posição do rotor de verdade, atravessando os dois hops.

    `rotor_connected` só é True se a cadeia inteira (painel -> Station Manager
    -> rotor) respondeu — é essa a saúde que a página reporta.
    """
    status_client = StationManagerZmqClient(pipeline.station_manager_endpoint, timeout_ms=1000)
    try:
        app = create_app(status_client)
        client = app.test_client()

        assert client.get("/health").get_json()["rotor_connected"] is True

        with socket.create_connection(pipeline.grs_manager.server_address, timeout=2) as sock:
            sock.sendall(b"P 55.5 12.5\n")
            sock.recv(4096)

            health = client.get("/health").get_json()
            assert health["rotor_position"] == {"azimuth_degrees": 55.5, "elevation_degrees": 12.5}
    finally:
        status_client.close()
