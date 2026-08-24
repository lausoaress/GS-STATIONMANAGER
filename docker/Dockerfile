# Imagem única para os dois processos deste repo: o Station Manager
# (mgm8.rotor_zmq.main) e o GRS Manager (grs_manager.main). O pyproject usa
# `packages.find where = ["src"]`, então um único `pip install` instala os dois
# pacotes; o compose diferencia os serviços pelo `command:`.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# README.md é exigido no build: pyproject.toml declara `readme = "README.md"`.
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY vendor/ ./vendor/

# Editable para que o bind mount de ./src no compose reflita mudanças sem rebuild.
# O extra [zmq] traz o pyzmq, que os dois adapters de rede precisam.
RUN pip install --no-cache-dir -e ".[zmq]"
