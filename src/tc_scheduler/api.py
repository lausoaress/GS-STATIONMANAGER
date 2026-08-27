"""API de leitura do TC Scheduler.

Expõe por HTTP o que `station_data` sabe responder sobre o plano da estação.
Existe para que o painel do GRS Manager não precise de uma conexão com o
Postgres: o banco tem um dono só, e quem quiser lê-lo pergunta a ele.

Os caminhos são os mesmos que o painel servia quando lia o banco direto
(`/api/station`, `/api/satellite/<code>`, `/api/tle/refresh`), para que o
cliente do outro lado seja um repasse de URL e nada da página precise mudar.

Roda numa thread do processo do Scheduler (ver `main.main`), mas nasce
executável sozinho — `python -m tc_scheduler.api` — de propósito: o laço de
replanejamento é SGP4 em Python puro, CPU-bound, e segura a GIL. Se a latência
durante um replan incomodar, a saída é subir este módulo num container próprio,
sem tocar em código.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Flask, jsonify

logger = logging.getLogger(__name__)


def create_app(station_data: Any) -> Flask:
    """Monta a aplicação em cima de um `station_data` já construído.

    Recebe a dependência pronta em vez de construí-la: é o que permite testar
    a API inteira contra um dublê, sem Postgres nenhum.
    """
    app = Flask(__name__)

    @app.get("/health")
    def health():
        """No ar, e com banco? São duas perguntas.

        A API responder já diz que o processo está vivo; `database_available`
        distingue disso o caso em que ela subiu mas o Postgres não veio junto.
        """
        return jsonify({"ok": True, "database_available": station_data.is_available()})

    @app.get("/api/station")
    def station():
        """Satélites e próximas passagens.

        200 mesmo com o banco fora do ar: `database_available: false` é um
        estado a mostrar na tela, e não um erro do cliente que perguntou.
        """
        return jsonify(station_data.snapshot())

    @app.get("/api/satellite/<code>")
    def satellite(code: str):
        """404 só para satélite que não existe.

        A distinção importa do outro lado: o cliente traduz 404 em "não
        encontrado" e qualquer outra falha em "sem acesso". Confundir os dois
        faria um código digitado errado aparecer como banco indisponível.
        """
        detail = station_data.satellite_detail(code)
        if detail is None:
            return jsonify({"error": f"satélite {code} não encontrado"}), 404
        return jsonify(detail)

    @app.post("/api/tle/refresh")
    def refresh_tle():
        """Revalida os elementos orbitais no CelesTrak, sem esperar o cache expirar.

        POST porque muda estado (o cache de TLE) — um GET aqui seria disparado
        por qualquer prefetch de navegador. É a única escrita da API, e ela vai
        para o cache, nunca para o banco.
        """
        return jsonify(station_data.refresh_orbital_data())

    return app


def main() -> None:
    """Sobe só a API, sem o laço de planejamento.

    Modo de escape para quando o replan segurando a GIL atrapalhar: um serviço
    a mais no compose, mesma imagem, mesmo repositório.
    """
    import logging as _logging

    from tc_scheduler import config, station_data as station_data_module

    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    data = station_data_module.from_environment()
    if data is None:
        raise SystemExit("PG_DATABASE_URL não definida: a API não tem o que servir.")

    logger.info("API de leitura em http://%s:%d", config.API_HOST, config.API_PORT)
    try:
        create_app(data).run(
            host=config.API_HOST, port=config.API_PORT,
            debug=False, use_reloader=False, threaded=True,
        )
    finally:
        data.close()


if __name__ == "__main__":
    main()
