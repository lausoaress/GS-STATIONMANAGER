#!/usr/bin/env python3
"""
cli.py — Ferramenta de linha de comando para depurar e validar o cálculo.

Não faz parte do caminho de produção (quem consome a biblioteca é o Station
Manager e o TC Scheduler); existe para responder "o número está certo?" sem
precisar subir a estação inteira.

Uso:
    python -m spacelab_tracking.cli --norad-id 25544
    python -m spacelab_tracking.cli --norad-id 25544 --minutes 90
    python -m spacelab_tracking.cli --norad-id 25544 --force-update
    python -m spacelab_tracking.cli --norad-id 25544 --next-pass
    python -m spacelab_tracking.cli --norad-id 25544 --next-pass --search-hours 72
    python -m spacelab_tracking.cli --tle-file meu_tle.txt
    python -m spacelab_tracking.cli --norad-id 25544 --export-tle atual.tle
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

from . import celestrak
from . import config
from . import propagation
from . import tracking


def format_report(info: tracking.TrackingInfo, station: dict) -> str:
    px, py, pz = info.position_teme_km
    vx, vy, vz = info.velocity_teme_km_s
    geo = info.geodetic
    topo = info.topocentric

    lines = [
        f"Satélite: {info.satellite_name}",
        f"NORAD ID: {info.norad_id}",
        f"Epoch (TLE/OMM): {info.tle_epoch.isoformat()}",
        f"UTC: {info.time_utc.isoformat()}",
        "",
        "ECI/TEME:",
        f"  Position (km):     X={px:10.3f}  Y={py:10.3f}  Z={pz:10.3f}",
        f"  Velocity (km/s):   Vx={vx:8.4f}  Vy={vy:8.4f}  Vz={vz:8.4f}",
        "",
        "Geodetic:",
        f"  Latitude:  {geo.latitude_deg:9.4f} deg",
        f"  Longitude: {geo.longitude_deg:9.4f} deg",
        f"  Altitude:  {geo.altitude_km:9.2f} km",
        "",
        "Ground Station:",
        f"  Name:      {station['name']}",
        f"  Latitude:  {station['latitude_deg']:9.4f} deg",
        f"  Longitude: {station['longitude_deg']:9.4f} deg",
        f"  Altitude:  {station['altitude_m']:9.1f} m",
        "",
        "Tracking:",
        f"  Azimuth:   {topo.azimuth_deg:7.2f} deg",
        f"  Elevation: {topo.elevation_deg:7.2f} deg",
        f"  Range:     {topo.range_km:9.2f} km",
        "",
        f"Status: {info.status_label}",
    ]
    return "\n".join(lines)


def format_pass_report(
    satellite_name: str,
    norad_id: int,
    station: dict,
    search_window_hours: float,
    satellite_pass,
) -> str:
    header = [
        f"Satélite: {satellite_name}",
        f"NORAD ID: {norad_id}",
        f"Ground Station: {station['name']} "
        f"({station['latitude_deg']:.4f}, {station['longitude_deg']:.4f}, "
        f"{station['altitude_m']:.0f} m)",
        "",
    ]

    if satellite_pass is None:
        header.append(
            f"Nenhuma passagem visível encontrada nas próximas "
            f"{search_window_hours:.0f}h (elevação mínima configurada: "
            f"{config.MIN_ELEVATION_DEG:.1f} deg)."
        )
        return "\n".join(header)

    p = satellite_pass
    header += [
        "Próxima passagem visível:",
        f"  AOS (nascer):       {p.aos_time.isoformat()}   Az: {p.aos_azimuth_deg:6.2f} deg",
        f"  Culminação (pico):  {p.culmination_time.isoformat()}   "
        f"El: {p.max_elevation_deg:5.2f} deg  Az: {p.culmination_azimuth_deg:6.2f} deg",
        f"  LOS (ocaso):        {p.los_time.isoformat()}   Az: {p.los_azimuth_deg:6.2f} deg",
        f"  Duração:            {p.duration_seconds / 60:.1f} min",
    ]
    return "\n".join(header)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Depuração do rastreamento de satélites (SGP4 + CelesTrak)."
    )
    parser.add_argument(
        "--norad-id", type=int, default=None,
        help="NORAD ID do satélite a consultar no CelesTrak. Obrigatório, "
             "exceto quando --tle-file é usado.",
    )
    parser.add_argument(
        "--minutes", type=float, default=0.0,
        help="Calcula a posição N minutos a partir de agora (padrão: 0 = agora).",
    )
    parser.add_argument(
        "--force-update", action="store_true",
        help="Ignora o cache local e busca dados orbitais novos no CelesTrak.",
    )
    parser.add_argument(
        "--next-pass", action="store_true",
        help="Em vez da posição atual, prevê e mostra a próxima passagem visível.",
    )
    parser.add_argument(
        "--search-hours", type=float, default=24.0,
        help="Janela de busca (horas) usada por --next-pass (padrão: 24).",
    )
    parser.add_argument(
        "--tle-file", type=str, default=None,
        help="Carrega o TLE de um arquivo local (2 ou 3 linhas) em vez de "
             "consultar o CelesTrak — não toca na rede.",
    )
    parser.add_argument(
        "--satellite-name", type=str, default=None,
        help="Nome do satélite a exibir; útil com --tle-file de 2 linhas "
             "(sem nome embutido) ou para sobrescrever o nome do TLE.",
    )
    parser.add_argument(
        "--export-tle", type=str, default=None,
        help="Salva o TLE atualmente em uso num arquivo de 3 linhas (nome + "
             "linhas 1/2), para importar exatamente o mesmo TLE em outra "
             "ferramenta (ex.: Gpredict) e comparar resultados.",
    )
    args = parser.parse_args()

    if args.tle_file:
        print(f"[cli] Carregando TLE local de '{args.tle_file}' (sem consultar a rede)...")
        try:
            orbital_data = celestrak.load_tle_file(args.tle_file)
        except (ValueError, FileNotFoundError) as exc:
            print(f"[cli] Erro ao carregar TLE: {exc}")
            sys.exit(1)
    else:
        if args.norad_id is None:
            parser.error("--norad-id é obrigatório quando --tle-file não é usado.")
        print(f"[cli] Obtendo dados orbitais para NORAD ID {args.norad_id}...")
        try:
            orbital_data = celestrak.get_orbital_data(
                args.norad_id, force_update=args.force_update
            )
        except RuntimeError as exc:
            print(f"[cli] {exc}")
            sys.exit(1)

    print(f"[cli] Fonte dos dados: {orbital_data.source.upper()}")

    satrec = propagation.build_satellite(orbital_data)
    satellite_name = args.satellite_name or orbital_data.satellite_name or "DESCONHECIDO"

    if args.export_tle:
        if orbital_data.source != "tle":
            print(
                "[cli] Não é possível exportar: os dados atuais vieram como "
                "OMM/JSON, sem conversão direta para texto TLE (que inclui "
                "checksum). Rode de novo com --tle-file, ou force um "
                "--force-update numa hora em que o fallback caia para TLE."
            )
        else:
            with open(args.export_tle, "w") as f:
                f.write(f"{satellite_name}\n{orbital_data.tle_line1}\n{orbital_data.tle_line2}\n")
            print(
                f"[cli] TLE exportado para '{args.export_tle}'. Importe esse "
                f"arquivo no Gpredict (Edit > Update TLE > From files) para "
                f"comparar com exatamente os mesmos elementos orbitais."
            )

    if args.next_pass:
        print(f"[cli] Buscando próxima passagem visível nas próximas {args.search_hours:.0f}h...")
        satellite_pass = tracking.predict_next_pass(
            satrec, satellite_name, search_window_hours=args.search_hours,
        )
        print()
        print(format_pass_report(
            satellite_name, satrec.satnum, config.GROUND_STATION,
            args.search_hours, satellite_pass,
        ))
        return

    when = datetime.now(timezone.utc) + timedelta(minutes=args.minutes)
    info = tracking.get_tracking_info(satrec, satellite_name, when=when)

    print()
    print(format_report(info, config.GROUND_STATION))


if __name__ == "__main__":
    main()
