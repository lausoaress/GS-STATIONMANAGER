# Imagem única para os três processos deste repo: Station Manager
# (mgm8.rotor_zmq.main), GRS Manager (grs_manager.main) e TC Scheduler
# (tc_scheduler.main). O pyproject usa `packages.find where = ["src"]`, então um
# único `pip install` instala os três pacotes; o compose diferencia os serviços
# pelo `command:`.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# gcc e libpq-dev são necessários para o psycopg2 (driver do PostgreSQL).
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# README.md é exigido no build: pyproject.toml declara `readme = "README.md"`.
COPY pyproject.toml README.md ./
COPY libs/ ./libs/
COPY src/ ./src/
COPY vendor/ ./vendor/

# spacelab-tracking é instalada à parte, e não como dependência declarada no
# pyproject: ela não está num índice de pacotes, e caminhos relativos em
# `dependencies` não são portáveis com setuptools.
#
# Editable nos dois para que os bind mounts de ./src e ./libs no compose
# reflitam mudanças sem rebuild. Os extras trazem o pyzmq (adapters de rede) e
# SQLAlchemy/psycopg2 (TC Scheduler).
RUN pip install --no-cache-dir -e ./libs/spacelab-tracking -e ".[zmq,scheduler]"

# Cache local de dados orbitais (TRACKING_DATA_DIR). Montado como volume no
# compose, para que o fallback offline do celestrak sobreviva a um restart.
RUN mkdir -p /app/data
