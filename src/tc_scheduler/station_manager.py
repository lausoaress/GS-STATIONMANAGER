"""Cliente ZMQ REQ para o Station Manager.

Espelha `grs_manager.adapters.station_manager_zmq`, que fala o mesmo protocolo
do lado do Control Desktop — inclusive na limitação: um REQ que estoura o
timeout fica num estado inconsistente (o ZMQ espera a resposta que nunca veio),
e a única saída é recriar o socket. Por isso `_request` recria a conexão ao
detectar timeout, em vez de deixar o cliente inutilizável até o processo
reiniciar.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

import zmq

logger = logging.getLogger(__name__)


class StationManagerError(RuntimeError):
    """O Station Manager respondeu, mas recusou o comando."""


class StationManagerUnavailable(RuntimeError):
    """O Station Manager não respondeu no tempo esperado."""


class StationManagerClient:
    def __init__(self, address: str, request_timeout_ms: int = 3000) -> None:
        self._address = address
        self._request_timeout_ms = request_timeout_ms
        # Context dedicado, pelo mesmo motivo documentado no RotorZmqServer.
        self._context = zmq.Context()
        self._lock = threading.Lock()
        self._socket: Optional[zmq.Socket] = None
        self._connect()

    def _connect(self) -> None:
        self._socket = self._context.socket(zmq.REQ)
        self._socket.setsockopt(zmq.RCVTIMEO, self._request_timeout_ms)
        self._socket.setsockopt(zmq.LINGER, 0)
        self._socket.connect(self._address)

    def _reconnect(self) -> None:
        if self._socket is not None:
            self._socket.close()
        self._connect()

    def _request(self, message: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            try:
                self._socket.send_json(message)
                reply = self._socket.recv_json()
            except zmq.Again as error:
                # O socket REQ ficou esperando uma resposta que não veio; sem
                # recriá-lo, todo pedido seguinte falharia por estar fora de
                # ordem no ciclo send/recv.
                self._reconnect()
                raise StationManagerUnavailable(
                    f"Station Manager não respondeu em {self._request_timeout_ms} ms"
                ) from error

        if not isinstance(reply, dict):
            raise StationManagerError(f"resposta inesperada: {reply!r}")
        if not reply.get("ok"):
            raise StationManagerError(reply.get("error", "erro desconhecido"))
        return reply

    # --- Rastreamento autônomo ---------------------------------------------

    def track_satellite(self, orbital_data: dict, until_iso: str,
                        satellite_name: Optional[str] = None) -> dict[str, Any]:
        """Entrega a passagem inteira ao Station Manager, numa ordem só."""
        reply = self._request({
            "cmd": "track_satellite",
            "orbital_data": orbital_data,
            "until": until_iso,
            "satellite_name": satellite_name,
        })
        return reply["tracking"]

    def get_tracking(self) -> Optional[dict[str, Any]]:
        return self._request({"cmd": "get_tracking"})["tracking"]

    def stop_tracking(self) -> None:
        self._request({"cmd": "stop_tracking"})

    # --- Apontamento manual -------------------------------------------------

    def get_position(self) -> dict[str, Any]:
        reply = self._request({"cmd": "get_position"})
        return {
            "azimuth_degrees": reply["azimuth_degrees"],
            "elevation_degrees": reply["elevation_degrees"],
        }

    def park(self) -> None:
        self._request({"cmd": "park"})

    def close(self) -> None:
        with self._lock:
            if self._socket is not None:
                self._socket.close()
                self._socket = None
            self._context.term()
