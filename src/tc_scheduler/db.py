"""Acesso ao banco do TC Generator, em SQL puro.

Não importa os modelos ORM do TC Generator de propósito: eles vivem noutro
repositório, com o seu próprio ciclo de vida, e arrastá-los para cá acoplaria
duas imagens Docker por código Python além de trazer o Flask para um processo
que não é web. O contrato entre os dois é o schema do banco, e é só isso que
este módulo assume.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrackableSatellite:
    """Satélite que a estação consegue rastrear e que tem trabalho pendente."""

    id: int
    name: str
    code: str
    norad_id: Optional[int]
    tle_line1: Optional[str]
    tle_line2: Optional[str]
    pending_telecommands: int
    max_priority: int

    @property
    def has_manual_tle(self) -> bool:
        return bool(self.tle_line1 and self.tle_line2)


def build_engine(database_url: str) -> Engine:
    # pool_pre_ping porque este processo fica horas ocioso entre ciclos e o
    # Postgres pode ter derrubado a conexão nesse meio tempo.
    return create_engine(database_url, pool_pre_ping=True, pool_size=2, max_overflow=2)


# --- Leitura ----------------------------------------------------------------

# Um telecomando ainda precisa de passagem quando está solto na fila, ou quando
# a passagem a que foi vinculado não vai mais acontecer. Um comando vinculado a
# uma passagem já concluída NÃO conta: sem os encoders não há como saber se foi
# de fato transmitido, mas reagendá-lo a cada ciclo faria a estação repetir a
# mesma passagem para sempre.
_NEEDS_A_PASS = """
    t.status IN ('pending', 'queued')
    AND (
        t.scheduled_pass_id IS NULL
        OR EXISTS (
            SELECT 1 FROM scheduled_passes sp
            WHERE sp.id = t.scheduled_pass_id
              AND sp.status IN ('planned', 'cancelled', 'missed')
        )
    )
"""


def fetch_trackable_satellites(conn: Connection) -> list[TrackableSatellite]:
    """Satélites ativos, com dado orbital, e com telecomando esperando.

    Sem telecomando esperando não há o que agendar; sem dado orbital não há como
    prever passagem. Os dois filtros juntos definem o universo do planejamento.
    """
    rows = conn.execute(text(f"""
        SELECT s.id, s.name, s.code, s.norad_id, s.tle_line1, s.tle_line2,
               COUNT(t.id) AS pending_telecommands,
               COALESCE(MAX(t.priority), 0) AS max_priority
        FROM satellites s
        JOIN telecommands t
          ON t.satellite_id = s.id
         AND {_NEEDS_A_PASS}
        WHERE s.status = 'active'
          AND (s.norad_id IS NOT NULL
               OR (s.tle_line1 IS NOT NULL AND s.tle_line2 IS NOT NULL))
        GROUP BY s.id, s.name, s.code, s.norad_id, s.tle_line1, s.tle_line2
        ORDER BY s.id
    """)).mappings().all()
    return [TrackableSatellite(**row) for row in rows]


def fetch_satellites_with_orbital_data(conn: Connection) -> list[dict[str, Any]]:
    """Todos os satélites rastreáveis, tenham trabalho pendente ou não.

    Usado para manter a posição corrente no banco: o painel mostra onde cada
    satélite está, e isso não depende de haver telecomando na fila.
    """
    return [dict(row) for row in conn.execute(text("""
        SELECT id, name, code, norad_id, tle_line1, tle_line2
        FROM satellites
        WHERE status = 'active'
          AND (norad_id IS NOT NULL
               OR (tle_line1 IS NOT NULL AND tle_line2 IS NOT NULL))
        ORDER BY id
    """)).mappings().all()]


def fetch_pass_to_activate(conn: Connection, now: datetime) -> Optional[dict[str, Any]]:
    """Passagem planejada cuja janela já começou e ainda não terminou."""
    row = conn.execute(text("""
        SELECT p.id, p.satellite_id, p.aos_time, p.los_time, p.max_elevation_deg,
               s.name AS satellite_name, s.norad_id, s.tle_line1, s.tle_line2
        FROM scheduled_passes p
        JOIN satellites s ON s.id = p.satellite_id
        WHERE p.status = 'planned'
          AND p.aos_time <= :now
          AND p.los_time > :now
        ORDER BY p.aos_time
        LIMIT 1
    """), {"now": now}).mappings().first()
    return dict(row) if row else None


def fetch_active_pass(conn: Connection) -> Optional[dict[str, Any]]:
    row = conn.execute(text("""
        SELECT p.id, p.satellite_id, p.aos_time, p.los_time,
               s.name AS satellite_name, s.norad_id, s.tle_line1, s.tle_line2
        FROM scheduled_passes p
        JOIN satellites s ON s.id = p.satellite_id
        WHERE p.status = 'active'
        ORDER BY p.aos_time
        LIMIT 1
    """)).mappings().first()
    return dict(row) if row else None


# --- Escrita ----------------------------------------------------------------

def clear_planned_passes(conn: Connection) -> int:
    """Descarta o plano ainda não iniciado, devolvendo os telecomandos à fila.

    Só mexe em passagens 'planned': uma passagem 'active' está acontecendo
    agora, com o rotor em movimento, e replanejar não pode interrompê-la.

    Os telecomandos voltam a 'pending' explicitamente — o ON DELETE SET NULL da
    FK zera o vínculo, mas deixaria o status em 'queued', ou seja, comandos
    presos numa passagem que não existe mais.
    """
    conn.execute(text("""
        UPDATE telecommands
        SET status = 'pending', scheduled_pass_id = NULL
        WHERE scheduled_pass_id IN (SELECT id FROM scheduled_passes WHERE status = 'planned')
          AND status = 'queued'
    """))
    return conn.execute(text("DELETE FROM scheduled_passes WHERE status = 'planned'")).rowcount


def insert_planned_pass(conn: Connection, satellite_id: int, satellite_pass, tle_epoch,
                        data_source: str) -> int:
    return conn.execute(text("""
        INSERT INTO scheduled_passes (
            satellite_id, aos_time, los_time, culmination_time,
            max_elevation_deg, aos_azimuth_deg, los_azimuth_deg,
            tle_epoch, data_source, status
        ) VALUES (
            :satellite_id, :aos_time, :los_time, :culmination_time,
            :max_elevation_deg, :aos_azimuth_deg, :los_azimuth_deg,
            :tle_epoch, :data_source, 'planned'
        ) RETURNING id
    """), {
        "satellite_id": satellite_id,
        "aos_time": satellite_pass.aos_time,
        "los_time": satellite_pass.los_time,
        "culmination_time": satellite_pass.culmination_time,
        "max_elevation_deg": satellite_pass.max_elevation_deg,
        "aos_azimuth_deg": satellite_pass.aos_azimuth_deg,
        "los_azimuth_deg": satellite_pass.los_azimuth_deg,
        "tle_epoch": tle_epoch,
        "data_source": data_source,
    }).scalar_one()


def assign_telecommands_to_pass(conn: Connection, pass_id: int, satellite_id: int) -> int:
    """Compromete os telecomandos pendentes do satélite com esta passagem.

    Não marca 'sent': transmitir de fato é trabalho dos encoders/moduladores,
    que ainda não existem. 'queued' diz o que é verdade — o comando tem hora
    marcada para sair.
    """
    return conn.execute(text("""
        UPDATE telecommands
        SET status = 'queued', scheduled_pass_id = :pass_id
        WHERE satellite_id = :satellite_id
          AND status = 'pending'
          AND scheduled_pass_id IS NULL
    """), {"pass_id": pass_id, "satellite_id": satellite_id}).rowcount


def delete_pass(conn: Connection, pass_id: int) -> None:
    conn.execute(text("DELETE FROM scheduled_passes WHERE id = :pass_id"),
                 {"pass_id": pass_id})


def release_telecommands(conn: Connection, pass_ids: Iterable[int]) -> int:
    """Devolve à fila os telecomandos de passagens que não vão mais acontecer.

    Sem isso, um comando vinculado a uma passagem perdida ficaria preso em
    'queued' para sempre: o replanejamento não o veria como pendente e ele
    nunca seria reagendado.
    """
    pass_ids = list(pass_ids)
    if not pass_ids:
        return 0
    return conn.execute(text("""
        UPDATE telecommands
        SET status = 'pending', scheduled_pass_id = NULL
        WHERE scheduled_pass_id = ANY(:pass_ids)
          AND status = 'queued'
    """), {"pass_ids": pass_ids}).rowcount


def mark_pass(conn: Connection, pass_id: int, status: str,
              message: Optional[str] = None) -> None:
    conn.execute(text("""
        UPDATE scheduled_passes
        SET status = :status, status_message = :message
        WHERE id = :pass_id
    """), {"pass_id": pass_id, "status": status, "message": message})


def expire_missed_passes(conn: Connection, now: datetime) -> list[int]:
    """Marca como 'missed' as janelas que passaram sem a estação assumir.

    Distingue "não rastreamos" de "rastreamos e falhou" — sem isso, uma
    passagem perdida ficaria indistinguível de uma que nunca foi planejada.
    """
    rows = conn.execute(text("""
        UPDATE scheduled_passes
        SET status = 'missed',
            status_message = 'janela encerrada sem a estação assumir a passagem'
        WHERE status = 'planned' AND los_time <= :now
        RETURNING id
    """), {"now": now}).scalars().all()
    return list(rows)


def close_finished_passes(conn: Connection, now: datetime) -> list[int]:
    rows = conn.execute(text("""
        UPDATE scheduled_passes
        SET status = 'completed'
        WHERE status = 'active' AND los_time <= :now
        RETURNING id
    """), {"now": now}).scalars().all()
    return list(rows)


def upsert_tracking_status(conn: Connection, satellite_id: int, **fields: Any) -> None:
    """Grava a posição corrente de um satélite (uma linha por satélite).

    Estado atual, não histórico: por isso ON CONFLICT DO UPDATE em vez de
    INSERT. Um satélite que falha guarda o motivo em status_message, para que
    uma falha isolada fique visível em vez de virar silêncio.
    """
    columns = [
        "latitude_deg", "longitude_deg", "altitude_km",
        "azimuth_deg", "elevation_deg", "range_km",
        "is_visible", "tle_epoch", "data_source", "status_message", "checked_at",
    ]
    params = {"satellite_id": satellite_id}
    params.update({column: fields.get(column) for column in columns})
    params["is_visible"] = bool(fields.get("is_visible", False))

    assignments = ", ".join(f"{column} = EXCLUDED.{column}" for column in columns)
    conn.execute(text(f"""
        INSERT INTO satellite_tracking_status (satellite_id, {", ".join(columns)})
        VALUES (:satellite_id, {", ".join(f":{column}" for column in columns)})
        ON CONFLICT (satellite_id) DO UPDATE SET {assignments}
    """), params)
