"""Configuração do TC Scheduler, toda por variável de ambiente.

As coordenadas da estação e o cache de dados orbitais vêm do
`spacelab_tracking.config` (variáveis GS_* e TRACKING_*), para que Scheduler e
Station Manager não possam divergir sobre de onde a estação observa.
"""

from __future__ import annotations

import os

from spacelab_tracking import config as tracking_config

# --- Banco de dados ---------------------------------------------------------
# Mesma variável que o TC Generator usa: é o mesmo banco.
DATABASE_URL = os.getenv(
    "PG_DATABASE_URL",
    "postgresql+psycopg2://admin:admin@postgres:5432/tc_generator",
)

# --- Station Manager --------------------------------------------------------
STATION_MANAGER_ADDRESS = os.getenv(
    "STATION_MANAGER_ZMQ_ADDRESS", "tcp://station-manager:5580"
)
ZMQ_REQUEST_TIMEOUT_MS = int(os.getenv("ZMQ_REQUEST_TIMEOUT_MS", "3000"))

# --- Ritmo do laço principal ------------------------------------------------
# O tick é curto porque é ele que determina a precisão com que a estação assume
# uma passagem no AOS. Nada aqui é tempo real: o apontamento fica com o Station
# Manager, justamente para que um replanejamento pesado não atrase o rotor.
TICK_SECONDS = float(os.getenv("SCHEDULER_TICK_SECONDS", "1"))

# Replanejar é caro (propagar N satélites por HORIZON_HOURS) e o resultado muda
# devagar: TLEs novos chegam a cada poucas horas.
REPLAN_INTERVAL_SECONDS = float(os.getenv("SCHEDULER_REPLAN_INTERVAL_SECONDS", "300"))
HORIZON_HOURS = float(os.getenv("SCHEDULER_HORIZON_HOURS", "24"))

# Atualização da posição corrente de cada satélite no banco (visão do painel).
TRACKING_POLL_INTERVAL_SECONDS = float(os.getenv("TRACKING_POLL_INTERVAL_SECONDS", "30"))

# Passagens curtas ou muito rasantes custam mais em movimentação de antena do
# que rendem em tempo de link útil.
MIN_PASS_DURATION_SECONDS = float(os.getenv("SCHEDULER_MIN_PASS_DURATION_SECONDS", "60"))
MIN_PASS_MAX_ELEVATION_DEG = float(os.getenv("SCHEDULER_MIN_PASS_ELEVATION_DEG", "5"))

# --- API de leitura ---------------------------------------------------------
# O painel do GRS Manager consome isto no lugar de abrir o Postgres. Porta
# vizinha à 5590 do painel, para as duas ficarem juntas na tabela de acessos.
#
# O default de host é 0.0.0.0, e não 127.0.0.1: este serviço é feito para rodar
# em container e ser consultado por outro (o default de DATABASE_URL já aponta
# para o hostname `postgres`). Um bind em localhost aqui não aceitaria conexão
# de fora do container e o painel ficaria sem satélites sem dizer por quê.
API_HOST = os.getenv("SCHEDULER_API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("SCHEDULER_API_PORT", "5591"))
API_ENABLED = os.getenv("SCHEDULER_API_ENABLED", "1").lower() not in ("0", "false", "no")

# --- Estação terrestre ------------------------------------------------------
GROUND_STATION = tracking_config.GROUND_STATION
MIN_ELEVATION_DEG = tracking_config.MIN_ELEVATION_DEG
