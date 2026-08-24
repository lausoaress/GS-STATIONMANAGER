"""Monitor da estação: o que está sendo rastreado, e por quê.

O fluxo autônomo é difícil de observar porque acontece em três processos
diferentes — o plano fica no banco, a decisão no TC Scheduler, o apontamento no
Station Manager. Este monitor junta os três num retrato só, para que dê para
acompanhar uma passagem do AOS ao LOS sem ficar alternando entre logs e psql.

    python -m tc_scheduler.monitor          # retrato único
    python -m tc_scheduler.monitor --watch  # atualiza continuamente
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from typing import Any, Optional

from tc_scheduler import config, db
from tc_scheduler.station_manager import (
    StationManagerClient,
    StationManagerError,
    StationManagerUnavailable,
)

WIDTH = 78


def _fmt_time(value: Optional[datetime]) -> str:
    if value is None:
        return "--:--:--"
    return value.astimezone(timezone.utc).strftime("%H:%M:%S")


def _fmt_delta(target: Optional[datetime], now: datetime) -> str:
    """Quanto falta (ou faz), em linguagem de operador."""
    if target is None:
        return ""
    seconds = (target - now).total_seconds()
    sign, seconds = ("em " if seconds >= 0 else "há "), abs(seconds)
    if seconds < 60:
        return f"{sign}{seconds:.0f}s"
    if seconds < 3600:
        return f"{sign}{seconds / 60:.0f}min"
    return f"{sign}{seconds / 3600:.1f}h"


def _header(title: str) -> str:
    return f"\n{title}\n{'-' * WIDTH}"


def render(overview: dict[str, Any], tracking: Any, rotor: Any, now: datetime) -> str:
    lines = [
        "=" * WIDTH,
        f"  ESTAÇÃO {config.GROUND_STATION['name']}"
        f"   ({config.GROUND_STATION['latitude_deg']:.4f}, "
        f"{config.GROUND_STATION['longitude_deg']:.4f})"
        f"   {now.strftime('%d/%m %H:%M:%S')} UTC",
        "=" * WIDTH,
    ]

    # --- Satélites ---
    lines.append(_header("SATÉLITES"))
    for sat in overview["satellites"]:
        if sat["norad_id"]:
            orbital = f"NORAD {sat['norad_id']}"
        elif sat["has_manual_tle"]:
            orbital = "TLE manual"
        else:
            orbital = "sem dado orbital"

        lines.append(f"  {sat['name']:<16} {sat['code']:<14} {orbital}")

        if sat["status_message"]:
            lines.append(f"      ! {sat['status_message'][:WIDTH - 8]}")
        elif sat["elevation_deg"] is not None:
            visibility = "VISÍVEL" if sat["is_visible"] else "abaixo do horizonte"
            lines.append(
                f"      az {sat['azimuth_deg']:6.1f}   el {sat['elevation_deg']:6.1f}   "
                f"dist {sat['range_km']:7.0f} km   {visibility}"
            )
            lines.append(
                f"      sobre  lat {sat['latitude_deg']:7.2f}  lon {sat['longitude_deg']:7.2f}"
                f"  alt {sat['altitude_km']:5.0f} km   [{sat['data_source']}]"
            )
        elif orbital == "sem dado orbital":
            lines.append("      (preencha norad_id para habilitar o rastreamento)")
        else:
            lines.append("      (aguardando o primeiro ciclo de rastreamento)")

    # --- Plano ---
    lines.append(_header("PLANO DE PASSAGENS"))
    if not overview["plan"]:
        lines.append("  (nenhuma passagem planejada)")
    for p in overview["plan"]:
        marker = ">>" if p["status"] == "active" else "  "
        when = _fmt_delta(p["aos_time"], now) if p["status"] == "planned" else ""
        lines.append(
            f"{marker} #{p['id']:<4} {p['satellite_name']:<16} {p['status']:<10} "
            f"AOS {_fmt_time(p['aos_time'])}  LOS {_fmt_time(p['los_time'])}  "
            f"el.máx {p['max_elevation_deg']:5.1f}  {p['telecommand_count']} TC  {when}"
        )

    # --- Station Manager ---
    lines.append(_header("STATION MANAGER"))
    if isinstance(tracking, str):
        lines.append(f"  ! {tracking}")
    elif tracking is None:
        lines.append("  rastreando: nada no momento")
    else:
        pointing = "SIM" if tracking["is_pointing"] else "não (abaixo da elevação mínima)"
        lines.append(
            f"  rastreando: {tracking['satellite_name']}  até {_fmt_time(datetime.fromisoformat(tracking['until']))}"
            f"  ({_fmt_delta(datetime.fromisoformat(tracking['until']), now)})"
        )
        if tracking["azimuth_degrees"] is not None:
            lines.append(
                f"  alvo calculado: az {tracking['azimuth_degrees']:6.1f}   "
                f"el {tracking['elevation_degrees']:6.1f}   comandando rotor: {pointing}"
            )

    if isinstance(rotor, str):
        lines.append(f"  ! rotor: {rotor}")
    else:
        lines.append(
            f"  rotor:          az {rotor['azimuth_degrees']:6.1f}   "
            f"el {rotor['elevation_degrees']:6.1f}"
        )

    # --- Telecomandos ---
    lines.append(_header("TELECOMANDOS"))
    counts = overview["telecommand_counts"]
    if counts:
        lines.append("  " + "   ".join(
            f"{status}={total}" for status, total in sorted(counts.items())
        ))
    else:
        lines.append("  (nenhum telecomando cadastrado)")
    lines.append("")

    return "\n".join(lines)


def snapshot(engine, station: StationManagerClient) -> str:
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        overview = db.fetch_station_overview(conn)

    # Uma falha de comunicação vira texto na tela em vez de derrubar o monitor:
    # é justamente quando algo está errado que se quer olhar para ele.
    try:
        tracking = station.get_tracking()
    except (StationManagerUnavailable, StationManagerError) as error:
        tracking = f"Station Manager indisponível: {error}"

    try:
        rotor = station.get_position()
    except (StationManagerUnavailable, StationManagerError) as error:
        rotor = str(error)

    return render(overview, tracking, rotor, now)


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor da estação terrestre.")
    parser.add_argument("--watch", action="store_true",
                        help="Atualiza continuamente em vez de imprimir uma vez.")
    parser.add_argument("--interval", type=float, default=1.0,
                        help="Segundos entre atualizações com --watch (padrão: 1).")
    args = parser.parse_args()

    engine = db.build_engine(config.DATABASE_URL)
    station = StationManagerClient(
        config.STATION_MANAGER_ADDRESS, config.ZMQ_REQUEST_TIMEOUT_MS
    )

    try:
        if not args.watch:
            print(snapshot(engine, station))
            return

        while True:
            # \033[H\033[J = cursor para o topo + limpa. Redesenhar por cima
            # evita o piscar de um clear-screen a cada segundo.
            print("\033[H\033[J" + snapshot(engine, station), flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        station.close()
        engine.dispose()


if __name__ == "__main__":
    main()
