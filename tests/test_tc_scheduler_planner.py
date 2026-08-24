"""Testes da escolha de passagens do TC Scheduler.

É onde mora a autonomia da estação: sem operador na tela do gpredict, é este
código que decide qual satélite acompanhar. Um erro aqui não quebra nada de
forma visível — a estação simplesmente rastreia a coisa errada.

Lógica pura, sem banco nem rede: as passagens são dublês com só o que o planner
consulta.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from tc_scheduler.planner import PassCandidate, is_worth_tracking, select_passes

T0 = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


@dataclass
class FakePass:
    aos_time: datetime
    los_time: datetime
    max_elevation_deg: float = 45.0

    @property
    def duration_seconds(self) -> float:
        return (self.los_time - self.aos_time).total_seconds()


def make_pass(offset_minutes: float, duration_minutes: float = 10.0,
              max_elevation_deg: float = 45.0) -> FakePass:
    aos = T0 + timedelta(minutes=offset_minutes)
    return FakePass(aos, aos + timedelta(minutes=duration_minutes), max_elevation_deg)


def candidate(satellite_id: int, satellite_pass: FakePass, *, priority: int = 5,
              pending: int = 1, name: str | None = None) -> PassCandidate:
    return PassCandidate(
        satellite_id=satellite_id,
        satellite_name=name or f"SAT-{satellite_id}",
        satellite_pass=satellite_pass,
        pending_telecommands=pending,
        max_priority=priority,
        tle_epoch=T0,
        data_source="omm",
    )


# --- Filtro de passagens aproveitáveis --------------------------------------

@pytest.mark.parametrize(
    "duration_min, elevation, expected",
    [
        (10.0, 45.0, True),    # boa passagem
        (0.5, 45.0, False),    # curta demais
        (10.0, 2.0, False),    # rasante demais
        (1.0, 5.0, True),      # exatamente nos limites: aceita
    ],
)
def test_is_worth_tracking(duration_min, elevation, expected):
    p = make_pass(0, duration_min, elevation)
    assert is_worth_tracking(p, min_duration_seconds=60, min_max_elevation_deg=5.0) is expected


# --- Detecção de sobreposição ------------------------------------------------
# A estação tem um rotor só: duas passagens que se cruzam no tempo são
# mutuamente exclusivas.

def test_passes_that_share_time_overlap():
    a = candidate(1, make_pass(0, 10))
    b = candidate(2, make_pass(5, 10))
    assert a.overlaps(b) and b.overlaps(a)


def test_passes_that_only_touch_do_not_overlap():
    """Uma janela que termina exatamente quando a outra começa não conflita."""
    a = candidate(1, make_pass(0, 10))
    b = candidate(2, make_pass(10, 10))
    assert not a.overlaps(b) and not b.overlaps(a)


def test_disjoint_passes_do_not_overlap():
    a = candidate(1, make_pass(0, 10))
    b = candidate(2, make_pass(60, 10))
    assert not a.overlaps(b)


# --- Seleção -----------------------------------------------------------------

def test_selects_everything_when_nothing_collides():
    candidates = [candidate(1, make_pass(0)), candidate(2, make_pass(30)),
                  candidate(3, make_pass(60))]
    assert len(select_passes(candidates)) == 3


def test_returns_passes_in_chronological_order():
    """O plano é lido em ordem de AOS, independentemente da ordem de escolha."""
    selected = select_passes([
        candidate(1, make_pass(60), priority=1),
        candidate(2, make_pass(0), priority=10),
        candidate(3, make_pass(30), priority=5),
    ])
    aos_times = [c.satellite_pass.aos_time for c in selected]
    assert aos_times == sorted(aos_times)


def test_higher_telecommand_priority_wins_a_collision():
    """A prioridade do telecomando é a única entrada que reflete intenção
    humana — tem que vencer elevação e quantidade."""
    urgent = candidate(1, make_pass(0, 10, max_elevation_deg=10.0), priority=10, pending=1)
    routine = candidate(2, make_pass(5, 10, max_elevation_deg=80.0), priority=3, pending=99)

    selected = select_passes([routine, urgent])

    assert [c.satellite_id for c in selected] == [1]


def test_more_telecommands_breaks_a_priority_tie():
    few = candidate(1, make_pass(0), priority=5, pending=1)
    many = candidate(2, make_pass(5), priority=5, pending=7)

    assert [c.satellite_id for c in select_passes([few, many])] == [2]


def test_higher_elevation_breaks_remaining_ties():
    low = candidate(1, make_pass(0, max_elevation_deg=12.0), priority=5, pending=2)
    high = candidate(2, make_pass(5, max_elevation_deg=70.0), priority=5, pending=2)

    assert [c.satellite_id for c in select_passes([low, high])] == [2]


def test_a_rejected_pass_does_not_block_a_later_compatible_one():
    """Descartar uma passagem por conflito não pode custar outra que caberia:
    a próxima órbita do satélite preterido ainda é aproveitável."""
    winner = candidate(1, make_pass(0, 10), priority=10)
    loser = candidate(2, make_pass(5, 10), priority=1)
    later = candidate(2, make_pass(100, 10), priority=1)

    selected = select_passes([winner, loser, later])

    assert [c.satellite_id for c in selected] == [1, 2]
    assert [c.satellite_pass.aos_time for c in selected] == [
        winner.satellite_pass.aos_time, later.satellite_pass.aos_time
    ]


def test_chain_of_overlaps_keeps_the_best_and_the_compatible():
    """Três passagens em cadeia (A-B, B-C, mas A e C disjuntas): fica a de maior
    pontuação e a que ainda couber."""
    a = candidate(1, make_pass(0, 10), priority=5)
    b = candidate(2, make_pass(5, 10), priority=9)   # colide com A e com C
    c = candidate(3, make_pass(12, 10), priority=5)

    selected = select_passes([a, b, c])

    assert [x.satellite_id for x in selected] == [2]


def test_empty_input_yields_empty_plan():
    assert select_passes([]) == []
