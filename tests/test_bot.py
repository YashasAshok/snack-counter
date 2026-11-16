"""The bot: fixed actions, permissions, and buttons that match the current state."""

from conftest import accept, done, oslo, report

from snack_counter.actions import CATALOGUE, Action
from snack_counter.models import RefillState as S
from snack_counter.sample_data import INGRID, KARI, LARS, MARTE, OLA, OSLO, RAVI


def _labels(app, person_id):
    return [b.label for b in app.bot.available_actions(person_id)]


def _refill_buttons(app, person_id, refill):
    return {b.action for b in app.bot.available_actions(person_id) if b.refill_id == refill.id}


# --- permissions --------------------------------------------------------------

def test_non_volunteer_cannot_accept(app):
    refill = report(app, KARI, OSLO)
    result = accept(app, KARI, refill)
    assert not result.ok
    assert "for volunteers" in result.message
    assert refill.state == S.OFFERED and refill.offer_to == LARS


def test_nobody_else_can_take_your_direct_offer(app):
    refill = report(app, KARI, OSLO)
    result = accept(app, INGRID, refill)
    assert not result.ok
    assert refill.offer_to == LARS


def test_volunteer_cannot_approve_purchases(app):
    refill = report(app, KARI, OSLO)
    accept(app, LARS, refill)
    done(app, LARS, refill, "1500")

    result = app.bot.press(LARS, Action.APPROVE_PURCHASE, refill.id)
    assert not result.ok and "Only the office admin" in result.message
    assert refill.state == S.NEEDS_APPROVAL


def test_admin_of_the_other_office_cannot_approve(app):
    refill = report(app, KARI, OSLO)
    accept(app, LARS, refill)
    done(app, LARS, refill, "1500")

    result = app.bot.press(RAVI, Action.APPROVE_PURCHASE, refill.id)
    assert not result.ok and "Only the Oslo office admin" in result.message
    assert refill.state == S.NEEDS_APPROVAL


def test_unknown_person_is_refused(app):
    result = app.bot.press("E-999", Action.REPORT_EMPTY, office=OSLO)
    assert not result.ok
    assert app.store.refills == {}


# --- buttons follow the state -------------------------------------------------

def test_volunteer_sees_accept_and_decline_only_for_their_own_offer(app):
    refill = report(app, KARI, OSLO)
    assert _refill_buttons(app, LARS, refill) == {Action.ACCEPT, Action.DECLINE}
    assert _refill_buttons(app, INGRID, refill) == set()


def test_after_accepting_the_buttons_change(app):
    refill = report(app, KARI, OSLO)
    accept(app, LARS, refill)
    assert _refill_buttons(app, LARS, refill) == {Action.MARK_DONE, Action.RELEASE}


def test_admin_sees_approve_and_reject_only_when_needed(app):
    refill = report(app, KARI, OSLO)
    accept(app, LARS, refill)
    assert Action.APPROVE_PURCHASE not in _refill_buttons(app, MARTE, refill)

    done(app, LARS, refill, "1500")
    assert {Action.APPROVE_PURCHASE, Action.REJECT_PURCHASE} <= _refill_buttons(app, MARTE, refill)


def test_employee_menu_is_small(app):
    assert _labels(app, KARI) == ["Snack box is empty", "Join volunteers"]


def test_anything_not_shown_is_refused_and_changes_nothing(app):
    """The bot never lets anyone do something it wouldn't show them as a button."""
    refill = report(app, KARI, OSLO)
    accept(app, LARS, refill)  # state: COMMITTED by Lars

    form = {
        Action.MARK_DONE: dict(amount="500", receipt="r.jpg", items=["Fruit"]),
        Action.ALLOW_EXTRA_BUDGET: dict(amount="500"),
        Action.ASSIGN: dict(person=OLA),
    }
    refill_actions = [a for a, spec in CATALOGUE.items() if spec.needs_refill]
    for person_id in (LARS, INGRID, KARI, MARTE, RAVI):
        shown = _refill_buttons(app, person_id, refill)
        for action in refill_actions:
            if action in shown:
                continue
            before = (refill.state, refill.committed_by)
            result = app.bot.press(person_id, action, refill.id, **form.get(action, {}))
            assert not result.ok, f"{person_id} could {action.name} without seeing the button"
            assert (refill.state, refill.committed_by) == before


def test_a_stale_button_changes_nothing(app):
    refill = report(app, KARI, OSLO)
    old_button = app.chat.button(LARS, "I'll do it")
    app.run_until(oslo(11, 2, 11, 0))  # Lars's offer expires; Ingrid is asked
    assert refill.offer_to == INGRID

    result = app.bot.tap(LARS, old_button)
    assert not result.ok
    assert "with someone else" in result.message
    assert refill.state == S.OFFERED and refill.offer_to == INGRID


def test_tapping_accept_twice_is_harmless(app):
    refill = report(app, KARI, OSLO)
    assert accept(app, LARS, refill).ok
    second = accept(app, LARS, refill)
    assert not second.ok and "already got this one" in second.message


# --- forms and free text --------------------------------------------------------

def test_typed_text_gets_the_menu_and_changes_nothing(app):
    refill = report(app, KARI, OSLO)
    result = app.bot.message(LARS, "the box is empty again, can someone get fruit?")

    assert "I work with buttons" in result.message
    assert {"I'll do it", "Can't today", "My status"} <= {b.label for b in result.buttons}
    assert len(app.store.refills) == 1 and refill.state == S.OFFERED


def test_mark_done_requires_the_receipt(app):
    refill = report(app, KARI, OSLO)
    accept(app, LARS, refill)
    result = app.bot.press(LARS, Action.MARK_DONE, refill.id, amount="845", items=["Fruit"])

    assert not result.ok and "receipt" in result.message
    assert refill.state == S.COMMITTED


def test_mark_done_rejects_a_bad_amount(app):
    refill = report(app, KARI, OSLO)
    accept(app, LARS, refill)
    assert not done(app, LARS, refill, "eight hundred").ok
    assert not done(app, LARS, refill, "-5").ok
    assert refill.state == S.COMMITTED


def test_forms_with_unexpected_fields_are_refused(app):
    result = app.bot.press(KARI, Action.REPORT_EMPTY, office=OSLO, amount="100")
    assert not result.ok


def test_every_action_has_a_unique_label_and_a_handler(app):
    labels = [spec.label for spec in CATALOGUE.values()]
    assert len(labels) == len(set(labels))
    assert set(CATALOGUE) == set(Action)


def test_every_action_is_recorded_in_the_audit_log(app):
    refill = report(app, KARI, OSLO)
    accept(app, INGRID, refill)  # refused
    entries = [(e.person_id, e.action, e.ok) for e in app.store.audit]
    assert entries == [(KARI, "report_empty", True), (INGRID, "accept", False)]
