#!/usr/bin/env python3
"""Exercita o fluxo autônomo da estação sem esperar uma passagem real.

Uma passagem de LEO acontece algumas vezes por dia em horários que a órbita
decide, o que torna difícil observar o ciclo completo (planejamento -> AOS ->
apontamento -> LOS) enquanto se está desenvolvendo. Este script encurta essa
espera.

Roda de dentro do container do TC Scheduler, que já tem banco, ZMQ e a
biblioteca de tracking:

    docker compose exec tc-scheduler python tools/station_demo.py prepare
    docker compose exec tc-scheduler python tools/station_demo.py simulate-pass
    docker compose exec tc-scheduler python tools/station_demo.py reset

O que é real e o que é encenado:

- `prepare` e `reset` só mexem em dados de entrada (NORAD ID, fila de
  telecomandos). O planejamento que vem depois é o de verdade, com dados
  orbitais do CelesTrak.
- `simulate-pass` INSERE uma janela artificial começando agora. Isso pula o
  planejador, mas exercita todo o resto de verdade: a ativação no AOS, o envio
  ao Station Manager, o apontamento e o encerramento no LOS. Os ângulos vêm da
  posição real do satélite naquele instante.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from spacelab_tracking import build_satellite, from_tle_lines, get_orbital_data, get_tracking_info
from tc_scheduler import config, db


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _fetch_satellite(conn, code: str) -> dict:
    row = conn.execute(text("""
        SELECT id, name, code, norad_id, tle_line1, tle_line2
        FROM satellites WHERE code = :code
    """), {"code": code}).mappings().first()
    if row is None:
        sys.exit(f"Satélite '{code}' não existe. Veja os cadastrados com: "
                 f"python -m tc_scheduler.monitor")
    return dict(row)


def cmd_prepare(engine, args) -> None:
    """Dá ao satélite dados orbitais e devolve os telecomandos à fila."""
    with engine.begin() as conn:
        satellite = _fetch_satellite(conn, args.code)

        if args.norad_id is not None:
            conn.execute(text("UPDATE satellites SET norad_id = :norad WHERE id = :id"),
                         {"norad": args.norad_id, "id": satellite["id"]})
            print(f"  {satellite['name']}: norad_id = {args.norad_id}")
        elif satellite["norad_id"] is None and not satellite["tle_line1"]:
            sys.exit(f"{satellite['name']} não tem dado orbital. Passe --norad-id "
                     f"(ex.: 25544 para a ISS).")
        else:
            print(f"  {satellite['name']}: já tem dado orbital "
                  f"(NORAD {satellite['norad_id']})")

        # Desfaz o plano anterior para que o próximo replanejamento comece limpo.
        conn.execute(text("DELETE FROM scheduled_passes"))
        released = conn.execute(text("""
            UPDATE telecommands
            SET status = 'pending', scheduled_pass_id = NULL
            WHERE satellite_id = :id AND status IN ('queued', 'failed')
        """), {"id": satellite["id"]}).rowcount

        pending = conn.execute(text("""
            SELECT COUNT(*) FROM telecommands
            WHERE satellite_id = :id AND status = 'pending'
        """), {"id": satellite["id"]}).scalar_one()

    print(f"  {released} telecomandos devolvidos à fila ({pending} pendentes no total)")
    print()
    print("Agora force um replanejamento e acompanhe:")
    print("  docker compose restart tc-scheduler")
    print("  docker compose exec tc-scheduler python -m tc_scheduler.monitor --watch")


def cmd_simulate_pass(engine, args) -> None:
    """Cria uma janela artificial começando agora, com ângulos reais."""
    with engine.begin() as conn:
        satellite = _fetch_satellite(conn, args.code)

    if satellite["tle_line1"] and satellite["tle_line2"]:
        orbital_data = from_tle_lines(
            satellite["tle_line1"], satellite["tle_line2"], satellite["name"]
        )
    elif satellite["norad_id"]:
        orbital_data = get_orbital_data(satellite["norad_id"])
    else:
        sys.exit(f"{satellite['name']} não tem dado orbital. Rode antes: "
                 f"station_demo.py prepare --code {args.code} --norad-id 25544")

    satrec = build_satellite(orbital_data)
    start = now_utc()
    end = start + timedelta(seconds=args.duration)
    middle = start + timedelta(seconds=args.duration / 2)

    def look(when):
        return get_tracking_info(
            satrec, satellite["name"], when=when, station=config.GROUND_STATION
        ).topocentric

    aos, culmination, los = look(start), look(middle), look(end)

    with engine.begin() as conn:
        # Uma passagem ativa por vez: a estação tem um rotor só. Os
        # telecomandos das passagens canceladas voltam à fila, senão ficariam
        # presos em 'queued' numa janela que não vai acontecer — e a janela
        # nova nasceria sem nada a transmitir.
        cancelled = conn.execute(text("""
            UPDATE scheduled_passes SET status = 'cancelled'
            WHERE status IN ('planned', 'active')
            RETURNING id
        """)).scalars().all()
        if cancelled:
            db.release_telecommands(conn, cancelled)
        pass_id = conn.execute(text("""
            INSERT INTO scheduled_passes (
                satellite_id, aos_time, los_time, culmination_time,
                max_elevation_deg, aos_azimuth_deg, los_azimuth_deg,
                data_source, status, status_message
            ) VALUES (
                :satellite_id, :aos, :los, :culmination,
                :max_elevation, :aos_az, :los_az,
                :source, 'planned', 'janela sintética criada por tools/station_demo.py'
            ) RETURNING id
        """), {
            "satellite_id": satellite["id"],
            "aos": start, "los": end, "culmination": middle,
            "max_elevation": culmination.elevation_deg,
            "aos_az": aos.azimuth_deg, "los_az": los.azimuth_deg,
            "source": orbital_data.source,
        }).scalar_one()

        assigned = conn.execute(text("""
            UPDATE telecommands SET status = 'queued', scheduled_pass_id = :pass_id
            WHERE satellite_id = :sat AND status = 'pending' AND scheduled_pass_id IS NULL
        """), {"pass_id": pass_id, "sat": satellite["id"]}).rowcount

    print(f"Janela sintética #{pass_id} para {satellite['name']}:")
    print(f"  AOS  {start:%H:%M:%S}  az {aos.azimuth_deg:6.1f}  el {aos.elevation_deg:6.1f}")
    print(f"  LOS  {end:%H:%M:%S}  az {los.azimuth_deg:6.1f}  el {los.elevation_deg:6.1f}")
    print(f"  {assigned} telecomandos vinculados   (duração {args.duration}s)")
    print()

    if culmination.elevation_deg < 0:
        print("O satélite está abaixo do horizonte agora. Com a elevação mínima")
        print("padrão (0), o Station Manager vai calcular o apontamento mas não vai")
        print("comandar o rotor — seguir um alvo do outro lado da Terra só")
        print("castigaria o hardware. Para ver o rotor se mexer mesmo assim:")
        print()
        print("  STATION_POINTING_MIN_ELEVATION=-90 docker compose up -d station-manager")
        print()
        print("(se já subiu assim, ignore: o monitor mostra 'comandando rotor: SIM')")
    else:
        print("O satélite está acima do horizonte: o rotor vai acompanhá-lo de verdade.")

    print()
    print("Acompanhe com:")
    print("  docker compose exec tc-scheduler python -m tc_scheduler.monitor --watch")


def cmd_reset(engine, args) -> None:
    """Apaga o plano e devolve todos os telecomandos à fila."""
    with engine.begin() as conn:
        passes = conn.execute(text("DELETE FROM scheduled_passes")).rowcount
        released = conn.execute(text("""
            UPDATE telecommands
            SET status = 'pending', scheduled_pass_id = NULL
            WHERE status = 'queued'
        """)).rowcount
    print(f"  {passes} passagens apagadas, {released} telecomandos devolvidos à fila")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Exercita o fluxo autônomo da estação.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="Dá dados orbitais e enfileira telecomandos")
    prepare.add_argument("--code", default="SAT-001", help="Código do satélite")
    prepare.add_argument("--norad-id", type=int, default=None,
                         help="NORAD ID a atribuir (ex.: 25544 para a ISS)")
    prepare.set_defaults(func=cmd_prepare)

    simulate = sub.add_parser("simulate-pass", help="Cria uma janela começando agora")
    simulate.add_argument("--code", default="SAT-001", help="Código do satélite")
    simulate.add_argument("--duration", type=float, default=120.0,
                          help="Duração da janela em segundos (padrão: 120)")
    simulate.set_defaults(func=cmd_simulate_pass)

    reset = sub.add_parser("reset", help="Apaga o plano e devolve os telecomandos à fila")
    reset.set_defaults(func=cmd_reset)

    args = parser.parse_args()

    engine = db.build_engine(config.DATABASE_URL)
    try:
        args.func(engine, args)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
