"""
config.py — Configurações centrais da biblioteca de rastreamento.

Mantenha aqui tudo que for "parâmetro" (URLs, estação terrestre, caminhos de
cache). Isso evita espalhar valores mágicos pelo resto do código e facilita a
evolução futura (nova estação, novo satélite, etc.).

Diferente da versão original em script, **não há um NORAD_ID global**: a
estação rastreia N satélites vindos do banco de dados, então o identificador é
sempre um parâmetro de função, nunca estado de módulo.

Tudo que muda entre instalações vem de variável de ambiente, para que trocar a
coordenada da estação não exija editar código nem reconstruir uma imagem.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# CelesTrak — API GP (General Perturbations)
# Documentação: https://celestrak.org/NORAD/documentation/gp-data-formats.php
# ---------------------------------------------------------------------------
CELESTRAK_BASE_URL = "https://celestrak.org/NORAD/elements/gp.php"


def celestrak_omm_json_url(norad_id: int) -> str:
    """OMM (Orbit Mean-Elements Message) em JSON — formato preferido."""
    return f"{CELESTRAK_BASE_URL}?CATNR={norad_id}&FORMAT=json"


def celestrak_tle_url(norad_id: int) -> str:
    """TLE clássico de 2 linhas — usado como fallback."""
    return f"{CELESTRAK_BASE_URL}?CATNR={norad_id}&FORMAT=tle"


HTTP_TIMEOUT_SECONDS = float(os.getenv("TRACKING_HTTP_TIMEOUT_SECONDS", "10"))

# ---------------------------------------------------------------------------
# Cache local dos dados orbitais
# ---------------------------------------------------------------------------
# Relativo ao diretório de trabalho por padrão (nos containers, /app/data), e
# não ao diretório do pacote: escrever dentro do próprio pacote instalado é
# frágil e pode nem ser permitido.
DATA_DIR = Path(os.getenv("TRACKING_DATA_DIR", "data"))


def orbital_data_cache_file(norad_id: int) -> Path:
    """Caminho do cache de um satélite. Um arquivo por NORAD ID, já que a
    estação acompanha vários satélites simultaneamente."""
    return DATA_DIR / f"orbital_data_{norad_id}.json"


# Satélites em órbita baixa sofrem decaimento perceptível (arrasto atmosférico)
# e manobras. Para uso "sério" de apontamento, não se recomenda um TLE com mais
# de ~24h. 6h é um valor conservador e seguro.
CACHE_MAX_AGE_HOURS = float(os.getenv("TRACKING_CACHE_MAX_AGE_HOURS", "6"))

# ---------------------------------------------------------------------------
# Estação terrestre (observador)
# ---------------------------------------------------------------------------
# ATENÇÃO: os defaults abaixo são um EXEMPLO (São Paulo) e devem ser trocados
# pelas coordenadas reais da estação via variável de ambiente. No futuro isso
# pode vir de um GPS conectado ao dispositivo em vez de configuração.
GROUND_STATION = {
    "name": os.getenv("GS_NAME", "Estação de Teste"),
    "latitude_deg": float(os.getenv("GS_LATITUDE_DEG", "-23.5505")),
    "longitude_deg": float(os.getenv("GS_LONGITUDE_DEG", "-46.6333")),
    "altitude_m": float(os.getenv("GS_ALTITUDE_M", "760.0")),
}

# Máscara de elevação: abaixo disso, considera-se sem visada útil mesmo que
# geometricamente o satélite já esteja acima do horizonte matemático
# (obstruções como prédios/árvores, ruído de RF perto do horizonte, etc.)
MIN_ELEVATION_DEG = float(os.getenv("GS_MIN_ELEVATION_DEG", "0.0"))
