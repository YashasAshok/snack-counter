"""The chat bot: the only way people interact with the system.

* `press()` handles a button tap or a submitted form. It checks the person's
  role and the form, then hands over to the refill service, which checks the
  person and the refill's state. The reply is sent back in chat.
* `available_actions()` works out which buttons a person should see right now.
  Hiding buttons is only a convenience: `press()` re-checks everything, so an
  old or stale button can never do anything it shouldn't.
* `message()` handles typed text: the bot doesn't interpret it, it replies
  with the menu of buttons.
"""

from __future__ import annotations

from .actions import CATALOGUE, Action, Role
from .assignment import why_not_eligible
from .models import BOX_EMPTY, WAITING_FOR_BUYER, Person, RefillState
from .ports import Button, ChatPort, Clock, FxRates
from .refill_service import RefillService
from .result import Result
from .store import AuditEntry, InMemoryStore

S = RefillState

_NOT_ALLOWED = {
    Role.VOLUNTEER: "That's for volunteers. Tap [Join volunteers] if you'd like to help!",
    Role.ADMIN: "Only the office admin can do that.",
}


def roles_of(store: InMemoryStore, person: Person) -> set[Role]:
    roles = {Role.EMPLOYEE}
    if person.is_volunteer:
        roles.add(Role.VOLUNTEER)
    if store.office_run_by(person.id):
        roles.add(Role.ADMIN)
    return roles


class Bot:
    def __init__(self, store: InMemoryStore, service: RefillService, chat: ChatPort,
                 clock: Clock, fx: FxRates) -> None:
        self.store = store
        self.service = service
        self.chat = chat
        self.clock = clock
        self.fx = fx

    # ------------------------------------------------------------------
    def press(self, person_id: str, action: Action, refill_id: str | None = None, **form) -> Result:
        """A person tapped a button (and filled in its form, if it has one)."""
        person = self.store.people.get(person_id)
        if person is None:
            result = Result(False, "Sorry, I don't recognise you. Please ask your office admin to add you.")
        else:
            result = self._handle(person, action, refill_id, form)
        self.store.audit.append(AuditEntry(self.clock.now(), person_id, action.value, refill_id,
                                           result.ok, result.message))
        self.chat.send(person_id, result.message, result.buttons)
        return result

    def tap(self, person_id: str, button: Button, **form) -> Result:
        return self.press(person_id, button.action, button.refill_id, **form)

    def message(self, person_id: str, text: str) -> Result:
        """Typed text is not interpreted: reply with what the person can do right now."""
        result = Result(True, "I work with buttons, so I don't read typed messages. "
                              "Here's what you can do right now:", self.available_actions(person_id))
        self.chat.send(person_id, result.message, result.buttons)
        return result

    # ------------------------------------------------------------------
    def available_actions(self, person_id: str) -> list[Button]:
        """Exactly the buttons that make sense for this person right now."""
        person = self.store.people.get(person_id)
        if person is None:
            return []
        roles = roles_of(self.store, person)
        now = self.clock.now()
        buttons = [self._button(Action.REPORT_EMPTY)]

        if Role.VOLUNTEER not in roles:
            buttons.append(self._button(Action.JOIN_VOLUNTEERS))
        else:
            for refill in self.store.refills.values():
                office = self.store.offices[refill.office_id]
                if refill.state == S.OFFERED and refill.offer_to == person.id:
                    buttons += [self._button(Action.ACCEPT, refill.id), self._button(Action.DECLINE, refill.id)]
                elif refill.state == S.BROADCAST and why_not_eligible(self.store, person, office, now, self.fx) is None:
                    buttons.append(self._button(Action.ACCEPT, refill.id))
                elif refill.state == S.COMMITTED and refill.committed_by == person.id:
                    buttons += [self._button(Action.MARK_DONE, refill.id), self._button(Action.RELEASE, refill.id)]
            buttons += [self._button(a) for a in
                        (Action.SET_AWAY, Action.SET_VISIT, Action.MY_STATUS, Action.LEAVE_VOLUNTEERS)]

        if Role.ADMIN in roles:
            office = self.store.office_run_by(person.id)
            for refill in self.store.refills_at(office.id):
                if refill.state == S.NEEDS_APPROVAL:
                    buttons += [self._button(Action.APPROVE_PURCHASE, refill.id),
                                self._button(Action.REJECT_PURCHASE, refill.id)]
                if refill.state == S.BLOCKED_BUDGET:
                    buttons += [self._button(Action.ALLOW_EXTRA_BUDGET, refill.id),
                                self._button(Action.KEEP_BLOCKED, refill.id)]
                if refill.state in WAITING_FOR_BUYER:
                    buttons.append(self._button(Action.ASSIGN, refill.id))
                if refill.state in BOX_EMPTY:
                    buttons.append(self._button(Action.CANCEL_REFILL, refill.id))
                claim = refill.claim
                if refill.state == S.CLAIM_SUBMITTED and claim and claim.escalated and not claim.followed_up:
                    buttons.append(self._button(Action.MARK_FOLLOWED_UP, refill.id))
            buttons += [self._button(Action.MANAGE_VOLUNTEERS), self._button(Action.MONTHLY_REPORT)]
        return buttons

    # ------------------------------------------------------------------
    def _handle(self, person: Person, action: Action, refill_id: str | None, form: dict) -> Result:
        spec = CATALOGUE[action]
        if spec.role not in roles_of(self.store, person):
            return Result(False, _NOT_ALLOWED[spec.role])
        if spec.needs_refill and not refill_id:
            return Result(False, "Which refill do you mean? Please use the button on its message.")
        missing = [name for name in spec.required if form.get(name) in (None, "", [], ())]
        if missing:
            return Result(False, "Please fill in: " + ", ".join(missing) + ".")
        unknown = set(form) - set(spec.required) - set(spec.optional)
        if unknown:
            return Result(False, "That form has unexpected fields: " + ", ".join(sorted(unknown)) + ".")
        return self._dispatch(person, action, refill_id, form)

    def _dispatch(self, person: Person, action: Action, refill_id: str | None, form: dict) -> Result:
        s = self.service
        match action:
            case Action.REPORT_EMPTY:
                # Office comes from the QR code on the box, or else where the person is today
                home = self.store.offices[person.home_office]
                office_id = form.get("office") or person.office_on(home.today(self.clock.now()))
                return s.report_empty(person.id, office_id)
            case Action.JOIN_VOLUNTEERS:
                return s.join(person.id)
            case Action.ACCEPT:
                return s.accept(person.id, refill_id)
            case Action.DECLINE:
                return s.decline(person.id, refill_id, form.get("reason"))
            case Action.RELEASE:
                return s.release(person.id, refill_id)
            case Action.MARK_DONE:
                return s.mark_done(person.id, refill_id, form["amount"], form["receipt"], form["items"],
                                   form.get("ran_out", ()), form.get("left_over", ()))
            case Action.SET_AWAY:
                return s.set_away(person.id, form["start"], form["end"])
            case Action.SET_VISIT:
                return s.set_visit(person.id, form["office"], form["start"], form["end"])
            case Action.MY_STATUS:
                return s.my_status(person.id)
            case Action.LEAVE_VOLUNTEERS:
                return s.leave(person.id)
            case Action.APPROVE_PURCHASE:
                return s.approve_purchase(person.id, refill_id)
            case Action.REJECT_PURCHASE:
                return s.reject_purchase(person.id, refill_id, form.get("reason"))
            case Action.ALLOW_EXTRA_BUDGET:
                return s.allow_extra_budget(person.id, refill_id, form["amount"])
            case Action.KEEP_BLOCKED:
                return s.keep_blocked(person.id, refill_id)
            case Action.ASSIGN:
                return s.assign(person.id, refill_id, form["person"])
            case Action.CANCEL_REFILL:
                return s.cancel_refill(person.id, refill_id, form.get("reason"))
            case Action.MARK_FOLLOWED_UP:
                return s.mark_followed_up(person.id, refill_id)
            case Action.MANAGE_VOLUNTEERS:
                return s.manage_volunteer(person.id, form["person"], form["volunteer"])
            case Action.MONTHLY_REPORT:
                return s.report_text(form["year"], form["month"])
        raise ValueError(f"Unhandled action {action}")  # every action in the catalogue is handled above

    @staticmethod
    def _button(action: Action, refill_id: str | None = None) -> Button:
        return Button(CATALOGUE[action].label, action, refill_id)
