import socket
import threading

import pytest

from mgm8.application.tracking_service import TrackingService
from mgm8.infrastructure.mock_rotor import MockRotor
from mgm8.rotctld.server import RotctldServer


class RaisingRotor(MockRotor):
    def move_to(self, position):
        raise RuntimeError("rotor físico indisponível")


def start_server(rotor):
    service = TrackingService(rotor)
    server = RotctldServer("127.0.0.1", 0, service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


@pytest.fixture
def server():
    instance = start_server(MockRotor())
    yield instance
    instance.shutdown()
    instance.server_close()


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


def test_p_command_returns_current_position(server):
    responses = send_lines(server.server_address, "p", "q")

    assert responses == ["0.000000", "0.000000"]


def test_uppercase_p_command_sets_target_and_acks(server):
    responses = send_lines(server.server_address, "P 180.5 45.25", "p", "q")

    assert responses[0] == "RPRT 0"
    assert responses[1:] == ["180.500000", "45.250000"]


def test_dump_state_command_returns_rotor_capabilities(server):
    # O backend NET rotctl do hamlib (rotctl -m 2, e o gpredict por baixo dos
    # panos) manda esse comando ao abrir a conexao e exige essa resposta
    # exata antes de aceitar qualquer outro comando -- sem isso, o cliente
    # fecha com "Protocol error" mesmo com o socket TCP continuando aberto.
    responses = send_lines(server.server_address, "\\dump_state", "q")

    assert responses == [
        "1",
        "1",
        "0.000000",
        "360.000000",
        "0.000000",
        "90.000000",
        "0",
        "rot_type=AzEl",
        "done",
    ]


def test_stop_command_acks(server):
    responses = send_lines(server.server_address, "S", "q")

    assert responses == ["RPRT 0"]


def test_unknown_command_gets_generic_ack_instead_of_dropping_connection(server):
    responses = send_lines(server.server_address, "X", "p", "q")

    assert responses[0] == "RPRT 0"
    assert responses[1:] == ["0.000000", "0.000000"]


def test_malformed_p_command_returns_error_without_dropping_connection(server):
    responses = send_lines(server.server_address, "P not-a-number", "p", "q")

    assert responses[0] == "RPRT -1"
    assert responses[1:] == ["0.000000", "0.000000"]


def test_service_exception_returns_error_instead_of_closing_connection():
    server = start_server(RaisingRotor())
    try:
        responses = send_lines(server.server_address, "P 10 10", "q")
    finally:
        server.shutdown()
        server.server_close()

    assert responses == ["RPRT -1"]
