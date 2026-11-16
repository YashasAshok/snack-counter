"""Shopping hints from what ran out and what was left over."""

from conftest import add_past_purchase, oslo, report

from snack_counter.insights import shopping_hint
from snack_counter.sample_data import INGRID, KARI, LARS, OLA, OSLO


def test_no_hint_without_history(app):
    assert shopping_hint(app.store, app.store.offices[OSLO]) is None
    report(app, KARI, OSLO)
    assert "Tip" not in app.chat.last(LARS).text


def test_hint_suggests_more_of_what_keeps_running_out(app):
    add_past_purchase(app, OLA, OSLO, oslo(10, 20), 800, ran_out=["Fruit"], left_over=["Biscuits"])
    add_past_purchase(app, OLA, OSLO, oslo(10, 25), 800, ran_out=["Fruit"], left_over=["Biscuits"])
    add_past_purchase(app, INGRID, OSLO, oslo(10, 28), 800, ran_out=["Chips"])

    hint = shopping_hint(app.store, app.store.offices[OSLO])
    assert hint == ("more Fruit (ran out first 2 of the last 3 times); "
                    "fewer Biscuits (left over 2 of the last 3 times)")


def test_one_off_items_are_not_mentioned(app):
    add_past_purchase(app, OLA, OSLO, oslo(10, 20), 800, ran_out=["Fruit"])
    add_past_purchase(app, OLA, OSLO, oslo(10, 25), 800, ran_out=["Chips"])
    add_past_purchase(app, OLA, OSLO, oslo(10, 28), 800, ran_out=["Nuts"])
    assert shopping_hint(app.store, app.store.offices[OSLO]) is None


def test_hint_is_included_in_the_offer(app):
    add_past_purchase(app, OLA, OSLO, oslo(10, 28), 800, ran_out=["Fruit"])
    report(app, KARI, OSLO)
    assert "Tip: more Fruit (ran out first last time)." in app.chat.last(LARS).text
