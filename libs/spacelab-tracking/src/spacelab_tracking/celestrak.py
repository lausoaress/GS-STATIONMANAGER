"""
celestrak.py — Obtenção e cache local dos dados orbitais do CelesTrak, e
carregamento de TLEs importados manualmente (arquivo local ou linhas
coladas diretamente), sem depender da rede.

Estratégia de obtenção via CelesTrak:
1. Tenta buscar OMM (Orbit Mean-Elements Message) em JSON. É o formato
   moderno recomendado pelo CelesTrak: estruturado, com nomes de campo
   explícitos (ECCENTRICITY, INCLINATION, ...), mais fácil de logar,
   versionar e depurar do que um TLE de texto fixo.
2. Se a busca em JSON falhar por qualquer motivo (rede, formato, campo
   ausente), cai para o TLE clássico de 2 linhas como fallback.
3. Toda busca bem-sucedida é gravada em cache local com timestamp. Se a
   rede estiver indisponível, o sistema usa o último cache válido em vez
   de falhar por completo — degradação graciosa, importante caso a
   máquina fique offline temporariamente.

Além disso, `load_tle_file()` e `from_tle_lines()` permitem usar um TLE
de qualquer origem (Space-Track, um arquivo baixado manualmente, um TLE
colado de outro lugar) — útil para testes offline e para rastrear
satélites cujo NORAD ID não esteja cadastrado.

O cache é por NORAD ID: a estação acompanha vários satélites ao mesmo
tempo, então não existe "o" arquivo de cache, e sim um por satélite.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from typing import Optional

import requests

from . import config


@dataclass
class OrbitalData:
    """Container genérico para dados orbitais, independente da origem.

    `to_json()`/`from_json()` também servem de formato de fio entre os
    processos da estação: o Scheduler busca os dados e envia este dicionário
    ao Station Manager. Serializar o objeto inteiro (em vez de só as duas
    linhas de TLE) é o que permite suportar OMM sem perda — OMM não é
    convertível para texto TLE, que exige recalcular o checksum.
    """

    source: str                     # "omm" ou "tle"
    fetched_at: float               # timestamp unix (época em que foi obtido)
    omm: Optional[dict] = None      # dict OMM, quando source == "omm"
    tle_line1: Optional[str] = None
    tle_line2: Optional[str] = None
    satellite_name: Optional[str] = None

    def to_json(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_json(data: dict) -> "OrbitalData":
        return OrbitalData(**data)


def _fetch_omm_json(norad_id: int) -> OrbitalData:
    url = config.celestrak_omm_json_url(norad_id)
    resp = requests.get(url, timeout=config.HTTP_TIMEOUT_SECONDS)
    resp.raise_for_status()
    payload = resp.json()

    if not payload:
        raise ValueError("CelesTrak retornou lista OMM vazia (NORAD ID inválido?)")

    omm_dict = payload[0]
    return OrbitalData(
        source="omm",
        fetched_at=time.time(),
        omm=omm_dict,
        satellite_name=omm_dict.get("OBJECT_NAME"),
    )


def _fetch_tle(norad_id: int) -> OrbitalData:
    url = config.celestrak_tle_url(norad_id)
    resp = requests.get(url, timeout=config.HTTP_TIMEOUT_SECONDS)
    resp.raise_for_status()

    lines = [ln.strip() for ln in resp.text.strip().splitlines() if ln.strip()]
    if len(lines) < 3:
        raise ValueError(f"Resposta TLE inesperada do CelesTrak: {lines!r}")

    name, line1, line2 = lines[0], lines[1], lines[2]
    return OrbitalData(
        source="tle",
        fetched_at=time.time(),
        tle_line1=line1,
        tle_line2=line2,
        satellite_name=name,
    )


def _validate_tle_lines(line1: str, line2: str) -> None:
    """Checagens básicas de sanidade — não é uma validação de checksum
    completa, só o suficiente para dar um erro legível cedo em vez de o
    SGP4 falhar silenciosamente ou de forma confusa mais adiante."""
    if not (line1.startswith("1 ") and line2.startswith("2 ")):
        raise ValueError(
            "Linhas de TLE inválidas: a linha 1 deve começar com '1 ' e a "
            "linha 2 com '2 '. Confira se o TLE foi copiado por inteiro."
        )
    if len(line1) < 69 or len(line2) < 69:
        raise ValueError(
            "Linhas de TLE parecem truncadas (esperado ~69 caracteres em cada)."
        )
    norad1, norad2 = line1[2:7].strip(), line2[2:7].strip()
    if norad1 != norad2:
        raise ValueError(
            f"NORAD ID diverge entre as linhas 1 ({norad1!r}) e 2 ({norad2!r}) "
            f"— confira se as duas linhas pertencem ao mesmo satélite."
        )


def from_tle_lines(line1: str, line2: str, satellite_name: Optional[str] = None) -> OrbitalData:
    """Constrói OrbitalData diretamente de duas linhas de TLE (ex.: vindas
    das colunas tle_line1/tle_line2 do banco, ou coladas manualmente), sem
    precisar de arquivo nem rede."""
    line1, line2 = line1.strip(), line2.strip()
    _validate_tle_lines(line1, line2)
    return OrbitalData(
        source="tle",
        fetched_at=time.time(),
        tle_line1=line1,
        tle_line2=line2,
        satellite_name=satellite_name,
    )


def load_tle_file(path: str) -> OrbitalData:
    """
    Carrega um TLE de um arquivo local, sem tocar na rede.

    Aceita tanto o formato de 2 linhas (só as linhas 1 e 2) quanto o de
    3 linhas (nome do satélite + linhas 1 e 2) — o mesmo formato que o
    CelesTrak devolve com FORMAT=tle, então um arquivo salvo direto do
    navegador ou de `curl ... > iss.tle` funciona sem edição.
    """
    try:
        with open(path) as f:
            lines = [ln.rstrip("\n") for ln in f if ln.strip()]
    except FileNotFoundError:
        raise FileNotFoundError(f"Arquivo TLE não encontrado: '{path}'") from None

    if len(lines) == 2:
        name = None
        line1, line2 = lines
    elif len(lines) >= 3:
        name = lines[0].strip()
        line1, line2 = lines[1], lines[2]
    else:
        raise ValueError(
            f"Arquivo TLE '{path}' precisa ter 2 linhas (linhas 1/2) ou 3 "
            f"linhas (nome + linhas 1/2); encontradas {len(lines)}."
        )

    line1, line2 = line1.strip(), line2.strip()
    _validate_tle_lines(line1, line2)

    return OrbitalData(
        source="tle",
        fetched_at=time.time(),
        tle_line1=line1,
        tle_line2=line2,
        satellite_name=name,
    )


def _save_cache(norad_id: int, orbital_data: OrbitalData) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.orbital_data_cache_file(norad_id), "w") as f:
        json.dump(orbital_data.to_json(), f, indent=2)


def _load_cache(norad_id: int) -> Optional[OrbitalData]:
    cache_file = config.orbital_data_cache_file(norad_id)
    if not cache_file.exists():
        return None
    try:
        with open(cache_file) as f:
            return OrbitalData.from_json(json.load(f))
    except (json.JSONDecodeError, TypeError, KeyError):
        return None


def _cache_age_minutes(orbital_data: OrbitalData) -> float:
    return (time.time() - orbital_data.fetched_at) / 60.0


def get_orbital_data(norad_id: int, force_update: bool = False) -> OrbitalData:
    """
    Ponto de entrada principal do módulo.

    Retorna os dados orbitais mais recentes disponíveis para o satélite:
      - usa o cache local se ele ainda estiver "fresco" (dentro de
        CACHE_MAX_AGE_MINUTES) e `force_update` for False;
      - caso contrário, tenta buscar na rede (OMM, depois TLE);
      - se a rede falhar nos dois formatos, cai para o último cache válido,
        mesmo que "velho" (melhor um TLE desatualizado do que nenhum dado).
    """
    cached = _load_cache(norad_id)

    if not force_update and cached is not None and _cache_age_minutes(cached) < config.CACHE_MAX_AGE_MINUTES:
        return cached

    for fetch_fn, label in ((_fetch_omm_json, "OMM/JSON"), (_fetch_tle, "TLE")):
        try:
            data = fetch_fn(norad_id)
            _save_cache(norad_id, data)
            return data
        except (requests.RequestException, ValueError) as exc:
            print(f"[celestrak] NORAD {norad_id}: falha ao obter {label}: {exc}")

    if cached is not None:
        print(
            f"[celestrak] NORAD {norad_id}: rede indisponível. Usando cache "
            f"local com {_cache_age_minutes(cached):.0f} min de idade."
        )
        return cached

    raise RuntimeError(
        f"Não foi possível obter dados orbitais do NORAD {norad_id} no "
        f"CelesTrak nem localizar um cache válido."
    )
