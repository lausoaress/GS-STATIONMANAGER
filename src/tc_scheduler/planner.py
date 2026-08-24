"""Escolha de quais passagens a estação vai usar.

É aqui que mora a autonomia: em vez de um operador decidir na tela do gpredict
qual satélite acompanhar, o Scheduler olha o que está esperando na fila de
telecomandos, prevê todas as passagens visíveis no horizonte e escolhe.

A estação tem um rotor só, então duas passagens que se sobrepõem no tempo são
mutuamente exclusivas — a escolha é um problema de seleção de intervalos com
peso. A heurística gulosa (maior pontuação primeiro, descartando o que colide
com algo já comprometido) não é ótima no caso geral, mas passagens de LEO são
curtas e esparsas: colisões são raras, e quando acontecem a diferença para o
ótimo é de uma passagem que volta a aparecer na próxima órbita.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PassCandidate:
    """Uma passagem prevista, com o contexto que decide se vale usá-la."""

    satellite_id: int
    satellite_name: str
    satellite_pass: object          # spacelab_tracking.SatellitePass
    pending_telecommands: int
    max_priority: int
    tle_epoch: object               # datetime do epoch dos elementos usados
    data_source: str                # 'omm' ou 'tle'

    @property
    def score(self) -> tuple:
        """Ordem de preferência entre passagens que competem pelo mesmo rotor.

        1. Prioridade do telecomando mais urgente à espera — é o que o operador
           efetivamente pediu, e a única entrada que reflete intenção humana.
        2. Quantos comandos saem nesta passagem: em empate, atender mais.
        3. Elevação máxima: passagem mais alta rende link melhor e mais longo.
        """
        return (
            self.max_priority,
            self.pending_telecommands,
            self.satellite_pass.max_elevation_deg,
        )

    def overlaps(self, other: "PassCandidate") -> bool:
        return (
            self.satellite_pass.aos_time < other.satellite_pass.los_time
            and other.satellite_pass.aos_time < self.satellite_pass.los_time
        )


def is_worth_tracking(
    satellite_pass,
    min_duration_seconds: float,
    min_max_elevation_deg: float,
) -> bool:
    """Descarta passagens rasantes ou curtas demais.

    Movimentar a antena custa tempo e desgaste; uma passagem de dois minutos a
    três graus de elevação raramente rende link utilizável o bastante para
    justificar isso.
    """
    return (
        satellite_pass.duration_seconds >= min_duration_seconds
        and satellite_pass.max_elevation_deg >= min_max_elevation_deg
    )


def select_passes(candidates: Iterable[PassCandidate]) -> list[PassCandidate]:
    """Escolhe o maior conjunto útil de passagens sem sobreposição.

    Devolve em ordem cronológica — é assim que o plano é gravado e lido.
    """
    committed: list[PassCandidate] = []

    for candidate in sorted(candidates, key=lambda c: c.score, reverse=True):
        conflict = next((c for c in committed if candidate.overlaps(c)), None)
        if conflict is not None:
            logger.info(
                "Passagem de %s (AOS %s) descartada: colide com %s (AOS %s), de "
                "pontuação maior.",
                candidate.satellite_name, candidate.satellite_pass.aos_time.isoformat(),
                conflict.satellite_name, conflict.satellite_pass.aos_time.isoformat(),
            )
            continue
        committed.append(candidate)

    return sorted(committed, key=lambda c: c.satellite_pass.aos_time)
