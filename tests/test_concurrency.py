"""Two people cannot both commit to the same refill.

Python runs the accept code so fast that two threads rarely overlap by chance,
so these tests deliberately slow down the moment between "is this refill
still free?" and "it's mine". Without the lock in RefillService, both people
would get the refill and these tests fail (checked by removing the lock).
"""

import threading
import time

import pytest
from conftest import accept, oslo, report

from snack_counter import budget
from snack_counter.actions import Action
from snack_counter.models import RefillState as S
from snack_counter.sample_data import INGRID, KARI, LARS, OLA, OSLO, PRIYA


def _broadcast_refill(app):
    """Nobody answers three direct offers, so the refill is offered to everyone at once."""
    refill = report(app, KARI, OSLO)
    app.run_until(oslo(11, 2, 15, 0))  # three 2-hour offers expire
    assert refill.state == S.BROADCAST
    assert set(refill.broadcast_to) == {LARS, INGRID, OLA, PRIYA}
    return refill


def _slow_down(monkeypatch, module, name):
    """Make `module.name` take 50 ms, widening the window where a race could happen."""
    real = getattr(module, name)

    def slow(*args, **kwargs):
        time.sleep(0.05)
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, slow)


@pytest.mark.parametrize("attempt", range(20))
def test_two_people_cannot_commit_to_the_same_refill(app, attempt, monkeypatch):
    refill = _broadcast_refill(app)
    # accept() checks the refill is free, then checks the budget, then commits:
    # a slow budget check gives the second tap every chance to sneak in.
    _slow_down(monkeypatch, budget, "can_start_refill")
    start = threading.Barrier(2)
    results = {}

    def tap(person_id):
        start.wait()  # both tap at the same instant
        results[person_id] = app.bot.press(person_id, Action.ACCEPT, refill.id)

    threads = [threading.Thread(target=tap, args=(p,)) for p in (LARS, OLA)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    winners = [p for p, r in results.items() if r.ok]
    assert len(winners) == 1
    assert refill.committed_by == winners[0]
    loser = (set(results) - set(winners)).pop()
    assert "already been taken" in results[loser].message


def test_everyone_else_is_told_who_took_the_broadcast(app):
    refill = _broadcast_refill(app)
    assert accept(app, INGRID, refill).ok

    for other in (LARS, OLA, PRIYA):
        assert "Ingrid is refilling the Oslo box" in app.chat.last(other).text


def test_only_one_refill_per_office_even_when_reported_at_the_same_instant(app, monkeypatch):
    # report_empty() checks there is no open refill, then creates one:
    # a slow ID generator gives the other reports every chance to sneak in.
    _slow_down(monkeypatch, app.store, "new_refill_id")
    start = threading.Barrier(5)
    people = [KARI, LARS, INGRID, OLA, PRIYA]

    def tap(person_id):
        start.wait()
        app.bot.press(person_id, Action.REPORT_EMPTY, office=OSLO)

    threads = [threading.Thread(target=tap, args=(p,)) for p in people]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(app.store.refills) == 1
    assert sorted(next(iter(app.store.refills.values())).reported_by) == sorted(people)
